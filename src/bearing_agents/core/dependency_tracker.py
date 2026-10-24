from dataclasses import dataclass, field

from bearing_agents.domain.enums import IssueStatus, ParameterStatus, PrecheckStatus
from bearing_agents.domain.state import DesignState


@dataclass
class InvalidationResult:
    invalidated_objects: list[str] = field(default_factory=list)


DEPENDENCIES: dict[str, set[str]] = {
    "journal_diameter": {"surface_speed", "mean_pressure"},
    "rotational_speed": {"surface_speed"},
    "load": {"mean_pressure"},
    "bearing_width": {"mean_pressure"},
    "material": {"material_precheck"},
    "constraints": {"constraint_precheck"},
}


def invalidate_dependents(state: DesignState, changed_fields: set[str]) -> InvalidationResult:
    affected: set[str] = set()
    for changed_field in changed_fields:
        affected.update(DEPENDENCIES.get(changed_field, set()))
    invalidated: list[str] = []
    for name in affected:
        record = state.parameters.get(name)
        if record:
            state.parameters[name] = record.model_copy(
                update={"status": ParameterStatus.STALE, "invalidated_by": sorted(changed_fields)}
            )
            invalidated.append(f"parameter:{name}")
    for index, candidate in enumerate(state.candidate_designs):
        used = set(candidate.source_parameter_revisions)
        if changed_fields & used or "journal_diameter" in changed_fields:
            state.candidate_designs[index] = candidate.model_copy(
                update={"precheck_status": PrecheckStatus.STALE}
            )
            invalidated.append(f"candidate:{candidate.candidate_id}")
    for index, issue in enumerate(state.issues):
        if changed_fields & set(issue.affected_fields):
            state.issues[index] = issue.model_copy(update={"status": IssueStatus.STALE})
            invalidated.append(f"issue:{issue.code}")
    for index, task in enumerate(state.task_plan):
        if changed_fields & set(task.dependencies):
            state.task_plan[index] = task.model_copy(update={"status": "STALE"})
            invalidated.append(f"task:{task.id}")
    state.stale_objects = sorted(set(state.stale_objects) | set(invalidated))
    return InvalidationResult(invalidated_objects=sorted(set(invalidated)))
