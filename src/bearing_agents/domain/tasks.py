"""Small trusted task commands; no engineering patch or user authority in this payload."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.domain.agent_protocols import TaskRecord
from bearing_agents.domain.state import DesignState


def engineering_digest(state: DesignState) -> str:
    """Conservative freshness, excluding orchestration bookkeeping and audit growth."""
    data = state.model_dump(mode="json", exclude={
        "state_version", "task_plan", "event_history", "thread_id",
    })
    return fingerprint(data)


def fingerprint(data: object) -> str:
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TaskCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    kind: Literal["register", "start", "complete", "fail", "wait", "resume", "expire"]
    task: TaskRecord | None = None
    reason: str = Field(min_length=1)
    expected_input_digest: str | None = None
    output_ref: str | None = None
    accepted: bool | None = None


class TaskReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_id: str
    design_id: str
    task_id: str
    state_version: int
    event_id: str
    replayed: bool = False
