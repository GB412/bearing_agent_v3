"""PR-14: guided interaction must not drift from the trusted app configuration."""

import builtins

import pytest
from examples.interactive_design import guided_options, main, resolve_guided_option

from bearing_agents.application import open_application
from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.agent_protocols import PlanDecision
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.knowledge.defaults import build_default_knowledge_base
from bearing_agents.orchestration.contracts import PlannerContext, observe_state
from bearing_agents.orchestration.llm_planner import build_prompt
from bearing_agents.requirements.interaction import InteractionService


def test_application_uses_same_validator_and_knowledge_for_runtime_and_service(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "state.sqlite"))
    knowledge = build_default_knowledge_base()
    with open_application(
        manager, tmp_path / "checkpoint.sqlite", actor="designer", knowledge=knowledge,
    ) as application:
        validator = application.runtime.agent_registry.get("validation_agent")
        assert application.validation_service.agent is validator
        assert validator.knowledge is knowledge


def test_planner_sees_bounded_unverified_user_intent_without_state_mutation(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "state.sqlite"))
    state = manager.create_design(user_goal="滑动轴承初步设计")
    summary = observe_state(
        state, "design", None,
        recent_text="齿轮箱轴承，可靠性优先，我想先知道还缺什么",
    )
    assert summary.scenario_hint == "gearbox"
    assert "reliability" in summary.objective_hints
    assert len(summary.recent_user_request) <= 160
    prompt = build_prompt(summary, PlannerContext())
    assert "UNVERIFIED_HINT" in prompt
    assert "reliability" in prompt
    assert "gearbox" in prompt
    assert state.parameters == {}
    assert state.constraints == []


def test_guided_cli_numbered_user_approval_and_confirmation(tmp_path, monkeypatch, capsys):
    db = tmp_path / "demo.sqlite"
    manager = StateManager(SQLiteStateRepository(db))
    design = InteractionService(manager, actor="local-engineer").create_design(
        "油润滑圆柱径向动压滑动轴承初步设计"
    )
    inputs = iter([
        "我要设计圆柱径向动压滑动轴承，单一稳态，轴径100mm，载荷12kN，转速1500rpm，轴承宽度60mm",
        "轴承宽度不能超过70mm",
        ":approve 1",
        ":confirm 1",
        ":quit",
    ])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(inputs))
    assert main(["--db", str(db), "--design-id", design.design_id]) == 0
    saved = manager.get_design(design.design_id)
    assert len(saved.constraints) == 1
    assert saved.constraints[0].approved is True
    assert any(item.confirmed_by for item in saved.parameters.values())
    stdout = capsys.readouterr().out
    assert "可选择操作" in stdout
    assert "为什么需要" in stdout


def test_numbered_confirmation_rejects_stale_displayed_revision(tmp_path):

    manager = StateManager(SQLiteStateRepository(tmp_path / "state.sqlite"))
    service = InteractionService(manager, actor="local-engineer")
    design = service.create_design("圆柱径向动压滑动轴承")
    service.submit_turn(
        design.design_id, "轴承宽度60mm", "width-initial",
    )
    shown = guided_options(manager.get_design(design.design_id))
    assert any(item[0] == "confirm" for item in shown)
    state = manager.get_design(design.design_id)
    assert state.parameters["bearing_width"].revision == 1
    service.correct_parameter(
        design.design_id, "bearing_width", 1,
        "轴承宽度65mm", "width-correction",
    )
    new_state = manager.get_design(design.design_id)
    assert new_state.parameters["bearing_width"].revision != 1
    with pytest.raises(ValueError, match="选项或版本已变化"):
        resolve_guided_option(new_state, "confirm", "1", shown)


def test_actual_application_runtime_receives_latest_user_intent(tmp_path):
    class CapturePlanner:
        def __init__(self):
            self.seen = []

        def plan(self, summary, *, context=None):
            self.seen.append(summary)
            return PlanDecision(
                action="clarify_requirement",
                selected_agent="requirements_fake",
                rationale="unverified intent needs clarification",
                expected_result="questions",
                state_version=summary.domain_version,
            )

    manager = StateManager(SQLiteStateRepository(tmp_path / "state.sqlite"))
    planner = CapturePlanner()
    with open_application(
        manager, tmp_path / "checkpoint.sqlite",
        actor="designer", planner=planner,
    ) as application:
        design = application.create_design("初步设计")
        application.submit_turn(
            design.design_id,
            "我要设计齿轮箱用的滑动轴承，可靠性优先，请先引导我。",
            "intent-turn",
            goal="design",
        )
    assert planner.seen
    assert planner.seen[0].scenario_hint == "gearbox"
    assert "reliability" in planner.seen[0].objective_hints
    assert not manager.get_design(design.design_id).constraints
