"""PR-11: targeted planning, partial metrics and trusted engineering boundaries."""

import pytest

from bearing_agents.core.state_manager import StateManagerError
from bearing_agents.design.agent import DesignAgent
from bearing_agents.domain.agent_protocols import ConfirmationEvent, StatePatch
from bearing_agents.domain.candidates import CandidateDesign, CandidatePrecheckReport
from bearing_agents.domain.enums import ParameterRole, ParameterStatus, PrecheckStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.tasks import engineering_digest
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.orchestration.llm_planner import LLMPlanner
from bearing_agents.validation.service import ValidationService


def candidate(candidate_id, width=60, unit="mm"):
    return CandidateDesign(
        candidate_id=candidate_id,
        version=1,
        parameters={
            "bearing_width": ParameterRecord(
                value=width,
                unit=unit,
                role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            ),
        },
    )


def test_unambiguous_precheck_target_is_selected_by_runtime(manager, ready, runtime_factory):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[candidate("one")]),
    )
    result = runtime_factory().invoke(state.design_id, goal="precheck")
    assert result["termination_reason"] == "NEEDS_REVIEW"
    assert any(
        entry.get("action") == "precheck_candidate" and entry["stage"] == "committed"
        for entry in result["trace"]
    )


def test_multiple_candidates_require_target_choice(manager, ready, runtime_factory):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[
            candidate("one"), candidate("two"),
        ]),
    )
    result = runtime_factory().invoke(state.design_id, goal="precheck")
    assert result["termination_reason"] == "TARGET_SELECTION_REQUIRED"
    assert not any(row["stage"] == "committed" for row in result["trace"])


def test_model_cannot_target_another_candidate_than_explicit_user_choice(
    manager, ready, runtime_factory,
):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[
            candidate("one"), candidate("two"),
        ]),
    )

    class TargetPlanner:
        def plan(self, summary):
            from bearing_agents.domain.agent_protocols import PlanDecision

            return PlanDecision(
                action="precheck_candidate",
                selected_agent="validation_agent",
                rationale="synthetic misdirected target",
                expected_result="test",
                target_ref="candidate:two@1",
                state_version=summary.domain_version,
            )

    result = runtime_factory(planner=TargetPlanner()).invoke(
        state.design_id, goal="precheck", target_ref="candidate:one@1",
    )
    assert result["termination_reason"] == "TARGET_CONFLICT"


def test_llm_planner_can_return_existing_candidate_reference():
    from bearing_agents.orchestration.contracts import StateSummary

    class Model:
        def invoke(self, prompt):
            return {
                "action": "precheck_candidate",
                "target_ref": "candidate:one@1",
                "rationale": "target this version",
            }

    summary = StateSummary(
        domain_version=3, input_digest="demo", input_ready=True,
        missing_inputs=(), supported_scope=True,
        completed_actions=frozenset(), candidate_ref="candidate:one@1",
        target_ref=None, goal="precheck",
        candidate_refs=("candidate:one@1", "candidate:two@1"),
    )
    decision = LLMPlanner(model=Model(), max_retries=0).plan(summary)
    assert decision.target_ref == "candidate:one@1"


def test_verified_partial_operating_inputs_produce_only_available_metrics(missing_load):
    analysis = DesignAgent().analyze_conditions(missing_load)
    assert not analysis.input_ready
    assert analysis.derived_metrics["surface_speed"]["unit"] == "m/s"
    assert "mean_pressure" not in analysis.derived_metrics


def test_unverified_values_cannot_be_used_for_partial_metrics(missing_load):
    state = missing_load.model_copy(deep=True)
    record = state.parameters["journal_diameter"]
    state.parameters["journal_diameter"] = record.model_copy(
        update={"verified_source_ref": None},
    )
    result = DesignAgent().analyze_conditions(state)
    assert "surface_speed" not in result.derived_metrics


def test_confirmed_width_is_not_overridden_by_candidate(manager, ready):
    locked = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(
            source="user",
            parameter_changes={
                "bearing_width": ParameterRecord(
                    value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                    status=ParameterStatus.CONFIRMED,
                ),
            },
            confirmation_events=[ConfirmationEvent(
                parameter_id="bearing_width", confirmed_by="designer",
            )],
        ),
        context=WriteContext(
            kind=WriterKind.USER, actor="designer",
            approved_parameter_ids=frozenset({"bearing_width"}),
        ),
    )
    with pytest.raises(StateManagerError, match="locked parameter"):
        manager.apply_patch(
            locked.design_id, locked.state_version,
            StatePatch(source="design_agent", candidate_additions=[
                candidate("conflict", width=80),
            ]),
        )
    same = manager.apply_patch(
        locked.design_id, locked.state_version,
        StatePatch(source="design_agent", candidate_additions=[
            candidate("compatible", width=0.06, unit="m"),
        ]),
    )
    assert len(same.candidate_designs) == 1
    proposal = DesignAgent().propose_candidate(same, DesignAgent().build_strategy(same))
    assert proposal.parameters["bearing_width"]["value"] == 60


def test_validation_service_rechecks_forged_pass_before_persistence(manager, ready):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="test", candidate_additions=[candidate("one")]),
    )
    forged = CandidatePrecheckReport(
        candidate_id="one", candidate_version=1,
        input_digest=engineering_digest(state),
        status=PrecheckStatus.PRECHECK_PASS,
        checks=[{"status": "PASS"}],
    )
    with pytest.raises(ValueError, match="trusted evaluation"):
        ValidationService(manager).persist_report(state.design_id, forged)
    assert manager.get_design(state.design_id).candidate_designs[0].precheck_report is None
