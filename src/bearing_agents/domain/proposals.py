"""Pending parameter amendments that do not mutate authoritative DesignState inputs."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.parameters import ParameterRecord


class ProposalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class ProposalDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ParameterChangeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    parameter_id: str = Field(min_length=1)
    proposed_record: ParameterRecord
    base_revision: int = Field(ge=0)
    reason: str = Field(min_length=1)
    status: ProposalStatus = ProposalStatus.PENDING
    proposed_by: str | None = None
    resolved_by: str | None = None
    resolved_at_version: int | None = None


class ProposalResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    decision: ProposalDecision
