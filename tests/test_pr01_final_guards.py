"""PR-01 final guard regression: confirmed variables, proposals, and single steady case."""

import pytest

from bearing_agents.core.readiness import readiness_for
from bearing_agents.core.state_manager import (
    FixedInputWriteError,
    StateManager,
    StateManagerError,
)
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.operating_cases import OperatingCase
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.proposals import (
    ParameterChangeProposal,
    ProposalStatus,
)
from bearing_agents.domain.state import DesignState
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "final-guards.sqlite3"))


def user_context(*approved):
    return WriteContext(
        kind=WriterKind.USER,
        actor="designer",
        approved_parameter_ids=frozenset(approved),
    )


def width(value, status=ParameterStatus.SUGGESTED):
    return ParameterRecord(
        value=value,
        unit="mm",
        role=ParameterRole.DESIGN_VARIABLE,
        status=status,
    )


def seed_confirmed_width(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {"source": "design_agent", "parameter_changes": {"bearing_width": width(60)}},
    )
    return manager.confirm_parameter(
        d.design_id, d.state_version, "bearing_width", context=user_context()
    )


def test_agent_cannot_override_confirmed_design_variable(manager):
    d = seed_confirmed_width(manager)
    with pytest.raises(FixedInputWriteError, match="Confirmed parameter"):
        manager.apply_patch(
            d.design_id, d.state_version,
            {"source": "design_agent", "parameter_changes": {"bearing_width": width(80)}},
        )
    unchanged = manager.get_design(d.design_id)
    assert unchanged.parameters["bearing_width"].value == 60
    assert unchanged.parameters["bearing_width"].status == ParameterStatus.CONFIRMED
    assert unchanged.state_version == d.state_version


def test_agent_proposal_does_not_change_confirmed_value_until_user_accepts(manager):
    d = seed_confirmed_width(manager)
    revision = d.parameters["bearing_width"].revision
    submitted = manager.apply_patch(
        d.design_id, d.state_version,
        {
            "source": "design_agent",
            "parameter_change_proposals": [
                ParameterChangeProposal(
                    proposal_id="width-80",
                    parameter_id="bearing_width",
                    proposed_record=width(80),
                    base_revision=revision,
                    reason="Reassess the candidate width after preliminary checks",
                )
            ],
        },
    )
    assert submitted.parameters["bearing_width"].value == 60
    proposal = submitted.parameter_change_proposals[0]
    assert proposal.status == ProposalStatus.PENDING
    assert proposal.proposed_by == "design_agent"

    with pytest.raises(FixedInputWriteError, match="explicit parameter permission"):
        manager.resolve_parameter_proposal(
            d.design_id, submitted.state_version, "width-80",
            approve=True, context=user_context(),
        )
    assert manager.get_design(d.design_id).state_version == submitted.state_version

    accepted = manager.resolve_parameter_proposal(
        d.design_id, submitted.state_version, "width-80",
        approve=True, context=user_context("bearing_width"),
    )
    assert accepted.parameters["bearing_width"].value == 80
    assert accepted.parameters["bearing_width"].status == ParameterStatus.CONFIRMED
    assert accepted.parameters["bearing_width"].confirmed_by == "designer"
    assert accepted.parameter_change_proposals[0].status == ProposalStatus.APPROVED
    assert accepted.event_history[-1].details["proposal_resolutions"]


def test_agent_proposal_can_be_rejected_without_changing_parameter(manager):
    d = seed_confirmed_width(manager)
    d = manager.apply_patch(
        d.design_id, d.state_version,
        {
            "source": "design_agent",
            "parameter_change_proposals": [
                ParameterChangeProposal(
                    proposal_id="width-90", parameter_id="bearing_width",
                    proposed_record=width(90),
                    base_revision=d.parameters["bearing_width"].revision,
                    reason="Alternative width",
                )
            ],
        },
    )
    rejected = manager.resolve_parameter_proposal(
        d.design_id, d.state_version, "width-90", approve=False, context=user_context()
    )
    assert rejected.parameters["bearing_width"].value == 60
    assert rejected.parameter_change_proposals[0].status == ProposalStatus.REJECTED


