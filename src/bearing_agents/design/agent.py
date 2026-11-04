from bearing_agents.core.readiness import StageRequirementRegistry, readiness_for
from bearing_agents.design.contracts import (
    AnalysisStep,
    CandidateProposal,
    ConditionAnalysis,
    DesignStrategy,
)
from bearing_agents.domain.agent_protocols import AgentResult, StatePatch, TaskRecord
from bearing_agents.domain.candidate_lifecycle import missing_design_variables
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.enums import (
    AgentResultStatus,
    ParameterRole,
    ParameterStatus,
    RuleStatus,
)
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
        stage_registry: StageRequirementRegistry | None = None,
        strategy_advisor=None,
    ):
        self.strategy_advisor = strategy_advisor
        self.knowledge = knowledge or build_default_knowledge_base()
        self.parameters = parameter_registry or ParameterSchemaRegistry()
        self.stage_registry = stage_registry
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
            status = (
                AgentResultStatus.NEEDS_REVIEW
                if proposal.status == "PARTIAL"
                else AgentResultStatus.SUCCESS
                if proposal.status == "COMPLETE"
                else AgentResultStatus.INSUFFICIENT_RULES
            )
            candidate = self._candidate_from_proposal(state, proposal)
            return AgentResult(
                task_id=task.id,
                status=status,
                state_patch=(
                    StatePatch(candidate_additions=[candidate], source="design_agent")
                    if candidate is not None else None
                ),
                issues=[
                    strategy.model_dump(mode="json"),
                    proposal.model_dump(mode="json"),
                ],
                evidence_refs=proposal.evidence_refs,
            )
        raise ValueError(f"DesignAgent does not support action: {task.action}")

    def analyze_conditions(self, state: DesignState) -> ConditionAnalysis:
        gate = readiness_for(
            state, "R2", self.stage_registry, parameter_registry=self.parameters,
        )
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

    def _analysis_steps(self, state: DesignState) -> list[AnalysisStep]:
        """Classify feasible diagnostic steps without inventing performance results."""
        analysis = self.analyze_conditions(state)
        metrics = analysis.derived_metrics
        active_rules = [
            rule for rule in self.knowledge.rules.for_scope(state.target_scope)
            if rule.status == RuleStatus.ACTIVE
        ]
        material_rules = [rule.rule_id for rule in active_rules if "material" in rule.inputs]
        lubricant_rules = [rule.rule_id for rule in active_rules if "lubricant" in rule.inputs]
        output = [
            AnalysisStep(
                step_id="surface_speed",
                status="DERIVED" if "surface_speed" in metrics else "NEEDS_EXTERNAL_INPUT",
                reason="Kinematic indicator only; no approved speed limit is inferred.",
                required_inputs=["journal_diameter", "rotational_speed"],
            ),
            AnalysisStep(
                step_id="mean_pressure",
                status=("DERIVED" if "mean_pressure" in metrics else
                        "NEEDS_DESIGN_VARIABLE" if "journal_diameter" in state.parameters
                        and "load" in state.parameters else "NEEDS_EXTERNAL_INPUT"),
                reason="Projected F/(D*B), not the maximum lubricant-film pressure.",
                required_inputs=["load", "journal_diameter", "bearing_width"],
            ),
            AnalysisStep(
                step_id="minimum_film_thickness", status="SOLVER_NOT_AVAILABLE",
                reason="No approved professional oil-film solver is installed.",
                required_inputs=["radial_clearance", "lubricant"],
            ),
            AnalysisStep(
                step_id="thermal_balance", status="SOLVER_NOT_AVAILABLE",
                reason="No validated thermal-balance calculator is installed.",
                required_inputs=["lubricant", "rotational_speed"],
            ),
            AnalysisStep(
                step_id="material_limits",
                status="REVIEWED_RULE_AVAILABLE" if material_rules else "NEEDS_REVIEWED_RULE",
                reason="Permissible material limits must come from reviewed ACTIVE rules.",
                required_inputs=["material"], evidence_refs=material_rules,
            ),
            AnalysisStep(
                step_id="lubricant_selection",
                status="REVIEWED_RULE_AVAILABLE" if lubricant_rules else "NEEDS_REVIEWED_RULE",
                reason="Lubricant selection requires approved tables and operating conditions.",
                required_inputs=["lubricant"], evidence_refs=lubricant_rules,
            ),
        ]
        return output

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
        steps = self._analysis_steps(state)
        advisory_note = None
        if self.strategy_advisor is not None:
            steps, advisory_note = self.strategy_advisor.prioritize(
                steps, objective=state.user_goal or "",
            )
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
            analysis_steps=steps,
            risk_questions=[
                "Minimum oil-film thickness has not been evaluated.",
                "Thermal balance and operating temperature have not been evaluated.",
                "Candidate material and lubricant limits require reviewed evidence.",
            ],
            unverified_advisory=advisory_note,
        )

    @staticmethod
    def _candidate_from_proposal(
        state: DesignState,
        proposal: CandidateProposal,
    ) -> CandidateDesign | None:
        if not proposal.parameters:
            return None
        parameters = {
            key: ParameterRecord(
                value=item["value"],
                unit=item["unit"],
                role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
                source="candidate_proposal",
                source_ref=item.get("source_ref"),
            )
            for key, item in proposal.parameters.items()
        }
        return CandidateDesign(
            candidate_id=f"candidate-{proposal.proposal_id}",
            version=1,
            parent_candidate_id=(
                state.candidate_designs[-1].candidate_id if state.candidate_designs else None
            ),
            parameters=parameters,
            rule_refs=sorted({
                item.get("rule_ref", "") for item in proposal.parameters.values()
                if item.get("rule_ref")
            }),
            assumptions=proposal.explanation,
            unresolved_parameters=proposal.unresolved_parameters,
            completeness_status=(
                "PARTIAL" if proposal.unresolved_parameters else "COMPLETE"
            ),
        )

    def propose_candidate(
        self,
        state: DesignState,
        strategy: DesignStrategy,
    ) -> CandidateProposal:
        suggestions = {}
        refs = []
        conflicted = set()
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
                if parameter_id not in self.DESIGN_VARIABLES or parameter_id in conflicted:
                    continue
                unit = result.units.get(parameter_id)
                if unit is None:
                    continue
                try:
                    self.parameters.validate(parameter_id, value, unit)
                except ValueError:
                    continue
                previous = suggestions.get(parameter_id)
                if previous is not None and (
                    previous["value"] != value or previous["unit"] != unit
                ):
                    conflicted.add(parameter_id)
                    del suggestions[parameter_id]
                    continue
                suggestions[parameter_id] = {
                    "value": value,
                    "unit": unit,
                    "source_ref": result.source_ref,
                    "rule_ref": rule.rule_id,
                }
                refs.append(result.source_ref or rule.rule_id)
        for key in self.DESIGN_VARIABLES:
            if key in suggestions or key in conflicted:
                continue
            record = state.parameters.get(key)
            if record is None or record.role != ParameterRole.DESIGN_VARIABLE:
                continue
            if record.status not in {
                ParameterStatus.PROVIDED,
                ParameterStatus.CONFIRMED,
                ParameterStatus.SUGGESTED,
            }:
                continue
            if record.value is None:
                continue
            if record.status == ParameterStatus.PROVIDED and not record.verified_source_ref:
                continue
            if record.status == ParameterStatus.CONFIRMED and not record.confirmed_by:
                continue
            self.parameters.validate_record(key, record)
            suggestions[key] = {
                "value": record.value,
                "unit": record.unit,
                "source_ref": record.verified_source_ref or record.source_ref,
                "rule_ref": None,
            }
        unresolved = missing_design_variables(
            {
                key: ParameterRecord(
                    value=item["value"], unit=item["unit"],
                    role=ParameterRole.DESIGN_VARIABLE, status=ParameterStatus.SUGGESTED,
                )
                for key, item in suggestions.items()
            },
            {},
            registry=self.parameters,
        )
        return CandidateProposal(
            proposal_id=engineering_digest(state)[:16],
            status=(
                "COMPLETE" if suggestions and not unresolved
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
                + (
                    ["Conflicting active table recommendations require expert review: "
                     + ", ".join(sorted(conflicted))]
                    if conflicted else []
                )
            ),
        )
