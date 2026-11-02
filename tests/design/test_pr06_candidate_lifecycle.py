import pytest

from bearing_agents.core.state_manager import StateManagerError, VersionConflictError
from bearing_agents.design.agent import DesignAgent
from bearing_agents.domain.agent_protocols import AgentResult, StatePatch, TaskRecord
from bearing_agents.domain.candidates import CandidateDesign, CandidatePrecheckReport
from bearing_agents.domain.enums import (
    AgentResultStatus,
    ParameterRole,
    ParameterStatus,
    PrecheckStatus,
    TaskStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.orchestration.contracts import validate_result
from bearing_agents.validation.agent import RuleCoverageSpec, ValidationAgent

SYSTEM = WriteContext(kind=WriterKind.SYSTEM, actor="pr06-validation")
USER = WriteContext(kind=WriterKind.USER, actor="test-designer")


def partial_candidate():
    return CandidateDesign(
        candidate_id="partial-01",
        version=1,
        parameters={
            "bearing_width": ParameterRecord(
                value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
                source="synthetic-fixture", source_ref="fixture-only",
            )
        },
    )


def test_partial_candidate_is_saved_with_missing_fields_and_authoritative_dependencies(
    manager, ready,
):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="design_agent", candidate_additions=[partial_candidate()]),
    )
    candidate = state.candidate_designs[-1]
    assert candidate.completeness_status == "PARTIAL"
    assert set(candidate.unresolved_parameters) == {
        "radial_clearance", "material", "lubricant"
    }
    assert candidate.precheck_status == PrecheckStatus.NOT_EVALUATED
    assert candidate.confirmation_status.value == "PENDING"
    assert candidate.input_dependency_refs["parameter:journal_diameter"] == "1"
    assert state.parameters == ready.parameters


def test_source_cannot_fake_complete_status_or_precheck_pass(manager, ready):
    forged = partial_candidate().model_copy(update={"completeness_status": "COMPLETE"})
    with pytest.raises(StateManagerError, match="cannot claim COMPLETE"):
        manager.apply_patch(
            ready.design_id, ready.state_version,
            StatePatch(source="untrusted", candidate_additions=[forged]),
        )
    forged = partial_candidate().model_copy(
        update={"precheck_status": PrecheckStatus.PRECHECK_PASS}
    )
    with pytest.raises(StateManagerError, match="must start PENDING"):
        manager.apply_patch(
            ready.design_id, ready.state_version,
            StatePatch(source="untrusted", candidate_additions=[forged]),
        )


def test_validation_is_review_required_with_missing_inputs_and_draft_rules(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[partial_candidate()]),
    )
    report = ValidationAgent().evaluate(state, state.candidate_designs[-1])
    assert report.status == PrecheckStatus.REVIEW_REQUIRED
    assert set(report.missing_parameters) == {
        "radial_clearance", "material", "lubricant"
    }
    assert report.uncovered_rules
    persisted = manager.record_candidate_precheck(
        state.design_id, state.state_version, report, context=SYSTEM,
    )
    candidate = persisted.candidate_designs[-1]
    assert candidate.precheck_status == PrecheckStatus.REVIEW_REQUIRED
    assert candidate.precheck_report == report
    assert candidate.confirmation_status.value == "PENDING"


def test_empty_coverage_is_not_a_vacuous_pass():
    with pytest.raises(ValueError, match="nonempty"):
        RuleCoverageSpec(required_rule_ids=())
    with pytest.raises(ValueError, match="unique"):
        RuleCoverageSpec(required_rule_ids=("same", "same"))


def test_fake_pass_report_is_blocked_even_with_system_context(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[partial_candidate()]),
    )
    report = CandidatePrecheckReport(
        candidate_id="partial-01", candidate_version=1,
        input_digest=__import__(
            "bearing_agents.domain.tasks", fromlist=["engineering_digest"]
        ).engineering_digest(state),
        status=PrecheckStatus.PRECHECK_PASS,
        checks=[{"status": "PASS"}],
    )
    with pytest.raises(StateManagerError, match="cannot PASS"):
        manager.record_candidate_precheck(
            state.design_id, state.state_version, report, context=SYSTEM,
        )


