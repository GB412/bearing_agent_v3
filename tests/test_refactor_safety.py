"""Refactor regressions: one write contract, one authority per state fact."""

import pytest

from bearing_agents.core.state_manager import StateManager, StateManagerError
from bearing_agents.domain.agent_protocols import StatePatch
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.proposals import ParameterChangeProposal
from bearing_agents.domain.state import DesignState
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "refactor.sqlite3"))


def test_obsolete_patch_entrypoints_are_rejected(manager):
    d = manager.create_design()
    for field in ("parameters", "state_updates", "authorized_fixed_input_ids"):
        with pytest.raises(StateManagerError, match="Extra inputs are not permitted"):
            manager.apply_patch(
                d.design_id, d.state_version,
                {"source": "agent", field: {} if field != "authorized_fixed_input_ids"
                 else ["journal_diameter"]},
            )
    assert manager.get_design(d.design_id).state_version == 0


def test_agent_design_variable_cannot_be_formally_provided(manager):
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="must remain SUGGESTED"):
        manager.apply_patch(
            d.design_id, 0,
            {"source": "design_agent",
             "parameter_changes": {
                 "bearing_width": ParameterRecord(
                     value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                     status=ParameterStatus.PROVIDED,
                 ),
             }},
        )
    assert manager.get_design(d.design_id).parameters == {}


def test_agent_derived_value_requires_trusted_calculator(manager):
    d = manager.create_design()
    calculation = ParameterRecord(
        value=7.85, unit="m/s", role=ParameterRole.DERIVED,
        status=ParameterStatus.PROVIDED,
    )
    patch = {"source": "calculator", "parameter_changes": {"surface_speed": calculation}}
    with pytest.raises(StateManagerError, match="trusted calculator"):
        manager.apply_patch(d.design_id, 0, patch)
    saved = manager.apply_patch(
        d.design_id, 0, patch,
        context=WriteContext(kind=WriterKind.SYSTEM, actor="calculator"),
    )
    assert saved.parameters["surface_speed"].value == 7.85


@pytest.mark.parametrize("forged", [
    {"confirmed_by": "designer"},
    {"verified_source_ref": "invented:message"},
])
def test_parameter_change_proposal_cannot_carry_claimed_authority(manager, forged):
    d = manager.create_design()
    d = manager.apply_patch(
        d.design_id, 0,
        {"source": "agent", "parameter_changes": {
            "bearing_width": ParameterRecord(
                value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            )
        }},
    )
    with pytest.raises(StateManagerError, match="proposal cannot claim user confirmation"):
        manager.apply_patch(
            d.design_id, d.state_version,
            {"source": "agent", "parameter_change_proposals": [
                ParameterChangeProposal(
                    proposal_id="width-70", parameter_id="bearing_width",
                    proposed_record=ParameterRecord(
                        value=70, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                        status=ParameterStatus.SUGGESTED, **forged,
                    ),
                    base_revision=d.parameters["bearing_width"].revision,
                    reason="Try another width",
                ),
            ]},
        )
    assert manager.get_design(d.design_id).parameter_change_proposals == []


def test_legacy_cached_fields_are_readable_but_no_longer_serialized():
    legacy = {
        "design_id": "legacy",
        "state_version": 4,
        "confirmations": {"bearing_width": {"confirmed_by": "designer"}},
        "event_log_refs": ["old-event"],
        "stale_objects": ["parameter:mean_pressure"],
        "parameters": {"journal_diameter": {
            "role": "FIXED_INPUT", "status": "MISSING",
            "required_for": ["R2"], "revision": 1,
        }},
    }
    state = DesignState.model_validate(legacy)
    serialized = state.model_dump(mode="json")
    for obsolete in ("confirmations", "event_log_refs", "stale_objects"):
        assert obsolete not in serialized
    assert "required_for" not in serialized["parameters"]["journal_diameter"]
    assert state.state_version == 4


def test_custom_stage_uses_only_registry_and_not_r2_case_gate(manager):
    d = manager.create_design()
    manager.stage_registry.register("custom", ("bearing_width",))
    assert {p.parameter_id for p in manager.list_missing_for(d.design_id, "custom")} == {
        "bearing_width"
    }
    d = manager.apply_patch(d.design_id, 0, {
        "source": "agent",
        "parameter_changes": {"bearing_width": ParameterRecord(
            value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
            status=ParameterStatus.SUGGESTED,
        )},
    })
    assert not manager.readiness_for(d.design_id, "custom").ready
    assert manager.readiness_for(d.design_id, "future-stage").not_configured
