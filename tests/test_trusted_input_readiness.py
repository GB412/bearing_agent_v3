"""Regression cases for the trusted external-input boundary and R2 readiness."""

import pytest

from bearing_agents.core.state_manager import (
    FixedInputWriteError,
    StateManager,
    StateManagerError,
)
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.operating_cases import OperatingCase
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "trusted-r2.sqlite3"))


def fixed(value, unit, status=ParameterStatus.PROVIDED, **kwargs):
    return ParameterRecord(
        value=value,
        unit=unit,
        role=ParameterRole.FIXED_INPUT,
        status=status,
        **kwargs,
    )


def case():
    return OperatingCase(
        case_id="c1",
        journal_diameter_ref="journal_diameter",
        load_ref="load",
        speed_ref="rotational_speed",
        is_steady_state=True,
    )


def required_parameters():
    return {
        "journal_diameter": fixed(100, "mm"),
        "load": fixed(12000, "N"),
        "rotational_speed": fixed(1500, "rpm"),
    }


def test_agent_cannot_fabricate_provided_external_inputs(manager):
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="verified source"):
        manager.apply_patch(
            d.design_id,
            0,
            {
                "source": "user",
                "actor": "pretend-human",
                "parameters": required_parameters(),
                "operating_case_changes": [case()],
            },
        )
    assert manager.get_design(d.design_id).state_version == 0


def test_agent_supplied_source_ref_cannot_self_verify(manager):
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="verified source"):
        manager.apply_patch(
            d.design_id,
            0,
            {
                "source": "user",
                "parameters": {
                    "journal_diameter": fixed(
                        100, "mm", source_ref="invented-user-message",
                        source="user",
                    ),
                },
            },
        )


def test_agent_can_suggest_inputs_but_r2_stays_not_ready(manager):
    d = manager.create_design()
    proposals = {
        key: record.model_copy(update={"status": ParameterStatus.SUGGESTED})
        for key, record in required_parameters().items()
    }
    d = manager.apply_patch(
        d.design_id, d.state_version,
        {"source": "requirement_agent", "parameters": proposals,
         "operating_case_changes": [case()]},
    )
    readiness = manager.readiness_for(d.design_id, "R2")
    assert not readiness.ready
    assert {r.parameter_id for r in readiness.missing} == set(proposals)
    assert any("lacks trusted evidence" in item for item in readiness.conflicts)


def test_trusted_user_can_directly_provide_inputs_without_reconfirmation(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "user",
            "parameters": required_parameters(),
            "operating_case_changes": [case()],
        },
        context=WriteContext(kind=WriterKind.USER, actor="engineer"),
    )
    assert manager.readiness_for(d.design_id, "R2").ready
    assert all(
        r.verified_source_ref and r.status == ParameterStatus.PROVIDED
        for r in d.parameters.values()
    )
    assert d.operating_cases[0].verified_source_ref


def test_verified_user_message_may_be_extracted_by_agent(manager):
    d = manager.create_design()
    input_refs = {
        "journal_diameter": "message-14",
        "load": "message-14",
        "rotational_speed": "message-14",
    }
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "requirement_agent",
            "parameters": required_parameters(),
            "operating_case_changes": [case()],
        },
        context=WriteContext(
            kind=WriterKind.AGENT,
            verified_parameter_refs=input_refs,
            verified_case_refs={"c1": "message-14"},
        ),
    )
    assert manager.readiness_for(d.design_id, "R2").ready
    assert d.parameters["load"].verified_source_ref == "message-14"
    assert d.parameters["load"].source_ref == "message-14"
    assert d.operating_cases[0].verified_source_ref == "message-14"


def test_verified_parameters_with_unverified_steady_case_are_not_ready(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "requirement_agent",
            "parameters": required_parameters(),
            "operating_case_changes": [case()],
        },
        context=WriteContext(
            verified_parameter_refs={
                key: "message-14" for key in required_parameters()
            }
        ),
    )
    assert not manager.readiness_for(d.design_id, "R2").ready
    assert "operating_case:steady-state claim lacks trusted evidence" in (
        manager.readiness_for(d.design_id, "R2").conflicts
    )


