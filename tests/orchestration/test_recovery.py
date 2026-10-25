import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).with_name("recovery_worker.py")


def worker(mode, manager, checkpoint, design_id, *extra):
    return subprocess.run(
        [sys.executable, str(WORKER), mode, manager.repository.path, str(checkpoint),
         design_id, *extra], capture_output=True, text=True, encoding="utf-8", timeout=45,
        env=os.environ | {"PYTHONIOENCODING": "utf-8", "LANGSMITH_TRACING": "false",
                          "LANGCHAIN_TRACING_V2": "false"},
    )


@pytest.mark.parametrize("mode, expected_code", [("crash", 71), ("fail", 1)])
def test_f11_committed_task_replays_after_real_checkpoint_failure(
    manager, tmp_path, mode, expected_code,
):
    design = manager.create_design()
    checkpoint = tmp_path / "persistent.sqlite"
    first = worker(mode, manager, checkpoint, design.design_id)
    assert first.returncode == expected_code, first.stderr
    assert "TASK_COMMITTED_CHECKPOINT_NOT_SAVED" in first.stdout
    committed = manager.get_design(design.design_id)
    assert committed.state_version == 3
    assert len(committed.task_plan) == 1
    assert committed.task_plan[0].status.value == "COMPLETED"
    assert len(committed.event_history) == 3
    with sqlite3.connect(manager.repository.path) as db:
        assert db.execute("SELECT count(*) FROM task_operations").fetchone()[0] == 3
    with sqlite3.connect(checkpoint) as db:
        assert db.execute("SELECT count(*) FROM checkpoints").fetchone()[0] > 0

    second = worker("recover", manager, checkpoint, design.design_id)
    assert second.returncode == 0, second.stderr
    result = json.loads(second.stdout)
    assert result["termination_reason"] == "MISSING_INPUT"
    assert any(e.get("replayed") for e in result["trace"])
    assert manager.get_design(design.design_id) == committed
    with sqlite3.connect(manager.repository.path) as db:
        assert db.execute("SELECT count(*) FROM task_operations").fetchone()[0] == 3


def test_real_checkpoint_interrupt_resumes_in_new_process(manager, ready, tmp_path):
    checkpoint = tmp_path / "persistent.sqlite"
    first = worker("pause", manager, checkpoint, ready.design_id)
    assert first.returncode == 0, first.stderr
    paused = json.loads(first.stdout)
    request_id = paused["confirmation"]["request_id"]
    second = worker("resume", manager, checkpoint, ready.design_id, "--request-id", request_id)
    assert second.returncode == 0, second.stderr
    resumed = json.loads(second.stdout)
    assert resumed["termination_reason"] == "GOAL_REACHED"
    assert resumed["state_version"] == paused["state_version"] + 1
    assert manager.get_design(ready.design_id).parameters == ready.parameters
