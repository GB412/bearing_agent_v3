import sqlite3
from contextlib import closing
from pathlib import Path

from bearing_agents.domain.state import DesignState
from bearing_agents.domain.tasks import TaskReceipt
from bearing_agents.requirements.contracts import InteractionReceipt, UserTurn


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
                "CREATE TABLE IF NOT EXISTS user_messages "
                "(operation_id TEXT PRIMARY KEY, design_id TEXT NOT NULL, actor TEXT NOT NULL, "
                "intent_hash TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS interaction_operations "
                "(operation_id TEXT PRIMARY KEY, design_id TEXT NOT NULL, "
                "intent_hash TEXT NOT NULL, receipt TEXT NOT NULL)"
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

    def save_user_message(self, message: UserTurn, intent_hash: str) -> UserTurn:
        """Persist the immutable user turn before nontransactional extraction."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT design_id,actor,intent_hash,payload FROM user_messages "
                "WHERE operation_id=?", (message.operation_id,),
            ).fetchone()
            if row:
                if (row[0], row[1], row[2]) != (
                    message.design_id, message.actor, intent_hash,
                ):
                    raise StateConflictError("Message operation ID reused with different intent")
                return UserTurn.model_validate_json(row[3])
            connection.execute(
                "INSERT INTO user_messages VALUES (?,?,?,?,?)",
                (message.operation_id,message.design_id,message.actor,intent_hash,
                 message.model_dump_json()),
            )
        return message

    def get_user_message(self, operation_id: str, design_id: str) -> UserTurn | None:
        with closing(self._connect()) as connection, connection:
            row=connection.execute(
                "SELECT payload FROM user_messages WHERE operation_id=? AND design_id=?",
                (operation_id,design_id),
            ).fetchone()
        return UserTurn.model_validate_json(row[0]) if row else None

    def list_user_messages(self, design_id: str) -> list[UserTurn]:
        with closing(self._connect()) as connection, connection:
            rows=connection.execute(
                "SELECT payload FROM user_messages WHERE design_id=? ORDER BY rowid",
                (design_id,),
            ).fetchall()
        return [UserTurn.model_validate_json(row[0]) for row in rows]

    def get_interaction_receipt(
        self, operation_id: str, design_id: str, intent_hash: str,
    ) -> InteractionReceipt | None:
        with closing(self._connect()) as connection, connection:
            row=connection.execute(
                "SELECT design_id,intent_hash,receipt FROM interaction_operations "
                "WHERE operation_id=?", (operation_id,),
            ).fetchone()
        if row is None:
            return None
        if row[0] != design_id or row[1] != intent_hash:
            raise StateConflictError(
                        "Interaction operation ID reused with different intent"
                    )
        return InteractionReceipt.model_validate_json(row[2]).model_copy(
            update={"replayed":True}
        )

    def commit_interaction(
        self, state: DesignState, expected_version: int, intent_hash: str,
        receipt: InteractionReceipt,
    ) -> InteractionReceipt:
        """Domain state, audit event and receipt are written in one SQLite transaction."""
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row=connection.execute(
                "SELECT design_id,intent_hash,receipt FROM interaction_operations "
                "WHERE operation_id=?", (receipt.operation_id,),
            ).fetchone()
            if row:
                if row[0] != state.design_id or row[1] != intent_hash:
                    raise StateConflictError("Interaction operation ID reused with different intent")
                return InteractionReceipt.model_validate_json(row[2]).model_copy(
                    update={"replayed":True}
                )
            cursor=connection.execute(
                "UPDATE designs SET state_version=?,payload=? "
                "WHERE design_id=? AND state_version=?",
                (state.state_version,state.model_dump_json(),state.design_id,expected_version),
            )
            if cursor.rowcount!=1:
                raise StateConflictError("Interaction commit has a stale domain version")
            connection.execute(
                "INSERT INTO interaction_operations VALUES (?,?,?,?)",
                (receipt.operation_id,state.design_id,intent_hash,receipt.model_dump_json()),
            )
        return receipt
