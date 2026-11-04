"""PR-09: strategy plans, bounded adviser outputs, and evidence-only comparison."""

import json

import pytest

from bearing_agents.design.advisory import StrategyAdviceError, StrategyAdvisor
from bearing_agents.design.agent import DesignAgent
from bearing_agents.design.comparison import compare_candidates
from bearing_agents.domain.candidates import CandidateDesign, CandidatePrecheckReport
from bearing_agents.domain.enums import PrecheckStatus


def _steps(strategy):
    return {item.step_id: item for item in strategy.analysis_steps}


def test_analysis_plan_distinguishes_derived_values_from_solver_gaps(ready):
    strategy = DesignAgent().build_strategy(ready)
    steps = _steps(strategy)
    assert steps["surface_speed"].status == "DERIVED"
    assert steps["mean_pressure"].status == "NEEDS_DESIGN_VARIABLE"
    assert steps["minimum_film_thickness"].status == "SOLVER_NOT_AVAILABLE"
    assert steps["thermal_balance"].status == "SOLVER_NOT_AVAILABLE"
    assert steps["material_limits"].status == "NEEDS_REVIEWED_RULE"
    assert steps["lubricant_selection"].status == "NEEDS_REVIEWED_RULE"
    assert strategy.unverified_advisory is None
    assert not any(
        "pass" in item.lower() for item in strategy.risk_questions
    )


def test_known_width_allows_kinematic_pressure_indicator_without_safety_claim(ready):
    from bearing_agents.domain.enums import ParameterRole, ParameterStatus
    from bearing_agents.domain.parameters import ParameterRecord

    state = ready.model_copy(deep=True)
    state.parameters["bearing_width"] = ParameterRecord(
        value=60, unit="mm",
        role=ParameterRole.DESIGN_VARIABLE,
        status=ParameterStatus.PROVIDED,
        verified_source_ref="test-user-evidence",
    )
    analysis = DesignAgent().analyze_conditions(state)
    assert analysis.derived_metrics["mean_pressure"]["value"] == pytest.approx(2e6)
    assert _steps(DesignAgent().build_strategy(state))["mean_pressure"].status == "DERIVED"


class StubAdvisor:
    def __init__(self, mode="good"):
        self.mode = mode
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        keys = [item["step_id"] for item in json.loads(prompt)["steps"]]
        if self.mode == "invent":
            keys[-1] = "invented_film_thickness_0_001mm"
        if self.mode == "unsafe":
            message = "膜厚已经合格，完全安全"
        else:
            message = "建议优先说明润滑条件和热过程的未知项"
        return {"ordered_step_ids": list(reversed(keys)), "explanation": message}


def test_model_can_only_reorder_existing_steps_and_is_explicitly_unverified(ready):
    model = StubAdvisor()
    agent = DesignAgent(strategy_advisor=StrategyAdvisor(model))
    strategy = agent.build_strategy(ready)
    ids = [item.step_id for item in strategy.analysis_steps]
    assert ids[0] == "lubricant_selection"
    assert set(ids) == {
        "surface_speed", "mean_pressure", "minimum_film_thickness",
        "thermal_balance", "material_limits", "lubricant_selection",
    }
    assert strategy.unverified_advisory.startswith("未审核模型建议")
    assert model.calls
    assert "model" not in strategy.available_rule_refs


@pytest.mark.parametrize("mode", ["invent", "unsafe"])
def test_model_cannot_invent_analysis_step_or_claim_engineering_safety(ready, mode):
    agent = DesignAgent(strategy_advisor=StrategyAdvisor(StubAdvisor(mode)))
    with pytest.raises(StrategyAdviceError):
        agent.build_strategy(ready)


def test_no_prechecks_means_no_claim_of_optimization():
    first = CandidateDesign(candidate_id="a", version=1)
    second = CandidateDesign(candidate_id="b", version=1)
    result = compare_candidates(first, second)
    assert result.comparability == "INCOMPARABLE"
    assert result.preferred_ref is None
    assert result.reasons


def test_candidate_precheck_comparison_requires_identical_evidence_and_completeness():
    common = {
        "completeness_status": "COMPLETE",
        "rule_set_version": "reviewed-1",
        "source_parameter_revisions": {"journal_diameter": 1, "load": 1},
        "input_constraint_revisions": {"width-limit": 1},
        "input_dependency_refs": {"parameter:load": "1", "parameter:journal_diameter": "1"},
    }

    def candidate(name, status):
        report = CandidatePrecheckReport(
            candidate_id=name, candidate_version=1,
            input_digest="synthetic-test-input",
            rule_set_version="reviewed-1",
            status=status,
            checks=[{
                "rule_id": "verified-test-rule",
                "status": "PASS" if status == PrecheckStatus.PRECHECK_PASS else "FAIL",
            }],
            evidence_refs=["synthetic-test-evidence"],
        )
        return CandidateDesign(
            candidate_id=name, version=1, **common,
            precheck_status=status, precheck_report=report,
        )

    passed = candidate("passed", PrecheckStatus.PRECHECK_PASS)
    failed = candidate("failed", PrecheckStatus.PRECHECK_FAIL)
    result = compare_candidates(passed, failed)
    assert result.comparability == "COMPARABLE"
    assert result.preferred_ref == "candidate:passed@1"
    assert result.evidence_refs == ["synthetic-test-evidence"]

    changed = failed.model_copy(deep=True)
    changed.input_dependency_refs["parameter:load"] = "2"
    invalidated = compare_candidates(passed, changed)
    assert invalidated.comparability == "INCOMPARABLE"
    assert invalidated.preferred_ref is None


def test_conflicting_stored_report_status_blocks_comparison():
    report = CandidatePrecheckReport(
        candidate_id="first", candidate_version=1,
        input_digest="synthetic",
        status=PrecheckStatus.PRECHECK_PASS,
        checks=[{"rule_id": "r", "status": "PASS"}],
    )
    first = CandidateDesign(
        candidate_id="first", version=1,
        completeness_status="COMPLETE",
        precheck_status=PrecheckStatus.PRECHECK_FAIL,
        precheck_report=report,
    )
    second = CandidateDesign(
        candidate_id="second", version=1,
        completeness_status="COMPLETE",
        precheck_status=PrecheckStatus.PRECHECK_FAIL,
        precheck_report=report.model_copy(update={"candidate_id": "second"}),
    )
    compared = compare_candidates(first, second)
    assert compared.comparability == "INCOMPARABLE"
    assert compared.preferred_ref is None
