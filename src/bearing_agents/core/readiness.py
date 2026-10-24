from dataclasses import dataclass

from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.state import DesignState


@dataclass(frozen=True)
class ReadinessResult:
    stage: str
    ready: bool
    missing: list[ParameterRecord]
    conflicts: list[str]
    not_configured: bool


class StageRequirementRegistry:
    def __init__(self, requirements: dict[str, tuple[str, ...]] | None = None):
        self._requirements = requirements or {
            "R2": ("journal_diameter", "load", "rotational_speed")
        }

    def requirements_for(self, stage: str) -> tuple[str, ...] | None:
        return self._requirements.get(stage)


def readiness_for(
    state: DesignState,
    stage: str,
    registry: StageRequirementRegistry | None = None,
) -> ReadinessResult:
    registry = registry or StageRequirementRegistry()
    required = registry.requirements_for(stage)
    if required is None:
        return ReadinessResult(stage, False, [], [], True)
    missing: list[ParameterRecord] = []
    conflicts: list[str] = []
    for parameter_id in required:
        record = state.parameters.get(parameter_id)
        if record is None:
            missing.append(
                ParameterRecord(
                    parameter_id=parameter_id,
                    role=ParameterRole.FIXED_INPUT,
                    status=ParameterStatus.MISSING,
                    required_for=[stage],
                )
            )
        elif record.status in {
            ParameterStatus.MISSING,
            ParameterStatus.CONFLICT,
            ParameterStatus.STALE,
        }:
            (conflicts if record.status == ParameterStatus.CONFLICT else missing).append(record)
    steady_cases = [case for case in state.operating_cases if case.is_steady_state]
    if not steady_cases:
        conflicts.append("operating_case:one steady-state case is required")
    else:
        required_refs = {
            "journal_diameter_ref": "journal_diameter",
            "load_ref": "load",
            "speed_ref": "rotational_speed",
        }
        for case in steady_cases:
            for field, expected_parameter in required_refs.items():
                reference = getattr(case, field)
                if reference is None:
                    conflicts.append(f"operating_case:{field} is required")
                elif reference != expected_parameter or reference not in state.parameters:
                    conflicts.append(
                        f"operating_case:{field} does not resolve to {expected_parameter}"
                    )
    return ReadinessResult(stage, not missing and not conflicts, missing, conflicts, False)
