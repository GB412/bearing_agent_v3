from bearing_agents.core.dependency_tracker import invalidate_dependents
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import IssueStatus, ParameterRole, ParameterStatus, PrecheckStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.state import DesignState, IssueRecord


def test_diameter_change_invalidates_only_dependent_outputs():
    state = DesignState(
        design_id="d1",
        parameters={
            "surface_speed": ParameterRecord(
                value=7.8,
                unit="m/s",
                role=ParameterRole.DERIVED,
                status=ParameterStatus.PROVIDED,
            ),
            "mean_pressure": ParameterRecord(
                value=2e6,
                unit="Pa",
                role=ParameterRole.DERIVED,
                status=ParameterStatus.PROVIDED,
            ),
            "shaft_material": ParameterRecord(
                value="alloy-x",
                unit="1",
                role=ParameterRole.FIXED_INPUT,
                status=ParameterStatus.CONFIRMED,
            ),
        },
        candidate_designs=[
            CandidateDesign(
                candidate_id="c1",
                version=1,
                source_parameter_revisions={"journal_diameter": 1},
                precheck_status=PrecheckStatus.PRECHECK_PASS,
            )
        ],
        issues=[
            IssueRecord(
                code="MAT-1",
                severity="INFO",
                explanation="unchanged",
                affected_fields=["shaft_material"],
            )
        ],
    )
    result = invalidate_dependents(state, {"journal_diameter"})
    assert state.parameters["surface_speed"].status == ParameterStatus.STALE
    assert state.parameters["mean_pressure"].status == ParameterStatus.STALE
    assert state.parameters["shaft_material"].status == ParameterStatus.CONFIRMED
    assert state.candidate_designs[0].precheck_status == PrecheckStatus.STALE
    assert state.issues[0].status == IssueStatus.OPEN
    assert "parameter:surface_speed" in result.invalidated_objects


def test_speed_change_does_not_invalidate_mean_pressure():
    state = DesignState(
        design_id="d1",
        parameters={
            "surface_speed": ParameterRecord(
                value=7.8,
                unit="m/s",
                role=ParameterRole.DERIVED,
                status=ParameterStatus.PROVIDED,
            ),
            "mean_pressure": ParameterRecord(
                value=2e6,
                unit="Pa",
                role=ParameterRole.DERIVED,
                status=ParameterStatus.PROVIDED,
            ),
        },
    )
    invalidate_dependents(state, {"rotational_speed"})
    assert state.parameters["surface_speed"].status == ParameterStatus.STALE
    assert state.parameters["mean_pressure"].status == ParameterStatus.PROVIDED
