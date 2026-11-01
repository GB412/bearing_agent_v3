"""Local trusted-input CLI for the PR-03 requirements interaction.

Examples:
    python examples/pr03_requirements_cli.py
    python examples/pr03_requirements_cli.py --db requirements.sqlite --design-id <id>
"""

import argparse
from pathlib import Path
from uuid import uuid4

from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.requirements.extraction import LLMExtractor
from bearing_agents.requirements.interaction import InteractionService


def show(view):
    print(f"\n设计 ID: {view.design_id}  版本: {view.state_version}")
    print(f"轴承范围: {view.scope}  R2 输入就绪: {view.input_ready}")
    for name, item in view.parameters.items():
        print(f"  {name}: {item['value']} {item['unit']} [{item['status']}]")
    for question in view.questions:
        print(f"  ? {question.text}")
    if view.input_ready:
        print("输入已达到 R2 基础条件；不是设计校核通过，专业模块尚未实现。")


def main():
    parser = argparse.ArgumentParser(description="PR-03 local requirements CLI")
    parser.add_argument("--db", type=Path, default=Path("pr03_requirements.sqlite"))
    parser.add_argument("--actor", default="local-designer")
    parser.add_argument("--design-id", default=None)
    parser.add_argument("--llm", action="store_true", help="Use explicit opt-in LLM extraction")
    args = parser.parse_args()
    manager = StateManager(SQLiteStateRepository(args.db))
    extractor = LLMExtractor.from_environment().extract if args.llm else None
    service = InteractionService(manager, actor=args.actor, extractor=extractor)
    design = (manager.get_design(args.design_id) if args.design_id
              else service.create_design("Interactive bearing design requirements"))
    print(f"设计 ID: {design.design_id}（重启后可用 --design-id 继续）")
    print("请输入轴承条件；:show 查看，:correct 字段 版本 新描述，"
          ":confirm 字段 版本，:approve 约束ID 版本，"
          ":reject 约束ID 版本，:quit 结束。")
    show(service.show_state(design.design_id))
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in {":quit", ":exit", ":cancel"}:
            break
        try:
            if line == ":show":
                view = service.show_state(design.design_id)
            elif line.startswith(":correct "):
                _, key, revision, text = line.split(" ", 3)
                _, view = service.correct_parameter(
                    design.design_id, key, int(revision), text, str(uuid4()),
                )
            elif line.startswith(":confirm "):
                _, key, revision = line.split(" ", 2)
                service.confirm_parameter(design.design_id, key, int(revision))
                view = service.show_state(design.design_id)
            elif line.startswith(":reject "):
                _, key, revision = line.split(" ", 2)
                service.reject_constraint(design.design_id, key, int(revision))
                view = service.show_state(design.design_id)
            elif line.startswith(":approve "):
                _, key, revision = line.split(" ", 2)
                service.approve_constraint(design.design_id, key, int(revision))
                view = service.show_state(design.design_id)
            else:
                _, view = service.submit_turn(design.design_id, line, str(uuid4()))
            show(view)
        except (ValueError, KeyError) as exc:
            print(f"输入未应用：{exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
