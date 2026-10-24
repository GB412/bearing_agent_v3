"""Deterministic readiness checks for a supported bearing-design stage.

R2 means necessary external inputs are available for preliminary design;
it does not establish engineering suitability or user approval.
"""

from dataclasses import dataclass

from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.parameter_registry import (
    ParameterSchemaError,
    ParameterSchemaRegistry,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.state import DesignState


@dataclass(frozen=True)
class ReadinessResult:
    stage: str
    ready: bool
    missing: list[ParameterRecord]
    conflicts: list[str]
    not_configured: bool


class StageRequirementRegistry:
    def __init__(self, requirements: dict[str, tuple[str, ...]] | None = None):
        # An explicitly empty configuration MUST NOT silently enable the default.
        self._requirements = (
            {"R2": ("journal_diameter", "load", "rotational_speed")}
            if requirements is None
            else dict(requirements)
        )

    def requirements_for(self, stage: str) -> tuple[str, ...] | None:
        return self._requirements.get(stage)


def readiness_for(
    state: DesignState,
    stage: str,
    registry: StageRequirementRegistry | None = None,
    *,
    parameter_registry: ParameterSchemaRegistry | None = None,
) -> ReadinessResult:
    registry = registry if registry is not None else StageRequirementRegistry()
    parameter_registry = (
        parameter_registry if parameter_registry is not None else ParameterSchemaRegistry()
    )
    required = registry.requirements_for(stage)
    # A missing or empty stage requirement set is not evidence that a design is ready.
    if not required:
        return ReadinessResult(stage, False, [], [], True)

    missing: list[ParameterRecord] = []
    conflicts: list[str] = []
    accepted_statuses = {ParameterStatus.PROVIDED, ParameterStatus.CONFIRMED}
    for parameter_id in required:
        record = state.parameters.get(parameter_id)
        if record is None:
            missing.append(
                ParameterRecord(
                    parameter_id=parameter_id,
                    role=ParameterRole.FIXED_INPUT,
                    status=ParameterStatus.MISSING,
                    required_for=[stage],
                )
            )
            continue
        if record.status == ParameterStatus.CONFLICT:
            conflicts.append(f"parameter:{parameter_id} is conflicting")
            continue
        # UNAVAILABLE, NOT_APPLICABLE, SUGGESTED, STALE, and MISSING must not
        # satisfy a required external input even though some have no value.
        if record.status not in accepted_statuses or record.value is None:
            missing.append(record)
            continue
        # R2 external inputs must originate from authenticated user actions or
        # evidence asserted by the trusted caller; source/source_ref are untrusted.
        if record.role != ParameterRole.FIXED_INPUT:
            conflicts.append(f"parameter:{parameter_id} must be a fixed external input")
            continue
        if record.status == ParameterStatus.PROVIDED and not record.verified_source_ref:
            conflicts.append(f"parameter:{parameter_id} has no trusted source evidence")
            continue
        if record.status == ParameterStatus.CONFIRMED and not record.confirmed_by:
            conflicts.append(f"parameter:{parameter_id} has no trusted confirmation")
            continue
        try:
            parameter_registry.validate_record(parameter_id, record)
        except ParameterSchemaError as exc:
            conflicts.append(f"parameter:{parameter_id}: {exc}")

    # V1 supports exactly one explicitly identified steady-state operating case.
    # Neither "unknown" nor the existence of one steady case among several is sufficient.
    if len(state.operating_cases) != 1:
        conflicts.append("operating_case:exactly one case is required for V1")
    else:
        case = state.operating_cases[0]
        if case.is_steady_state is not True:
            conflicts.append("operating_case:steady-state operation must be explicit")
        if not (case.confirmed_by or case.verified_source_ref):
            conflicts.append("operating_case:steady-state claim lacks trusted evidence")
        required_refs = {
            "journal_diameter_ref": "journal_diameter",
            "load_ref": "load",
            "speed_ref": "rotational_speed",
        }
        for field, expected_parameter in required_refs.items():
            reference = getattr(case, field)
            if reference is None:
                conflicts.append(f"operating_case:{case.case_id}:{field} is required")
            elif reference != expected_parameter or reference not in state.parameters:
                conflicts.append(
                    f"operating_case:{case.case_id}:{field} does not resolve to "
                    f"{expected_parameter}"
                )
            elif state.parameters[reference].applies_to_case not in {None, case.case_id}:
                conflicts.append(
                    f"operating_case:{case.case_id}:{field} refers to a different case"
                )

    return ReadinessResult(stage, not missing and not conflicts, missing, conflicts, False)