def test_agent_cannot_inject_its_own_verified_source_field(manager):
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="cannot come from the patch"):
        manager.apply_patch(
            d.design_id, 0,
            {"source": "agent",
             "parameters": {"journal_diameter": fixed(
                 100, "mm", verified_source_ref="untrusted-claim"
             )}},
        )
    with pytest.raises(StateManagerError, match="cannot come from the patch"):
        manager.apply_patch(
            d.design_id, 0,
            {"source": "agent",
             "operating_case_changes": [
                 case().model_copy(update={"verified_source_ref": "untrusted"})
             ]},
        )


def test_agent_claimed_source_must_match_attested_reference(manager):
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="disagrees with trusted evidence"):
        manager.apply_patch(
            d.design_id, 0,
            {
                "source": "agent",
                "parameters": {
                    "journal_diameter": fixed(
                        100, "mm", source_ref="different-message"
                    )
                },
            },
            context=WriteContext(
                verified_parameter_refs={"journal_diameter": "message-14"}
            ),
        )


def test_agent_cannot_change_verified_input_without_user_approval(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "user",
            "parameters": {"journal_diameter": fixed(100, "mm")},
        },
        context=WriteContext(kind=WriterKind.USER, actor="engineer"),
    )
    with pytest.raises(FixedInputWriteError):
        manager.apply_patch(
            d.design_id, d.state_version,
            {"source": "agent",
             "parameters": {
                 "journal_diameter": fixed(120, "mm", status=ParameterStatus.SUGGESTED)
             }},
        )
    assert manager.get_design(d.design_id).parameters["journal_diameter"].value == 100


def test_agent_cannot_relabel_external_inputs_as_design_variables_for_r2(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "agent",
            "parameters": {
                key: record.model_copy(
                    update={
                        "role": ParameterRole.DESIGN_VARIABLE,
                        "status": ParameterStatus.PROVIDED,
                    }
                )
                for key, record in required_parameters().items()
            },
            "operating_case_changes": [case()],
        },
        context=WriteContext(verified_case_refs={"c1": "message-14"}),
    )
    assert not manager.readiness_for(d.design_id, "R2").ready
    assert any("fixed external input" in s for s in manager.readiness_for(
        d.design_id, "R2"
    ).conflicts)


def test_get_quantity_rejects_provisional_design_value_by_default(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "design_agent",
            "parameters": {
                "bearing_width": ParameterRecord(
                    value=60, unit="mm",
                    role=ParameterRole.DESIGN_VARIABLE,
                    status=ParameterStatus.SUGGESTED,
                ),
            },
        },
    )
    with pytest.raises(StateManagerError, match="no usable quantity"):
        manager.get_quantity(d.design_id, "bearing_width", "mm")
    assert manager.get_quantity(
        d.design_id, "bearing_width", "mm", allow_suggested=True
    ) == 60


def test_get_quantity_refuses_unverified_legacy_fixed_input(manager):
    d = manager.create_design()
    # Simulate a legacy database record produced before the provenance guard.
    d.parameters["journal_diameter"] = fixed(100, "mm")
    manager.repository.save(d, expected_version=d.state_version)
    with pytest.raises(StateManagerError, match="no trusted source"):
        manager.get_quantity(d.design_id, "journal_diameter", "mm")
    assert not manager.readiness_for(d.design_id, "R2").ready



def test_r2_rejects_input_scoped_to_another_case(manager):
    d = manager.create_design()
    parameters = required_parameters()
    parameters["load"] = parameters["load"].model_copy(
        update={"applies_to_case": "different-case"}
    )
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "user", "parameters": parameters,
            "operating_case_changes": [case()],
        },
        context=WriteContext(kind=WriterKind.USER, actor="engineer"),
    )
    assert not manager.readiness_for(d.design_id, "R2").ready
    assert any("different case" in error for error in (
        manager.readiness_for(d.design_id, "R2").conflicts
    ))



def test_get_quantity_never_promotes_unverified_fixed_suggestion(manager):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {
            "source": "agent",
            "parameters": {
                "journal_diameter": fixed(
                    100, "mm", status=ParameterStatus.SUGGESTED
                ),
            },
        },
    )
    with pytest.raises(StateManagerError, match="trusted source evidence"):
        manager.get_quantity(
            d.design_id, "journal_diameter", "mm", allow_suggested=True
        )
