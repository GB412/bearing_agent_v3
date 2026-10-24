from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bearing_agents.domain.enums import ParameterRole, ParameterStatus


class ParameterRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter_id: str | None = None
    value: Any = None
    unit: str | None = None
    role: ParameterRole
    status: ParameterStatus = ParameterStatus.MISSING
    source: str | None = None
    source_ref: str | None = None
    # Authority-managed evidence reference, never accepted from an Agent patch.
    verified_source_ref: str | None = None
    applies_to_case: str | None = None
    confirmed_by: str | None = None
    revision: int = Field(default=0, ge=0)
    invalidated_by: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_stage_hint(cls, data: object) -> object:
        if isinstance(data, dict):
            data = dict(data)
            data.pop("required_for", None)
        return data

    @field_validator("parameter_id")
    @classmethod
    def nonempty_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("parameter_id cannot be empty")
        return value
