"""PR-10: evidence-bound diagnosis, without granting LLM or Agent engineering authority."""

import pytest

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.agent_protocols import StatePatch
from bearing_agents.domain.candidates import CandidateDesign, CandidatePrecheckReport
from bearing_agents.domain.enums import ParameterRole, ParameterStatus, PrecheckStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.validation.diagnosis import diagnose_precheck
from bearing_agents.validation.service import ValidationService


def partial_candidate():
    return CandidateDesign(
        candidate_id="pr10-test", version=1,
        parameters={
            "bearing_width": ParameterRecord(
                value=50, unit="mm",
                role=ParameterRole.DESIGN_VARIABLE, status=ParameterStatus.SUGGESTED,
            ),
        },
    )


def test_diagnose_stored_report_shows_missing_inputs_and_rule_gaps(manager, ready):
    saved = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test-fixture", candidate_additions=[partial_candidate()]),
    )
    service = ValidationService(manager)
    report = service.assess(saved.design_id, "pr10-test", 1)
    assert report.status == PrecheckStatus.REVIEW_REQUIRED
    diagnosis = service.diagnose(saved.design_id, "pr10-test", 1)
    assert diagnosis.precheck_status == PrecheckStatus.REVIEW_REQUIRED
    assert any(item.kind == "MISSING_PARAMETER" for item in diagnosis.findings)
    assert any(item.kind == "RULE_COVERAGE_GAP" for item in diagnosis.findings)
    assert all(not item.adjustable_parameter_ids for item in diagnosis.findings)
    assert manager.get_design(saved.design_id).candidate_designs[0].precheck_report == report


def test_diagnosis_rejects_nonexistent_candidate_or_unstored_report(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="fixture", candidate_additions=[partial_candidate()]),
    )
    service = ValidationService(manager)
    with pytest.raises(ValueError, match="no stored"):
        service.diagnose(state.design_id, "pr10-test", 1)
    with pytest.raises(ValueError, match="no stored"):
        service.diagnose(state.design_id, "wrong", 1)


def test_diagnosis_only_suggests_unconfirmed_design_variables(manager, ready):
    saved = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="fixture", candidate_additions=[partial_candidate()]),
    )
    candidate = saved.candidate_designs[0]
    report = CandidatePrecheckReport(
        candidate_id=candidate.candidate_id,
        candidate_version=candidate.version,
        input_digest="synthetic-only",
        status=PrecheckStatus.PRECHECK_FAIL,
        checks=[
            {"rule_id": "synthetic-width-check", "status": "FAIL",
             "parameter_id": "bearing_width", "source_ref": "fixture-rule"},
            {"rule_id": "synthetic-load-check", "status": "FAIL",
             "parameter_id": "load", "source_ref": "fixture-rule"},
        ],
    )
    candidate.precheck_report = report
    candidate.precheck_status = PrecheckStatus.PRECHECK_FAIL
    diagnosis = diagnose_precheck(saved, candidate, report)
    checks = [item for item in diagnosis.findings if item.kind == "RULE_FAILURE"]
    assert len(checks) == 2
    assert checks[0].adjustable_parameter_ids == ["bearing_width"]
    assert checks[1].adjustable_parameter_ids == []
    assert checks[1].next_action == "EXPERT_REVIEW"
    assert diagnosis.precheck_status == PrecheckStatus.PRECHECK_FAIL

    candidate.parameters["bearing_width"].confirmed_by = "trusted-user"
    candidate.parameters["bearing_width"].status = ParameterStatus.CONFIRMED
    confirmed_diagnosis = diagnose_precheck(saved, candidate, report)
    assert not any(item.adjustable_parameter_ids for item in confirmed_diagnosis.findings)


def test_stale_candidate_requires_recheck_and_never_uses_old_failures(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="fixture", candidate_additions=[partial_candidate()]),
    )
    candidate = state.candidate_designs[0]
    old_report = CandidatePrecheckReport(
        candidate_id=candidate.candidate_id, candidate_version=1,
        input_digest="synthetic-only", status=PrecheckStatus.PRECHECK_FAIL,
        checks=[{"rule_id": "fixture", "status": "FAIL", "parameter_id": "bearing_width"}],
    )
    candidate.precheck_report = old_report
    candidate.precheck_status = PrecheckStatus.STALE
    diagnosis = diagnose_precheck(state, candidate, old_report)
    assert diagnosis.precheck_status == PrecheckStatus.STALE
    assert [item.kind for item in diagnosis.findings] == ["STALE_RESULT"]
    assert diagnosis.findings[0].next_action == "RECHECK_INPUT"


def test_mismatch_between_candidate_and_stored_report_is_rejected(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="fixture", candidate_additions=[partial_candidate()]),
    )
    candidate = state.candidate_designs[0]
    valid = CandidatePrecheckReport(
        candidate_id=candidate.candidate_id, candidate_version=1,
        input_digest="synthetic-only", status=PrecheckStatus.REVIEW_REQUIRED,
    )
    candidate.precheck_report = valid
    candidate.precheck_status = PrecheckStatus.REVIEW_REQUIRED
    forged = valid.model_copy(update={"input_digest": "forged"})
    with pytest.raises(ValueError, match="persisted"):
        diagnose_precheck(state, candidate, forged)
    with pytest.raises(ValueError, match="authoritative"):
        diagnose_precheck(
            state,
            candidate.model_copy(update={"candidate_id": "not-this-one"}),
            valid,
        )


def test_successful_precheck_does_not_invent_adjustment_recommendations(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="fixture", candidate_additions=[partial_candidate()]),
    )
    candidate = state.candidate_designs[0]
    report = CandidatePrecheckReport(
        candidate_id=candidate.candidate_id, candidate_version=1,
        input_digest="synthetic-only", status=PrecheckStatus.PRECHECK_PASS,
        checks=[{"rule_id": "fixture", "status": "PASS"}],
    )
    candidate.precheck_report = report
    candidate.precheck_status = PrecheckStatus.PRECHECK_PASS
    diagnosis = diagnose_precheck(state, candidate, report)
    assert diagnosis.findings == []
