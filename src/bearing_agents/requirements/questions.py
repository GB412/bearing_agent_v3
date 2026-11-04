"""Adaptive and deterministic questions grounded in the authoritative R2 gate."""

from bearing_agents.core.readiness import ReadinessResult
from bearing_agents.domain.state import DesignState
from bearing_agents.requirements.contracts import Question, RequirementSpecView
from bearing_agents.requirements.guidance import interpret_requirements

_QUESTION_CATALOG = {
    "journal_diameter": (
        "请提供轴颈直径（如 100 mm）。",
        "轴颈直径属于设备给定条件，用于计算表面速度并确定轴承尺寸边界。",
    ),
    "load": (
        "请提供径向载荷及其单位（如 12 kN）；如果是估算值请说明。",
        "载荷是外部工况输入，用于后续承载能力分析，不能由 Agent 自行猜测。",
    ),
    "rotational_speed": (
        "请提供转速及其单位（如 1500 rpm）。",
        "转速用于分析表面速度和润滑工况，必须有可信的外部依据。",
    ),
}


def _external_order(text: str) -> tuple[str, ...]:
    """Reorder only actual R2 inputs; never promote a design variable to a required fact."""
    if "载荷" in text and any(tag in text for tag in ("估计", "大约", "不确定")):
        return ("load", "journal_diameter", "rotational_speed")
    if any(word in text for word in ("温升", "高速", "发热", "temperature", "high speed")):
        return ("rotational_speed", "load", "journal_diameter")
    if any(word in text for word in ("重载", "承载", "大载荷", "load capacity")):
        return ("load", "journal_diameter", "rotational_speed")
    return ("journal_diameter", "load", "rotational_speed")


def build_view(
    state: DesignState,
    gate: ReadinessResult,
    unresolved=(),
    *,
    recent_text: str = "",
) -> RequirementSpecView:
    """Pure projection: no state writes, inferred facts or unapproved rule values."""
    guidance = interpret_requirements(state, gate, recent_text=recent_text)
    questions: list[Question] = []

    def ask(code: str, message: str, why: str) -> None:
        if len(questions) < 3 and code not in {q.reason_code for q in questions}:
            questions.append(Question(
                question_id=f"{state.design_id}:{state.state_version}:{code}",
                reason_code=code,
                text=message,
                why_needed=why,
            ))

    if state.target_scope == "unknown":
        ask(
            "SCOPE_UNKNOWN",
            "请确认是否设计油润滑圆柱径向动压滑动轴承（单稳态），或说明轴承具体类型。",
            "需要先确认适用轴承类型，才能判断可用的计算与设计规则。",
        )
    elif state.target_scope != "cylindrical_radial_hydrodynamic":
        ask(
            "UNSUPPORTED_SCOPE",
            "这类轴承超出当前版本范围，请改为圆柱径向动压滑动轴承或另行处理。",
            "当前版本不支持对该轴承类型作专业设计承诺。",
        )

    # An estimated value may not match a strict numeric extractor pattern.
    # Ask for clarification without ever promoting it into a verified parameter.
    if not unresolved and any(
        tag in recent_text for tag in ("估计", "大约", "大概", "不确定")
    ) and any(
        field in recent_text for field in ("载荷", "轴径", "轴颈", "转速")
    ):
        ask(
            "CLARIFY_INPUT",
            "当前工况数值被描述为估计或不确定；请明确数值、单位和依据。",
            "估计或未经核实的信息不能自动升级为确定性工程输入。",
        )
    for reason in unresolved:
        ask(
            "CLARIFY_INPUT",
            f"这条信息尚不明确：{reason}。请提供准确数值、单位或明确说明。",
            "不明确或否定的信息不能作为已经验证的工程输入。",
        )
    parameter_conflicts = [
        conflict for conflict in gate.conflicts if not conflict.startswith("operating_case:")
    ]
    if parameter_conflicts:
        ask(
            "INPUT_CONFLICT",
            "现有设计条件存在冲突，请核对：" + "; ".join(parameter_conflicts[:2]),
            "冲突未澄清前，后续计算可能基于错误工况。",
        )

    if state.target_scope != "unsupported":
        missing = {item.parameter_id for item in gate.missing}
        text = " ".join((state.user_goal or "", recent_text)).lower()
        ordered = list(_external_order(text))
        # A registered R2 profile may contain other external inputs; do not silently drop them.
        ordered.extend(sorted(missing - set(ordered)))
        for key in ordered:
            if key in missing:
                message, why = _QUESTION_CATALOG.get(
                    key, (f"请补充已登记的外部工况输入 {key} 及其单位。",
                          f"{key} 是当前受信 R2 要求中的外部输入。"),
                )
                ask("MISSING_" + key.upper(), message, why)
        if not any(
            item.is_steady_state is True and (item.confirmed_by or item.verified_source_ref)
            for item in state.operating_cases
        ):
            ask(
                "STEADY_STATE_UNKNOWN",
                "请确认这是单一、明确的稳态工况吗？",
                "当前专业计算范围只覆盖单一稳态条件。",
            )
    if not questions and guidance.pending_user_decisions:
        ask(
            "CONSTRAINT_APPROVAL",
            "存在尚未批准的安装或材料约束，请明确批准或拒绝对应约束。",
            "用户声明的硬约束必须经过可信用户操作，不能由 Agent 自动批准。",
        )

    return RequirementSpecView(
        design_id=state.design_id,
        state_version=state.state_version,
        scope=state.target_scope,
        input_ready=gate.ready and state.target_scope == "cylindrical_radial_hydrodynamic",
        parameters={
            key: {
                "value": record.value,
                "unit": record.unit,
                "role": record.role.value,
                "status": record.status.value,
                "revision": record.revision,
                "verified_source_ref": record.verified_source_ref,
            }
            for key, record in state.parameters.items()
        },
        questions=questions,
        unresolved=list(unresolved),
        pending_constraints=guidance.pending_user_decisions,
        guidance=guidance,
    )
