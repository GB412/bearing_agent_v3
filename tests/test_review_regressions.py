import pytest

from bearing_agents.core.state_manager import StateManager, StateManagerError
from bearing_agents.domain.agent_protocols import ConfirmationEvent
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    ConstraintOperator,
    ConstraintSeverity,
    ParameterRole,
    ParameterStatus,
    PrecheckStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.tools.engineering_calculator import (
    journal_surface_speed,
    projected_mean_pressure,
)


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "review.sqlite3"))


def record(value, unit, role=ParameterRole.FIXED_INPUT, status=ParameterStatus.PROVIDED):
    return ParameterRecord(value=value, unit=unit, role=role, status=status)


def user_context(actor="designer", **kwargs):
    return WriteContext(kind=WriterKind.USER, actor=actor, **kwargs)


def test_state_updates_cannot_replace_locked_parameter(manager):
    design = manager.create_design()
    manager.apply_patch(
        design.design_id,
        0,
        {"source": "user", "parameters": {"journal_diameter": record(100, "mm")}},
    )
    with pytest.raises(StateManagerError, match="state_updates is closed"):
        manager.apply_patch(
            design.design_id,
            1,
            {
                "source": "agent",
                "state_updates": {
                    "parameters": {"journal_diameter": record(1, "mm")}
                },
            },
        )


def test_installation_limit_change_stales_passed_candidate(manager):
    design = manager.create_design()
    seeded = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "user",
            "parameters": {
                "bearing_width": record(60, "mm", ParameterRole.DESIGN_VARIABLE),
                "installation_width_limit": record(80, "mm", ParameterRole.HARD_CONSTRAINT),
            },
            "candidate_additions": [
                CandidateDesign(
                    candidate_id="c1",
                    version=1,
                    source_parameter_revisions={"bearing_width": 1},
                    input_dependency_refs={"installation_width_limit": "1"},
                    precheck_status=PrecheckStatus.NOT_EVALUATED,
                )
            ],
        },
    )
    # Seed a previously approved result through the repository for historical
    # invalidation testing; ordinary Agent creation cannot claim a pass.
    persisted = manager.get_design(design.design_id)
    persisted.candidate_designs[0].precheck_status = PrecheckStatus.PRECHECK_PASS
    manager.repository.save(persisted, persisted.state_version)

    updated = manager.apply_patch(
        design.design_id,
        seeded.state_version,
        {
            "source": "user",
            "parameters": {
                "installation_width_limit": record(50, "mm", ParameterRole.HARD_CONSTRAINT)
            },
            "authorized_fixed_input_ids": ["installation_width_limit"],
        },
        context=user_context(
            approved_parameter_ids=frozenset({"installation_width_limit"})
        ),
    )
    candidate = updated.candidate_designs[0]
    assert candidate.precheck_status == PrecheckStatus.STALE
    assert candidate.precheck_history[-1].status == PrecheckStatus.PRECHECK_PASS


def test_new_candidate_captures_current_dependency_snapshot(manager):
    design = manager.create_design()
    updated = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "agent",
            "parameters": {"journal_diameter": record(100, "mm")},
            "candidate_additions": [
                CandidateDesign(
                    candidate_id="c1",
                    version=1,
                    source_parameter_revisions={"journal_diameter": 1},
                    precheck_status=PrecheckStatus.NOT_EVALUATED,
                )
            ],
        },
    )
    candidate = updated.candidate_designs[0]
    assert candidate.input_dependency_refs["parameter:journal_diameter"] == "1"
    assert candidate.precheck_status == PrecheckStatus.NOT_EVALUATED


def test_unit_conversion_is_used_by_calculators():
    assert journal_surface_speed(100, 1500) == pytest.approx(
        journal_surface_speed(0.1, 1500, diameter_unit="m")
    )
    assert projected_mean_pressure(12000, 100, 60) == pytest.approx(
        projected_mean_pressure(12, 0.1, 0.06, load_unit="kN", diameter_unit="m", width_unit="m")
    )


def test_category_values_and_numeric_schema_reject_bool_and_bad_units(manager):
    design = manager.create_design()
    material = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "user",
            "parameters": {
                "material": record("铜合金", "1", ParameterRole.HARD_CONSTRAINT)
            },
        },
    )
    assert material.parameters["material"].value == "铜合金"
    with pytest.raises(StateManagerError, match="numeric"):
        manager.apply_patch(
            design.design_id,
            1,
            {"source": "user", "parameters": {"journal_diameter": record(True, "mm")}},
        )
    with pytest.raises(StateManagerError, match="dimension|allowed"):
        manager.apply_patch(
            design.design_id,
            1,
            {"source": "user", "parameters": {"journal_diameter": record(100, "N")}},
        )


