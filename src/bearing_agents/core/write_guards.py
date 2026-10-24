"""Pure authorization guards for untrusted domain write payloads.

These checks do not authenticate users. Only the trusted application boundary
may supply USER/SYSTEM WriteContext and verified source references.
"""

from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    ParameterRole,
    ParameterStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriterKind


def _forged_authority(record: ParameterRecord) -> bool:
    return (
        record.status == ParameterStatus.CONFIRMED
        or record.confirmed_by is not None
        or record.verified_source_ref is not None
    )


def candidate_parameter_violation(
    record: ParameterRecord, kind: WriterKind,
) -> str | None:
    if _forged_authority(record):
        return "cannot claim user confirmation or trusted source evidence"
    if kind == WriterKind.AGENT and record.status == ParameterStatus.PROVIDED:
        return "cannot claim PROVIDED status"
    return None


def proposed_parameter_violation(record: ParameterRecord) -> str | None:
    # Proposed values are always untrusted, even before user approval.
    if _forged_authority(record):
        return "proposal cannot claim user confirmation or trusted source evidence"
    return None


def authoritative_parameter_violation(
    record: ParameterRecord, kind: WriterKind,
) -> str | None:
    # Unlike a verified extraction of a user's FIXED_INPUT, provisional design
    # values and LLM-calculated quantities must not become formal PROVIDED data.
    if kind == WriterKind.AGENT and record.status == ParameterStatus.PROVIDED:
        if record.role == ParameterRole.DESIGN_VARIABLE:
            return "Agent design variables must remain SUGGESTED"
        if record.role == ParameterRole.DERIVED:
            return "Derived PROVIDED results require trusted calculator execution"
    return None


def agent_constraint_violation(
    constraint: ConstraintRecord, kind: WriterKind,
) -> str | None:
    if kind == WriterKind.AGENT and (
        constraint.severity.value == "HARD"
        or constraint.origin.strip().casefold() == "user"
    ):
        return "Agents may submit only non-user-origin SOFT or INFO constraints"
    return None
