"""Chinese multi-agent bearing design demo; offline by default, real LLM is opt-in.

Offline: python examples/interactive_design.py --db .venv/design.sqlite
Real API: python examples/interactive_design.py --llm --db .venv/design.sqlite

Only confirmed mathematical indicators are calculated; DLAP is NOT integrated.
"""

import argparse
from pathlib import Path
from uuid import uuid4

from bearing_agents.application import open_application
from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.llm_planner import LLMPlanner
from bearing_agents.requirements.extraction import LLMExtractor


def render_report(state, execution=None) -> str:
    """Render authoritative facts; the language model never authors this report."""
    lines = [
        "# 多 Agent 轴承设计过程记录",
        "",
        f"- Design ID: `{state.design_id}`",
        f"- State version: {state.state_version}",
        f"- Goal: {state.user_goal or '未指定'}",
        f"- Bearing scope: {state.target_scope}",
        "- Professional acceptance: **ENGINEERING_DOMAIN_PENDING**",
        "- DLAP: **NOT_AVAILABLE** (no oil-film / thermal solver result)",
        "",
        "## 用户输入与设计变量",
        "",
    ]
    for key, record in sorted(state.parameters.items()):
        lines.append(
            f"- `{key}`: {record.value} {record.unit or ''} "
            f"({record.role.value}, {record.status.value}; "
            f"verified={bool(record.verified_source_ref)})"
        )
    lines.extend(["", "## 用户约束", ""])
    for constraint in state.constraints:
        lines.append(
            f"- `{constraint.id}`: {constraint.parameter} {constraint.operator.value} "
            f"{constraint.target} {constraint.unit}; approved={constraint.approved}"
        )
    lines.extend(["", "## 候选与预校核", ""])
    for candidate in state.candidate_designs:
        lines.append(
            f"### `candidate:{candidate.candidate_id}@{candidate.version}`"
        )
        lines.append(
            f"- Completeness: {candidate.completeness_status}; "
            f"precheck: {candidate.precheck_status.value}"
        )
        lines.append(
            "- Missing variables: "
            + (", ".join(candidate.unresolved_parameters) or "none")
        )
        if candidate.parent_candidate_version:
            lines.append(
                f"- Parent: {candidate.parent_candidate_id}@"
                f"{candidate.parent_candidate_version}"
            )
        for key, record in sorted(candidate.parameters.items()):
            lines.append(
                f"- {key}: {record.value} {record.unit}; "
                f"evidence={record.source_ref or 'not supplied'}"
            )
        if candidate.precheck_report:
            lines.append(
                "- Uncovered rules: "
                + (", ".join(candidate.precheck_report.uncovered_rules) or "none")
            )
            for issue in candidate.precheck_report.issues[:8]:
                lines.append(f"- Issue: {issue}")
    if execution:
        lines.extend(["", "## 最近一次 Supervisor 运行", ""])
        lines.append(
            f"- Termination: {execution.get('termination_reason', 'unknown')}"
        )
        for event in execution.get("trace", [])[-30:]:
            if event.get("stage") in {"plan", "guard", "committed"}:
                lines.append(
                    f"- {event.get('stage')}: {event.get('action', '')} "
                    f"{event.get('reason', '')}"
                )
    lines.extend([
        "", "## 适用性声明", "",
        "本文件仅用于软件框架和交互演示；没有经过专家审核的完整工程规则覆盖，"
        "不能据此声称轴承设计通过专业校核。",
        "",
    ])
    return "\n".join(lines)


def guided_options(state):
    """Rebuild options from authoritative state on every turn; never store an index."""
    items = []
    for constraint in state.constraints:
        if not constraint.approved:
            items.append(("approve", constraint.id, constraint.revision))
    for field, record in sorted(state.parameters.items()):
        if record.value is not None and not record.confirmed_by:
            items.append(("confirm", field, record.revision))
    return items


