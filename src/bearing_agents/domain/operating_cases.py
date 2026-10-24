from pydantic import BaseModel, ConfigDict


class OperatingCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    journal_diameter_ref: str | None = None
    load_ref: str | None = None
    speed_ref: str | None = None
    load_direction: str | None = None
    is_steady_state: bool = True
    description: str | None = None


class AssumptionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assumption_id: str
    statement: str
    source: str
    confirmed_by: str | None = None
