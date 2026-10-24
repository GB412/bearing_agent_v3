import math


def _positive_finite(name: str, value: float) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return value


def journal_surface_speed(diameter_mm: float, speed_rpm: float) -> float:
    """Return journal surface speed in m/s from diameter in mm and speed in rpm."""
    diameter_mm = _positive_finite("diameter_mm", diameter_mm)
    speed_rpm = _positive_finite("speed_rpm", speed_rpm)
    return math.pi * (diameter_mm / 1000.0) * speed_rpm / 60.0


def projected_mean_pressure(load_N: float, diameter_mm: float, width_mm: float) -> float:
    """Return projected mean pressure F/(D*B) in Pa, not local film pressure."""
    load_N = _positive_finite("load_N", load_N)
    diameter_mm = _positive_finite("diameter_mm", diameter_mm)
    width_mm = _positive_finite("width_mm", width_mm)
    area_m2 = (diameter_mm / 1000.0) * (width_mm / 1000.0)
    return load_N / area_m2
