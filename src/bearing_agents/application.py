"""Unified application entry point for trusted user interaction and the Supervisor."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from bearing_agents.core.state_manager import StateManager
from bearing_agents.design.agent import DesignAgent
from bearing_agents.knowledge.defaults import KnowledgeBase
from bearing_agents.orchestration.registry import AgentRegistry, ToolRegistry
from bearing_agents.orchestration.workflow import Runtime, open_runtime
from bearing_agents.requirements.agent import RequirementsAgent
from bearing_agents.requirements.contracts import InteractionReceipt, RequirementSpecView
from bearing_agents.requirements.interaction import InteractionService
from bearing_agents.validation.agent import ValidationAgent


@dataclass(frozen=True)
class ApplicationTurnResult:
    """The persisted user-turn receipt, refreshed requirements, and Supervisor run."""

    receipt: InteractionReceipt
    requirements: RequirementSpecView
    execution: dict[str, Any]


class BearingDesignApplication:
    """One supported entry point for language input, state views, and runtime actions."""

    def __init__(
        self,
        manager: StateManager,
        runtime: Runtime,
        *,
        actor: str,
        extractor=None,
    ):
        self.manager = manager
        self.runtime = runtime
        self.interaction = InteractionService(manager, actor=actor, extractor=extractor)

    def create_design(self, goal: str | None = None):
        return self.interaction.create_design(goal)

    def show_state(self, design_id: str) -> RequirementSpecView:
        return self.interaction.show_state(design_id)

    def submit_turn(
        self,
        design_id: str,
        content: str,
        operation_id: str,
        *,
        goal: str = "demo",
    ) -> ApplicationTurnResult:
        receipt, requirements = self.interaction.submit_turn(
            design_id, content, operation_id,
        )
        execution = self.runtime.invoke(design_id, goal=goal)
        return ApplicationTurnResult(
            receipt=receipt,
            requirements=self.interaction.show_state(design_id),
            execution=execution,
        )

    def precheck_candidate(self, design_id: str, candidate_ref: str) -> dict[str, Any]:
        """Run the registered deterministic precheck for one exact candidate version."""
        return self.runtime.invoke(
            design_id, goal="precheck", target_ref=candidate_ref,
        )

    def recover(self, design_id: str) -> dict[str, Any]:
        return self.runtime.recover(design_id)

    def resume(self, design_id: str, request_id: str, *, accepted: bool, context):
        return self.runtime.resume(
            design_id, request_id, accepted=accepted, context=context,
        )


@contextmanager
def open_application(
    manager: StateManager,
    checkpoint_path,
    *,
    actor: str,
    extractor=None,
    planner=None,
    agents: dict[str, Any] | None = None,
    agent_registry: AgentRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    catalog=None,
    knowledge: KnowledgeBase | None = None,
    **runtime_options,
) -> Iterator[BearingDesignApplication]:
    """Compose the current V1 agents without making the Supervisor depend on their types.

    The offline FakePlanner remains the explicit default. Pass an LLMPlanner to opt
    into real model planning; failures are surfaced by Runtime and never replaced
    by a fake result.
    """
    if agent_registry is not None and not isinstance(agent_registry, AgentRegistry):
        raise TypeError("agent_registry must be an AgentRegistry")
    if tool_registry is not None and not isinstance(tool_registry, ToolRegistry):
        raise TypeError("tool_registry must be a ToolRegistry")

    design_agent = DesignAgent(
        knowledge=knowledge,
        parameter_registry=manager.parameter_registry,
    )
    registered = {
        "requirements_fake": RequirementsAgent(
            manager.stage_registry, manager.parameter_registry,
        ),
        "conditions_fake": design_agent,
        "design_fake": design_agent,
        "validation_agent": ValidationAgent(knowledge=knowledge),
    }
    if agent_registry is not None:
        registered.update(agent_registry.as_dict())
    if agents:
        registered.update(agents)

    with open_runtime(
        manager,
        checkpoint_path,
        planner=planner,
        agents=registered,
        tool_registry=tool_registry,
        catalog=catalog,
        **runtime_options,
    ) as runtime:
        yield BearingDesignApplication(
            manager, runtime, actor=actor, extractor=extractor,
        )
