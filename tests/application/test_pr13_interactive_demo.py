"""PR-13 offline smoke tests: all model API calls remain explicit opt-ins."""

import builtins

import pytest
from examples.interactive_design import main, render_report

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.enums import ParameterRole
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.llm_planner import PlannerError
from bearing_agents.requirements.extraction import extract
from bearing_agents.requirements.interaction import InteractionService


def test_natural_language_design_width_is_verified_but_width_limit_is_constraint(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "domain.sqlite"))
    svc = InteractionService(manager, actor="demo-user")
    design = svc.create_design("圆柱径向动压滑动轴承")
    svc.submit_turn(
        design.design_id,
        "我要设计圆柱径向动压滑动轴承，单一稳态，轴径100mm，"
        "载荷12kN，转速1500rpm，轴承宽度60mm，径向间隙0.1mm",
        "turn-one",
    )
    state = manager.get_design(design.design_id)
    assert state.parameters["bearing_width"].role == ParameterRole.DESIGN_VARIABLE
    assert state.parameters["bearing_width"].verified_source_ref
    assert state.parameters["radial_clearance"].value == pytest.approx(0.1)
    assert manager.readiness_for(design.design_id, "R2").ready
    assert not any(
        prop.kind == "parameter" and prop.field_id == "bearing_width"
        for prop in extract("轴承宽度不能超过70mm")
    )
    svc.submit_turn(design.design_id, "轴承宽度不能超过70mm", "turn-two")
    constraints = manager.get_design(design.design_id).constraints
    assert len(constraints) == 1
    assert not constraints[0].approved


def test_cli_offline_dialogue_and_report(tmp_path, monkeypatch, capsys):
    db = tmp_path / "demo.sqlite"
    report = tmp_path / "report.md"
    answers = iter([
        "我要设计圆柱径向动压滑动轴承，单一稳态，轴径100mm，"
        "载荷12kN，转速1500rpm，轴承宽度60mm",
        f":report {report}",
        ":quit",
    ])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(answers))
    assert main(["--db", str(db)]) == 0
    text = capsys.readouterr().out
    assert "OFFLINE" in text
    assert "Supervisor" in text
    assert "ENGINEERING_DOMAIN_PENDING" in text
    data = report.read_text(encoding="utf-8")
    assert "# 多 Agent 轴承设计过程记录" in data
    assert "bearing_width" in data
    assert "NOT_AVAILABLE" in data
    assert "ENGINEERING_DOMAIN_PENDING" in data


def test_real_model_mode_never_implicitly_falls_back_to_fake(tmp_path, monkeypatch):
    monkeypatch.delenv("BEARING_LLM_ENABLED", raising=False)
    with pytest.raises(PlannerError, match="BEARING_LLM_ENABLED"):
        main(["--llm", "--db", str(tmp_path / "unused.sqlite")])
    assert not (tmp_path / "unused.sqlite").exists()


def test_report_is_explicit_about_unverified_professional_coverage(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "report.sqlite"))
    state = manager.create_design()
    report = render_report(state)
    assert "ENGINEERING_DOMAIN_PENDING" in report
    assert "DLAP" in report
    assert "NOT_AVAILABLE" in report
