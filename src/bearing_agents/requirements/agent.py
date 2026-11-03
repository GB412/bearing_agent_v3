"""Read-only RequirementsAgent for the shared Supervisor runtime."""

from bearing_agents.core.readiness import StageRequirementRegistry, readiness_for
from bearing_agents.domain.agent_protocols import AgentResult, TaskRecord
from bearing_agents.domain.enums import AgentResultStatus
from bearing_agents.domain.parameter_registry import ParameterSchemaRegistry
from bearing_agents.domain.state import DesignState
from bearing_agents.requirements.questions import build_view


class RequirementsAgent:
    """Builds requirement questions from an immutable state snapshot.

    It deliberately receives no StateManager or Repository. The trusted
    InteractionService owns user writes; this agent only reports questions.
    """

    def __init__(
        self,
        stage_registry: StageRequirementRegistry | None = None,
        parameter_registry: ParameterSchemaRegistry | None = None,
    ):
        self.stage_registry = stage_registry
        self.parameter_registry = parameter_registry

    def run(self, state: DesignState, task: TaskRecord) -> AgentResult:
        if task.action != "clarify_requirement":
            raise ValueError("RequirementsAgent only handles clarify_requirement")
        gate = readiness_for(
            state,
            "R2",
            self.stage_registry,
            parameter_registry=self.parameter_registry,
        )
        view = build_view(state, gate)
        return AgentResult(
            task_id=task.id,
            status=AgentResultStatus.SUCCESS,
            issues=[
                {
                    "question_id": question.question_id,
                    "reason_code": question.reason_code,
                    "question": question.text,
                }
                for question in view.questions
            ],
        )
