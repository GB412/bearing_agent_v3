from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.enums import (
    ConfirmationStatus,
    PrecheckStatus,
    SimulationStatus,
)
from bearing_agents.domain.parameters import ParameterRecord


class CandidateDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    version: int = Field(ge=1)
    parent_candidate_id: str | None = None
    parameters: dict[str, ParameterRecord] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    source_parameter_revisions: dict[str, int] = Field(default_factory=dict)
    rule_refs: list[str] = Field(default_factory=list)
    confirmation_status: ConfirmationStatus = ConfirmationStatus.PENDING
    precheck_status: PrecheckStatus = PrecheckStatus.NOT_EVALUATED
    simulation_status: SimulationStatus = SimulationStatus.NOT_REQUESTED
