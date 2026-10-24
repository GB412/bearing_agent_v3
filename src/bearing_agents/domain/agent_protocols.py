from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    AgentResultStatus,
    ParameterRole,
    RuleStatus,
    TaskStatus,
)
from bearing_agents.domain.operating_cases import OperatingCase
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.proposals import ParameterChangeProposal, ProposalResolution

if TYPE_CHECKING:
    from bearing_agents.domain.state import DesignState


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: str
    agent: str
    status: TaskStatus
    dependencies: list[str] = Field(default_factory=list)
    input_version: int = Field(ge=0)
    output_ref: str | None = None
    attempt_count: int = Field(default=0, ge=0)


class PlanDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    selected_agent: str
    input_refs: list[str] = Field(default_factory=list)
    rationale: str
    expected_result: str
    requires_confirmation: bool = False
    state_version: int = Field(ge=0)


class StatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter_changes: dict[str, ParameterRecord] = Field(default_factory=dict)
    parameter_change_proposals: list[ParameterChangeProposal] = Field(default_factory=list)
    proposal_resolutions: list[ProposalResolution] = Field(default_factory=list)
    constraint_changes: list[ConstraintRecord] = Field(default_factory=list)
    operating_case_changes: list[OperatingCase] = Field(default_factory=list)
    candidate_additions: list[CandidateDesign] = Field(default_factory=list)
    confirmation_events: list["ConfirmationEvent"] = Field(default_factory=list)
    role_changes: list["RoleChange"] = Field(default_factory=list)
    rule_set_change: "RuleSetChange | None" = None
    source: str
    actor: str | None = None


class ConfirmationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter_id: str
    confirmed_by: str
    reason: str | None = None


class RoleChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parameter_id: str
    from_role: ParameterRole
    to_role: ParameterRole
    approved_by: str


class RuleSetChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    status: AgentResultStatus
    state_patch: StatePatch | None = None
    issues: list[Any] = Field(default_factory=list)
    suggested_next_actions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class RuleRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    source_document: str
    section: str
    scope: str
    inputs: list[str] = Field(default_factory=list)
    operation: str
    status: RuleStatus
    version: str
    reviewer: str | None = None
    tests: list[str] = Field(default_factory=list)


class StateRepository(Protocol):
    def create(self, state: "DesignState") -> None: ...

    def get(self, design_id: str) -> "DesignState | None": ...

    def save(self, state: "DesignState", expected_version: int) -> None: ...


class Agent(Protocol):
    def run(self, state: Any, task: TaskRecord) -> AgentResult: ...
