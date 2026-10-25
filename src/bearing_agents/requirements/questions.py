"""Deterministic user questions based on authoritative readiness, never a second R2."""

from bearing_agents.core.state_manager import StateManager
from bearing_agents.requirements.contracts import Question, RequirementSpecView


def build_view(manager: StateManager, design_id: str, unresolved=()) -> RequirementSpecView:
    state=manager.get_design(design_id)
    gate=manager.readiness_for(design_id, "R2")
    questions=[]
    def ask(code, message):
        if len(questions)<3 and code not in {q.reason_code for q in questions}:
            questions.append(Question(
                question_id=f"{design_id}:{state.state_version}:{code}",
                reason_code=code,text=message,
            ))
    if state.target_scope=="unknown":
        ask("SCOPE_UNKNOWN","请确认是否设计油润滑圆柱径向动压滑动轴承（单稳态），或说明轴承具体类型。")
    elif state.target_scope!="cylindrical_radial_hydrodynamic":
        ask("UNSUPPORTED_SCOPE","这类轴承超出当前版本范围，请改为圆柱径向动压滑动轴承或另行处理。")
    for reason in unresolved:
        ask("CLARIFY_INPUT",f"这条信息尚不明确：{reason}。请提供准确数值、单位或明确说明。")
    parameter_conflicts = [
        conflict for conflict in gate.conflicts if not conflict.startswith("operating_case:")
    ]
    if parameter_conflicts:
        ask("INPUT_CONFLICT", "现有设计条件存在冲突，请核对：" + "; ".join(parameter_conflicts[:2]))
    if state.target_scope!="unsupported":
        missing={p.parameter_id for p in gate.missing}
        for key,message in (
            ("journal_diameter","请提供轴颈直径（如 100 mm）。"),
            ("load","请提供径向载荷及其单位（如 12 kN）；如果是估算值请说明。"),
            ("rotational_speed","请提供转速及其单位（如 1500 rpm）。"),
        ):
            if key in missing:
                ask("MISSING_"+key.upper(),message)
        if not any(c.is_steady_state is True and (c.confirmed_by or c.verified_source_ref)
                   for c in state.operating_cases):
            ask("STEADY_STATE_UNKNOWN","请确认这是单一、明确的稳态工况吗？")
    pending=[c.id for c in state.constraints if not c.approved]
    if not questions and pending:
        ask("CONSTRAINT_APPROVAL","存在尚未批准的安装或材料约束，请明确批准或拒绝对应约束。")
    return RequirementSpecView(
        design_id=state.design_id,state_version=state.state_version,
        scope=state.target_scope,
        input_ready=gate.ready and state.target_scope=="cylindrical_radial_hydrodynamic",
        parameters={k:{"value":v.value,"unit":v.unit,"role":v.role.value,
                       "status":v.status.value,"revision":v.revision,
                       "verified_source_ref":v.verified_source_ref}
                    for k,v in state.parameters.items()},
        questions=questions,unresolved=list(unresolved),
        pending_constraints=pending,
    )
