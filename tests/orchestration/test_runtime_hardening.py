"""Regression tests for trusted runtime gates and partial task startup."""

from tests.orchestration.conftest import seed_ready

from bearing_agents.core.readiness import StageRequirementRegistry
from bearing_agents.core.state_manager import StateManager, StateManagerError
from bearing_agents.domain.agent_protocols import PlanDecision
from bearing_agents.domain.enums import TaskStatus
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.contracts import CATALOG, policy_guard
from bearing_agents.orchestration.workflow import open_runtime


def test_custom_r2_registry_controls_observe_and_dispatch(tmp_path):
    manager = StateManager(
        SQLiteStateRepository(tmp_path / "domain.sqlite"),
        stage_registry=StageRequirementRegistry({
            "R2": ("journal_diameter", "load", "rotational_speed", "bearing_width")
        }),
    )
    ready = seed_ready(manager)
    assert not manager.readiness_for(ready.design_id, "R2").ready
    with open_runtime(manager, tmp_path / "checkpoint.sqlite") as runtime:
        result = runtime.invoke(ready.design_id)
        assert result["termination_reason"] == "MISSING_INPUT"
        assert not any(row.get("action") == "analyze_conditions"
                       and row.get("stage") == "committed"
                       for row in result["trace"])


def test_candidate_action_requires_current_completed_analysis(ready):
    decision = PlanDecision(
        action="generate_candidate", selected_agent="design_fake",
        rationale="Skip preliminary analysis", expected_result="DEMO_ONLY",
        state_version=ready.state_version,
    )
    verdict = policy_guard(decision, ready, None, CATALOG)
    assert verdict.verdict == "BLOCK"
    assert verdict.reason_code == "ANALYSIS_NOT_READY"


def test_start_failure_expires_registered_task(manager, ready, tmp_path, monkeypatch):
    original = manager.apply_task_command
    failed = {"value": False}

    def fail_start_once(design_id, version, command, *, context):
        if command.kind == "start" and not failed["value"]:
            failed["value"] = True
            raise StateManagerError("synthetic start failure")
        return original(design_id, version, command, context=context)

    monkeypatch.setattr(manager, "apply_task_command", fail_start_once)
    with open_runtime(manager, tmp_path / "checkpoint.sqlite", max_steps=2) as runtime:
        result = runtime.invoke(ready.design_id)
    saved = manager.get_design(ready.design_id)
    assert failed["value"]
    assert all(task.status not in {TaskStatus.PENDING, TaskStatus.RUNNING}
               for task in saved.task_plan)
    assert result["termination_reason"] in {"BUDGET_EXHAUSTED", "NO_PROGRESS", "GOAL_REACHED"}
