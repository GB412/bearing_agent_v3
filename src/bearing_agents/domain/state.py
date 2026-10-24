from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.agent_protocols import TaskRecord
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import IssueStatus, SimulationStatus
from bearing_agents.domain.events import StateEvent
from bearing_agents.domain.operating_cases import AssumptionRecord, OperatingCase
from bearing_agents.domain.parameters import ParameterRecord


class IssueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: str
    affected_fields: list[str] = Field(default_factory=list)
    explanation: str
    status: IssueStatus = IssueStatus.OPEN
    suggested_actions: list[str] = Field(default_factory=list)
    rule_refs: list[str] = Field(default_factory=list)


class DesignState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: str
    state_version: int = Field(default=0, ge=0)
    thread_id: str | None = None
    target_scope: str = "cylindrical_radial_hydrodynamic"
    user_goal: str | None = None
    operating_cases: list[OperatingCase] = Field(default_factory=list)
    parameters: dict[str, ParameterRecord] = Field(default_factory=dict)
    constraints: list[ConstraintRecord] = Field(default_factory=list)
    assumptions: list[AssumptionRecord] = Field(default_factory=list)
    candidate_designs: list[CandidateDesign] = Field(default_factory=list)
    issues: list[IssueRecord] = Field(default_factory=list)
    task_plan: list[TaskRecord] = Field(default_factory=list)
    knowledge_rule_set_version: str | None = None
    confirmations: dict[str, Any] = Field(default_factory=dict)
    simulation_status: SimulationStatus = SimulationStatus.NOT_REQUESTED
    event_log_refs: list[str] = Field(default_factory=list)
    stale_objects: list[str] = Field(default_factory=list)
    event_history: list[StateEvent] = Field(default_factory=list)
