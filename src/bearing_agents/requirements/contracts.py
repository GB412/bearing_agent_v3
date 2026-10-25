"""Small contracts: model proposals carry no identity or approval authority."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.enums import ParameterRole


class UserTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    message_id: str
    design_id: str
    actor: str
    received_at: datetime
    content: str
    content_sha256: str


class RequirementProposal(BaseModel):
    """Untrusted extraction. Message identity is supplied separately by the caller."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["parameter", "steady_state", "scope", "constraint"]
    field_id: str
    quote: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    value: float | str | None = None
    unit: str | None = None
    role: ParameterRole | None = None
    modality: Literal["EXPLICIT", "UNCERTAIN", "NEGATED", "AMBIGUOUS"] = "EXPLICIT"
    operator: Literal["LE", "IN", "NOT_IN"] | None = None


class VerifiedRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: RequirementProposal
    decision: Literal["ACCEPT", "CLARIFY", "REJECT"]
    reason: str
    normalized_value: float | str | None = None
    normalized_unit: str | None = None


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str
    reason_code: str
    text: str = Field(min_length=1, max_length=300)


class RequirementSpecView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    design_id: str
    state_version: int
    scope: str
    input_ready: bool
    parameters: dict[str, dict]
    questions: list[Question] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    pending_constraints: list[str] = Field(default_factory=list)


class InteractionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    design_id: str
    message_id: str
    state_version: int
    replayed: bool = False