def test_precheck_requires_trusted_system_and_current_snapshot(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[partial_candidate()]),
    )
    report = ValidationAgent().evaluate(state, state.candidate_designs[-1])
    with pytest.raises(StateManagerError, match="SYSTEM"):
        manager.record_candidate_precheck(
            state.design_id, state.state_version, report, context=USER,
        )
    with pytest.raises(VersionConflictError):
        manager.record_candidate_precheck(
            state.design_id, state.state_version - 1, report, context=SYSTEM,
        )


def test_candidate_becomes_stale_after_authoritative_input_change(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[partial_candidate()]),
    )
    report = ValidationAgent().evaluate(state, state.candidate_designs[-1])
    checked = manager.record_candidate_precheck(
        state.design_id, state.state_version, report, context=SYSTEM,
    )
    changed = manager.apply_patch(
        state.design_id, checked.state_version,
        {"source": "user", "parameter_changes": {
            "load": ParameterRecord(
                value=15000, unit="N", role=ParameterRole.FIXED_INPUT,
                status=ParameterStatus.PROVIDED,
            ),
        }},
        context=WriteContext(
            kind=WriterKind.USER, actor="test-designer",
            approved_parameter_ids=frozenset({"load"}),
            verified_parameter_refs={"load": "load-update-message"},
        ),
    )
    assert changed.candidate_designs[-1].precheck_status == PrecheckStatus.STALE
    with pytest.raises(StateManagerError, match="stale candidate"):
        manager.record_candidate_precheck(
            changed.design_id, changed.state_version,
            ValidationAgent().evaluate(changed, changed.candidate_designs[-1]),
            context=SYSTEM,
        )


def test_agent_domain_patch_is_restricted_to_single_candidate():
    task = TaskRecord(
        id="task", action="generate_candidate", agent="design_fake",
        status=TaskStatus.RUNNING, input_version=0,
    )
    malicious = AgentResult(
        task_id=task.id, status=AgentResultStatus.SUCCESS,
        state_patch=StatePatch(
            source="design_agent", candidate_additions=[partial_candidate()],
            parameter_changes={
                "journal_diameter": ParameterRecord(
                    value=1, unit="mm", role=ParameterRole.FIXED_INPUT,
                    status=ParameterStatus.SUGGESTED,
                )
            },
        ),
    )
    with pytest.raises(ValueError, match="FORBIDDEN"):
        validate_result(malicious, task.id, allow_candidate_additions=True)
    with pytest.raises(ValueError, match="DOMAIN_PATCH_NOT_ALLOWED"):
        validate_result(
            AgentResult(
                task_id=task.id, status=AgentResultStatus.SUCCESS,
                state_patch=StatePatch(
                    source="design_agent", candidate_additions=[partial_candidate()]
                ),
            ),
            task.id,
        )


def test_design_agent_can_propose_partial_from_user_supplied_width(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        {"source": "user", "parameter_changes": {
            "bearing_width": ParameterRecord(
                value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.PROVIDED,
            )
        }},
        context=WriteContext(
            kind=WriterKind.USER, actor="test-designer",
            verified_parameter_refs={"bearing_width": "user-width-message"},
        ),
    )
    task = TaskRecord(
        id="task", action="generate_candidate", agent="design_fake",
        status=TaskStatus.RUNNING, input_version=state.state_version,
    )
    result = DesignAgent().run(state, task)
    assert result.status == AgentResultStatus.NEEDS_REVIEW
    assert result.state_patch is not None
    assert result.state_patch.candidate_additions[0].unresolved_parameters == [
        "radial_clearance", "material", "lubricant",
    ]
    assert result.state_patch.candidate_additions[0].parameters["bearing_width"].status == (
        ParameterStatus.SUGGESTED
    )
