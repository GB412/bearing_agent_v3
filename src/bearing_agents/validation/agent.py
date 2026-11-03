"""Read-only, fail-closed preliminary candidate validation (not a DLAP solver)."""

from dataclasses import dataclass

from bearing_agents.core.readiness import StageRequirementRegistry, readiness_for
from bearing_agents.domain.agent_protocols import AgentResult, TaskRecord
from bearing_agents.domain.candidate_lifecycle import missing_design_variables
from bearing_agents.domain.candidates import CandidateDesign, CandidatePrecheckReport
from bearing_agents.domain.enums import (
    AgentResultStatus,
    ConstraintSeverity,
    PrecheckStatus,
    RuleStatus,
)
from bearing_agents.domain.parameter_registry import ParameterSchemaRegistry
from bearing_agents.domain.state import DesignState
from bearing_agents.orchestration.registry import AgentContext
from bearing_agents.domain.tasks import engineering_digest
from bearing_agents.knowledge.defaults import KnowledgeBase, build_default_knowledge_base
from bearing_agents.rules.engine import RuleEngine, RuleEvaluationStatus


@dataclass(frozen=True)
class RuleCoverageSpec:
    """The rule IDs below are required capabilities, not invented numerical limits."""

    required_rule_ids: tuple[str, ...] = (
        "geometry_and_clearance_limit",
        "load_and_film_capacity_limit",
        "material_allowable_limit",
        "lubrication_and_temperature_limit",
    )

    def __post_init__(self) -> None:
        if not self.required_rule_ids or len(set(self.required_rule_ids)) != len(
            self.required_rule_ids
        ):
            raise ValueError("Precheck coverage must be nonempty and have unique rule IDs")