def resolve_guided_option(state, command: str, index: str, shown_options):
    """Use the *displayed* target, rejecting changes before confirmation."""
    options = [item for item in shown_options if item[0] == command]
    number = int(index)
    if number < 1 or number > len(options):
        raise ValueError("选择编号无效，请使用 :show 查看当前选项")
    selected = options[number - 1]
    if selected not in guided_options(state):
        raise ValueError("选项或版本已变化，请先使用 :show 刷新")
    return selected[1:]


def display(application, design_id: str, execution=None) -> None:
    view = application.show_state(design_id)
    state = application.manager.get_design(design_id)
    print(
        f"\n设计 {design_id} | 版本 {state.state_version} | "
        f"R2就绪={view.input_ready} | 轴承类型={view.scope}"
    )
    for key, record in sorted(state.parameters.items()):
        print(f"  参数 {key}: {record.value} {record.unit} [{record.status.value}]")
    for item in state.constraints:
        print(
            f"  约束 {item.id} (v{item.revision}): "
            f"{item.parameter} {item.operator.value} {item.target} {item.unit}; "
            f"approved={item.approved}"
        )
    for candidate in state.candidate_designs:
        print(
            f"  候选 candidate:{candidate.candidate_id}@{candidate.version}: "
            f"{candidate.completeness_status}, {candidate.precheck_status.value}; "
            f"未解决={','.join(candidate.unresolved_parameters)}"
        )
    if execution:
        print(f"  Supervisor: {execution.get('termination_reason', 'unknown')}")
        for event in execution.get("trace", [])[-35:]:
            if event.get("stage") == "plan":
                print(
                    f"  调度 → {event.get('action')}: {event.get('reason', '')}"
                )
            elif event.get("stage") == "guard":
                print(
                    f"  Guard → {event.get('guard')}: {event.get('reason', '')}"
                )
            elif event.get("stage") == "committed":
                print(f"  执行完成 → {event.get('action')}")
        for q in execution.get("questions", []):
            prompt = q.get("question") or q.get("text")
            if prompt:
                print(f"  系统提问：{prompt}")
    print("  已知信息来自用户核实的参数；未决条件不会被自动确认。")
    for q in view.questions[:2]:
        print(f"  下一步问题：{q.text}")
        if q.why_needed:
            print(f"  为什么需要：{q.why_needed}")
    if view.guidance.objective_hints:
        print("  用户偏好线索（未确认）：" + "、".join(view.guidance.objective_hints))
    options = guided_options(state)
    if options:
        print("  可选择操作（显示时绑定当前版本，提交时再次核验）：")
        approvals = [item for item in options if item[0] == "approve"]
        confirmations = [item for item in options if item[0] == "confirm"]
        for idx, (_, key, _) in enumerate(approvals, 1):
            print(f"    :approve {idx}  批准当前约束 {key}")
        for idx, (_, key, _) in enumerate(confirmations, 1):
            print(f"    :confirm {idx}  确认当前参数 {key}")
    print("  工程结论：ENGINEERING_DOMAIN_PENDING；DLAP 未接入。")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="多 Agent 轴承设计中文交互演示")
    parser.add_argument("--db", type=Path, default=Path(".venv/design.sqlite"))
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--design-id", default=None)
    parser.add_argument("--actor", default="local-engineer")
    parser.add_argument("--llm", action="store_true", help="Use real API, never fake fallback")
    args = parser.parse_args(argv)
    # Fail before creating a session if real model config is missing or invalid.
    planner = LLMPlanner() if args.llm else None
    extractor_instance = LLMExtractor.from_environment() if args.llm else None
    extractor = extractor_instance.extract if extractor_instance else None
    args.db.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = args.checkpoint or args.db.with_suffix(".checkpoint.sqlite")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    manager = StateManager(SQLiteStateRepository(args.db))
    last_execution = None
    with open_application(
        manager, checkpoint, actor=args.actor, extractor=extractor, planner=planner,
    ) as application:
        state = (
            manager.get_design(args.design_id) if args.design_id
            else application.create_design("油润滑圆柱径向动压滑动轴承初步设计")
        )
        design_id = state.design_id
        print(
            f"多 Agent 轴承设计 | {'REAL_LLM' if args.llm else 'OFFLINE'} "
            f"| design_id={design_id}"
        )
        print(
            "输入中文需求；:show 查看，:run 继续，:approve 编号 批准约束，"
            ":confirm 编号 确认参数（也兼容 ID/字段 + 版本），:correct 字段 版本 新描述，"
            ":report [文件名] 导出报告，:quit 退出。"
        )
        display(application, design_id)
        shown_options = guided_options(manager.get_design(design_id))
        while True:
            try:
                user_text = input("\n设计> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not user_text:
                continue
            if user_text in {":quit", ":exit"}:
                break
            try:
                if user_text == ":show":
                    display(application, design_id, last_execution)
                    shown_options = guided_options(manager.get_design(design_id))
                    continue
                if user_text == ":run":
                    last_execution = application.runtime.invoke(design_id, goal="design")
                elif user_text.startswith(":approve "):
                    parts = user_text.split()
                    if len(parts) == 2:
                        constraint_id, revision = resolve_guided_option(
                            manager.get_design(design_id), "approve", parts[1], shown_options,
                        )
                    elif len(parts) == 3:
                        _, constraint_id, raw_revision = parts
                        revision = int(raw_revision)
                    else:
                        raise ValueError("请使用 :approve 编号 或 :approve ID 版本")
                    application.interaction.approve_constraint(
                        design_id, constraint_id, int(revision),
                    )
                elif user_text.startswith(":confirm "):
                    parts = user_text.split()
                    if len(parts) == 2:
                        field, revision = resolve_guided_option(
                            manager.get_design(design_id), "confirm", parts[1], shown_options,
                        )
                    elif len(parts) == 3:
                        _, field, raw_revision = parts
                        revision = int(raw_revision)
                    else:
                        raise ValueError("请使用 :confirm 编号 或 :confirm 字段 版本")
                    application.interaction.confirm_parameter(
                        design_id, field, int(revision),
                    )
                elif user_text.startswith(":correct "):
                    _, field, revision, corrected = user_text.split(" ", 3)
                    application.interaction.correct_parameter(
                        design_id, field, int(revision), corrected, str(uuid4())
                    )
                elif user_text == ":report" or user_text.startswith(":report "):
                    parts = user_text.split(" ", 1)
                    report_path = (
                        Path(parts[1]) if len(parts) == 2
                        else args.db.with_suffix(".report.md")
                    )
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(
                        render_report(manager.get_design(design_id), last_execution),
                        encoding="utf-8",
                    )
                    print(f"报告已保存：{report_path}")
                    continue
                else:
                    turn = application.submit_turn(
                        design_id, user_text, str(uuid4()), goal="design",
                    )
                    last_execution = turn.execution
                    if extractor_instance and extractor_instance.last_recovery:
                        detail = extractor_instance.last_recovery
                        print(
                            "提取提示：模型返回了 "
                            f"{detail['invalid_proposals']} 条格式不符的提案，"
                            f"已从用户原文安全恢复 {detail['recovered_from_text']} 条；"
                            "所有提案仍需原文证据核验。"
                        )
                display(application, design_id, last_execution)
                shown_options = guided_options(manager.get_design(design_id))
            except (ValueError, PermissionError, KeyError, RuntimeError) as exc:
                if args.llm:
                    # Provider exceptions can contain raw request metadata. Never
                    # echo their messages in real-API mode.
                    print(f"操作未完成：{type(exc).__name__}；请检查模型服务或输入。")
                else:
                    print(f"操作未完成：{type(exc).__name__}: {exc}")
                # On model failure, no automatic switch to FakePlanner.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
