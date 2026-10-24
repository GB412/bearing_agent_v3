from pydantic import BaseModel, ConfigDict, Field, model_validator

from bearing_agents.domain.agent_protocols import TaskRecord
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import IssueStatus, SimulationStatus
from bearing_agents.domain.events import StateEvent
from bearing_agents.domain.operating_cases import AssumptionRecord, OperatingCase
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.proposals import ParameterChangeProposal


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
    parameter_change_proposals: list[ParameterChangeProposal] = Field(default_factory=list)
    issues: list[IssueRecord] = Field(default_factory=list)
    task_plan: list[TaskRecord] = Field(default_factory=list)
    knowledge_rule_set_version: str | None = None
    simulation_status: SimulationStatus = SimulationStatus.NOT_REQUESTED
    event_history: list[StateEvent] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_cached_indexes(cls, data: object) -> object:
        """Old JSON state may contain redundant materialized indexes.

        Current parameter confirmation lives on ParameterRecord; the event log
        preserves decisions, and the status of each object records staleness.
        """
        if isinstance(data, dict):
            data = dict(data)
            for obsolete in ("confirmations", "event_log_refs", "stale_objects"):
                data.pop(obsolete, None)
        return data