def test_proposal_stales_if_user_changes_parameter_by_other_route(manager):
    d = seed_confirmed_width(manager)
    d = manager.apply_patch(
        d.design_id, d.state_version,
        {
            "source": "design_agent",
            "parameter_change_proposals": [
                ParameterChangeProposal(
                    proposal_id="old-width", parameter_id="bearing_width",
                    proposed_record=width(90),
                    base_revision=d.parameters["bearing_width"].revision,
                    reason="Alternative",
                )
            ],
        },
    )
    d = manager.apply_patch(
        d.design_id, d.state_version,
        {
            "source": "user",
            "parameter_changes": {"bearing_width": width(70, ParameterStatus.CONFIRMED)},
            "confirmation_events": [
                {"parameter_id": "bearing_width", "confirmed_by": "designer"}
            ],
        },
        context=user_context("bearing_width"),
    )
    assert d.parameter_change_proposals[0].status == ProposalStatus.STALE
    with pytest.raises(StateManagerError, match="no longer pending"):
        manager.resolve_parameter_proposal(
            d.design_id, d.state_version, "old-width",
            approve=True, context=user_context("bearing_width"),
        )


def make_case(case_id="case-1", steady=True, confirmed_by=None):
    return OperatingCase(
        case_id=case_id,
        journal_diameter_ref="journal_diameter",
        load_ref="load",
        speed_ref="rotational_speed",
        is_steady_state=steady,
        confirmed_by=confirmed_by,
    )


def case_ready_state(steady=True):
    return DesignState(
        design_id="d",
        parameters={
            "journal_diameter": ParameterRecord(
                value=100, unit="mm", role=ParameterRole.FIXED_INPUT,
                status=ParameterStatus.PROVIDED,
            ),
            "load": ParameterRecord(
                value=12000, unit="N", role=ParameterRole.FIXED_INPUT,
                status=ParameterStatus.PROVIDED,
            ),
            "rotational_speed": ParameterRecord(
                value=1500, unit="rpm", role=ParameterRole.FIXED_INPUT,
                status=ParameterStatus.PROVIDED,
            ),
        },
        operating_cases=[make_case(steady=steady)],
    )


def test_default_case_and_nonsteady_case_do_not_pass_r2():
    default_case = make_case()
    default_case.is_steady_state = None
    state = case_ready_state()
    state.operating_cases = [default_case]
    assert not readiness_for(state, "R2").ready
    assert not readiness_for(case_ready_state(steady=False), "R2").ready


def test_single_explicit_steady_case_is_ready():
    assert readiness_for(case_ready_state(), "R2").ready


def test_multiple_cases_cannot_pass_r2_and_cannot_be_persisted(manager):
    state = case_ready_state()
    state.operating_cases.append(make_case(case_id="case-2"))
    assert not readiness_for(state, "R2").ready

    d = manager.create_design()
    with pytest.raises(StateManagerError, match="only one operating case"):
        manager.apply_patch(
            d.design_id, d.state_version,
            {"source": "agent", "operating_case_changes": [
                make_case("case-1"), make_case("case-2")
            ]},
        )
    assert manager.get_design(d.design_id).operating_cases == []


def test_agent_cannot_set_confirmation_identity_or_override_confirmed_case(manager):
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="trusted user"):
        manager.apply_patch(
            d.design_id, d.state_version,
            {"source": "agent", "operating_case_changes": [
                make_case(confirmed_by="designer")
            ]},
        )

    d = manager.apply_patch(
        d.design_id, d.state_version,
        {"source": "user", "operating_case_changes": [
            make_case(confirmed_by="designer")
        ]},
        context=user_context(),
    )
    with pytest.raises(StateManagerError, match="Confirmed operating case"):
        manager.apply_patch(
            d.design_id, d.state_version,
            {"source": "agent", "operating_case_changes": [
                make_case(steady=False)
            ]},
        )
    assert manager.get_design(d.design_id).operating_cases[0].is_steady_state is True
    changed = manager.apply_patch(
        d.design_id, d.state_version,
        {"source": "user", "operating_case_changes": [
            make_case(steady=False, confirmed_by="designer")
        ]},
        context=user_context(),
    )
    assert changed.operating_cases[0].is_steady_state is False
    assert changed.operating_cases[0].revision == 2


def test_case_change_invalidates_precheck(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {"source": "user",
         "operating_case_changes": [make_case(confirmed_by="designer")],
         "candidate_additions": [CandidateDesign(candidate_id="c1", version=1)]},
        context=user_context(),
    )
    modified = manager.apply_patch(
        d.design_id, d.state_version,
        {"source": "user", "operating_case_changes": [
            make_case(steady=False, confirmed_by="designer")
        ]},
        context=user_context(),
    )
    assert modified.candidate_designs[0].precheck_status.value == "STALE"
