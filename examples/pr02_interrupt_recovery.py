"""Two independent processes pause/resume a demo task using real SQLite checkpoints."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository


def demo():
    worker = Path(__file__).resolve().parents[1] / "tests/orchestration/recovery_worker.py"
    with tempfile.TemporaryDirectory() as directory:
        domain = str(Path(directory) / "domain.sqlite")
        checkpoint = str(Path(directory) / "checkpoint.sqlite")
        manager = StateManager(SQLiteStateRepository(domain))
        design = manager.create_design()
        design = manager.apply_patch(design.design_id, 0, {
            "source": "SYNTHETIC_WORKFLOW",
            "parameter_changes": {"journal_diameter": {
                "value": 100, "unit": "mm", "role": "FIXED_INPUT", "status": "PROVIDED",
            }},
        }, context=WriteContext(kind=WriterKind.USER, actor="offline-fixture-user"))
        base = [sys.executable, str(worker)]
        first = subprocess.run(base + ["pause", domain, checkpoint, design.design_id],
                               check=True, capture_output=True, text=True, encoding="utf-8")
        paused = json.loads(first.stdout)
        second = subprocess.run(base + ["resume", domain, checkpoint, design.design_id,
                                        "--request-id", paused["confirmation"]["request_id"]],
                                check=True, capture_output=True, text=True, encoding="utf-8")
        resumed = json.loads(second.stdout)
        return {"source_class": "SYNTHETIC_WORKFLOW", "independent_processes": 2,
                "paused_version": paused["state_version"], "resumed": resumed}


if __name__ == "__main__":
    print(json.dumps(demo(), ensure_ascii=False, indent=2))
