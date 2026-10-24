from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.enums import ConstraintOperator, ConstraintSeverity


class ConstraintRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    parameter: str
    operator: ConstraintOperator
    target: Any
    unit: str | None = None
    severity: ConstraintSeverity
    origin: str
    approved: bool = False
    scope: str | None = None
    rule_ref: str | None = None
    revision: int = Field(default=0, ge=0)
