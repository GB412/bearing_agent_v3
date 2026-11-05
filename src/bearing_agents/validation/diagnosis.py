"""Evidence-only diagnosis of persisted deterministic precheck reports.

No solver is run; no pass/fail decision, input or constraint is modified here.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.candidates import CandidateDesign, CandidatePrecheckReport
from bearing_agents.domain.enums import ParameterRole, ParameterStatus, PrecheckStatus
from bearing_agents.domain.state import DesignState


class ValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding_id: str
    kind: Literal[
        "MISSING_PARAMETER",
        "RULE_COVERAGE_GAP",
        "RULE_FAILURE",
        "RULE_REVIEW",
        "STALE_RESULT",
        "GENERAL_REVIEW",
    ]
    message: str
    source_ref: str | None = None
    parameter_id: str | None = None
    adjustable_parameter_ids: list[str] = Field(default_factory=list)
    next_action: Literal[
        "CLARIFY_REQUIREMENT",
        "REVIEW_RULE_SOURCE",
        "REVIEW_DESIGN_VARIABLE",
        "RECHECK_INPUT",
        "EXPERT_REVIEW",
    ]


class ValidationDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_ref: str
    precheck_status: PrecheckStatus
    findings: list[ValidationFinding] = Field(default_factory=list)
    note: str = (
        "诊断仅解释已有的确定性校核证据；不改变校核结论，也不表示已完成油膜性能求解。"
    )


def _adjustable_parameter(
    state: DesignState,
    candidate: CandidateDesign,
    parameter_id: Any,
) -> bool:
    if not isinstance(parameter_id, str) or not parameter_id:
        return False
    record = candidate.parameters.get(parameter_id)
    if record is None or record.role != ParameterRole.DESIGN_VARIABLE:
        return False
    if record.status == ParameterStatus.CONFIRMED or record.confirmed_by:
        return False
    existing = state.parameters.get(parameter_id)
    if existing is not None and (
        existing.role != ParameterRole.DESIGN_VARIABLE
        or existing.status == ParameterStatus.CONFIRMED
        or existing.confirmed_by
    ):
        return False
    return True


def diagnose_precheck(
    state: DesignState,
    candidate: CandidateDesign,
    report: CandidatePrecheckReport,
) -> ValidationDiagnosis:
    """Explain the current stored report, never accept a model-authored report."""
    persisted = next(
        (
            item for item in state.candidate_designs
            if item.candidate_id == candidate.candidate_id
            and item.version == candidate.version
        ),
        None,
    )
    if persisted is None or candidate != persisted:
        raise ValueError("Candidate must match its authoritative state version")
    if persisted.precheck_report is None or persisted.precheck_report != report:
        raise ValueError("Diagnosis requires the persisted precheck report")
    if report.status != persisted.precheck_status:
        # Invalidated candidates may retain historical precheck reports.
        if persisted.precheck_status != PrecheckStatus.STALE:
            raise ValueError("Candidate/report status mismatch")

    ref = f"candidate:{candidate.candidate_id}@{candidate.version}"
    findings: list[ValidationFinding] = []

    if persisted.precheck_status == PrecheckStatus.STALE:
        findings.append(ValidationFinding(
            finding_id="input-stale",
            kind="STALE_RESULT",
            message="设计输入已改变，原预校核结果失效；需重新生成或复核相应候选。",
            next_action="RECHECK_INPUT",
        ))
        return ValidationDiagnosis(
            candidate_ref=ref, precheck_status=PrecheckStatus.STALE, findings=findings,
        )

    for parameter_id in sorted(set(report.missing_parameters)):
        findings.append(ValidationFinding(
            finding_id=f"missing:{parameter_id}",
            kind="MISSING_PARAMETER",
            message=f"设计变量 {parameter_id} 尚无足够的可信输入或推荐依据。",
            parameter_id=parameter_id,
            next_action="CLARIFY_REQUIREMENT",
        ))
    for rule_id in sorted(set(report.uncovered_rules)):
        findings.append(ValidationFinding(
            finding_id=f"uncovered:{rule_id}",
            kind="RULE_COVERAGE_GAP",
            message=f"规则 {rule_id} 尚未形成可执行、已审核的覆盖证据。",
            next_action="REVIEW_RULE_SOURCE",
        ))
    for index, check in enumerate(report.checks):
        status = check.get("status")
        if status == "PASS":
            continue
        parameter_id = check.get("parameter_id")
        safe_param = parameter_id if isinstance(parameter_id, str) else None
        adjustable = (
            [safe_param] if _adjustable_parameter(state, candidate, safe_param) else []
        )
        rule_id = check.get("rule_id")
        source = check.get("source_ref")
        findings.append(ValidationFinding(
            finding_id=f"check:{index}",
            kind="RULE_FAILURE" if status == "FAIL" else "RULE_REVIEW",
            message=(
                f"校核项 {rule_id or index} 的结果为 {status or 'UNKNOWN'}，"
                "请根据原始规则和实际计算记录进行处理。"
            ),
            source_ref=source if isinstance(source, str) else None,
            parameter_id=safe_param,
            adjustable_parameter_ids=adjustable,
            next_action="REVIEW_DESIGN_VARIABLE" if adjustable else "EXPERT_REVIEW",
        ))
    if not findings and report.status != PrecheckStatus.PRECHECK_PASS:
        findings.append(ValidationFinding(
            finding_id="general-review",
            kind="GENERAL_REVIEW",
            message="预校核未通过或证据不足，需要人工检查原始报告。",
            next_action="EXPERT_REVIEW",
        ))

    return ValidationDiagnosis(
        candidate_ref=ref, precheck_status=persisted.precheck_status,
        findings=findings,
    )
