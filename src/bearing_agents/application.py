"""Unified application entry point for trusted user interaction and the Supervisor."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from bearing_agents.core.state_manager import StateManager
from bearing_agents.design.agent import DesignAgent
from bearing_agents.design.comparison import CandidateComparison, compare_candidates
from bearing_agents.domain.candidates import CandidatePrecheckReport
from bearing_agents.knowledge.defaults import KnowledgeBase
from bearing_agents.orchestration.registry import AgentRegistry, ToolRegistry
from bearing_agents.orchestration.workflow import Runtime, open_runtime
from bearing_agents.requirements.agent import RequirementsAgent
from bearing_agents.requirements.contracts import InteractionReceipt, RequirementSpecView
from bearing_agents.requirements.interaction import InteractionService
from bearing_agents.validation.agent import ValidationAgent
from bearing_agents.validation.service import ValidationService


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
        validation_service: ValidationService | None = None,
    ):
        self.manager = manager
        self.runtime = runtime
        self.interaction = InteractionService(manager, actor=actor, extractor=extractor)
        self.validation_service = validation_service or ValidationService(manager)

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
        receipt, _ = self.interaction.submit_turn(
            design_id, content, operation_id,
        )
        execution = self.runtime.invoke(design_id, goal=goal)
        return ApplicationTurnResult(
            receipt=receipt,
            requirements=self.interaction.show_state(design_id),
            execution=execution,
        )

    def precheck_candidate(self, design_id: str, candidate_ref: str) -> dict[str, Any]:
        """Run and persist a deterministic precheck for one exact candidate version."""
        execution = self.runtime.invoke(
            design_id, goal="precheck", target_ref=candidate_ref,
        )
        outputs = execution.get("agent_outputs", [])
        if not outputs:
            raise ValueError(
                f"Precheck did not produce a report: {execution.get('termination_reason')}"
            )
        report = CandidatePrecheckReport.model_validate(outputs[-1])
        self.validation_service.persist_report(design_id, report)
        diagnosis = self.validation_service.diagnose(
            design_id, report.candidate_id, report.candidate_version,
        )
        return {
            "execution": execution,
            "report": report,
            "diagnosis": diagnosis,
            "state_version": self.manager.get_design(design_id).state_version,
        }

    def compare_candidate_versions(
        self,
        design_id: str,
        first_ref: str,
        second_ref: str,
    ) -> CandidateComparison:
        """Compare only candidate versions retrieved from authoritative state."""
        state = self.manager.get_design(design_id)
        indexed = {
            f"candidate:{item.candidate_id}@{item.version}": item
            for item in state.candidate_designs
        }
        if first_ref not in indexed or second_ref not in indexed or first_ref == second_ref:
            raise ValueError("Two distinct, existing candidate versions are required")
        return compare_candidates(indexed[first_ref], indexed[second_ref])

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
    requirements_question_ranker=None,
    design_strategy_advisor=None,
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

    if tool_registry is None:
        # The read-only message lookup is scoped to the trusted design ID
        # supplied by Runtime, not a model-authored identity.
        tool_registry = ToolRegistry()

        def last_user_turn(design_id: str) -> str:
            messages = manager.repository.list_user_messages(design_id)
            return messages[-1].content[:2000] if messages else ""

        tool_registry.register(
            "last_user_turn", last_user_turn,
            allowed_agent_ids={"requirements_fake"}, version="1",
        )

    design_agent = DesignAgent(
        knowledge=knowledge,
        parameter_registry=manager.parameter_registry,
        stage_registry=manager.stage_registry,
        strategy_advisor=design_strategy_advisor,
    )
    registered = {
        "requirements_fake": RequirementsAgent(
            manager.stage_registry, manager.parameter_registry,
            question_ranker=requirements_question_ranker,
        ),
        "conditions_fake": design_agent,
        "design_fake": design_agent,
        "validation_agent": ValidationAgent(
            knowledge=knowledge,
            stage_registry=manager.stage_registry,
            parameter_registry=manager.parameter_registry,
        ),
    }
    if agent_registry is not None:
        registered.update(agent_registry.as_dict())
    if agents:
        registered.update(agents)
    # Use the exact validator registered for the Runtime when persisting
    # reports. A different default rule set here would reject legitimate
    # custom-knowledge checks or silently reinterpret their evidence.
    shared_validator = registered["validation_agent"]
    if not isinstance(shared_validator, ValidationAgent):
        raise TypeError("validation_agent must be a trusted ValidationAgent")

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
            manager,
            runtime,
            actor=actor,
            extractor=extractor,
            validation_service=ValidationService(manager, agent=shared_validator),
        )
