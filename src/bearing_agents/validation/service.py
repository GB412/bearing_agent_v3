"""Trusted application entry point: evaluate then persist precheck at one state version."""

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.candidates import CandidatePrecheckReport
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.validation.agent import ValidationAgent


class ValidationService:
    """This service belongs to the application boundary, not model-authored tools."""

    def __init__(self, manager: StateManager, agent: ValidationAgent | None = None):
        self.manager = manager
        self.agent = agent or ValidationAgent()

    def assess(
        self,
        design_id: str,
        candidate_id: str,
        candidate_version: int,
    ) -> CandidatePrecheckReport:
        state = self.manager.get_design(design_id)
        candidate = next(
            (
                item for item in state.candidate_designs
                if item.candidate_id == candidate_id
                and item.version == candidate_version
            ),
            None,
        )
        if candidate is None:
            raise ValueError("Unknown candidate version")
        report = self.agent.evaluate(state, candidate)
        self.manager.record_candidate_precheck(
            design_id,
            state.state_version,
            report,
            context=WriteContext(kind=WriterKind.SYSTEM, actor="validation-service"),
        )
        return report
