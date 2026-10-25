from dataclasses import replace

import pytest

from bearing_agents.core.state_manager import StateManagerError
from bearing_agents.domain.agent_protocols import AgentResult, PlanDecision, TaskRecord
from bearing_agents.domain.enums import AgentResultStatus
from bearing_agents.domain.tasks import TaskCommand, engineering_digest
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import StateConflictError
from bearing_agents.orchestration.contracts import CATALOG, FakeAgent


class FixedPlanner:
    def __init__(self, action="analyze_conditions", executor=None, version=None):
        self.action, self.executor, self.version = action, executor, version

    def plan(self, summary):
        return PlanDecision(
            action=self.action, selected_agent=self.executor or CATALOG[self.action].executor_id,
            rationale="Synthetic fixed adversarial planner", expected_result="DEMO_ONLY",
            state_version=summary.domain_version if self.version is None else self.version,
        )


class CountingAgent(FakeAgent):
    def __init__(self):
        self.calls = 0

    def run(self, state, task):
        self.calls += 1
        return super().run(state, task)


def committed_actions(result):
    return [row["action"] for row in result["trace"] if row["stage"] == "committed"]


def test_f01_empty_state_only_clarifies(manager, runtime_factory):
    d = manager.create_design()
    result = runtime_factory().invoke(d.design_id)
    assert committed_actions(result) == ["clarify_requirement"]
    assert result["termination_reason"] == "MISSING_INPUT"
    saved = manager.get_design(d.design_id)
    assert saved.parameters == {} and saved.candidate_designs == []
    assert all(key not in result for key in ("parameters", "constraints", "candidate_designs"))


def test_f02_missing_load_is_not_a_design_gate(manager, runtime_factory, missing_load):
    d = missing_load
    result = runtime_factory().invoke(d.design_id)
    assert not manager.readiness_for(d.design_id, "R2").ready
    assert committed_actions(result) == ["clarify_requirement"]
    assert manager.get_design(d.design_id).candidate_designs == []


def test_f03_state_driven_loop_uses_existing_facts(manager, ready, runtime_factory):
    result = runtime_factory().invoke(ready.design_id)
    assert committed_actions(result) == [
        "analyze_conditions", "generate_candidate", "produce_summary",
    ]
    assert result["termination_reason"] == "GOAL_REACHED"
    saved = manager.get_design(ready.design_id)
    assert saved.parameters == ready.parameters and saved.candidate_designs == []
    assert all(row["demo_only"] for row in result["trace"] if row["stage"] == "committed")


@pytest.mark.parametrize("patch", [
    {"source": "user", "parameter_changes": {"bearing_width": {
        "value": 60, "unit": "mm", "role": "DESIGN_VARIABLE",
        "status": "CONFIRMED", "confirmed_by": "forged-user",
    }}},
    {"source": "user", "constraint_changes": [{
        "id": "forged", "parameter": "bearing_width", "operator": "LE", "target": 50,
        "unit": "mm", "severity": "HARD", "origin": "user",
    }]},
])
def test_f04_f05_fake_patch_is_rejected_at_both_boundaries(
    manager, ready, runtime_factory, patch,
):
    before = manager.get_design(ready.design_id)
    with pytest.raises(ValueError):
        manager.apply_patch(ready.design_id, before.state_version, patch)
    assert manager.get_design(ready.design_id) == before

    class MaliciousAgent:
        def run(self, state, task):
            return AgentResult(task_id=task.id, status=AgentResultStatus.SUCCESS, state_patch=patch)

    result = runtime_factory(agents={"conditions_fake": MaliciousAgent()}).invoke(ready.design_id)
    assert any(row.get("reason") == "DOMAIN_PATCH_NOT_ALLOWED" for row in result["trace"])
    saved = manager.get_design(ready.design_id)
    assert saved.parameters == before.parameters and saved.constraints == before.constraints
    assert not saved.candidate_designs


