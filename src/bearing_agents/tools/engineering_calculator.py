import math

from bearing_agents.core.unit_normalizer import normalize


def _positive_finite(name: str, value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def journal_surface_speed(
    diameter_mm: float,
    speed_rpm: float,
    *,
    diameter_unit: str = "mm",
    speed_unit: str = "rpm",
) -> float:
    """Return journal surface speed in m/s with explicit input units."""
    if isinstance(diameter_mm, bool) or isinstance(speed_rpm, bool):
        raise ValueError("diameter and speed must be numeric, not bool")
    diameter_m, _ = normalize(_positive_finite("diameter", diameter_mm), diameter_unit, "length")
    speed, _ = normalize(_positive_finite("speed", speed_rpm), speed_unit, "rotational_speed")
    return math.pi * diameter_m * speed / 60.0


def projected_mean_pressure(
    load_N: float,
    diameter_mm: float,
    width_mm: float,
    *,
    load_unit: str = "N",
    diameter_unit: str = "mm",
    width_unit: str = "mm",
) -> float:
    """Return projected mean pressure F/(D*B) in Pa, not local film pressure."""
    if any(isinstance(value, bool) for value in (load_N, diameter_mm, width_mm)):
        raise ValueError("load and geometry must be numeric, not bool")
    load, _ = normalize(_positive_finite("load", load_N), load_unit, "force")
    diameter, _ = normalize(_positive_finite("diameter", diameter_mm), diameter_unit, "length")
    width, _ = normalize(_positive_finite("width", width_mm), width_unit, "length")
    return load / (diameter * width)
