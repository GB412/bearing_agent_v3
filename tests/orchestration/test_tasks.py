import sqlite3

import pytest

from bearing_agents.core.dependency_tracker import invalidate_dependents
from bearing_agents.core.state_manager import StateManager, StateManagerError, VersionConflictError
from bearing_agents.domain.agent_protocols import StatePatch, TaskRecord
from bearing_agents.domain.enums import TaskStatus
from bearing_agents.domain.state import DesignState
from bearing_agents.domain.tasks import TaskCommand, engineering_digest
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository, StateConflictError

SYSTEM = WriteContext(kind=WriterKind.SYSTEM, actor="runtime")
USER = WriteContext(kind=WriterKind.USER, actor="offline-user")


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "domain.sqlite"))


def task(task_id="t1", **kwargs):
    data = {"id": task_id, "action": "produce_summary", "agent": "fake",
            "status": TaskStatus.PENDING, "input_version": 0}
    return TaskRecord(**(data | kwargs))


def register(manager, design, record=None):
    record = record or task()
    return manager.apply_task_command(
        design.design_id, design.state_version,
        TaskCommand(operation_id=f"{record.id}:register", task_id=record.id,
                    kind="register", task=record, reason="Initial near-term plan"),
        context=SYSTEM,
    )


def test_task_cas_idempotency_and_audit(manager):
    d = manager.create_design()
    first = register(manager, d)
    replay = register(manager, d)
    assert replay.replayed and replay.event_id == first.event_id
    saved = manager.get_design(d.design_id)
    assert saved.state_version == 1 and len(saved.event_history) == 1
    assert saved.event_history[0].details["plan_revision"] == 1
    with pytest.raises(StateConflictError, match="different task intent"):
        register(manager, d, task(agent="another"))
    command = TaskCommand(operation_id="t1:start", task_id="t1", kind="start", reason="Run")
    with pytest.raises(VersionConflictError):
        manager.apply_task_command(d.design_id, 0, command, context=SYSTEM)
    manager.apply_task_command(d.design_id, 1, command, context=SYSTEM)
    saved = manager.get_design(d.design_id)
    assert saved.task_plan[0].attempt_count == 1
    assert saved.task_plan[0].input_version == saved.state_version
    with pytest.raises(StateManagerError, match="Illegal task transition"):
        manager.apply_task_command(
            d.design_id, 2, command.model_copy(update={"operation_id": "new-start"}),
            context=SYSTEM,
        )


def test_task_authority_and_patch_boundary(manager):
    d = manager.create_design()
    cmd = TaskCommand(operation_id="register", task_id="t1", kind="register",
                      task=task(), reason="Plan")
    for context in (WriteContext(), USER):
        with pytest.raises(StateManagerError):
            manager.apply_task_command(d.design_id, 0, cmd, context=context)
    with pytest.raises(ValueError):
        StatePatch.model_validate({"source": "agent", "task_plan": [task().model_dump()]})
    assert manager.get_design(d.design_id).state_version == 0


def test_f08_old_json_and_distinct_dependency_semantics(manager):
    old = task(dependencies=["load"]).model_dump()
    old.pop("depends_on_task_ids")
    assert TaskRecord.model_validate(old).depends_on_task_ids == []
    state = DesignState(design_id="old", task_plan=[
        task(dependencies=["load"]),
        task("t2", dependencies=["rotational_speed"], depends_on_task_ids=["t1"]),
        task("t3", dependencies=["t1"]),  # ambiguous legacy data: never guess topology
    ])
    invalidate_dependents(state, {"task_plan"})
    assert all(t.status == TaskStatus.PENDING for t in state.task_plan)
    invalidate_dependents(state, {"load"})
    assert all(t.status == TaskStatus.STALE for t in state.task_plan)
    assert engineering_digest(state) == engineering_digest(
        state.model_copy(update={"state_version": 50, "task_plan": []})
    )
    d = manager.create_design()
    with pytest.raises(StateManagerError, match="existing task IDs"):
        register(manager, d, task(depends_on_task_ids=["t1"]))
    register(manager, d)
    d = manager.get_design(d.design_id)
    register(manager, d, task("t2", depends_on_task_ids=["t1"]).model_copy(
        update={"input_version": d.state_version},
    ))
    with pytest.raises(StateManagerError, match="predecessors"):
        manager.apply_task_command(d.design_id, 2, TaskCommand(
            operation_id="t2:start", task_id="t2", kind="start", reason="Run",
        ), context=SYSTEM)


def test_task_journal_failure_rolls_back_domain_and_event(manager):
    d = manager.create_design()
    with sqlite3.connect(manager.repository.path) as db:
        db.execute("CREATE TRIGGER reject_receipt BEFORE INSERT ON task_operations "
                   "BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
        register(manager, d)
    saved = manager.get_design(d.design_id)
    assert saved.state_version == 0 and saved.event_history == [] and saved.task_plan == []


def test_legacy_ambiguous_task_cannot_start(manager):
    d = manager.create_design()
    register(manager, d, task(dependencies=["task:old"]))
    with pytest.raises(StateManagerError, match="Ambiguous legacy"):
        manager.apply_task_command(d.design_id, 1, TaskCommand(
            operation_id="start", task_id="t1", kind="start", reason="Run",
        ), context=SYSTEM)