class ValidationAgent:
    """Independently assesses a candidate without mutating DesignState."""

    def __init__(
        self,
        knowledge: KnowledgeBase | None = None,
        *,
        coverage: RuleCoverageSpec | None = None,
        stage_registry: StageRequirementRegistry | None = None,
        parameter_registry: ParameterSchemaRegistry | None = None,
    ):
        self.knowledge = knowledge or build_default_knowledge_base()
        self.coverage = coverage or RuleCoverageSpec()
        self.stage_registry = stage_registry
        self.parameter_registry = parameter_registry or ParameterSchemaRegistry()
        self.rules = RuleEngine(
            self.knowledge.rules,
            self.knowledge.sources,
            tables=self.knowledge.tables,
            parameter_registry=self.parameter_registry,
        )

    def run(
        self,
        state: DesignState,
        task: TaskRecord,
        *,
        context: AgentContext | None = None,
    ) -> AgentResult:
        if task.action != "precheck_candidate":
            raise ValueError("ValidationAgent only handles precheck_candidate")
        target_ref = context.target_ref if context is not None else None
        if not target_ref or not target_ref.startswith("candidate:"):
            raise ValueError("MISSING_PRECHECK_TARGET")
        try:
            candidate_id, version_text = target_ref.removeprefix("candidate:").rsplit("@", 1)
            version = int(version_text)
        except (ValueError, TypeError) as exc:
            raise ValueError("INVALID_PRECHECK_TARGET") from exc
        candidate = next(
            (item for item in state.candidate_designs
             if item.candidate_id == candidate_id and item.version == version),
            None,
        )
        if candidate is None:
            raise ValueError("MISSING_PRECHECK_TARGET")
        report = self.evaluate(state, candidate)
        status = (
            AgentResultStatus.SUCCESS
            if report.status == PrecheckStatus.PRECHECK_PASS
            else AgentResultStatus.NEEDS_REVIEW
        )
        return AgentResult(
            task_id=task.id,
            status=status,
            issues=[report.model_dump(mode="json")],
            evidence_refs=report.evidence_refs,
        )

    def evaluate(self, state: DesignState, candidate: CandidateDesign) -> CandidatePrecheckReport:
        persisted = next(
            (
                item for item in state.candidate_designs
                if item.candidate_id == candidate.candidate_id
                and item.version == candidate.version
            ),
            None,
        )
        if persisted is None:
            raise ValueError("Candidate must exist in the authoritative state")
        if candidate.model_dump(mode="json") != persisted.model_dump(mode="json"):
            raise ValueError("Candidate data differs from the authoritative snapshot")
        missing = missing_design_variables(candidate.parameters, state.parameters)
        issues: list[str] = []
        checks: list[dict] = []
        evidence_refs: list[str] = []
        uncovered: list[str] = []
        hard_fail = False
        invalid = False

        gate = readiness_for(
            state, "R2", self.stage_registry, parameter_registry=self.parameter_registry,
        )
        if not gate.ready:
            issues.append("R2 requirements are not ready")
            issues.extend(gate.conflicts)
            issues.extend(f"Missing external input: {item.parameter_id}" for item in gate.missing)
        if state.target_scope != "cylindrical_radial_hydrodynamic":
            issues.append("Unsupported bearing scope")
        if candidate.precheck_status == PrecheckStatus.STALE:
            issues.append("Candidate dependency snapshot is stale")
        if missing:
            issues.append("Incomplete candidate: " + ", ".join(missing))
        if (state.knowledge_rule_set_version is not None
            and state.knowledge_rule_set_version != self.knowledge.rules.version):
            issues.append("Knowledge rule set version does not match the active repository")

        combined = dict(state.parameters)
        combined.update(candidate.parameters)
        steady = (
            state.operating_cases[0].is_steady_state
            if len(state.operating_cases) == 1
            else None
        )
        for rule_id in self.coverage.required_rule_ids:
            rule = self.knowledge.rules.get(rule_id)
            if rule is None or rule.status != RuleStatus.ACTIVE:
                uncovered.append(rule_id)
                continue
            result = self.rules.evaluate_rule(
                rule_id, combined,
                target_scope=state.target_scope,
                is_steady_state=steady,
            )
            checks.append(result.model_dump(mode="json"))
            if result.source_ref:
                evidence_refs.append(result.source_ref)
            if result.status != RuleEvaluationStatus.PASS:
                issues.append(f"Rule {rule_id}: {result.status.value}")
                if result.status == RuleEvaluationStatus.FAIL:
                    hard_fail = True
                elif result.status == RuleEvaluationStatus.INVALID:
                    invalid = True

        for constraint in state.constraints:
            if constraint.severity not in {ConstraintSeverity.HARD, ConstraintSeverity.SOFT}:
                continue
            # Unapproved, non-user constraints cannot become engineering hard limits.
            if constraint.origin != "user" or not constraint.approved:
                if constraint.severity == ConstraintSeverity.HARD:
                    issues.append(f"Constraint {constraint.id} lacks trusted user approval")
                continue
            result = self.rules.evaluate_constraint(constraint, combined)
            checks.append(result.model_dump(mode="json"))
            if result.source_ref:
                evidence_refs.append(result.source_ref)
            if result.status == RuleEvaluationStatus.FAIL:
                if constraint.severity == ConstraintSeverity.HARD:
                    hard_fail = True
                else:
                    issues.append(f"Soft constraint {constraint.id} is not satisfied")
            elif result.status == RuleEvaluationStatus.INVALID:
                invalid = True
            elif result.status != RuleEvaluationStatus.PASS:
                issues.append(f"Constraint {constraint.id}: {result.status.value}")

        if uncovered:
            issues.append("Required professional rule coverage is incomplete")
        if hard_fail:
            status = PrecheckStatus.PRECHECK_FAIL
        elif invalid:
            status = PrecheckStatus.INVALID
        elif issues:
            status = PrecheckStatus.REVIEW_REQUIRED
        else:
            status = PrecheckStatus.PRECHECK_PASS
        return CandidatePrecheckReport(
            candidate_id=candidate.candidate_id,
            candidate_version=candidate.version,
            input_digest=engineering_digest(state),
            rule_set_version=state.knowledge_rule_set_version,
            status=status,
            missing_parameters=missing,
            uncovered_rules=uncovered,
            checks=checks,
            evidence_refs=sorted(set(evidence_refs)),
            issues=issues,
        )
