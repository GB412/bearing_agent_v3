from pydantic import BaseModel, ConfigDict, Field


class OperatingCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    journal_diameter_ref: str | None = None
    load_ref: str | None = None
    speed_ref: str | None = None
    load_direction: str | None = None
    # An unknown operating regime must never be assumed to be steady-state.
    is_steady_state: bool | None = None
    confirmed_by: str | None = None
    description: str | None = None
    revision: int = Field(default=0, ge=0)


class AssumptionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumption_id: str
    statement: str
    source: str
    confirmed_by: str | None = None
