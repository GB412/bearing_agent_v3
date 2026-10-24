import pytest

from bearing_agents.core.unit_normalizer import UnitError, normalize
from bearing_agents.tools.engineering_calculator import (
    journal_surface_speed,
    projected_mean_pressure,
)


def test_known_unit_conversion_and_dimension_check():
    assert normalize(100, "mm", "length") == pytest.approx((0.1, "m"))
    with pytest.raises(UnitError):
        normalize(100, "N", "length")
    with pytest.raises(UnitError):
        normalize(100, "furlong", "length")


def test_surface_speed_reference_case():
    assert journal_surface_speed(100, 1500) == pytest.approx(7.8539816, rel=1e-7)


@pytest.mark.parametrize("diameter,speed", [(0, 1000), (-1, 1000), (100, -1)])
def test_surface_speed_rejects_non_positive_values(diameter, speed):
    with pytest.raises(ValueError):
        journal_surface_speed(diameter, speed)


def test_surface_speed_rejects_non_finite_values():
    with pytest.raises(ValueError):
        journal_surface_speed(float("nan"), 1000)


def test_projected_mean_pressure_reference_case():
    assert projected_mean_pressure(12000, 100, 60) == pytest.approx(2e6)


@pytest.mark.parametrize(
    "load,diameter,width",
    [(0, 100, 60), (-1, 100, 60), (1, 0, 60), (1, 1, -2)],
)
def test_pressure_rejects_non_positive_values(load, diameter, width):
    with pytest.raises(ValueError):
        projected_mean_pressure(load, diameter, width)
