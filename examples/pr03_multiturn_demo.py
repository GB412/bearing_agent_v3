"""Reproducible, offline, multi-turn requirements workflow."""

import json
import tempfile
from pathlib import Path

from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.requirements.interaction import InteractionService


def run_demo():
    with tempfile.TemporaryDirectory() as root:
        database = Path(root) / "pr03.sqlite"
        first = StateManager(SQLiteStateRepository(database))
        service = InteractionService(first, actor="demo-designer")
        design = service.create_design("Initial bearing requirements")
        turns = [
            ("t1", "圆柱径向动压滑动轴承，轴径100mm，转速1500rpm"),
            ("t2", "载荷12kN，单一稳态"),
        ]
        output = []
        for operation_id, content in turns:
            receipt, view = service.submit_turn(design.design_id, content, operation_id)
            output.append({
                "operation": operation_id, "message_id": receipt.message_id,
                "version": view.state_version, "ready": view.input_ready,
                "questions": [question.reason_code for question in view.questions],
            })
        # Exercise persisted restart and a replayed user operation.
        restored = InteractionService(
            StateManager(SQLiteStateRepository(database)), actor="demo-designer",
        )
        replay, resumed = restored.submit_turn(design.design_id, turns[-1][1], "t2")
        assert replay.replayed and resumed.input_ready
        assert resumed.parameters["load"]["value"] == 12000
        output.append({
            "replayed": True, "version": resumed.state_version,
            "scope": resumed.scope, "input_ready": resumed.input_ready,
        })
        return output


def main():
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
