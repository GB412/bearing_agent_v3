import pytest

from bearing_agents.domain.agent_protocols import AgentResult, PlanDecision
from bearing_agents.domain.enums import AgentResultStatus
from bearing_agents.orchestration.contracts import ActionSpec, CATALOG, policy_guard
from bearing_agents.orchestration.registry import (
    AgentContext,
    AgentRegistry,
    AgentRegistryError,
    ToolAccessError,
    ToolRegistry,
)


def test_agent_registry_accepts_a_new_executor_without_workflow_changes(ready):
    class DiagnosticAgent:
        def run(self, state, task):
            return AgentResult(
                task_id=task.id,
                status=AgentResultStatus.SUCCESS,
                issues=[{"diagnostic": "read-only"}],
            )

    registry = AgentRegistry({"diagnostic_agent": DiagnosticAgent()})
    assert registry.require("diagnostic_agent").__class__.__name__ == "DiagnosticAgent"
    assert "diagnostic_agent" in registry.executor_ids
    with pytest.raises(AgentRegistryError):
        registry.require("not_registered")


def test_agent_registry_rejects_invalid_and_duplicate_executors():
    registry = AgentRegistry()

    with pytest.raises(TypeError):
        registry.register("broken", object())

    class Agent:
        def run(self, state, task):
            return None

    registry.register("agent", Agent())
    with pytest.raises(ValueError, match="Duplicate"):
        registry.register("agent", Agent())


def test_tool_registry_enforces_allowlist_and_records_safe_metadata():
    calls = []
    tools = ToolRegistry()
    tools.register(
        "sum_values",
        lambda left, right: calls.append((left, right)) or left + right,
        allowed_agent_ids={"calculator"},
        version="2",
    )

    toolbox = tools.for_agent("calculator")
    assert toolbox.available_tool_ids == ("sum_values",)
    assert toolbox.call("sum_values", left=2, right=3) == 5
    record = toolbox.calls[0].as_dict()
    assert record["tool_id"] == "sum_values"
    assert record["tool_version"] == "2"
    assert record["status"] == "SUCCESS"
    assert record["input_digest"] and record["output_digest"]
    assert "left" not in str(record) and "right" not in str(record)

    denied = tools.for_agent("requirements_agent")
    assert denied.available_tool_ids == ()
    with pytest.raises(ToolAccessError):
        denied.call("sum_values", left=10, right=20)
    assert denied.calls[0].status == "DENIED"
    assert calls == [(2, 3)]


def test_tool_registry_rejects_duplicate_tool_ids():
    tools = ToolRegistry()
    tools.register("lookup", lambda: 1, allowed_agent_ids={"design"})
    with pytest.raises(ValueError, match="Duplicate"):
        tools.register("lookup", lambda: 2, allowed_agent_ids={"design"})


def test_agent_context_has_no_state_writer_and_tools_are_executor_bound():
    tools = ToolRegistry()
    tools.register("lookup", lambda: "ok", allowed_agent_ids={"design"})
    context = AgentContext(
        action="analyze_conditions",
        target_ref=None,
        input_refs=(),
        tools=tools.for_agent("design"),
    )

    assert context.tools.call("lookup") == "ok"
    assert not hasattr(context, "manager")
    assert not hasattr(context, "repository")
    assert not hasattr(context, "write_context")


def test_action_scope_is_declared_by_the_catalog_not_supervisor_code(ready):
    profile_state = ready.model_copy(update={"target_scope": "test_bearing_profile"})
    catalog = {
        "test_diagnostic": ActionSpec(
            executor_id="diagnostic_agent",
            required_gate=None,
            supported_scopes=("test_bearing_profile",),
        )
    }
    decision = PlanDecision(
        action="test_diagnostic",
        selected_agent="diagnostic_agent",
        rationale="Test profile action",
        expected_result="read-only test result",
        state_version=profile_state.state_version,
    )

    allowed = policy_guard(decision, profile_state, None, catalog)
    assert allowed.verdict == "ALLOW"

    blocked = policy_guard(
        decision,
        ready,
        None,
        catalog,
    )
    assert blocked.verdict == "BLOCK"
    assert blocked.reason_code == "UNSUPPORTED_SCOPE"


def test_runtime_dispatches_registered_agent_and_audits_tool_version(
    manager, ready, tmp_path,
):
    from bearing_agents.orchestration.workflow import open_runtime

    class Planner:
        def plan(self, summary):
            return PlanDecision(
                action="produce_summary",
                selected_agent="tool_agent",
                rationale="Use the registered diagnostic executor",
                expected_result="read-only result",
                state_version=summary.domain_version,
            )

    class ToolAgent:
        def run(self, state, task, *, context):
            value = context.tools.call("sum_values", left=4, right=5)
            return AgentResult(
                task_id=task.id,
                status=AgentResultStatus.SUCCESS,
                issues=[{"value": value}],
            )

    catalog = dict(CATALOG)
    catalog["produce_summary"] = ActionSpec(
        executor_id="tool_agent",
        supported_scopes=("*",),
    )
    tools = ToolRegistry()
    tools.register(
        "sum_values", lambda left, right: left + right,
        allowed_agent_ids={"tool_agent"}, version="3",
    )

    with open_runtime(
        manager,
        tmp_path / "registry-checkpoint.sqlite",
        planner=Planner(),
        agent_registry=AgentRegistry({"tool_agent": ToolAgent()}),
        tool_registry=tools,
        catalog=catalog,
    ) as runtime:
        result = runtime.invoke(ready.design_id)

    assert result["termination_reason"] == "GOAL_REACHED"
    committed = next(row for row in result["trace"] if row["stage"] == "committed")
    assert committed["tool_calls"] == [{
        "tool_id": "sum_values",
        "tool_version": "3",
        "input_digest": committed["tool_calls"][0]["input_digest"],
        "output_digest": committed["tool_calls"][0]["output_digest"],
        "status": "SUCCESS",
    }]
    assert committed["tool_calls"][0]["input_digest"]
    assert committed["tool_calls"][0]["output_digest"]