def test_agent_cannot_confirm_but_user_command_records_event_and_role_change(manager):
    design = manager.create_design()
    suggested = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "agent",
            "parameters": {
                "bearing_width": record(
                    60, "mm", ParameterRole.DESIGN_VARIABLE, ParameterStatus.SUGGESTED
                )
            },
        },
    )
    with pytest.raises(StateManagerError, match="explicit user confirmation"):
        manager.apply_patch(
            design.design_id,
            suggested.state_version,
            {
                "source": "agent",
                "parameters": {
                    "bearing_width": record(
                        60, "mm", ParameterRole.DESIGN_VARIABLE, ParameterStatus.CONFIRMED
                    )
                },
            },
        )
    confirmed = manager.confirm_parameter(
        design.design_id, suggested.state_version, "bearing_width", context=user_context()
    )
    changed = manager.change_parameter_role(
        design.design_id,
        confirmed.state_version,
        "bearing_width",
        ParameterRole.HARD_CONSTRAINT,
        context=user_context(approved_parameter_ids=frozenset({"bearing_width"})),
    )
    assert changed.parameters["bearing_width"].role == ParameterRole.HARD_CONSTRAINT
    assert len(changed.event_history) == 3
    assert "confirmations" in changed.event_history[1].changed_fields


def test_agent_confirmation_event_is_rejected(manager):
    design = manager.create_design()
    with pytest.raises(StateManagerError, match="trusted user context"):
        manager.apply_patch(
            design.design_id,
            0,
            {
                "source": "agent",
                "parameters": {
                    "bearing_width": record(
                        60, "mm", ParameterRole.DESIGN_VARIABLE, ParameterStatus.CONFIRMED
                    )
                },
                "confirmation_events": [
                    ConfirmationEvent(parameter_id="bearing_width", confirmed_by="designer")
                ],
            },
        )


def test_hard_constraint_change_requires_explicit_user_approval(manager):
    design = manager.create_design()
    seeded = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "agent",
            "constraint_changes": [
                ConstraintRecord(
                    id="width-limit",
                    parameter="bearing_width",
                    operator=ConstraintOperator.LE,
                    target=80,
                    unit="mm",
                    severity=ConstraintSeverity.HARD,
                    origin="user",
                )
            ],
        },
    )
    changed = ConstraintRecord(
        id="width-limit",
        parameter="bearing_width",
        operator=ConstraintOperator.LE,
        target=50,
        unit="mm",
        severity=ConstraintSeverity.HARD,
        origin="user",
    )
    with pytest.raises(StateManagerError, match="requires user approval"):
        manager.apply_patch(
            design.design_id,
            seeded.state_version,
            {"source": "user", "constraint_changes": [changed]},
            context=user_context(),
        )
    approved = manager.apply_patch(
        design.design_id,
        seeded.state_version,
        {"source": "user", "constraint_changes": [changed]},
        context=user_context(approved_constraint_ids=frozenset({"width-limit"})),
    )
    assert approved.constraints[0].target == 50


def test_empty_design_is_not_ready_and_width_can_remain_design_variable(manager):
    design = manager.create_design()
    readiness = manager.readiness_for(design.design_id, "R2")
    assert readiness.ready is False
    assert readiness.not_configured is False
    assert {item.parameter_id for item in readiness.missing} == {
        "journal_diameter",
        "load",
        "rotational_speed",
    }
    assert {item.parameter_id for item in manager.list_missing_for(design.design_id, "R2")} == {
        "journal_diameter",
        "load",
        "rotational_speed",
    }
    assert manager.readiness_for(design.design_id, "future-template").not_configured is True
    updated = manager.apply_patch(
        design.design_id,
        0,
        {
            "source": "agent",
            "parameters": {
                "bearing_width": record(
                    None, "mm", ParameterRole.DESIGN_VARIABLE, ParameterStatus.MISSING
                )
            },
        },
    )
    assert updated.parameters["bearing_width"].status == ParameterStatus.MISSING


def test_parameter_id_must_match_key(manager):
    design = manager.create_design()
    with pytest.raises(StateManagerError, match="does not match"):
        manager.apply_patch(
            design.design_id,
            0,
            {
                "source": "agent",
                "parameters": {
                    "journal_diameter": ParameterRecord(
                        parameter_id="load",
                        value=100,
                        unit="mm",
                        role=ParameterRole.FIXED_INPUT,
                    )
                },
            },
        )

