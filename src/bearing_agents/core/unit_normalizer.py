from dataclasses import dataclass


class UnitError(ValueError):
    """Raised when a unit is unknown or dimensionally incompatible."""


@dataclass(frozen=True)
class UnitDefinition:
    dimension: str
    to_base: float
    base_unit: str


UNITS: dict[str, UnitDefinition] = {
    "mm": UnitDefinition("length", 1e-3, "m"),
    "m": UnitDefinition("length", 1.0, "m"),
    "N": UnitDefinition("force", 1.0, "N"),
    "kN": UnitDefinition("force", 1e3, "N"),
    "rpm": UnitDefinition("rotational_speed", 1.0, "rpm"),
    "Pa": UnitDefinition("pressure", 1.0, "Pa"),
    "kPa": UnitDefinition("pressure", 1e3, "Pa"),
    "MPa": UnitDefinition("pressure", 1e6, "Pa"),
    "m/s": UnitDefinition("speed", 1.0, "m/s"),
    "1": UnitDefinition("dimensionless", 1.0, "1"),
}


def normalize(value: float, unit: str, expected_dimension: str | None = None) -> tuple[float, str]:
    try:
        definition = UNITS[unit]
    except KeyError as exc:
        raise UnitError(f"Unknown unit: {unit!r}") from exc
    if expected_dimension and definition.dimension != expected_dimension:
        raise UnitError(
            f"Unit {unit!r} has dimension {definition.dimension!r}; expected {expected_dimension!r}"
        )
    return value * definition.to_base, definition.base_unit
