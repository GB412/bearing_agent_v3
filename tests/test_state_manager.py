import pytest
from pydantic import ValidationError

from bearing_agents.core.state_manager import (
    FixedInputWriteError,
    StateManager,
    StateManagerError,
    VersionConflictError,
)
from bearing_agents.domain.agent_protocols import StatePatch
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "designs.sqlite3"))


def parameter(
    value=None,
    status=ParameterStatus.PROVIDED,
    role=ParameterRole.FIXED_INPUT,
    unit="mm",
    **kwargs,
):
    return ParameterRecord(value=value, unit=unit, role=role, status=status, **kwargs)


def test_create_design_persists_empty_state_without_default_values(manager):
    created = manager.create_design()
    loaded = manager.get_design(created.design_id)
    assert loaded == created
    assert loaded.parameters == {}
    assert loaded.operating_cases == []


def test_unknown_diameter_remains_missing_and_missing_items_are_metadata_driven(manager):
    design = manager.create_design()
    updated = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "user",
            "parameters": {
                "journal_diameter": parameter(
                    None, ParameterStatus.MISSING, required_for=["candidate"]
                ),
                "optional_note": ParameterRecord(
                    role=ParameterRole.DESIGN_VARIABLE, status=ParameterStatus.MISSING
                ),
            },
        },
    )
    assert updated.parameters["journal_diameter"].value is None
    assert updated.parameters["journal_diameter"].status == ParameterStatus.MISSING
    assert [r.parameter_id for r in manager.list_missing_for(design.design_id, "candidate")] == [
        "journal_diameter"
    ]


def test_confirming_suggested_design_variable_preserves_role(manager):
    design = manager.create_design()
    manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "design_agent",
            "parameters": {
                "bearing_width": parameter(
                    60, ParameterStatus.SUGGESTED, ParameterRole.DESIGN_VARIABLE
                )
            },
        },
    )
    confirmed = manager.confirm_parameter(
        design.design_id,
        1,
        "bearing_width",
        context=WriteContext(kind=WriterKind.USER, actor="designer"),
    )
    record = confirmed.parameters["bearing_width"]
    assert record.role == ParameterRole.DESIGN_VARIABLE
    assert record.status == ParameterStatus.CONFIRMED
    assert record.confirmed_by == "designer"


def test_patch_records_versions_sources_and_event_history(manager):
    design = manager.create_design()
    updated = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "user",
            "actor": "engineer",
            "parameters": {"journal_diameter": parameter(100, source_ref="drawing-A")},
        },
    )
    assert updated.state_version == 1
    assert updated.parameters["journal_diameter"].revision == 1
    assert updated.parameters["journal_diameter"].source_ref == "drawing-A"
    assert updated.parameters["journal_diameter"].source == "user"
    assert updated.event_history[-1].from_version == 0
    assert updated.event_history[-1].to_version == 1
    assert updated.event_history[-1].source == "user"
    assert manager.get_design(design.design_id) == updated


def test_old_state_patch_is_rejected(manager):
    design = manager.create_design()
    manager.apply_patch(
        design.design_id, 0, {"source": "user", "parameters": {"journal_diameter": parameter(100)}}
    )
    with pytest.raises(VersionConflictError):
        manager.apply_patch(
            design.design_id,
            0,
            {"source": "user", "parameters": {"rotational_speed": parameter(1500, unit="rpm")}},
        )


def test_fixed_input_modification_requires_explicit_authorization(manager):
    design = manager.create_design()
    manager.apply_patch(
        design.design_id, 0, {"source": "user", "parameters": {"journal_diameter": parameter(100)}}
    )
    with pytest.raises(FixedInputWriteError):
        manager.apply_patch(
            design.design_id,
            1,
            {"source": "agent", "parameters": {"journal_diameter": parameter(110)}},
        )
    updated = manager.apply_patch(
        design.design_id,
        1,
        {
            "source": "user",
            "parameters": {"journal_diameter": parameter(110)},
            "authorized_fixed_input_ids": ["journal_diameter"],
        },
        context=WriteContext(
            kind=WriterKind.USER,
            actor="designer",
            approved_parameter_ids=frozenset({"journal_diameter"}),
        ),
    )
    assert updated.parameters["journal_diameter"].value == 110


def test_agent_cannot_self_authorize_fixed_input_change(manager):
    design = manager.create_design()
    manager.apply_patch(
        design.design_id,
        0,
        {"source": "user", "parameters": {"journal_diameter": parameter(100)}},
    )
    with pytest.raises(FixedInputWriteError, match="user-sourced"):
        manager.apply_patch(
            design.design_id,
            1,
            {
                "source": "design_agent",
                "authorized_fixed_input_ids": ["journal_diameter"],
                "parameters": {"journal_diameter": parameter(110)},
            },
        )


@pytest.mark.parametrize("unit", ["inch-ish", "furlong"])
def test_unknown_unit_is_rejected(manager, unit):
    design = manager.create_design()
    with pytest.raises(StateManagerError, match="Unknown unit"):
        manager.apply_patch(
            design.design_id,
            0,
            {"source": "user", "parameters": {"journal_diameter": parameter(100, unit=unit)}},
        )


def test_missing_value_cannot_be_coerced_to_zero_and_value_requires_unit(manager):
    design = manager.create_design()
    with pytest.raises(StateManagerError, match="MISSING"):
        manager.apply_patch(
            design.design_id,
            0,
            {
                "source": "user",
                "parameters": {"journal_diameter": parameter(0, ParameterStatus.MISSING)},
            },
        )
    with pytest.raises(StateManagerError, match="explicit unit"):
        manager.apply_patch(
            design.design_id,
            0,
            {"source": "user", "parameters": {"load": parameter(12000, unit=None)}},
        )


def test_derived_values_and_candidate_are_staled_after_diameter_change(manager):
    design = manager.create_design()
    manager.apply_patch(
        design.design_id, 0, {"source": "user", "parameters": {"journal_diameter": parameter(100)}}
    )
    seeded = manager.apply_patch(
        design.design_id,
        1,
            {
            "source": "calculator",
            "parameters": {
                "surface_speed": ParameterRecord(
                    value=7.85,
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
            "candidate_additions": [
                CandidateDesign(
                    candidate_id="c1",
                    version=1,
                    source_parameter_revisions={"journal_diameter": 1},
                    precheck_status="NOT_EVALUATED",
                )
            ],
        },
    )
    updated = manager.apply_patch(
        design.design_id,
        seeded.state_version,
        {
            "source": "user",
            "authorized_fixed_input_ids": ["journal_diameter"],
            "parameters": {"journal_diameter": parameter(120)},
        },
        context=WriteContext(
            kind=WriterKind.USER,
            actor="designer",
            approved_parameter_ids=frozenset({"journal_diameter"}),
        ),
    )
    assert updated.parameters["surface_speed"].status == ParameterStatus.STALE
    assert updated.parameters["mean_pressure"].status == ParameterStatus.STALE
    assert updated.candidate_designs[0].precheck_status.value == "STALE"


def test_patch_model_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        StatePatch.model_validate({"source": "x", "unexpected": True})