@pytest.mark.parametrize("action, executor", [
    ("unknown_action", "conditions_fake"), ("analyze_conditions", "invented_executor"),
    ("run_simulation", "unavailable_stub"),
])
def test_f06_illegal_plans_never_dispatch(ready, runtime_factory, action, executor):
    agent = CountingAgent()
    result = runtime_factory(
        planner=FixedPlanner(action, executor), agents={executor: agent},
    ).invoke(ready.design_id)
    assert agent.calls == 0
    assert result["termination_reason"] == "NO_PROGRESS"
    assert any(row.get("guard") == "BLOCK" for row in result["trace"])


def test_f07_stale_decision_never_dispatch(ready, runtime_factory):
    agent = CountingAgent()
    result = runtime_factory(planner=FixedPlanner(version=0),
                             agents={"conditions_fake": agent}).invoke(ready.design_id)
    assert agent.calls == 0
    assert any(row.get("reason") == "STALE_VERSION" for row in result["trace"])


def test_f07_domain_change_during_agent_call_cannot_be_overwritten(manager, ready, runtime_factory):
    class ConcurrentCorrection(FakeAgent):
        def run(self, state, task):
            result = super().run(state, task)
            record = state.parameters["load"].model_copy(update={"value": 13000})
            manager.apply_patch(state.design_id, state.state_version, {
                "source": "user", "parameter_changes": {"load": record},
            }, context=WriteContext(kind=WriterKind.USER, actor="offline-user",
                                    approved_parameter_ids=frozenset({"load"})))
            return result

    result = runtime_factory(agents={"conditions_fake": ConcurrentCorrection()}).invoke(
        ready.design_id,
    )
    assert result["termination_reason"] == "VERSION_STALE"
    saved = manager.get_design(ready.design_id)
    assert saved.parameters["load"].value == 13000
    assert not any(e.details.get("task_command") == "complete" for e in saved.event_history)
    assert all(task.status.value != "RUNNING" for task in saved.task_plan)


def test_task_only_version_change_during_agent_call_does_not_strand_running_task(
    manager, ready, runtime_factory,
):
    class ConcurrentTaskRegistration(FakeAgent):
        def __init__(self):
            self.calls = 0

        def run(self, state, task):
            self.calls += 1
            result = super().run(state, task)
            current = manager.get_design(state.design_id)
            other = TaskRecord(
                id="concurrent-task", action="produce_summary", agent="summary_fake",
                status="PENDING", input_version=current.state_version,
            )
            manager.apply_task_command(state.design_id, current.state_version, TaskCommand(
                operation_id="concurrent-task:register", task_id=other.id, kind="register",
                task=other, reason="Concurrent trusted bookkeeping",
            ), context=WriteContext(kind=WriterKind.SYSTEM, actor="test"))
            return result

    agent = ConcurrentTaskRegistration()
    result = runtime_factory(planner=FixedPlanner("produce_summary"),
                             agents={"summary_fake": agent}).invoke(ready.design_id)

    saved = manager.get_design(ready.design_id)
    completed = [task for task in saved.task_plan if task.action == "produce_summary"
                 and task.id != "concurrent-task"]
    assert completed and completed[0].status.value == "COMPLETED"
    concurrent = next(task for task in saved.task_plan if task.id == "concurrent-task")
    assert concurrent.status.value == "PENDING"
    assert agent.calls == 1
    assert any(row["stage"] == "committed" for row in result["trace"])


