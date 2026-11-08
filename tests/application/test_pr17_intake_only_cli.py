"""A separate requirements acceptance path must not schedule any agent actions."""

import builtins

from bearing_agents.requirements.contracts import RequirementProposal
from examples import interactive_design


def test_intake_only_writes_complete_state_without_supervisor(tmp_path, monkeypatch, capsys):
    text = "圆柱径向动压滑动轴承，轴径100mm，载荷12kN，转速1500rpm，单一稳态"
    values = iter([text, ":quit"])
    monkeypatch.setattr(builtins, "input", lambda _: next(values))
    assert interactive_design.main([
        "--intake-only", "--db", str(tmp_path / "intake.sqlite"),
    ]) == 0
    printed = capsys.readouterr().out
    assert "INTAKE_ONLY" in printed
    assert "R2就绪=True" in printed
    assert "工况 nominal: 单一稳态=True" in printed
    assert "Supervisor:" not in printed


def test_real_llm_intake_mode_never_builds_planner(tmp_path, monkeypatch, capsys):
    class NoPlanner:
        def __init__(self):
            raise AssertionError("Planner must not be created in intake-only mode")

    class FakeExtractor:
        last_recovery = None

        @classmethod
        def from_environment(cls):
            return cls()

        def extract(self, text):
            assert text == "轴径100mm"
            return [RequirementProposal(
                kind="parameter", field_id="journal_diameter", value=100, unit="mm",
            )]

    monkeypatch.setattr(interactive_design, "LLMPlanner", NoPlanner)
    monkeypatch.setattr(interactive_design, "LLMExtractor", FakeExtractor)
    texts = iter(["轴径100mm", ":run", ":quit"])
    monkeypatch.setattr(builtins, "input", lambda _: next(texts))
    assert interactive_design.main([
        "--llm", "--intake-only", "--db", str(tmp_path / "real-intake.sqlite"),
    ]) == 0
    output = capsys.readouterr().out
    assert "REAL_LLM" in output
    assert "100.0 mm" in output
    assert "需求录入模式不执行 Supervisor" in output
    assert "Supervisor:" not in output
