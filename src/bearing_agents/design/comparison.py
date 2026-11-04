"""Conservative comparison; no unsupported numeric optimization claims."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import PrecheckStatus


class CandidateComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    first_ref: str
    second_ref: str
    comparability: Literal["COMPARABLE", "INCOMPARABLE"]
    preferred_ref: str | None = None
    reasons: list[str] = Field(default_factory=list)
    changed_design_variables: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


def compare_candidates(first: CandidateDesign, second: CandidateDesign) -> CandidateComparison:
    """Only comparable approved, complete check coverage can support preference."""
    first_ref = f"candidate:{first.candidate_id}@{first.version}"
    second_ref = f"candidate:{second.candidate_id}@{second.version}"
    changed = sorted(
        key for key in set(first.parameters) | set(second.parameters)
        if first.parameters.get(key) != second.parameters.get(key)
    )
    reasons: list[str] = []
    reports = (first.precheck_report, second.precheck_report)
    if any(report is None for report in reports):
        reasons.append("Both candidates require persisted deterministic precheck reports.")
    else:
        a, b = reports
        if first.rule_set_version != second.rule_set_version:
            reasons.append("Rule-set versions differ.")
        if first.source_parameter_revisions != second.source_parameter_revisions:
            reasons.append("Fixed engineering input revisions differ.")
        if first.input_constraint_revisions != second.input_constraint_revisions:
            reasons.append("Approved constraint revisions differ.")
        if a.uncovered_rules or b.uncovered_rules or a.missing_parameters or b.missing_parameters:
            reasons.append("One or both candidates have incomplete rule or parameter coverage.")
        ids_a = {item.get("rule_id") for item in a.checks}
        ids_b = {item.get("rule_id") for item in b.checks}
        if not ids_a or ids_a != ids_b or None in ids_a:
            reasons.append("The two reports lack identical traceable rule coverage.")
        if a.rule_set_version != b.rule_set_version:
            reasons.append("Precheck reports used different rule sets.")
    evidence_refs = sorted({
        ref for report in reports if report is not None
        for ref in report.evidence_refs
    })
    if reasons:
        return CandidateComparison(
            first_ref=first_ref, second_ref=second_ref,
            comparability="INCOMPARABLE", reasons=reasons,
            changed_design_variables=changed, evidence_refs=evidence_refs,
        )

    a_status, b_status = first.precheck_status, second.precheck_status
    preferred = None
    if a_status == PrecheckStatus.PRECHECK_PASS and b_status == PrecheckStatus.PRECHECK_FAIL:
        preferred = first_ref
    elif b_status == PrecheckStatus.PRECHECK_PASS and a_status == PrecheckStatus.PRECHECK_FAIL:
        preferred = second_ref
    else:
        reasons.append("No objective superiority established by matching prechecks.")
    return CandidateComparison(
        first_ref=first_ref, second_ref=second_ref,
        comparability="COMPARABLE", preferred_ref=preferred,
        reasons=reasons, changed_design_variables=changed,
        evidence_refs=evidence_refs,
    )