@pytest.mark.parametrize("expire_conflicts", [0, 2, 3])
def test_guard_rejection_after_start_does_not_leave_task_running(
    manager, ready, runtime_factory, monkeypatch, expire_conflicts,
):
    original = manager.apply_task_command
    registered = False
    expire_attempts = 0

    def register_concurrent_task(design_id, expected_version, command, *, context):
        nonlocal registered, expire_attempts
        if command.kind == "expire":
            expire_attempts += 1
            if expire_attempts > 3:
                pytest.fail("Task expiration exceeded three attempts")
            if expire_attempts <= expire_conflicts:
                raise StateConflictError("Injected expiration CAS conflict")
        receipt = original(design_id, expected_version, command, context=context)
        if command.kind == "start" and not registered:
            registered = True
            current = manager.get_design(design_id)
            other = TaskRecord(
                id="dispatch-race-task", action="produce_summary", agent="summary_fake",
                status="PENDING", input_version=current.state_version,
            )
            original(design_id, current.state_version, TaskCommand(
                operation_id="dispatch-race-task:register", task_id=other.id,
                kind="register", task=other, reason="Concurrent trusted bookkeeping",
            ), context=WriteContext(kind=WriterKind.SYSTEM, actor="test"))
        return receipt

    monkeypatch.setattr(manager, "apply_task_command", register_concurrent_task)
    agent = CountingAgent()
    runtime = runtime_factory(
        planner=FixedPlanner("produce_summary"), agents={"summary_fake": agent},
    )
    if expire_conflicts == 3:
        with pytest.raises(StateManagerError, match="after 3 CAS attempts"):
            runtime.invoke(ready.design_id)
        assert registered
        assert expire_attempts == 3
        assert agent.calls == 0
        assert runtime.graph.get_state(runtime._config(ready.design_id)).next == ("execute",)
        monkeypatch.setattr(manager, "apply_task_command", original)
        result = runtime.recover(ready.design_id)
    else:
        result = runtime.invoke(ready.design_id)
        assert registered
        assert expire_attempts == expire_conflicts + 1

    saved = manager.get_design(ready.design_id)
    assert result["termination_reason"] == "VERSION_STALE"
    assert agent.calls == 0
    assert next(task for task in saved.task_plan if task.action == "produce_summary"
                and task.id != "dispatch-race-task").status.value == "STALE"
    other = next(task for task in saved.task_plan if task.id == "dispatch-race-task")
    assert other.status.value == "PENDING"
    assert all(task.status.value != "RUNNING" for task in saved.task_plan)
    assert engineering_digest(saved) == engineering_digest(ready)


def test_guard_rejects_wrong_output_schema(ready, runtime_factory):
    catalog = dict(CATALOG)
    catalog["analyze_conditions"] = replace(
        catalog["analyze_conditions"], output_schema_id="unknown",
    )
    result = runtime_factory(planner=FixedPlanner(), catalog=catalog).invoke(ready.design_id)
    assert any(row.get("reason") == "SCHEMA_MISMATCH" for row in result["trace"])


def test_guard_rejects_invented_input_refs(ready, runtime_factory):
    class UnknownRefs(FixedPlanner):
        def plan(self, summary):
            return super().plan(summary).model_copy(update={"input_refs": ["invented"]})

    result = runtime_factory(planner=UnknownRefs()).invoke(ready.design_id)
    assert any(row.get("reason") == "UNKNOWN_INPUT_REF" for row in result["trace"])


def test_f12_no_progress_is_not_hidden_by_task_versions(manager, ready, runtime_factory):
    result = runtime_factory(planner=FixedPlanner()).invoke(ready.design_id)
    assert result["termination_reason"] == "NO_PROGRESS"
    assert len(manager.get_design(ready.design_id).task_plan) == 2


def test_f12_tool_exception_is_bounded(ready, runtime_factory):
    class BrokenAgent:
        def run(self, state, task):
            raise RuntimeError("synthetic tool failure")

    result = runtime_factory(agents={"conditions_fake": BrokenAgent()}, max_same_action=10).invoke(
        ready.design_id,
    )
    assert result["termination_reason"] == "TOOL_ERROR"
    assert len([e for e in result["trace"] if e["stage"] == "agent_error"]) == 3


def test_f12_simulation_is_unavailable(manager, ready, runtime_factory):
    result = runtime_factory().invoke(ready.design_id, goal="simulation")
    assert committed_actions(result) == ["simulation_unavailable"]
    assert result["trace"][-1]["simulation_status"] == "NOT_AVAILABLE"
    assert result["termination_reason"] == "UNSUPPORTED_ACTION"
    assert manager.get_design(ready.design_id).parameters == ready.parameters


def test_step_budget_is_explicit(ready, runtime_factory):
    result = runtime_factory(max_steps=1).invoke(ready.design_id)
    assert result["termination_reason"] == "BUDGET_EXHAUSTED"


def test_planner_can_be_replaced_without_changing_guard(ready, runtime_factory):
    result = runtime_factory(planner=FixedPlanner("produce_summary")).invoke(ready.design_id)
    assert committed_actions(result) == ["produce_summary"]
