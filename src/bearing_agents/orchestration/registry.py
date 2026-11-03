"""Small, trusted registries for agent dispatch and read-only tool access.

The action catalog remains the authority for which executor may handle an action.
Agents receive only an action-scoped context; they never receive StateManager,
Repository, or a WriteContext through this interface.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from bearing_agents.domain.agent_protocols import TaskRecord
from bearing_agents.domain.state import DesignState


class AgentRegistryError(ValueError):
    """An executor registration or invocation violates the agent contract."""


class ToolAccessError(PermissionError):
    """An agent attempted to call a tool it is not authorized to use."""


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=repr,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ToolCallRecord:
    tool_id: str
    tool_version: str
    input_digest: str
    output_digest: str | None
    status: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "tool_id": self.tool_id,
            "tool_version": self.tool_version,
            "input_digest": self.input_digest,
            "output_digest": self.output_digest,
            "status": self.status,
        }


@dataclass(frozen=True)
class ToolSpec:
    tool_id: str
    handler: Callable[..., Any]
    allowed_agent_ids: frozenset[str]
    version: str = "1"

    def __post_init__(self) -> None:
        if not self.tool_id.strip() or not self.version.strip():
            raise ValueError("Tool ID and version must be nonempty")
        if not callable(self.handler):
            raise TypeError("Tool handler must be callable")
        if not self.allowed_agent_ids or any(not item.strip() for item in self.allowed_agent_ids):
            raise ValueError("A tool must name at least one allowed agent ID")


class ToolRegistry:
    """Explicit allowlist of in-process, read-only tools; no dynamic code loading."""

    def __init__(self, specs: Iterable[ToolSpec] = ()):
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register_spec(spec)

    def register(
        self,
        tool_id: str,
        handler: Callable[..., Any],
        *,
        allowed_agent_ids: Iterable[str],
        version: str = "1",
    ) -> ToolSpec:
        spec = ToolSpec(
            tool_id=tool_id,
            handler=handler,
            allowed_agent_ids=frozenset(allowed_agent_ids),
            version=version,
        )
        return self.register_spec(spec)

    def register_spec(self, spec: ToolSpec) -> ToolSpec:
        if spec.tool_id in self._specs:
            raise ValueError(f"Duplicate tool ID: {spec.tool_id}")
        self._specs[spec.tool_id] = spec
        return spec

    def for_agent(self, agent_id: str) -> AgentToolbox:
        if not agent_id.strip():
            raise ValueError("Agent ID must be nonempty")
        return AgentToolbox(self, agent_id)

    def available_for(self, agent_id: str) -> tuple[str, ...]:
        return tuple(sorted(
            tool_id for tool_id, spec in self._specs.items()
            if agent_id in spec.allowed_agent_ids
        ))


class AgentToolbox:
    """Capability-limited tool view bound to one registered executor identity."""

    def __init__(self, registry: ToolRegistry, agent_id: str):
        self._registry = registry
        self.agent_id = agent_id
        self._calls: list[ToolCallRecord] = []

    @property
    def available_tool_ids(self) -> tuple[str, ...]:
        return self._registry.available_for(self.agent_id)

    @property
    def calls(self) -> tuple[ToolCallRecord, ...]:
        return tuple(self._calls)

    def call(self, tool_id: str, **arguments: Any) -> Any:
        input_digest = _digest(arguments)
        spec = self._registry._specs.get(tool_id)
        if spec is None or self.agent_id not in spec.allowed_agent_ids:
            self._calls.append(ToolCallRecord(
                tool_id=tool_id,
                tool_version=spec.version if spec else "unknown",
                input_digest=input_digest,
                output_digest=None,
                status="DENIED",
            ))
            raise ToolAccessError(f"Agent {self.agent_id!r} cannot call tool {tool_id!r}")
        try:
            result = spec.handler(**arguments)
        except Exception:
            self._calls.append(ToolCallRecord(
                tool_id=tool_id, tool_version=spec.version, input_digest=input_digest,
                output_digest=None, status="FAILED",
            ))
            raise
        self._calls.append(ToolCallRecord(
            tool_id=tool_id, tool_version=spec.version, input_digest=input_digest,
            output_digest=_digest(result), status="SUCCESS",
        ))
        return result


@dataclass(frozen=True)
class AgentContext:
    """Untrusted-result execution context; deliberately contains no state writer."""

    action: str
    target_ref: str | None
    input_refs: tuple[str, ...]
    tools: AgentToolbox


class AgentRegistry:
    """Maps trusted executor IDs to implementations; action authorization stays in CATALOG."""

    def __init__(self, agents: dict[str, Any] | None = None):
        self._agents: dict[str, Any] = {}
        for executor_id, agent in (agents or {}).items():
            self.register(executor_id, agent)

    def register(self, executor_id: str, agent: Any, *, replace: bool = False) -> None:
        if not executor_id.strip():
            raise ValueError("Executor ID must be nonempty")
        if not callable(getattr(agent, "run", None)):
            raise TypeError(f"Agent {executor_id!r} must provide run(state, task)")
        if executor_id in self._agents and not replace:
            raise ValueError(f"Duplicate executor ID: {executor_id}")
        self._agents[executor_id] = agent

    def get(self, executor_id: str) -> Any | None:
        return self._agents.get(executor_id)

    def require(self, executor_id: str) -> Any:
        agent = self.get(executor_id)
        if agent is None:
            raise AgentRegistryError(f"Executor is not registered: {executor_id}")
        return agent

    def as_dict(self) -> dict[str, Any]:
        return dict(self._agents)

    @property
    def executor_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))

    def invoke(
        self,
        executor_id: str,
        state: DesignState,
        task: TaskRecord,
        *,
        context: AgentContext,
    ) -> Any:
        agent = self.require(executor_id)
        run = agent.run
        try:
            parameters = inspect.signature(run).parameters.values()
        except (TypeError, ValueError) as exc:
            raise AgentRegistryError("Agent run signature cannot be inspected") from exc
        accepts_context = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == "context"
            for parameter in parameters
        )
        if accepts_context:
            return run(state, task, context=context)
        if context.tools.available_tool_ids:
            raise AgentRegistryError(
                f"Agent {executor_id!r} has authorized tools but does not accept AgentContext"
            )
        return run(state, task)
