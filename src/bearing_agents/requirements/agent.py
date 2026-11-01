"""Read-only RequirementsAgent for the existing LangGraph action slot."""

from bearing_agents.domain.agent_protocols import AgentResult, TaskRecord
from bearing_agents.domain.enums import AgentResultStatus
from bearing_agents.domain.state import DesignState
from bearing_agents.requirements.questions import build_view


class RequirementsAgent:
    def __init__(self, manager):
        self.manager = manager

    def run(self, state: DesignState, task: TaskRecord) -> AgentResult:
        if task.action != "clarify_requirement":
            raise ValueError("RequirementsAgent only handles clarify_requirement")
        view = build_view(self.manager,state.design_id)
        return AgentResult(
            task_id=task.id,status=AgentResultStatus.SUCCESS,
            issues=[{"question_id":q.question_id,"reason_code":q.reason_code,
                     "question":q.text} for q in view.questions],
        )
