import sqlite3
from contextlib import closing
from pathlib import Path

from bearing_agents.domain.state import DesignState
from bearing_agents.domain.tasks import TaskReceipt


class StateConflictError(RuntimeError):
    pass


class SQLiteStateRepository:
    """SQLite storage for authoritative design state, independent of graph memory."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS designs "
                "(design_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL, "
                "payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS task_operations "
                "(operation_id TEXT PRIMARY KEY, design_id TEXT NOT NULL, "
                "intent_hash TEXT NOT NULL, receipt TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def create(self, state: DesignState) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT INTO designs (design_id, state_version, payload) VALUES (?, ?, ?)",
                (state.design_id, state.state_version, state.model_dump_json()),
            )

    def get(self, design_id: str) -> DesignState | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT payload FROM designs WHERE design_id = ?", (design_id,)
            ).fetchone()
        return DesignState.model_validate_json(row[0]) if row else None

    def save(self, state: DesignState, expected_version: int) -> None:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE designs SET state_version = ?, payload = ? "
                "WHERE design_id = ? AND state_version = ?",
                (
                    state.state_version,
                    state.model_dump_json(),
                    state.design_id,
                    expected_version,
                ),
            )
            if cursor.rowcount != 1:
                raise StateConflictError(
                    f"Design {state.design_id!r} changed or does not exist at version "
                    f"{expected_version}"
                )

    def get_task_operation(
        self, operation_id: str, design_id: str, intent_hash: str,
    ) -> TaskReceipt | None:
        with closing(self._connect()) as connection, connection:
            return self._task_receipt(connection, operation_id, design_id, intent_hash)

    @staticmethod
    def _task_receipt(connection, operation_id, design_id, intent_hash):
        row = connection.execute(
            "SELECT design_id, intent_hash, receipt FROM task_operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row[0] != design_id or row[1] != intent_hash:
            raise StateConflictError("Operation ID reused with a different task intent")
        return TaskReceipt.model_validate_json(row[2]).model_copy(update={"replayed": True})

    def commit_task(
        self, state: DesignState, expected_version: int, intent_hash: str, receipt: TaskReceipt,
    ) -> TaskReceipt:
        """Only task effects: state/event and the receipt share this single transaction."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = self._task_receipt(
                connection, receipt.operation_id, state.design_id, intent_hash,
            )
            if prior is not None:
                return prior
            cursor = connection.execute(
                "UPDATE designs SET state_version = ?, payload = ? "
                "WHERE design_id = ? AND state_version = ?",
                (state.state_version, state.model_dump_json(), state.design_id, expected_version),
            )
            if cursor.rowcount != 1:
                raise StateConflictError("Task commit has a stale domain version")
            connection.execute(
                "INSERT INTO task_operations VALUES (?, ?, ?, ?)",
                (receipt.operation_id, state.design_id, intent_hash, receipt.model_dump_json()),
            )
        return receipt
