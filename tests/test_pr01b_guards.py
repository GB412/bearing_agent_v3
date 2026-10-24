import pytest

from bearing_agents.core.readiness import StageRequirementRegistry
from bearing_agents.core.state_manager import StateManager, StateManagerError
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import (
    ConfirmationStatus, ParameterRole, ParameterStatus, PrecheckStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "pr01b.sqlite3"))


def test_empty_stage_registry_does_not_use_defaults():
    assert StageRequirementRegistry({}).requirements_for("R2") is None


def test_empty_design_reports_r2_missing(manager):
    design = manager.create_design()
    result = manager.readiness_for(design.design_id, "R2")
    assert result.ready is False
    assert {p.parameter_id for p in result.missing} == {
        "journal_diameter", "load", "rotational_speed"
    }
    assert manager.list_missing_for(design.design_id, "R2")


@pytest.mark.parametrize("status", [
    ParameterStatus.UNAVAILABLE,
    ParameterStatus.NOT_APPLICABLE,
    ParameterStatus.SUGGESTED,
    ParameterStatus.MISSING,
])
def test_required_unusable_load_is_not_ready(manager, status):
    d = manager.create_design()
    d = manager.apply_patch(d.design_id, 0, {
        "source": "user",
        "parameters": {
            "load": ParameterRecord(
                role=ParameterRole.FIXED_INPUT, status=status,
                value=12000 if status == ParameterStatus.SUGGESTED else None,
                unit="N",
            )
        },
    })
    result = manager.readiness_for(d.design_id, "R2")
    assert not result.ready
    assert "load" in {p.parameter_id for p in result.missing}


def test_confirm_requires_trusted_context(manager):
    d = manager.create_design()
    d = manager.apply_patch(d.design_id, 0, {
        "source": "agent",
        "parameters": {
            "bearing_width": ParameterRecord(
                value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            )
        }
    })
    with pytest.raises(StateManagerError, match="Trusted USER context"):
        manager.confirm_parameter(
            d.design_id, d.state_version, "bearing_width",
            context=WriteContext(kind=WriterKind.AGENT, actor="agent"),
        )
    assert manager.get_design(d.design_id).state_version == 1
    user_context = WriteContext(kind=WriterKind.USER, actor="designer")
    confirmed = manager.confirm_parameter(
        d.design_id, d.state_version, "bearing_width", context=user_context
    )
    assert confirmed.parameters["bearing_width"].status == ParameterStatus.CONFIRMED


def test_role_change_requires_trusted_context(manager):
    d = manager.create_design()
    d = manager.apply_patch(d.design_id, 0, {
        "source": "agent",
        "parameters": {
            "bearing_width": ParameterRecord(
                value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            )
        }
    })
    with pytest.raises(StateManagerError, match="Trusted USER context"):
        manager.change_parameter_role(
            d.design_id, d.state_version, "bearing_width",
            ParameterRole.HARD_CONSTRAINT,
            context=WriteContext(kind=WriterKind.AGENT, actor="agent"),
        )


@pytest.mark.parametrize("status_changes", [
    {"precheck_status": PrecheckStatus.PRECHECK_PASS},
    {"confirmation_status": ConfirmationStatus.CONFIRMED},
])
def test_agent_cannot_claim_candidate_approval(manager, status_changes):
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="New candidates must start"):
        manager.apply_patch(d.design_id, d.state_version, {
            "source": "agent",
            "candidate_additions": [
                CandidateDesign(candidate_id="x1", version=1, **status_changes)
            ],
        })
    assert manager.get_design(d.design_id).candidate_designs == []


def test_candidate_starts_unchecked(manager):
    d = manager.create_design()
    updated = manager.apply_patch(d.design_id, 0, {
        "source": "agent",
        "candidate_additions": [CandidateDesign(candidate_id="x1", version=1)],
    })
    candidate = updated.candidate_designs[0]
    assert candidate.precheck_status == PrecheckStatus.NOT_EVALUATED
    assert candidate.confirmation_status == ConfirmationStatus.PENDING


def test_untrusted_claimed_actor_is_not_audited_as_authenticated_user(manager):
    d = manager.create_design()
    updated = manager.apply_patch(d.design_id, 0, {
        "source": "agent", "actor": "claimed-designer",
        "parameters": {
            "journal_diameter": ParameterRecord(
                value=100, unit="mm", role=ParameterRole.FIXED_INPUT,
                status=ParameterStatus.PROVIDED,
            ),
        },
    })
    assert updated.event_history[-1].actor is None
