from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.enums import AgentResultStatus, RuleStatus
from bearing_agents.domain.events import StateEvent
from bearing_agents.domain.parameters import ParameterRecord


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    action: str
    agent: str
    status: str
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

    parameters: dict[str, ParameterRecord] = Field(default_factory=dict)
    state_updates: dict[str, Any] = Field(default_factory=dict)
    source: str
    actor: str | None = None
    authorized_fixed_input_ids: set[str] = Field(default_factory=set)


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
    def create(self, state: Any) -> None: ...

    def get(self, design_id: str) -> Any | None: ...

    def save(self, state: Any, expected_version: int) -> None: ...


class EventRepository(Protocol):
    def append(self, event: StateEvent) -> None: ...


class Agent(Protocol):
    def run(self, state: Any, task: TaskRecord) -> AgentResult: ...
