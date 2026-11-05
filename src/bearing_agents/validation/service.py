"""Trusted application entry point: evaluate then persist precheck at one state version."""

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.candidates import CandidatePrecheckReport
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.validation.agent import ValidationAgent
from bearing_agents.validation.diagnosis import ValidationDiagnosis, diagnose_precheck


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
        return self.persist_report(design_id, report)

    def persist_report(
        self,
        design_id: str,
        report: CandidatePrecheckReport,
    ) -> CandidatePrecheckReport:
        """Persist an already computed, evidence-bound report through StateManager."""
        state = self.manager.get_design(design_id)
        self.manager.record_candidate_precheck(
            design_id,
            state.state_version,
            report,
            context=WriteContext(kind=WriterKind.SYSTEM, actor="validation-service"),
        )
        return report

    def diagnose(
        self,
        design_id: str,
        candidate_id: str,
        candidate_version: int,
    ) -> ValidationDiagnosis:
        """Explain only a report already persisted for this exact candidate."""
        state = self.manager.get_design(design_id)
        candidate = next(
            (
                item for item in state.candidate_designs
                if item.candidate_id == candidate_id
                and item.version == candidate_version
            ),
            None,
        )
        if candidate is None or candidate.precheck_report is None:
            raise ValueError("Candidate has no stored precheck report")
        return diagnose_precheck(state, candidate, candidate.precheck_report)
