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
    """Untrusted structured extraction, without model-authored evidence offsets.

    The application—not the model—attaches message identity and write authority.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["parameter", "steady_state", "scope", "constraint", "preference"]
    field_id: str
    value: float | str | bool | None = None
    unit: str | None = None
    modality: Literal[
        "EXPLICIT", "UNCERTAIN", "NEGATED", "AMBIGUOUS", "UNKNOWN", "CORRECTION"
    ] = "EXPLICIT"
    operator: Literal["LE", "IN", "NOT_IN"] | None = None
    # Kept for deterministic/legacy callers; ignored for write permissions.
    role: ParameterRole | None = None


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
    why_needed: str | None = None


class RequirementGuidance(BaseModel):
    """Advisory interpretation, never a trusted engineering parameter."""

    model_config = ConfigDict(extra="forbid")

    scenario_hint: str | None = None
    scenario_confirmed: bool = False
    objective_hints: list[str] = Field(default_factory=list)
    required_external_missing: list[str] = Field(default_factory=list)
    proposable_design_variables: list[str] = Field(default_factory=list)
    derived_not_requested: list[str] = Field(default_factory=list)
    pending_user_decisions: list[str] = Field(default_factory=list)
    optional_topics: list[str] = Field(default_factory=list)
    next_step: Literal["CLARIFY_SCOPE", "RESOLVE_CONFLICT", "COLLECT_EXTERNAL",
                       "APPROVE_CONSTRAINT", "READY_FOR_DESIGN"]
    note: str


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
    guidance: RequirementGuidance | None = None


class InteractionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    design_id: str
    message_id: str
    state_version: int
    replayed: bool = False
