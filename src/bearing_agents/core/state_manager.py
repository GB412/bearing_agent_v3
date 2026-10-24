from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from bearing_agents.core.dependency_tracker import InvalidationResult, invalidate_dependents
from bearing_agents.core.readiness import (
    ReadinessResult,
    StageRequirementRegistry,
    readiness_for,
)
from bearing_agents.domain.agent_protocols import (
    StateRepository,
    ConfirmationEvent,
    RoleChange,
    StatePatch,
)
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    ConfirmationStatus,
    ParameterRole,
    ParameterStatus,
    PrecheckStatus,
    SimulationStatus,
)
from bearing_agents.domain.events import StateEvent
from bearing_agents.domain.parameter_registry import (
    ParameterSchemaError,
    ParameterSchemaRegistry,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.proposals import (
    ProposalDecision,
    ProposalResolution,
    ProposalStatus,
)
from bearing_agents.domain.state import DesignState
from bearing_agents.domain.write_context import WriteContext, WriterKind


class StateManagerError(ValueError):
    pass


class VersionConflictError(StateManagerError):
    pass


class FixedInputWriteError(StateManagerError):
    pass


def _snapshot_candidate_dependencies(
    candidate: CandidateDesign, state: DesignState
) -> CandidateDesign:
    """Attach current revisions to a newly submitted candidate."""
    parameter_revisions = {
        key: record.revision for key, record in state.parameters.items()
    }
    constraint_revisions = {item.id: item.revision for item in state.constraints}
    for supplied, actual in (
        (candidate.source_parameter_revisions, parameter_revisions),
        (candidate.input_constraint_revisions, constraint_revisions),
    ):
        if any(actual.get(key) != revision for key, revision in supplied.items()):
            raise StateManagerError("Candidate dependency revision is not current")
    if (
        candidate.rule_set_version is not None
        and candidate.rule_set_version != state.knowledge_rule_set_version
    ):
        raise StateManagerError("Candidate rule set version is not current")
    dependency_refs = {
        f"parameter:{key}": str(revision) for key, revision in parameter_revisions.items()
    }
    for constraint in state.constraints:
        dependency_refs[f"constraint:{constraint.id}"] = str(constraint.revision)
    for operating_case in state.operating_cases:
        dependency_refs[f"operating_case:{operating_case.case_id}"] = str(
            operating_case.revision
        )
    rule_set_version = state.knowledge_rule_set_version
    if rule_set_version is not None:
        dependency_refs["rule_set_version"] = rule_set_version
    for key, value in candidate.input_dependency_refs.items():
        expected = dependency_refs.get(key)
        # Accept the legacy unprefixed parameter reference spelling too.
        if key in parameter_revisions:
            expected = str(parameter_revisions[key])
        if expected is None or expected != value:
            raise StateManagerError(f"Candidate dependency reference {key!r} is not current")
    dependency_refs.update(candidate.input_dependency_refs)
    return candidate.model_copy(
        update={
            "source_parameter_revisions": parameter_revisions,
            "input_constraint_revisions": constraint_revisions,
            "input_dependency_refs": dependency_refs,
            "rule_set_version": rule_set_version,
        }
    )


class StateManager:
    def __init__(
        self,
        repository: StateRepository,
        *,
        parameter_registry: ParameterSchemaRegistry | None = None,
        stage_registry: StageRequirementRegistry | None = None,
    ):
        self.repository = repository
        self.parameter_registry = parameter_registry or ParameterSchemaRegistry()
        self.stage_registry = stage_registry or StageRequirementRegistry()

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
        *,
        context: WriteContext | None = None,
    ) -> DesignState:
        try:
            # model_copy()/model_construct() may contain invalid fields; even model
            # instances must cross the same validation boundary as external dicts.
            patch = StatePatch.model_validate(
                patch.model_dump() if isinstance(patch, StatePatch) else patch
            )
        except ValidationError as exc:
            raise StateManagerError(str(exc)) from exc
        current = self.get_design(design_id)
        context = context or WriteContext()
        if current.state_version != expected_version:
            raise VersionConflictError(
                f"Expected version {expected_version}, current version is {current.state_version}"
            )
        updated = current.model_copy(deep=True)
        changed: set[str] = set()
        parameter_changes = dict(patch.parameter_changes)
        confirmation_events = list(patch.confirmation_events)
        resolutions: dict[str, ProposalResolution] = {}
        for resolution in patch.proposal_resolutions:
            if context.kind != WriterKind.USER or not context.actor:
                raise StateManagerError("Proposal resolution requires trusted USER context")
            if resolution.proposal_id in resolutions:
                raise StateManagerError("Duplicate proposal resolutions")
            proposal = next(
                (p for p in current.parameter_change_proposals
                 if p.proposal_id == resolution.proposal_id),
                None,
            )
            if proposal is None or proposal.status != ProposalStatus.PENDING:
                raise StateManagerError("Proposal is missing or no longer pending")
            prior = current.parameters.get(proposal.parameter_id)
            if prior is None or prior.revision != proposal.base_revision:
                raise VersionConflictError("Proposal is stale; input parameter changed")
            if resolution.decision == ProposalDecision.APPROVE:
                if proposal.parameter_id not in context.approved_parameter_ids:
                    raise FixedInputWriteError(
                        "Proposal approval requires explicit parameter permission"
                    )
                if proposal.parameter_id in parameter_changes:
                    raise StateManagerError("Proposal conflicts with direct parameter change")
                record = proposal.proposed_record.model_copy(
                    deep=True,
                    update={
                        "status": ParameterStatus.CONFIRMED,
                        "confirmed_by": context.actor,
                    },
                )
                parameter_changes[proposal.parameter_id] = record
                confirmation_events.append(
                    ConfirmationEvent(
                        parameter_id=proposal.parameter_id,
                        confirmed_by=context.actor,
                        reason=f"Approved proposal {proposal.proposal_id}",
                    )
                )
            resolutions[resolution.proposal_id] = resolution
        confirmation_ids = {event.parameter_id for event in confirmation_events}
        role_changes = {change.parameter_id: change for change in patch.role_changes}
        if confirmation_events:
            if context.kind != WriterKind.USER:
                raise StateManagerError("Confirmation events require a trusted user context")
            if any(event.confirmed_by != context.actor for event in confirmation_events):
                raise StateManagerError("Confirmation actor mismatch")
            if not confirmation_ids <= set(parameter_changes):
                raise StateManagerError(
                    "Each confirmation event must accompany the corresponding parameter change"
                )
            if any(
                parameter_changes[key].status != ParameterStatus.CONFIRMED
                for key in confirmation_ids
            ):
                raise StateManagerError("Confirmation events require CONFIRMED parameter changes")
            if len(confirmation_ids) != len(confirmation_events):
                raise StateManagerError("Duplicate confirmation events")
        if role_changes:
            if len(role_changes) != len(patch.role_changes):
                raise StateManagerError("Duplicate role changes")
            if context.kind != WriterKind.USER or not set(role_changes) <= set(parameter_changes):
                raise StateManagerError("Role changes require user approval and parameter changes")
            for key, change in role_changes.items():
                old = current.parameters.get(key)
                if (
                    old is None or old.role != change.from_role
                    or parameter_changes[key].role != change.to_role
                    or change.approved_by != context.actor
                ):
                    raise StateManagerError(f"Invalid approved role change for {key!r}")
        for key, proposed in parameter_changes.items():
            record = proposed.model_copy(deep=True)
            if record.parameter_id is not None and record.parameter_id != key:
                raise StateManagerError(
                    f"Parameter ID {record.parameter_id!r} does not match key {key!r}"
                )
            record.parameter_id = key
            old = updated.parameters.get(key)
            trusted_ref = context.verified_parameter_refs.get(key)
            if trusted_ref is None and context.kind == WriterKind.USER:
                # A directly authenticated user input is trusted by the API boundary.
                trusted_ref = f"user-input:{design_id}:{expected_version + 1}:{key}"
            unchanged_value = bool(
                old and old.value == record.value and old.unit == record.unit
                and old.role == record.role
                and old.applies_to_case == record.applies_to_case
            )
            if record.verified_source_ref is not None and (
                old is None or record.verified_source_ref != old.verified_source_ref
            ):
                raise StateManagerError(
                    f"Verified source for {key!r} cannot come from the patch"
                )
            if (
                old and old.verified_source_ref is not None
                and old.role in {ParameterRole.FIXED_INPUT, ParameterRole.HARD_CONSTRAINT}
                and (
                    not unchanged_value or old.status != record.status
                )
                and (context.kind != WriterKind.USER
                     or key not in context.approved_parameter_ids)
            ):
                raise FixedInputWriteError(
                    f"Verified input {key!r} requires user approval to change"
                )
            if record.status == ParameterStatus.PROVIDED and record.role in {
                ParameterRole.FIXED_INPUT, ParameterRole.HARD_CONSTRAINT
            } and not (trusted_ref or (unchanged_value and old.verified_source_ref)):
                raise StateManagerError(
                    f"External input {key!r} requires a verified source before PROVIDED"
                )
            if record.status != ParameterStatus.CONFIRMED and record.confirmed_by is not None:
                raise StateManagerError(
                    f"Parameter {key!r} cannot have confirmed_by without CONFIRMED status"
                )
            if context.kind == WriterKind.AGENT and record.confirmed_by is not None:
                raise StateManagerError("Agents cannot write user confirmation identity")
            # A user-confirmed DESIGN_VARIABLE is as authoritative as fixed inputs.
            # Agents may submit a ParameterChangeProposal instead of replacing it.
            if old and old.status == ParameterStatus.CONFIRMED:
                if context.kind != WriterKind.USER:
                    raise FixedInputWriteError(
                        f"Confirmed parameter {key!r} cannot be changed by an agent"
                    )
                if (
                    old.value != record.value or old.unit != record.unit
                    or old.role != record.role or old.status != record.status
                    or old.applies_to_case != record.applies_to_case
                ) and key not in context.approved_parameter_ids:
                    raise FixedInputWriteError(
                        f"Confirmed parameter {key!r} requires explicit user approval"
                    )
            if record.status == ParameterStatus.CONFIRMED:
                if context.kind != WriterKind.USER or key not in confirmation_ids:
                    raise StateManagerError(
                        f"Parameter {key!r} requires an explicit user confirmation command"
                    )
            if old and old.role != record.role:
                change = role_changes.get(key)
                if (
                    context.kind != WriterKind.USER
                    or change is None
                    or change.from_role != old.role
                    or change.to_role != record.role
                    or change.approved_by != context.actor
                ):
                    raise StateManagerError(f"Role change for {key!r} requires user approval")
                changed.add(f"parameter_role:{key}")
            if (
                old
                and old.role in {ParameterRole.FIXED_INPUT, ParameterRole.HARD_CONSTRAINT}
                and (
                    old.value != record.value or old.unit != record.unit
                    or old.applies_to_case != record.applies_to_case
                    or (old.status == ParameterStatus.CONFIRMED and record.status != old.status)
                )
                and (
                    context.kind != WriterKind.USER
                    or key not in context.approved_parameter_ids
                )
            ):
                raise FixedInputWriteError(
                    f"Modification of locked parameter {key!r} is not authorized"
                )
            if record.status == ParameterStatus.CONFIRMED:
                confirmation = next(e for e in confirmation_events if e.parameter_id == key)
                if (
                    confirmation.confirmed_by != context.actor
                    or record.confirmed_by not in {None, confirmation.confirmed_by}
                ):
                    raise StateManagerError(f"Confirmation actor mismatch for {key!r}")
                record.confirmed_by = confirmation.confirmed_by
            if record.source is None:
                record.source = patch.source
            if context.kind == WriterKind.AGENT and trusted_ref is not None:
                if record.source_ref is not None and record.source_ref != trusted_ref:
                    raise StateManagerError(
                        f"Source reference for {key!r} disagrees with trusted evidence"
                    )
                record.source_ref = trusted_ref
            # Provenance is computed at the trusted write boundary rather than
            # accepted from source/source_ref strings supplied by an Agent.
            record.verified_source_ref = (
                trusted_ref
                or (old.verified_source_ref if unchanged_value else None)
            )
            try:
                self.parameter_registry.validate_record(key, record)
            except ParameterSchemaError as exc:
                raise StateManagerError(str(exc)) from exc
            record.revision = (old.revision + 1) if old else 1
            if key not in confirmation_ids and key in updated.confirmations:
                del updated.confirmations[key]
                changed.add("confirmations")
            updated.parameters[key] = record
            changed.add(key)
        for constraint in patch.constraint_changes:
            self._validate_constraint(constraint)
            existing = next(
                (item for item in updated.constraints if item.id == constraint.id), None
            )
            if context.kind == WriterKind.AGENT and (
                constraint.severity.value == "HARD"
                or constraint.origin.strip().casefold() == "user"
            ):
                raise StateManagerError(
                    "Agents may submit only non-user-origin SOFT or INFO constraints"
                )
            requires_approval = bool(
                existing and (existing.approved or existing.severity.value == "HARD")
            )
            if constraint.approved and (
                context.kind != WriterKind.USER
                or constraint.id not in context.approved_constraint_ids
            ):
                raise StateManagerError(
                    f"Constraint {constraint.id!r} approval requires a trusted user context"
                )
            if existing and existing != constraint and (
                context.kind != WriterKind.USER
                or (requires_approval and constraint.id not in context.approved_constraint_ids)
            ):
                raise StateManagerError(
                    f"Constraint {constraint.id!r} requires user approval to change"
                )
            if existing:
                constraint = constraint.model_copy(update={"revision": existing.revision + 1})
                updated.constraints = [
                    constraint if item.id == constraint.id else item for item in updated.constraints
                ]
            else:
                updated.constraints.append(
                    constraint.model_copy(update={"revision": 1})
                )
            changed.add("constraints")
            changed.add(f"constraint:{constraint.id}")
        for operating_case in patch.operating_case_changes:
            if operating_case.verified_source_ref is not None:
                existing_verified = next(
                    (item for item in updated.operating_cases
                     if item.case_id == operating_case.case_id),
                    None,
                )
                if (existing_verified is None or
                    operating_case.verified_source_ref !=
                    existing_verified.verified_source_ref):
                    raise StateManagerError(
                        "Verified operating-case source cannot come from the patch"
                    )
            if operating_case.confirmed_by is not None and (
                context.kind != WriterKind.USER
                or operating_case.confirmed_by != context.actor
            ):
                raise StateManagerError(
                    "Only the trusted user may confirm operating-case conditions"
                )
            existing_case = next(
                (
                    item
                    for item in updated.operating_cases
                    if item.case_id == operating_case.case_id
                ),
                None,
            )
            if existing_case and existing_case.confirmed_by is not None:
                if context.kind != WriterKind.USER:
                    raise StateManagerError(
                        "Confirmed operating case cannot be overwritten by an agent"
                    )
                if operating_case.confirmed_by != context.actor:
                    raise StateManagerError(
                        "Changing a confirmed operating case requires user reconfirmation"
                    )
            trusted_case_ref = context.verified_case_refs.get(operating_case.case_id)
            if trusted_case_ref is None and context.kind == WriterKind.USER:
                trusted_case_ref = (
                    f"user-case:{design_id}:{expected_version + 1}:{operating_case.case_id}"
                )
            same_conditions = bool(
                existing_case
                and existing_case.journal_diameter_ref == operating_case.journal_diameter_ref
                and existing_case.load_ref == operating_case.load_ref
                and existing_case.speed_ref == operating_case.speed_ref
                and existing_case.load_direction == operating_case.load_direction
                and existing_case.is_steady_state == operating_case.is_steady_state
            )
            if (existing_case and existing_case.verified_source_ref
                and not same_conditions
                and context.kind != WriterKind.USER):
                raise StateManagerError(
                    "Verified operating case cannot be overwritten by an agent"
                )
            operating_case = operating_case.model_copy(
                update={
                    "revision": existing_case.revision + 1 if existing_case else 1,
                    "verified_source_ref": (
                        trusted_case_ref
                        or (existing_case.verified_source_ref
                            if same_conditions else None)
                    ),
                }
            )
            updated.operating_cases = [
                item for item in updated.operating_cases if item.case_id != operating_case.case_id
            ]
            updated.operating_cases.append(operating_case)
            changed.add(f"operating_case:{operating_case.case_id}")
            changed.add("operating_cases")
        if len(updated.operating_cases) > 1:
            raise StateManagerError("V1 supports only one operating case")
        if patch.candidate_additions:
            changed.add("candidate_designs")
        if confirmation_events:
            updated.confirmations.update(
                {
                    event.parameter_id: {
                        "confirmed_by": event.confirmed_by,
                        "reason": event.reason,
                    }
                    for event in confirmation_events
                }
            )
            changed.add("confirmations")
        # Pending proposals are inert: they never change authoritative parameters.
        incoming_ids = [p.proposal_id for p in patch.parameter_change_proposals]
        if len(set(incoming_ids)) != len(incoming_ids):
            raise StateManagerError("Duplicate new proposal IDs")
        known_ids = {p.proposal_id for p in updated.parameter_change_proposals}
        for proposal in patch.parameter_change_proposals:
            if proposal.proposal_id in known_ids:
                raise StateManagerError("Duplicate proposal ID")
            prior = current.parameters.get(proposal.parameter_id)
            if prior is None or prior.revision != proposal.base_revision:
                raise VersionConflictError("Proposal does not match the current parameter")
            if (proposal.status != ProposalStatus.PENDING or proposal.resolved_by is not None
                or proposal.resolved_at_version is not None):
                raise StateManagerError("Proposals must start PENDING and unresolved")
            if (proposal.proposed_record.role != prior.role
                or proposal.proposed_record.status != ParameterStatus.SUGGESTED):
                raise StateManagerError(
                    "Proposals must preserve the parameter role and use SUGGESTED status"
                )
            try:
                self.parameter_registry.validate_record(
                    proposal.parameter_id, proposal.proposed_record
                )
            except ParameterSchemaError as exc:
                raise StateManagerError(str(exc)) from exc
            updated.parameter_change_proposals.append(
                proposal.model_copy(
                    update={
                        "proposed_by": context.actor or patch.source,
                    }
                )
            )
            known_ids.add(proposal.proposal_id)
            changed.add("parameter_change_proposals")
        for index, proposal in enumerate(updated.parameter_change_proposals):
            resolution = resolutions.get(proposal.proposal_id)
            if resolution is not None:
                new_status = (
                    ProposalStatus.APPROVED
                    if resolution.decision == ProposalDecision.APPROVE
                    else ProposalStatus.REJECTED
                )
                updated.parameter_change_proposals[index] = proposal.model_copy(
                    update={
                        "status": new_status,
                        "resolved_by": context.actor,
                        "resolved_at_version": expected_version + 1,
                    }
                )
                changed.add("parameter_change_proposals")
            elif (
                proposal.status == ProposalStatus.PENDING
                and proposal.parameter_id in parameter_changes
            ):
                updated.parameter_change_proposals[index] = proposal.model_copy(
                    update={
                        "status": ProposalStatus.STALE,
                        "resolved_at_version": expected_version + 1,
                    }
                )
                changed.add("parameter_change_proposals")
        if patch.rule_set_change is not None:
            if context.kind == WriterKind.AGENT:
                raise StateManagerError("Rule set changes require a trusted user or system context")
            updated.knowledge_rule_set_version = patch.rule_set_change.version
            changed.add("knowledge_rule_set_version")
        next_version = expected_version + 1
        updated.state_version = next_version
        invalidated = invalidate_dependents(updated, changed)
        # New candidates are evaluated against this patch's final inputs. They must
        # not be invalidated by the very change that creates them.
        for candidate in patch.candidate_additions:
            if (candidate.confirmation_status != ConfirmationStatus.PENDING
                or candidate.precheck_status != PrecheckStatus.NOT_EVALUATED
                or candidate.simulation_status != SimulationStatus.NOT_REQUESTED
                or candidate.precheck_history):
                raise StateManagerError(
                    "New candidates must start PENDING, NOT_EVALUATED, and NOT_REQUESTED"
                )
            for parameter_id, record in candidate.parameters.items():
                if (
                    record.status == ParameterStatus.CONFIRMED
                    or record.confirmed_by is not None
                    or record.verified_source_ref is not None
                ):
                    raise StateManagerError(
                        f"Candidate parameter {parameter_id!r} cannot claim user confirmation "
                        "or trusted source evidence; confirm inputs in DesignState first"
                    )
                if context.kind == WriterKind.AGENT and record.status == ParameterStatus.PROVIDED:
                    raise StateManagerError(
                        f"Agent candidate parameter {parameter_id!r} cannot claim PROVIDED status"
                    )
            if any(existing.candidate_id == candidate.candidate_id
                   and existing.version == candidate.version
                   for existing in updated.candidate_designs):
                raise StateManagerError("Duplicate candidate version")
            updated.candidate_designs.append(
                _snapshot_candidate_dependencies(candidate, updated)
            )
        event = StateEvent(
            design_id=design_id,
            from_version=expected_version,
            to_version=next_version,
            changed_fields=sorted(changed),
            source=patch.source,
            actor=context.actor,
            occurred_at=datetime.now(UTC),
            details={
                "writer_kind": context.kind.value,
                "invalidated_objects": invalidated.invalidated_objects,
                "confirmation_events": [
                    e.model_dump(mode="json") for e in confirmation_events
                ],
                "role_changes": [e.model_dump(mode="json") for e in patch.role_changes],
                "proposal_resolutions": [
                    e.model_dump(mode="json") for e in patch.proposal_resolutions
                ],
                "rule_set_change": (
                    patch.rule_set_change.model_dump(mode="json") if patch.rule_set_change else None
                ),
            },
        )
        updated.state_version = next_version
        updated.event_history.append(event)
        updated.event_log_refs.append(event.event_id)
        updated = self._validate_state(updated)
        self.repository.save(updated, expected_version)
        return updated

    def resolve_parameter_proposal(
        self,
        design_id: str,
        expected_version: int,
        proposal_id: str,
        *,
        approve: bool,
        context: WriteContext,
    ) -> DesignState:
        if context.kind != WriterKind.USER or not context.actor:
            raise StateManagerError("Proposal resolution requires trusted USER context")
        return self.apply_patch(
            design_id,
            expected_version,
            StatePatch(
                source="user",
                actor=context.actor,
                proposal_resolutions=[
                    ProposalResolution(
                        proposal_id=proposal_id,
                        decision=ProposalDecision.APPROVE if approve else ProposalDecision.REJECT,
                    )
                ],
            ),
            context=context,
        )

    def confirm_parameter(
        self,
        design_id: str,
        expected_version: int,
        parameter_id: str,
        *,
        context: WriteContext,
        reason: str | None = None,
    ) -> DesignState:
        if context.kind != WriterKind.USER or not context.actor:
            raise StateManagerError("Trusted USER context required for confirmation")
        actor = context.actor
        current = self.get_design(design_id)
        record = current.parameters.get(parameter_id)
        if record is None:
            raise StateManagerError(f"Unknown parameter: {parameter_id}")
        return self.apply_patch(
            design_id,
            expected_version,
            StatePatch(
                source="user",
                actor=actor,
                parameter_changes={
                    parameter_id: record.model_copy(
                        update={"status": ParameterStatus.CONFIRMED, "confirmed_by": actor}
                    )
                },
                confirmation_events=[
                    ConfirmationEvent(parameter_id=parameter_id, confirmed_by=actor, reason=reason)
                ],
            ),
            context=context,
        )

    def change_parameter_role(
        self,
        design_id: str,
        expected_version: int,
        parameter_id: str,
        to_role: ParameterRole,
        *,
        context: WriteContext,
    ) -> DesignState:
        if context.kind != WriterKind.USER or not context.actor:
            raise StateManagerError("Trusted USER context required for role changes")
        actor = context.actor
        current = self.get_design(design_id)
        record = current.parameters.get(parameter_id)
        if record is None:
            raise StateManagerError(f"Unknown parameter: {parameter_id}")
        return self.apply_patch(
            design_id,
            expected_version,
            StatePatch(
                source="user",
                actor=actor,
                parameter_changes={
                    parameter_id: record.model_copy(
                        update={
                            "role": to_role,
                            # A role change changes the meaning of the value; the old
                            # confirmation must be reviewed again by the user.
                            "status": (
                                ParameterStatus.SUGGESTED
                                if record.status == ParameterStatus.CONFIRMED
                                else record.status
                            ),
                            "confirmed_by": None,
                        }
                    )
                },
                role_changes=[
                    RoleChange(
                        parameter_id=parameter_id,
                        from_role=record.role,
                        to_role=to_role,
                        approved_by=actor,
                    )
                ],
            ),
            context=context,
        )

    def get_quantity(
        self, design_id: str, parameter_id: str, target_unit: str,
        *, allow_suggested: bool = False,
    ) -> float:
        """Read a valid quantity; opt in to provisional design suggestions explicitly."""
        record = self.get_design(design_id).parameters.get(parameter_id)
        valid_statuses = {ParameterStatus.PROVIDED, ParameterStatus.CONFIRMED}
        if allow_suggested:
            valid_statuses.add(ParameterStatus.SUGGESTED)
        if (
            record is None or record.value is None or record.unit is None
            or record.status not in valid_statuses
        ):
            raise StateManagerError(f"Parameter {parameter_id!r} has no usable quantity")
        if (
            record.role in {ParameterRole.FIXED_INPUT, ParameterRole.HARD_CONSTRAINT}
            and not (record.verified_source_ref or (
                record.status == ParameterStatus.CONFIRMED and record.confirmed_by
            ))
        ):
            raise StateManagerError(
                f"External input {parameter_id!r} has no trusted source evidence"
            )
        if record.status == ParameterStatus.CONFIRMED and not record.confirmed_by:
            raise StateManagerError(
                f"Parameter {parameter_id!r} lacks trusted user confirmation"
            )
        try:
            return self.parameter_registry.convert(
                parameter_id, record.value, record.unit, target_unit
            )
        except ParameterSchemaError as exc:
            raise StateManagerError(str(exc)) from exc

    def readiness_for(self, design_id: str, stage: str) -> ReadinessResult:
        return readiness_for(
            self.get_design(design_id), stage, self.stage_registry,
            parameter_registry=self.parameter_registry,
        )

    def list_missing_for(self, design_id: str, stage: str) -> list[ParameterRecord]:
        state = self.get_design(design_id)
        readiness = self.readiness_for(design_id, stage)
        if not readiness.not_configured:
            return readiness.missing
        return [
            record
            for record in state.parameters.values()
            if record.status == ParameterStatus.MISSING and stage in record.required_for
        ]

    def _validate_constraint(self, constraint: ConstraintRecord) -> None:
        if self.parameter_registry.get(constraint.parameter) is None:
            raise StateManagerError(
                f"Unknown constrained parameter: {constraint.parameter!r}"
            )
        targets = (
            constraint.target
            if isinstance(constraint.target, (list, tuple, set, frozenset))
            else (constraint.target,)
        )
        for target in targets:
            try:
                self.parameter_registry.validate(
                    constraint.parameter, target, constraint.unit
                )
            except ParameterSchemaError as exc:
                raise StateManagerError(str(exc)) from exc

    def _validate_state(self, state: DesignState) -> DesignState:
        try:
            state = DesignState.model_validate(state.model_dump())
            for key, record in state.parameters.items():
                self.parameter_registry.validate_record(key, record)
            if len(state.operating_cases) > 1:
                raise StateManagerError("V1 supports only one operating case")
            for candidate in state.candidate_designs:
                for key, record in candidate.parameters.items():
                    self.parameter_registry.validate_record(key, record)
            for constraint in state.constraints:
                self._validate_constraint(constraint)
        except (ValidationError, ParameterSchemaError) as exc:
            raise StateManagerError(str(exc)) from exc
        return state

    def invalidate_dependents(
        self, design_id: str, changed_fields: set[str], expected_version: int
    ) -> tuple[DesignState, InvalidationResult]:
        current = self.get_design(design_id)
        if current.state_version != expected_version:
            raise VersionConflictError(
                f"Expected version {expected_version}, current version is {current.state_version}"
            )
        updated = current.model_copy(deep=True)
        updated.state_version += 1
        result = invalidate_dependents(updated, changed_fields)
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
        updated = self._validate_state(updated)
        self.repository.save(updated, expected_version)
        return updated, result
