import pytest
from pydantic import ValidationError

from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import (
    ConfirmationStatus,
    ParameterRole,
    ParameterStatus,
    PrecheckStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.state import DesignState


def test_empty_design_uses_scope_without_inventing_operating_values():
    state = DesignState(design_id="d1")
    assert state.target_scope == "cylindrical_radial_hydrodynamic"
    assert state.parameters == {}
    assert state.operating_cases == []


def test_role_and_confirmation_status_are_independent():
    parameter = ParameterRecord(
        value=60,
        unit="mm",
        role=ParameterRole.DESIGN_VARIABLE,
        status=ParameterStatus.SUGGESTED,
    )
    confirmed = parameter.model_copy(update={"status": ParameterStatus.CONFIRMED})
    assert confirmed.role == ParameterRole.DESIGN_VARIABLE
    assert confirmed.status == ParameterStatus.CONFIRMED


def test_candidate_defaults_do_not_claim_validation_or_confirmation():
    candidate = CandidateDesign(candidate_id="c1", version=1)
    assert candidate.confirmation_status == ConfirmationStatus.PENDING
    assert candidate.precheck_status == PrecheckStatus.NOT_EVALUATED


def test_models_reject_uncontracted_fields():
    with pytest.raises(ValidationError):
        ParameterRecord(role="DESIGN_VARIABLE", unexpected=True)
