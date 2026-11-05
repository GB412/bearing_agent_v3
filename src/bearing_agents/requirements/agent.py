"""Read-only RequirementsAgent for the shared Supervisor runtime."""

from bearing_agents.core.readiness import StageRequirementRegistry, readiness_for
from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.agent_protocols import AgentResult, TaskRecord
from bearing_agents.domain.enums import AgentResultStatus
from bearing_agents.domain.parameter_registry import ParameterSchemaRegistry
from bearing_agents.domain.state import DesignState
from bearing_agents.orchestration.registry import AgentContext
from bearing_agents.requirements.contracts import Question
from bearing_agents.requirements.questions import build_view
from bearing_agents.validation.diagnosis import diagnose_precheck


class RequirementsAgent:
    """Builds requirement questions from an immutable state snapshot.

    It deliberately receives no StateManager or Repository. The trusted
    InteractionService owns user writes; this agent only reports questions.
    """

    def __init__(
        self,
        stage_registry: StageRequirementRegistry | None = None,
        parameter_registry: ParameterSchemaRegistry | None = None,
        question_ranker=None,
    ):
        # Backward-compatible constructor input only: copy the two read-only
        # registries and do not retain the StateManager reference.
        if isinstance(stage_registry, StateManager):
            manager = stage_registry
            stage_registry = manager.stage_registry
            parameter_registry = parameter_registry or manager.parameter_registry
        self.stage_registry = stage_registry
        self.parameter_registry = parameter_registry
        self.question_ranker = question_ranker

    def run(
        self, state: DesignState, task: TaskRecord, *, context: AgentContext | None = None,
    ) -> AgentResult:
        if task.action != "clarify_requirement":
            raise ValueError("RequirementsAgent only handles clarify_requirement")
        gate = readiness_for(
            state,
            "R2",
            self.stage_registry,
            parameter_registry=self.parameter_registry,
        )
        recent_text = ""
        if context is not None and "last_user_turn" in context.tools.available_tool_ids:
            recent_text = context.tools.call("last_user_turn", design_id=state.design_id)
        view = build_view(state, gate, recent_text=recent_text)
        questions = list(view.questions)
        if context is not None and context.target_ref:
            candidate = next(
                (item for item in state.candidate_designs
                 if f"candidate:{item.candidate_id}@{item.version}" == context.target_ref),
                None,
            )
            if candidate is not None and candidate.precheck_report is not None:
                diagnosis = diagnose_precheck(state, candidate, candidate.precheck_report)
                for finding in diagnosis.findings:
                    if len(questions) >= 3:
                        break
                    if finding.kind not in {
                        "MISSING_PARAMETER", "RULE_COVERAGE_GAP", "RULE_FAILURE",
                    }:
                        continue
                    questions.append(Question(
                        question_id=(
                            f"{state.design_id}:{state.state_version}:{finding.finding_id}"
                        ),
                        reason_code=finding.kind,
                        text=(
                            f"设计校核需要进一步处理：{finding.message} "
                            "请提供相应的设计条件或可靠专业依据。"
                        )[:300],
                    ))
        if self.question_ranker is not None and len(questions) > 1:
            questions = self.question_ranker.reorder(questions, view.guidance)
        return AgentResult(
            task_id=task.id,
            status=AgentResultStatus.SUCCESS,
            issues=[
                {
                    "question_id": question.question_id,
                    "reason_code": question.reason_code,
                    "question": question.text,
                }
                for question in questions
            ],
        )
