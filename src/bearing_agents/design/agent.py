from bearing_agents.core.readiness import readiness_for
from bearing_agents.design.contracts import CandidateProposal, ConditionAnalysis, DesignStrategy
from bearing_agents.domain.agent_protocols import AgentResult, StatePatch, TaskRecord
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import AgentResultStatus, RuleStatus
from bearing_agents.domain.parameter_registry import ParameterSchemaRegistry
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.state import DesignState
from bearing_agents.domain.tasks import engineering_digest
from bearing_agents.knowledge.defaults import KnowledgeBase, build_default_knowledge_base
from bearing_agents.rules.engine import RuleEngine, RuleEvaluationStatus
from bearing_agents.tools.engineering_calculator import (
    journal_surface_speed,
    projected_mean_pressure,
)


class DesignAgent:
    """Deterministic first-pass design assistant; no LLM authority and no DLAP."""

    DESIGN_VARIABLES = ("bearing_width", "radial_clearance", "material", "lubricant")

    def __init__(
        self,
        knowledge: KnowledgeBase | None = None,
        parameter_registry: ParameterSchemaRegistry | None = None,
    ):
        self.knowledge = knowledge or build_default_knowledge_base()
        self.parameters = parameter_registry or ParameterSchemaRegistry()
        self.rule_engine = RuleEngine(
            self.knowledge.rules,
            self.knowledge.sources,
            tables=self.knowledge.tables,
            parameter_registry=self.parameters,
        )

    def run(self, state: DesignState, task: TaskRecord) -> AgentResult:
        if task.action == "analyze_conditions":
            analysis = self.analyze_conditions(state)
            status = (
                AgentResultStatus.SUCCESS
                if analysis.input_ready
                else AgentResultStatus.NEEDS_REVIEW
            )
            return AgentResult(
                task_id=task.id,
                status=status,
                issues=[analysis.model_dump(mode="json")],
                evidence_refs=analysis.knowledge_refs,
            )
        if task.action == "generate_candidate":
            strategy = self.build_strategy(state)
            proposal = self.propose_candidate(state, strategy)
            status = {
                "COMPLETE": AgentResultStatus.SUCCESS,
                "PARTIAL": AgentResultStatus.NEEDS_REVIEW,
                "INSUFFICIENT_RULES": AgentResultStatus.INSUFFICIENT_RULES,
            }[proposal.status]
            candidate = self._candidate_from_proposal(proposal)
            patch = (
                StatePatch(candidate_additions=[candidate], source="design_agent")
                if candidate is not None
                else None
            )
            return AgentResult(
                task_id=task.id,
                status=status,
                state_patch=patch,
                issues=[
                    strategy.model_dump(mode="json"),
                    proposal.model_dump(mode="json"),
                ],
                evidence_refs=proposal.evidence_refs,
            )
        raise ValueError(f"DesignAgent does not support action: {task.action}")

    def analyze_conditions(self, state: DesignState) -> ConditionAnalysis:
        gate = readiness_for(state, "R2", parameter_registry=self.parameters)
        if state.target_scope != "cylindrical_radial_hydrodynamic":
            return ConditionAnalysis(
                status="UNSUPPORTED_SCOPE",
                scope=state.target_scope,
                input_ready=False,
                conflicts=[f"Unsupported V1 scope: {state.target_scope}"],
            )
        metrics = {}
        diameter = state.parameters.get("journal_diameter")
        speed = state.parameters.get("rotational_speed")
        if diameter and speed and diameter.value is not None and speed.value is not None:
            metrics["surface_speed"] = {
                "value": journal_surface_speed(
                    diameter.value,
                    speed.value,
                    diameter_unit=diameter.unit,
                    speed_unit=speed.unit,
                ),
                "unit": "m/s",
                "meaning": "Derived kinematic indicator, not a pass/fail limit.",
            }
        width = state.parameters.get("bearing_width")
        load = state.parameters.get("load")
        if (
            diameter
            and width
            and load
            and all(x.value is not None for x in (diameter, width, load))
        ):
            metrics["mean_pressure"] = {
                "value": projected_mean_pressure(
                    load.value,
                    diameter.value,
                    width.value,
                    load_unit=load.unit,
                    diameter_unit=diameter.unit,
                    width_unit=width.unit,
                ),
                "unit": "Pa",
                "meaning": (
                    "Projected mean pressure F/(D*B), not local maximum film pressure."
                ),
            }
        hits = self.knowledge.knowledge.search(
            "适用范围 模型假设 层流 紊流 不确定性 热平衡",
            limit=8,
        )
        refs = [
            f"{h.source.document_number}@{h.source.version}#{h.entry.section}"
            for h in hits
        ]
        cautions = [
            "Surface speed is a derived indicator; no engineering threshold is inferred.",
            "Projected mean pressure is not local maximum oil-film pressure.",
            "PR-05 does not calculate film pressure, minimum film thickness or thermal balance.",
        ]
        if not width:
            cautions.append(
                "Bearing width is a design variable; no approved default recommendation exists."
            )
        return ConditionAnalysis(
            status="INPUTS_READY" if gate.ready else "INPUTS_INCOMPLETE",
            scope=state.target_scope,
            input_ready=gate.ready,
            missing_inputs=[p.parameter_id or "" for p in gate.missing],
            conflicts=gate.conflicts,
            derived_metrics=metrics,
            knowledge_refs=refs,
            cautions=cautions,
        )

    def build_strategy(self, state: DesignState) -> DesignStrategy:
        rules = self.knowledge.rules.for_scope(state.target_scope)
        active = [r for r in rules if r.status == RuleStatus.ACTIVE]
        unavailable = [r.rule_id for r in rules if r.status != RuleStatus.ACTIVE]
        hits = self.knowledge.knowledge.search(
            "间隙比 最小膜厚 材料 润滑油 许用参数",
            limit=8,
        )
        evidence = [
            f"{h.source.document_number}@{h.source.version}#{h.entry.section}"
            for h in hits
        ]
        return DesignStrategy(
            strategy_id=engineering_digest(state)[:16],
            objective=state.user_goal or "cylindrical_radial_hydrodynamic_preliminary_design",
            design_variables=list(self.DESIGN_VARIABLES),
            required_evidence=evidence,
            available_rule_refs=[r.rule_id for r in active],
            unavailable_rule_refs=unavailable,
            rationale=[
                "Only ACTIVE rules and reviewed tables may supply numeric recommendations.",
                "User fixed inputs and approved constraints are not design variables.",
                "Table lookup never interpolates or extrapolates.",
            ],
        )

    @staticmethod
    def _candidate_from_proposal(proposal: CandidateProposal) -> CandidateDesign | None:
        if proposal.status != "COMPLETE":
            return None
        parameters = {
            parameter_id: ParameterRecord(
                value=item["value"], unit=item["unit"], role="DESIGN_VARIABLE",
                status="SUGGESTED", source="engineering_table", source_ref=item["source_ref"],
            )
            for parameter_id, item in proposal.parameters.items()
        }
        assumptions = list(proposal.explanation)
        if proposal.unresolved_parameters:
            assumptions.append("Unresolved design variables: " + ", ".join(proposal.unresolved_parameters))
        return CandidateDesign(
            candidate_id=f"candidate-{proposal.proposal_id}", version=1,
            parameters=parameters, assumptions=assumptions, rule_refs=proposal.evidence_refs,
        )

    def propose_candidate(
        self,
        state: DesignState,
        strategy: DesignStrategy,
    ) -> CandidateProposal:
        suggestions = {}
        refs = []
        for rule in self.knowledge.rules.for_scope(state.target_scope):
            if rule.status != RuleStatus.ACTIVE or rule.operation != "TABLE_LOOKUP":
                continue
            result = self.rule_engine.evaluate_rule(
                rule.rule_id,
                state.parameters,
                target_scope=state.target_scope,
                is_steady_state=(
                    state.operating_cases[0].is_steady_state
                    if len(state.operating_cases) == 1
                    else None
                ),
            )
            if result.status != RuleEvaluationStatus.VALUE_FOUND:
                continue
            for parameter_id, value in result.values.items():
                schema = self.parameters.get(parameter_id)
                unit = result.units.get(parameter_id)
                if schema is None or unit is None:
                    continue
                suggestions[parameter_id] = {
                    "value": value,
                    "unit": unit,
                    "source_ref": result.source_ref,
                    "rule_ref": rule.rule_id,
                }
                refs.append(result.source_ref or rule.rule_id)
        unresolved = [key for key in self.DESIGN_VARIABLES if key not in suggestions]
        return CandidateProposal(
            proposal_id=engineering_digest(state)[:16],
            status=(
                "COMPLETE" if not unresolved
                else "PARTIAL" if suggestions
                else "INSUFFICIENT_RULES"
            ),
            parameters=suggestions,
            unresolved_parameters=unresolved,
            evidence_refs=sorted(set(refs)),
            explanation=(
                ["Numeric recommendations only come from ACTIVE reviewed tables."]
                + (
                    ["No active reviewed table supplied a design-variable value."]
                    if not suggestions
                    else ["Partial proposal: unresolved variables must not be guessed."]
                )
            ),
        )
