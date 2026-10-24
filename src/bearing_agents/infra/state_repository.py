import sqlite3
from pathlib import Path

from bearing_agents.domain.state import DesignState


class StateConflictError(RuntimeError):
    pass


class SQLiteStateRepository:
    """SQLite storage for authoritative design state, independent of graph memory."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS designs "
                "(design_id TEXT PRIMARY KEY, state_version INTEGER NOT NULL, "
                "payload TEXT NOT NULL)"
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def create(self, state: DesignState) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO designs (design_id, state_version, payload) VALUES (?, ?, ?)",
                (state.design_id, state.state_version, state.model_dump_json()),
            )

    def get(self, design_id: str) -> DesignState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM designs WHERE design_id = ?", (design_id,)
            ).fetchone()
        return DesignState.model_validate_json(row[0]) if row else None

    def save(self, state: DesignState, expected_version: int) -> None:
        with self._connect() as connection:
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
