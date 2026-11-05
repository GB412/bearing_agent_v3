from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConditionAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    status: str
    scope: str
    input_ready: bool
    missing_inputs: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    derived_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    knowledge_refs: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)


class AnalysisStep(BaseModel):
    """A planning item, never a claim that a solver or expert rule has run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str
    status: str
    reason: str
    required_inputs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class DesignStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    strategy_id: str
    objective: str
    design_variables: list[str]
    required_evidence: list[str]
    available_rule_refs: list[str]
    unavailable_rule_refs: list[str]
    rationale: list[str]
    analysis_steps: list[AnalysisStep] = Field(default_factory=list)
    risk_questions: list[str] = Field(default_factory=list)
    unverified_advisory: str | None = None


class CandidateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    proposal_id: str
    status: str
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    unresolved_parameters: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
