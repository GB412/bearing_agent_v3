"""Read-only engineering-intent hints; not an additional source of verified inputs."""

from bearing_agents.core.readiness import ReadinessResult
from bearing_agents.domain.state import DesignState
from bearing_agents.requirements.contracts import RequirementGuidance

_SCENARIOS = (
    ("齿轮箱", "gearbox"),
    ("变速箱", "gearbox"),
    ("汽轮机", "turbine"),
    ("电动机", "electric_motor"),
    ("压缩机", "compressor"),
)
_OBJECTIVES = (
    ("可靠性", "reliability"),
    ("温升", "temperature"),
    ("发热", "temperature"),
    ("成本", "cost"),
    ("噪声", "noise"),
    ("寿命", "service_life"),
)
_PROPOSABLE = ("bearing_width", "radial_clearance", "material", "lubricant")


def interpret_requirements(
    state: DesignState,
    gate: ReadinessResult,
    *,
    recent_text: str = "",
) -> RequirementGuidance:
    """Interpret descriptions as hints without altering parameter roles or approvals."""
    text = " ".join((state.user_goal or "", recent_text)).lower()
    scenario = next((value for keyword, value in _SCENARIOS if keyword in text), None)
    objectives = list(dict.fromkeys(
        value for keyword, value in _OBJECTIVES if keyword in text
    ))
    missing = [item.parameter_id for item in gate.missing]
    pending = [item.id for item in state.constraints if not item.approved]
    proposable = [
        key for key in _PROPOSABLE
        if key not in state.parameters or state.parameters[key].value is None
    ]
    if state.target_scope == "unknown":
        next_step = "CLARIFY_SCOPE"
    elif state.target_scope != "cylindrical_radial_hydrodynamic" or gate.conflicts:
        next_step = "RESOLVE_CONFLICT"
    elif missing or not gate.ready:
        next_step = "COLLECT_EXTERNAL"
    elif pending:
        next_step = "APPROVE_CONSTRAINT"
    else:
        next_step = "READY_FOR_DESIGN"

    return RequirementGuidance(
        scenario_hint=scenario,
        scenario_confirmed=False,
        objective_hints=objectives,
        required_external_missing=missing,
        proposable_design_variables=proposable,
        derived_not_requested=["surface_speed", "mean_pressure"],
        pending_user_decisions=pending,
        optional_topics=[
            "安装宽度和其他空间限制", "材料及润滑偏好", "可接受的温升与成本目标",
        ],
        next_step=next_step,
        note=(
            "场景和偏好仅由已记录文字推测，未经用户单独核实；"
            "R2 外部必需参数以受信 readiness 结果为准；"
            "轴承宽度、间隙、材料和润滑剂可由设计阶段提出候选，不强迫用户先填。"
        ),
    )
