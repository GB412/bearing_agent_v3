"""Small orchestration contracts and deterministic substitutes, without another domain state."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from typing_extensions import TypedDict

from bearing_agents.core.readiness import ReadinessResult, readiness_for
from bearing_agents.domain.agent_protocols import AgentResult, PlanDecision, TaskRecord
from bearing_agents.domain.enums import AgentResultStatus, TaskStatus
from bearing_agents.domain.state import DesignState
from bearing_agents.domain.tasks import engineering_digest
from bearing_agents.tools.engineering_calculator import journal_surface_speed


class GraphState(TypedDict, total=False):
    design_id: str
    thread_id: str
    run_id: str
    goal: str
    target_ref: str | None
    finding_ref: str | None
    observed_domain_version: int
    input_digest: str
    action: str
    executor: str
    rationale: str
    decision_version: int
    input_refs: list[str]
    requires_confirmation: bool
    current_task_id: str
    last_result_ref: str
    steps: int
    errors: int
    same_action_count: int
    last_signature: str
    termination_reason: str | None
    confirmation: dict | None
    trace: list[dict]
    questions: list[dict]
    agent_outputs: list[dict]


@dataclass(frozen=True)
class ActionSpec:
    executor_id: str
    output_schema_id: str = "AgentResult/v1"
    required_gate: str | None = None
    effect_class: str = "READ_ONLY"
    supported: bool = True
    version: str = "1"
    supported_scopes: tuple[str, ...] = ("*",)
    candidate_source: str | None = None
    required_completed_actions: tuple[str, ...] = ()
    prerequisite_failure_code: str = "PREREQUISITE_NOT_READY"
    terminal: bool = False


# The catalog is the trusted action registry: the planner may select an entry,
# but cannot create executors, scopes, permissions, or side-effect classes.
CATALOG = {
    "clarify_requirement": ActionSpec("requirements_fake", terminal=True),
    "analyze_conditions": ActionSpec(
        "conditions_fake",
        supported_scopes=("cylindrical_radial_hydrodynamic",),
    ),
    "generate_candidate": ActionSpec(
        "design_fake", required_gate="R2", effect_class="CANDIDATE_PROPOSAL",
        supported_scopes=("cylindrical_radial_hydrodynamic",),
        candidate_source="design_agent",
        required_completed_actions=("analyze_conditions",),
        prerequisite_failure_code="ANALYSIS_NOT_READY",
    ),
    "precheck_candidate": ActionSpec(
        "validation_agent", required_gate="R2",
        supported_scopes=("cylindrical_radial_hydrodynamic",),
        terminal=True,
    ),
    "revise_candidate": ActionSpec(
        "design_fake", required_gate="R2", effect_class="CANDIDATE_PROPOSAL",
        supported_scopes=("cylindrical_radial_hydrodynamic",),
        candidate_source="design_agent",
    ),
    "request_confirmation": ActionSpec("confirmation_gateway", effect_class="HUMAN_DECISION"),
    "produce_summary": ActionSpec("summary_fake", terminal=True),
    "simulation_unavailable": ActionSpec("unavailable_stub", terminal=True),
    "run_simulation": ActionSpec("unavailable_stub", supported=False),
}


@dataclass(frozen=True)
class GuardDecision:
    verdict: Literal["ALLOW", "NEEDS_USER", "BLOCK"]
    reason_code: str
    domain_version: int
    action_spec_version: str | None = None


@dataclass(frozen=True)
class StateSummary:
    domain_version: int
    input_digest: str
    input_ready: bool
    missing_inputs: tuple[str, ...]
    supported_scope: bool
    completed_actions: frozenset[str]
    candidate_ref: str | None
    target_ref: str | None
    goal: str
    target_scope: str = "cylindrical_radial_hydrodynamic"
    candidate_refs: tuple[str, ...] = ()
    latest_precheck_status: str | None = None
    recent_findings: tuple[str, ...] = ()
    actionable_finding_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannerContext:
    """Small, trusted planning context assembled outside the model."""

    action_descriptions: tuple[tuple[str, str, str | None, bool], ...] = ()
    action_scope_descriptions: tuple[tuple[str, tuple[str, ...]], ...] = ()
    action_terminal_descriptions: tuple[tuple[str, bool], ...] = ()
    action_prerequisite_descriptions: tuple[tuple[str, tuple[str, ...]], ...] = ()
    recent_failures: tuple[str, ...] = ()
    # None means the caller did not supply a budget; zero means it is exhausted.
    remaining_steps: int | None = None
    remaining_errors: int | None = None


def target_exists(state: DesignState, reference: str | None) -> bool:
    if not reference:
        return False
    try:
        kind, rest = reference.split(":", 1)
        object_id, version = rest.rsplit("@", 1)
        if kind == "parameter":
            item = state.parameters.get(object_id)
            return item is not None and item.revision == int(version)
        if kind == "candidate":
            return any(c.candidate_id == object_id and c.version == int(version)
                       for c in state.candidate_designs)
    except ValueError:
        pass
    return False


ReadinessCheck = Callable[[DesignState, str], ReadinessResult]


def fresh_completed_actions(state: DesignState) -> frozenset[str]:
    """Only persisted, current-input task receipts count as prerequisite evidence."""
    digest = engineering_digest(state)
    fresh_ids = {
        event.details.get("task_id")
        for event in state.event_history
        if event.details.get("task_command") in {"complete", "resume"}
        and event.details.get("input_digest") == digest
    }
    return frozenset(
        task.action for task in state.task_plan
        if task.status == TaskStatus.COMPLETED and task.id in fresh_ids
    )


def observe_state(
    state: DesignState, goal: str, target_ref: str | None,
    *, readiness_check: ReadinessCheck = readiness_for,
) -> StateSummary:
    gate = readiness_check(state, "R2")
    digest = engineering_digest(state)
    done = fresh_completed_actions(state)
    candidate = state.candidate_designs[-1] if state.candidate_designs else None
    candidate_refs = tuple(
        f"candidate:{item.candidate_id}@{item.version}"
        for item in state.candidate_designs
    )
    findings = ()
    actionable = ()
    if candidate is not None and candidate.precheck_report is not None:
        from bearing_agents.validation.diagnosis import diagnose_precheck

        diagnosis = diagnose_precheck(state, candidate, candidate.precheck_report)
        findings = tuple(
            f"{finding.finding_id}: {finding.message}"
            for finding in diagnosis.findings[:3]
        )
        actionable = tuple(
            finding.finding_id
            for finding in diagnosis.findings
            if finding.next_action == "REVIEW_DESIGN_VARIABLE"
            and finding.adjustable_parameter_ids
        )[:3]
    return StateSummary(
        state.state_version, digest, gate.ready,
        tuple(p.parameter_id for p in gate.missing),
        state.target_scope == "cylindrical_radial_hydrodynamic", done,
        f"candidate:{candidate.candidate_id}@{candidate.version}" if candidate else None,
        target_ref, goal, state.target_scope,
        candidate_refs=candidate_refs,
        latest_precheck_status=(
            candidate.precheck_status.value if candidate else None
        ),
        recent_findings=findings,
        actionable_finding_refs=actionable,
    )


def task_plan_view(state: DesignState) -> dict:
    """Disposable projection of the only task list, never another writable plan."""
    revisions = [e for e in state.event_history if e.details.get("task_command") == "register"]
    return {
        "goal": state.user_goal,
        "plan_revision": revisions[-1].details["plan_revision"] if revisions else 0,
        "replan_reason": revisions[-1].details["reason"] if revisions else None,
        "tasks": [task.model_dump(mode="json") for task in state.task_plan[-3:]],
    }


class FakePlanner:
    def __init__(self, catalog: dict[str, ActionSpec] | None = None):
        self.catalog = dict(CATALOG if catalog is None else catalog)

    def bind_catalog(self, catalog: dict[str, ActionSpec]) -> None:
        self.catalog = dict(catalog)

    def plan(self, summary: StateSummary) -> PlanDecision:
        if summary.goal == "simulation":
            action = "simulation_unavailable"
        elif summary.goal == "precheck":
            action = "precheck_candidate"
        elif summary.target_scope == "unknown":
            action = "clarify_requirement"
        elif not summary.supported_scope:
            action = "produce_summary"
        elif (summary.goal == "confirmation" and summary.target_ref
              and "request_confirmation" not in summary.completed_actions):
            action = "request_confirmation"
        elif not summary.input_ready:
            action = "clarify_requirement"
        elif summary.goal == "summary":
            action = "produce_summary"
        elif summary.goal == "design" and summary.candidate_ref:
            if summary.latest_precheck_status == "NOT_EVALUATED":
                action = "precheck_candidate"
            elif (
                summary.latest_precheck_status == "PRECHECK_FAIL"
                and summary.actionable_finding_refs
            ):
                action = "revise_candidate"
            elif summary.latest_precheck_status in {"PRECHECK_FAIL", "REVIEW_REQUIRED"}:
                action = "clarify_requirement"
            else:
                action = "produce_summary"
        elif summary.candidate_ref and "precheck_candidate" not in summary.completed_actions:
            action = "precheck_candidate"
        elif summary.candidate_ref:
            action = "produce_summary"
        elif "analyze_conditions" not in summary.completed_actions:
            action = "analyze_conditions"
        elif "generate_candidate" not in summary.completed_actions:
            action = "generate_candidate"
        else:
            action = "produce_summary"
        return PlanDecision(
            action=action, selected_agent=self.catalog[action].executor_id,
            rationale=f"State-driven offline {action}; missing={summary.missing_inputs}",
            expected_result="DEMO_ONLY workflow information, not engineering validation",
            requires_confirmation=action == "request_confirmation",
            state_version=summary.domain_version,
            target_ref=(
                summary.target_ref or summary.candidate_refs[0]
                if action in {"precheck_candidate", "revise_candidate"}
                and len(summary.candidate_refs) == 1
                else summary.target_ref or (
                    summary.candidate_ref if action == "revise_candidate" else None
                )
            ),
            finding_ref=(
                summary.actionable_finding_refs[0]
                if action == "revise_candidate" and summary.actionable_finding_refs
                else None
            ),
        )


def policy_guard(
    decision: PlanDecision, state: DesignState, target_ref: str | None,
    catalog: dict[str, ActionSpec], *,
    readiness_check: ReadinessCheck = readiness_for,
) -> GuardDecision:
    spec = catalog.get(decision.action)
    reason = None
    if spec is None or not spec.supported:
        reason = "UNSUPPORTED_ACTION"
    elif decision.selected_agent != spec.executor_id:
        reason = "EXECUTOR_MISMATCH"
    elif decision.state_version != state.state_version:
        reason = "STALE_VERSION"
    elif "*" not in spec.supported_scopes and state.target_scope not in spec.supported_scopes:
        reason = "UNSUPPORTED_SCOPE"
    elif spec.output_schema_id != "AgentResult/v1":
        reason = "SCHEMA_MISMATCH"
    elif any(ref not in state.parameters and not target_exists(state, ref)
             for ref in decision.input_refs):
        reason = "UNKNOWN_INPUT_REF"
    elif spec.required_gate and not readiness_check(state, spec.required_gate).ready:
        reason = "INPUT_NOT_READY"
    elif any(
        action not in fresh_completed_actions(state)
        for action in spec.required_completed_actions
    ):
        # Requirements are supplied by the trusted ActionSpec, not embedded
        # into the Supervisor. Completion must have a fresh task receipt.
        reason = spec.prerequisite_failure_code
    elif decision.target_ref and target_ref != decision.target_ref:
        reason = "TARGET_MISMATCH"
    elif (decision.action in {"precheck_candidate", "revise_candidate"}
          and not (target_ref and target_ref.startswith("candidate:")
                   and target_exists(state, target_ref))):
        reason = "MISSING_PRECHECK_TARGET"
    elif decision.action == "revise_candidate":
        from bearing_agents.validation.diagnosis import diagnose_precheck

        candidate = next(
            (item for item in state.candidate_designs
             if f"candidate:{item.candidate_id}@{item.version}" == target_ref),
            None,
        )
        if candidate is None or candidate.precheck_report is None:
            reason = "REVISION_REQUIRES_PRECHECK"
        else:
            diagnosis = diagnose_precheck(state, candidate, candidate.precheck_report)
            available = {
                finding.finding_id for finding in diagnosis.findings
                if finding.next_action == "REVIEW_DESIGN_VARIABLE"
                and finding.adjustable_parameter_ids
            }
            if decision.finding_ref not in available:
                reason = "INVALID_REVISION_FINDING"
    elif spec.effect_class not in {"READ_ONLY", "CANDIDATE_PROPOSAL", "HUMAN_DECISION"}:
        reason = "PERMISSION_DENIED"
    elif (spec.effect_class == "HUMAN_DECISION" or decision.requires_confirmation) and not (
        target_exists(state, target_ref)
    ):
        reason = "MISSING_CONFIRMATION_TARGET"
    if reason:
        return GuardDecision("BLOCK", reason, state.state_version, spec.version if spec else None)
    if decision.requires_confirmation or spec.effect_class == "HUMAN_DECISION":
        return GuardDecision("NEEDS_USER", "USER_REQUIRED", state.state_version, spec.version)
    return GuardDecision("ALLOW", "ALLOWED", state.state_version, spec.version)


class FakeAgent:
    """Returns information only; it has neither a repository nor a write context."""

    def run(self, state: DesignState, task: TaskRecord) -> AgentResult:
        summary = {"source_class": "SYNTHETIC_WORKFLOW", "demo_only": True,
                   "action": task.action}
        if task.action == "analyze_conditions":
            diameter = state.parameters["journal_diameter"]
            speed = state.parameters["rotational_speed"]
            summary["surface_speed_m_s"] = journal_surface_speed(
                diameter.value, speed.value, diameter_unit=diameter.unit, speed_unit=speed.unit,
            )
        if task.action == "generate_candidate":
            summary["message"] = "Design intent only; no engineering candidate or rule approval"
        if task.action == "simulation_unavailable":
            summary["simulation_status"] = "NOT_AVAILABLE"
        if task.action == "precheck_candidate":
            summary["message"] = "ValidationAgent was not registered; no validation performed"
            return AgentResult(
                task_id=task.id, status=AgentResultStatus.NEEDS_REVIEW, issues=[summary],
            )
        return AgentResult(task_id=task.id, status=AgentResultStatus.SUCCESS, issues=[summary])


def validate_result(
    result: AgentResult,
    task_id: str,
    *,
    effect_class: str = "READ_ONLY",
    candidate_source: str | None = None,
    allow_candidate_additions: bool | None = None,
) -> AgentResult:
    # Keep the PR-02 helper argument readable for existing callers; Runtime
    # now derives proposal permission exclusively from the trusted ActionSpec.
    if allow_candidate_additions is not None:
        effect_class = "CANDIDATE_PROPOSAL" if allow_candidate_additions else "READ_ONLY"
        if allow_candidate_additions and candidate_source is None:
            candidate_source = "design_agent"
    result = AgentResult.model_validate(result.model_dump())
    if result.task_id != task_id:
        raise ValueError("RESULT_TASK_MISMATCH")
    if result.state_patch is not None:
        patch = result.state_patch
        if effect_class != "CANDIDATE_PROPOSAL" or len(patch.candidate_additions) != 1:
            raise ValueError("DOMAIN_PATCH_NOT_ALLOWED")
        if (candidate_source is None or patch.source != candidate_source
                or patch.actor is not None):
            raise ValueError("CANDIDATE_PATCH_SOURCE_MISMATCH")
        for field, value in patch.model_dump().items():
            if field not in {"candidate_additions", "source", "actor"} and value not in (
                None, [], {},
            ):
                raise ValueError("CANDIDATE_PATCH_CONTAINS_FORBIDDEN_EFFECTS")
    if result.status == AgentResultStatus.FAILED:
        raise ValueError("AGENT_FAILED")
    return result
