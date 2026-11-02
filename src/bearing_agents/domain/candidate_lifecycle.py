"""Shared, conservative completeness policy for the first bearing-design scope."""

from collections.abc import Mapping

from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.parameter_registry import ParameterSchemaError, ParameterSchemaRegistry
from bearing_agents.domain.parameters import ParameterRecord

# V1 explicit coverage: missing fields remain review items, never invented defaults.
REQUIRED_DESIGN_VARIABLES = (
    "bearing_width",
    "radial_clearance",
    "material",
    "lubricant",
)


def missing_design_variables(
    candidate_parameters: Mapping[str, ParameterRecord],
    state_parameters: Mapping[str, ParameterRecord],
    *,
    registry: ParameterSchemaRegistry | None = None,
) -> list[str]:
    registry = registry or ParameterSchemaRegistry()
    missing: list[str] = []
    for key in REQUIRED_DESIGN_VARIABLES:
        record = candidate_parameters.get(key) or state_parameters.get(key)
        if record is None or record.value is None:
            missing.append(key)
            continue
        if record.role != ParameterRole.DESIGN_VARIABLE or record.status not in {
            ParameterStatus.PROVIDED,
            ParameterStatus.CONFIRMED,
            ParameterStatus.SUGGESTED,
        }:
            missing.append(key)
            continue
        if record.status == ParameterStatus.PROVIDED and not record.verified_source_ref:
            missing.append(key)
            continue
        if record.status == ParameterStatus.CONFIRMED and not record.confirmed_by:
            missing.append(key)
            continue
        try:
            registry.validate_record(key, record)
        except ParameterSchemaError:
            missing.append(key)
    return missing
