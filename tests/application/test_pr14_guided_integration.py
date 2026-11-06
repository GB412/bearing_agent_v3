"""PR-14: guided interaction must not drift from the trusted app configuration."""

import builtins

from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.knowledge.defaults import build_default_knowledge_base
from bearing_agents.application import open_application
from bearing_agents.orchestration.contracts import observe_state
from bearing_agents.orchestration.llm_planner import build_prompt
from bearing_agents.requirements.interaction import InteractionService
from examples.interactive_design import main


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
    prompt = build_prompt(summary)
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
