import pytest
from pydantic import ValidationError

from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import ConstraintOperator, ConstraintSeverity


def test_constraint_keeps_origin_approval_scope_and_rule_provenance():
    constraint = ConstraintRecord(
        id="clearance-max",
        parameter="radial_clearance",
        operator=ConstraintOperator.LE,
        target=0.1,
        unit="mm",
        severity=ConstraintSeverity.HARD,
        origin="user",
        approved=True,
        scope="single operating case",
        rule_ref="user-input-17",
    )
    assert constraint.approved is True
    assert constraint.rule_ref == "user-input-17"
    assert constraint.origin == "user"


def test_constraint_rejects_unknown_operator():
    with pytest.raises(ValidationError):
        ConstraintRecord(
            id="c1",
            parameter="bearing_width",
            operator="APPROX",
            target=10,
            unit="mm",
            severity="HARD",
            origin="user",
        )
