import math
from dataclasses import dataclass
from typing import Any

from bearing_agents.core.unit_normalizer import UNITS, UnitError, normalize
from bearing_agents.domain.enums import ParameterStatus, ParameterValueType
from bearing_agents.domain.parameters import ParameterRecord


class ParameterSchemaError(ValueError):
    """Raised when a parameter does not match its registered schema."""


@dataclass(frozen=True)
class ParameterSchema:
    parameter_id: str
    value_type: ParameterValueType
    dimension: str | None = None
    allowed_units: frozenset[str] = frozenset()
    allowed_values: frozenset[str] = frozenset()
    allowed_statuses: frozenset[ParameterStatus] = frozenset(ParameterStatus)


class ParameterSchemaRegistry:
    """Small PR-01 registry; it is not an engineering rule database."""

    def __init__(self, schemas: dict[str, ParameterSchema] | None = None):
        self._schemas = dict(schemas) if schemas is not None else self._default_schemas()

    def register(self, schema: ParameterSchema, *, replace: bool = False) -> None:
        """Register an extension field without turning the registry into a rule database."""
        if schema.parameter_id in self._schemas and not replace:
            raise ParameterSchemaError(f"Parameter already registered: {schema.parameter_id!r}")
        self._schemas[schema.parameter_id] = schema

    @staticmethod
    def _default_schemas() -> dict[str, ParameterSchema]:
        def length(parameter_id: str) -> ParameterSchema:
            return ParameterSchema(
                parameter_id,
                ParameterValueType.POSITIVE_NUMBER,
                "length",
                frozenset({"mm", "m"}),
            )
        return {
            "journal_diameter": length("journal_diameter"),
            "bearing_bore_diameter": length("bearing_bore_diameter"),
            "radial_clearance": length("radial_clearance"),
            "diametral_clearance": length("diametral_clearance"),
            "bearing_width": length("bearing_width"),
            "installation_width_limit": length("installation_width_limit"),
            "load": ParameterSchema(
                "load", ParameterValueType.POSITIVE_NUMBER, "force", frozenset({"N", "kN"}),
            ),
            "rotational_speed": ParameterSchema(
                "rotational_speed", ParameterValueType.POSITIVE_NUMBER, "rotational_speed",
                frozenset({"rpm"}),
            ),
            "surface_speed": ParameterSchema(
                "surface_speed", ParameterValueType.POSITIVE_NUMBER, "speed", frozenset({"m/s"})
            ),
            "mean_pressure": ParameterSchema(
                "mean_pressure", ParameterValueType.NON_NEGATIVE_NUMBER, "pressure",
                frozenset({"Pa", "kPa", "MPa"}),
            ),
            "clearance_ratio": ParameterSchema(
                "clearance_ratio", ParameterValueType.NON_NEGATIVE_NUMBER, "dimensionless",
                frozenset({"1"}),
            ),
            # Material labels are caller-supplied categories. The registry does not
            # encode a recommendation or an approved engineering materials list.
            "material": ParameterSchema(
                "material", ParameterValueType.CATEGORY, "dimensionless", frozenset({"1"})
            ),
            "shaft_material": ParameterSchema(
                "shaft_material", ParameterValueType.CATEGORY, "dimensionless", frozenset({"1"})
            ),
            "lubricant": ParameterSchema(
                "lubricant", ParameterValueType.CATEGORY, "dimensionless", frozenset({"1"})
            ),
            "rotation_direction": ParameterSchema(
                "rotation_direction",
                ParameterValueType.CATEGORY,
                "dimensionless",
                frozenset({"1"}),
                allowed_values=frozenset({"CW", "CCW"}),
            ),
        }

    def get(self, parameter_id: str) -> ParameterSchema | None:
        return self._schemas.get(parameter_id)

    def validate(self, parameter_id: str, value: Any, unit: str | None) -> None:
        schema = self.get(parameter_id)
        if schema is None:
            if value is not None:
                raise ParameterSchemaError(f"Unknown parameter_id with a value: {parameter_id!r}")
            return
        if schema.value_type in {
            ParameterValueType.POSITIVE_NUMBER,
            ParameterValueType.NON_NEGATIVE_NUMBER,
        }:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ParameterSchemaError(f"Parameter {parameter_id!r} requires a numeric value")
            if not math.isfinite(value):
                raise ParameterSchemaError(f"Parameter {parameter_id!r} must be finite")
            if schema.value_type == ParameterValueType.POSITIVE_NUMBER and value <= 0:
                raise ParameterSchemaError(f"Parameter {parameter_id!r} must be positive")
            if schema.value_type == ParameterValueType.NON_NEGATIVE_NUMBER and value < 0:
                raise ParameterSchemaError(f"Parameter {parameter_id!r} cannot be negative")
        elif schema.value_type == ParameterValueType.CATEGORY:
            if not isinstance(value, str) or not value.strip():
                raise ParameterSchemaError(f"Parameter {parameter_id!r} requires a category string")
            if schema.allowed_values and value not in schema.allowed_values:
                raise ParameterSchemaError(
                    f"Value {value!r} is not allowed for parameter {parameter_id!r}"
                )
        elif schema.value_type == ParameterValueType.TEXT and not isinstance(value, str):
            raise ParameterSchemaError(f"Parameter {parameter_id!r} requires text")
        if value is not None:
            if unit is None:
                raise ParameterSchemaError(f"Parameter {parameter_id!r} requires an explicit unit")
            if unit not in UNITS:
                raise ParameterSchemaError(f"Unknown unit: {unit!r}")
            if schema.allowed_units and unit not in schema.allowed_units:
                raise ParameterSchemaError(
                    f"Unit {unit!r} is not allowed for parameter {parameter_id!r}"
                )
            if schema.value_type in {
                ParameterValueType.POSITIVE_NUMBER,
                ParameterValueType.NON_NEGATIVE_NUMBER,
            }:
                try:
                    normalize(value, unit, schema.dimension)
                except (UnitError, TypeError, ValueError) as exc:
                    raise ParameterSchemaError(str(exc)) from exc

    def convert(self, parameter_id: str, value: Any, unit: str, target_unit: str) -> float:
        schema = self.get(parameter_id)
        if schema is None or schema.dimension is None:
            raise ParameterSchemaError(f"No convertible schema for {parameter_id!r}")
        if schema.value_type not in {
            ParameterValueType.POSITIVE_NUMBER,
            ParameterValueType.NON_NEGATIVE_NUMBER,
        }:
            raise ParameterSchemaError(f"Parameter {parameter_id!r} is not numeric")
        self.validate(parameter_id, value, unit)
        if target_unit not in UNITS:
            raise ParameterSchemaError(f"Unknown unit: {target_unit!r}")
        if schema.allowed_units and target_unit not in schema.allowed_units:
            raise ParameterSchemaError(
                f"Unit {target_unit!r} is not allowed for parameter {parameter_id!r}"
            )
        base_value, base_unit = normalize(value, unit, schema.dimension)
        target_value, _ = normalize(1.0, target_unit, schema.dimension)
        if target_value == 0:
            raise ParameterSchemaError(f"Invalid target unit: {target_unit!r}")
        # Both factors are expressed in the same base unit.
        return base_value / target_value

    def validate_record(self, parameter_id: str, record: ParameterRecord) -> None:
        if not parameter_id.strip():
            raise ParameterSchemaError("parameter_id cannot be empty")
        if record.parameter_id is not None and record.parameter_id != parameter_id:
            raise ParameterSchemaError(
                f"Parameter ID {record.parameter_id!r} does not match key {parameter_id!r}"
            )
        schema = self.get(parameter_id)
        if schema is not None and record.status not in schema.allowed_statuses:
            raise ParameterSchemaError(
                f"Status {record.status!r} is not allowed for {parameter_id!r}"
            )
        if record.status in {
            ParameterStatus.MISSING, ParameterStatus.UNAVAILABLE, ParameterStatus.NOT_APPLICABLE
        }:
            if record.value is not None:
                raise ParameterSchemaError(f"A {record.status} parameter cannot carry a value")
        elif record.value is None:
            raise ParameterSchemaError(f"Parameter {parameter_id!r} has status but no value")
        if record.value is not None:
            self.validate(parameter_id, record.value, record.unit)

