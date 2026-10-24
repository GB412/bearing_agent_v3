import math
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from bearing_agents.core.dependency_tracker import InvalidationResult, invalidate_dependents
from bearing_agents.core.unit_normalizer import UnitError, normalize
from bearing_agents.domain.agent_protocols import StatePatch
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.events import StateEvent
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.state import DesignState
from bearing_agents.infra.state_repository import SQLiteStateRepository


class StateManagerError(ValueError):
    pass


class VersionConflictError(StateManagerError):
    pass


class FixedInputWriteError(StateManagerError):
    pass


UNIT_DIMENSIONS = {
    "journal_diameter": "length",
    "bearing_bore_diameter": "length",
    "radial_clearance": "length",
    "diametral_clearance": "length",
    "bearing_width": "length",
    "load": "force",
    "rotational_speed": "rotational_speed",
    "surface_speed": "speed",
    "mean_pressure": "pressure",
    "clearance_ratio": "dimensionless",
}


class StateManager:
    def __init__(self, repository: SQLiteStateRepository):
        self.repository = repository

    def create_design(
        self, user_goal: str | None = None, thread_id: str | None = None
    ) -> DesignState:
        state = DesignState(design_id=str(uuid4()), user_goal=user_goal, thread_id=thread_id)
        self.repository.create(state)
        return state

    def get_design(self, design_id: str) -> DesignState:
        state = self.repository.get(design_id)
        if state is None:
            raise KeyError(f"Unknown design_id: {design_id}")
        return state

    def apply_patch(
        self,
        design_id: str,
        expected_version: int,
        patch: StatePatch | dict,
    ) -> DesignState:
        try:
            patch = patch if isinstance(patch, StatePatch) else StatePatch.model_validate(patch)
        except ValidationError as exc:
            raise StateManagerError(str(exc)) from exc
        current = self.get_design(design_id)
        if current.state_version != expected_version:
            raise VersionConflictError(
                f"Expected version {expected_version}, current version is {current.state_version}"
            )
        if patch.authorized_fixed_input_ids and patch.source != "user":
            raise FixedInputWriteError(
                "Only a user-sourced patch may authorize fixed input changes"
            )
        updated = current.model_copy(deep=True)
        changed: set[str] = set()
        for key, proposed in patch.parameters.items():
            record = proposed.model_copy(deep=True)
            record.parameter_id = record.parameter_id or key
            old = updated.parameters.get(key)
            if (
                old
                and old.role == ParameterRole.FIXED_INPUT
                and key not in patch.authorized_fixed_input_ids
            ):
                raise FixedInputWriteError(f"Modification of fixed input {key!r} is not authorized")
            if record.status == ParameterStatus.MISSING:
                if record.value is not None:
                    raise StateManagerError("A MISSING parameter cannot carry a value")
            elif record.status != ParameterStatus.UNAVAILABLE and record.value is None:
                raise StateManagerError(
                    f"Parameter {key!r} has status {record.status} but no value"
                )
            expected_dimension = UNIT_DIMENSIONS.get(key)
            if record.value is not None:
                if not record.unit:
                    raise StateManagerError(f"Parameter {key!r} requires an explicit unit")
                try:
                    numeric_value = float(record.value)
                    if not math.isfinite(numeric_value) or numeric_value <= 0:
                        raise ValueError(f"Parameter {key!r} must be finite and positive")
                    normalize(numeric_value, record.unit, expected_dimension)
                except (UnitError, TypeError, ValueError) as exc:
                    raise StateManagerError(str(exc)) from exc
            if record.status == ParameterStatus.CONFIRMED and record.confirmed_by is None:
                record.confirmed_by = patch.actor
            if record.source is None:
                record.source = patch.source
            record.revision = (old.revision + 1) if old else max(record.revision, 1)
            updated.parameters[key] = record
            changed.add(key)
        for key, value in patch.state_updates.items():
            if key in {"design_id", "state_version", "event_history", "event_log_refs"}:
                raise StateManagerError(f"State field {key!r} is managed by StateManager")
            if not hasattr(updated, key):
                raise StateManagerError(f"Unknown DesignState field: {key!r}")
            setattr(updated, key, value)
            changed.add(key)
        invalidated = invalidate_dependents(updated, changed)
        next_version = expected_version + 1
        event = StateEvent(
            design_id=design_id,
            from_version=expected_version,
            to_version=next_version,
            changed_fields=sorted(changed),
            source=patch.source,
            actor=patch.actor,
            occurred_at=datetime.now(UTC),
            details={"invalidated_objects": invalidated.invalidated_objects},
        )
        updated.state_version = next_version
        updated.event_history.append(event)
        updated.event_log_refs.append(event.event_id)
        self.repository.save(updated, expected_version)
        return updated

    def list_missing_for(self, design_id: str, stage: str) -> list[ParameterRecord]:
        state = self.get_design(design_id)
        return [
            record
            for record in state.parameters.values()
            if record.status == ParameterStatus.MISSING and stage in record.required_for
        ]

    def invalidate_dependents(
        self, design_id: str, changed_fields: set[str], expected_version: int
    ) -> tuple[DesignState, InvalidationResult]:
        current = self.get_design(design_id)
        if current.state_version != expected_version:
            raise VersionConflictError(
                f"Expected version {expected_version}, current version is {current.state_version}"
            )
        updated = current.model_copy(deep=True)
        result = invalidate_dependents(updated, changed_fields)
        updated.state_version += 1
        event = StateEvent(
            design_id=design_id,
            from_version=expected_version,
            to_version=updated.state_version,
            changed_fields=sorted(changed_fields),
            source="dependency_tracker",
            details={"invalidated_objects": result.invalidated_objects},
        )
        updated.event_history.append(event)
        updated.event_log_refs.append(event.event_id)
        self.repository.save(updated, expected_version)
        return updated, result
