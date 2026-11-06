"""PR-15: verifier must be safe offline, bounded, and honest about real API status."""

import json

import pytest
from examples.pr15_live_verification import (
    SCENARIOS,
    evaluate_records,
    main,
    require_live_config,
    run_scenario,
    summarize_run,
)


def test_natural_scenarios_are_not_agent_directives():
    assert set(SCENARIOS) == {"missing_load", "space_limit", "uncertain_design"}
    for turns in SCENARIOS.values():
        assert len(turns) >= 3
        assert all("Agent" not in message and "Supervisor" not in message for message in turns)


def test_offline_verifier_runs_existing_full_application_without_credentials(
    monkeypatch, tmp_path, capsys,
):
    monkeypatch.delenv("BEARING_LLM_API_KEY", raising=False)
    out = tmp_path / "sanitized.json"
    assert main(["--scenario", "missing_load", "--max-steps", "4",
                 "--output", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["summary"]["api_mode"] == "OFFLINE"
    assert document["summary"]["real_api_observed"] is False
    assert document["summary"]["engineering_approval"] is False
    assert len(document["turns"]) == 3
    assert all(item["engineering_acceptance"] == "DOMAIN_PENDING"
               for item in document["turns"])
    assert "sk-" not in out.read_text(encoding="utf-8")
    assert "OFFLINE" in capsys.readouterr().out


def test_verifier_has_a_strict_budget():
    with pytest.raises(ValueError, match="max_steps"):
        run_scenario("missing_load", live=False, max_steps=0)
    with pytest.raises(ValueError, match="max_steps"):
        run_scenario("missing_load", live=False, max_steps=9)


def test_live_mode_requires_explicit_opt_in_before_any_api_call(
    monkeypatch, tmp_path,
):
    monkeypatch.delenv("BEARING_LLM_ENABLED", raising=False)
    with pytest.raises(ValueError, match="BEARING_LLM_ENABLED"):
        main(["--live", "--scenario", "missing_load"])
    monkeypatch.setenv("BEARING_LLM_ENABLED", "true")
    monkeypatch.delenv("BEARING_LLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="BEARING_LLM_API_KEY"):
        require_live_config()
    assert not any(tmp_path.iterdir())


def test_live_failure_redacts_sensitive_provider_error(monkeypatch, capsys):
    import examples.pr15_live_verification as runner

    secret_marker = "sensitive-test-key-never-print"
    monkeypatch.setenv("BEARING_LLM_ENABLED", "true")
    monkeypatch.setenv("BEARING_LLM_API_KEY", secret_marker)
    monkeypatch.setenv("BEARING_LLM_BASE_URL", "https://api.example.invalid")
    monkeypatch.setenv("BEARING_PLANNER_MODEL", "example-model")

    def raise_sensitive_error(*_args, **_kwargs):
        raise RuntimeError("provider error included " + secret_marker)

    monkeypatch.setattr(runner, "run_scenario", raise_sensitive_error)
    assert main(["--live", "--scenario", "missing_load"]) == 2
    assert secret_marker not in capsys.readouterr().out


def test_summary_never_claims_real_api_from_offline_metadata():
    fake = {
        "scenario": "missing_load", "termination": "MISSING_INPUT",
        "planned_actions": [{"action": "clarify_requirement",
                             "model_id": "injected", "token_usage": None}],
        "candidates": [],
    }
    summary = evaluate_records([fake], live=False)
    assert summary["real_api_observed"] is False
    assert summary["engineering_approval"] is False
    assert summary["distinct_action_sequences"] == 1


def test_summarize_run_drops_prompts_headers_and_raw_content():
    class State:
        parameters = {}
        constraints = []
        candidate_designs = []

    execution = {
        "termination_reason": "MISSING_INPUT",
        "trace": [{
            "stage": "plan", "action": "clarify_requirement",
            "reason": "sensitive-untrusted-user-utterance",
            "planner_metadata": {
                "model_id": "deepseek-v4-pro", "latency_ms": 7,
                "token_usage": {"total_tokens": 9},
                "api_key": "do-not-serialize",
            },
        }],
        "questions": [{"text": "sensitive-user-text"}],
    }
    result = summarize_run(execution, State(), scenario="missing_load", turn=1)
    serialized = json.dumps(result, ensure_ascii=False)
    assert "do-not-serialize" not in serialized
    assert "sensitive-user-text" not in serialized
    assert "sensitive-untrusted-user-utterance" not in serialized
    assert result["planned_actions"][0]["model_id"] == "deepseek-v4-pro"


def test_offline_all_scenarios_show_distinct_state_driven_routes():
    records = [
        item
        for name in SCENARIOS
        for item in run_scenario(name, live=False, max_steps=4)
    ]
    assessment = evaluate_records(records, live=False)
    assert assessment["independent_scenarios"] == 3
    assert len(records) == 9
    assert assessment["distinct_action_sequences"] >= 2
    assert assessment["engineering_approval"] is False
    assert all(row["engineering_acceptance"] == "DOMAIN_PENDING" for row in records)


def test_cli_real_error_does_not_echo_provider_error(tmp_path, monkeypatch, capsys):
    import builtins

    import examples.interactive_design as cli
    from bearing_agents.orchestration.contracts import FakePlanner

    secret_marker = "private-marker-from-provider"
    monkeypatch.setattr(cli, "LLMPlanner", lambda: FakePlanner())

    class BadExtractor:
        @staticmethod
        def from_environment():
            return BadExtractor()

        def extract(self, _text):
            raise RuntimeError("Provider error leaked: " + secret_marker)

    monkeypatch.setattr(cli, "LLMExtractor", BadExtractor)
    inputs = iter(["我想设计一个轴承", ":quit"])
    monkeypatch.setattr(builtins, "input", lambda _prompt: next(inputs))
    assert cli.main(["--llm", "--db", str(tmp_path / "test.sqlite")]) == 0
    printed = capsys.readouterr().out
    assert "RuntimeError" in printed
    assert secret_marker not in printed
