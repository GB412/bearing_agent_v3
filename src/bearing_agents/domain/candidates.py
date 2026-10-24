from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.enums import (
    ConfirmationStatus,
    PrecheckStatus,
    SimulationStatus,
)
from bearing_agents.domain.parameters import ParameterRecord


class PrecheckHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PrecheckStatus
    input_dependency_refs: dict[str, str]
    invalidated_at_state_version: int
    changed_fields: list[str]


class CandidateDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    version: int = Field(ge=1)
    parent_candidate_id: str | None = None
    parameters: dict[str, ParameterRecord] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    source_parameter_revisions: dict[str, int] = Field(default_factory=dict)
    input_constraint_revisions: dict[str, int] = Field(default_factory=dict)
    input_dependency_refs: dict[str, str] = Field(default_factory=dict)
    rule_set_version: str | None = None
    precheck_history: list[PrecheckHistoryEntry] = Field(default_factory=list)
    rule_refs: list[str] = Field(default_factory=list)
    confirmation_status: ConfirmationStatus = ConfirmationStatus.PENDING
    precheck_status: PrecheckStatus = PrecheckStatus.NOT_EVALUATED
    simulation_status: SimulationStatus = SimulationStatus.NOT_REQUESTED
