"""Trusted local interaction boundary; extraction never grants its own privileges."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from bearing_agents.core.state_manager import StateManager, StateManagerError, VersionConflictError
from bearing_agents.domain.agent_protocols import StatePatch
from bearing_agents.domain.enums import (
    ConstraintOperator,
    ConstraintSeverity,
    ParameterRole,
    ParameterStatus,
)
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import StateConflictError
from bearing_agents.requirements.contracts import InteractionReceipt, UserTurn
from bearing_agents.requirements.evidence import verify
from bearing_agents.requirements.extraction import extract
from bearing_agents.requirements.questions import build_view


class InteractionService:
    """Offline trusted USER adapter, not a network authentication service."""

    def __init__(self, manager: StateManager, actor: str, extractor=None):
        if not actor or not actor.strip():
            raise ValueError("A nonempty trusted local actor is required")
        self.manager = manager
        self.actor = actor
        self.extractor = extractor or extract

    def create_design(self, goal: str | None = None):
        # PR-01 default is intentionally unchanged for existing callers.
        # New language-first workflows begin outside the established design scope.
        return self.manager.create_design(user_goal=goal, target_scope="unknown")

    def show_state(self, design_id: str):
        return build_view(self.manager, design_id)

    def resume_session(self, design_id: str):
        return self.show_state(design_id)

    def submit_turn(self, design_id: str, content: str, operation_id: str):
        """Return a persisted receipt and a fresh view.

        The immutable message is committed before extraction. The verified
        state+event+receipt is committed atomically; a failure is retryable.
        """
        if not content.strip() or not operation_id.strip():
            raise ValueError("A nonempty user turn and operation ID are required")
        repo = self.manager.repository
        self.manager.get_design(design_id)  # Fail for an unknown design.
        intent = hashlib.sha256(
            repr(("turn", design_id, self.actor, operation_id, content)).encode("utf-8")
        ).hexdigest()
        prior=repo.get_interaction_receipt(operation_id, design_id, intent)
        if prior:
            return prior, self.show_state(design_id)
        message=UserTurn(
            operation_id=operation_id, message_id=str(uuid4()),
            design_id=design_id, actor=self.actor, received_at=datetime.now(UTC),
            content=content, content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        message=repo.save_user_message(message,intent)
        # Proposals cannot name a trusted message. Bind them to the immutable stored turn.
        verified=[verify(message.content,p,self.manager.parameter_registry)
                  for p in self.extractor(message.content)]
        accepted=[v for v in verified if v.decision=="ACCEPT"]
        uncertain=[v.reason for v in verified if v.decision!="ACCEPT"]
        changes={}
        constraints=[]
        scope=None
        steady=None
        # Two explicit claims for the same parameter require clarification;
        # never silently take the last value.
        counts={}
        for v in accepted:
            if v.proposal.kind=="parameter":
                key=v.proposal.field_id
                counts[key]=counts.get(key,0)+1
        if any(n>1 for n in counts.values()):
            uncertain.append("同一个参数出现多个数值，请明确最终数值。")
        current=self.manager.get_design(design_id)
        for v in accepted:
            p=v.proposal
            if p.kind=="parameter":
                if counts[p.field_id]>1:
                    continue
                old=current.parameters.get(p.field_id)
                if old is not None and old.value is not None:
                    # Existing user inputs are changed by explicit revision-bound correction only.
                    if old.value != v.normalized_value or old.unit != v.normalized_unit:
                        uncertain.append(f"{p.field_id} 已存在；请使用明确的纠错操作。")
                    continue
                changes[p.field_id]={
                    "value":v.normalized_value,"unit":v.normalized_unit,
                    "role":ParameterRole.FIXED_INPUT,"status":ParameterStatus.PROVIDED,
                    "source":"user","source_ref":message.message_id,
                }
            elif p.kind=="scope":
                scope=p.value
            elif p.kind=="steady_state":
                steady=(p.value=="true")
            elif p.kind=="constraint":
                # Keep user-declared boundaries inert until explicit approval.
                constraints.append({
                    "id":f"msg:{message.message_id}:constraint:{p.field_id}",
                    "parameter":p.field_id,"operator":ConstraintOperator(p.operator),
                    "target":v.normalized_value,"unit":v.normalized_unit,
                    "severity":ConstraintSeverity.HARD,"origin":"user",
                    "approved":False,
                })
        if scope and scope not in {"cylindrical_radial_hydrodynamic","unsupported"}:
            scope=None
        if current.target_scope=="unsupported" and scope=="cylindrical_radial_hydrodynamic":
            uncertain.append("更改已判定的轴承范围需要人工复核。")
            scope=None
        if steady is False:
            scope="unsupported"
        cases=[]
        if steady is True and current.target_scope!="unsupported":
            if any(c.is_steady_state is False for c in current.operating_cases):
                uncertain.append("现有工况不是稳态，请先明确更正。")
            else:
                cases=[{
                    "case_id":"nominal","is_steady_state":True,
                    "journal_diameter_ref":"journal_diameter",
                    "load_ref":"load","speed_ref":"rotational_speed",
                }]
        patch=StatePatch.model_validate({
            "source":"user","actor":self.actor,"parameter_changes":changes,
            "constraint_changes":constraints,"operating_case_changes":cases,
            "scope_change":scope,
        })
        context=WriteContext(
            kind=WriterKind.USER,actor=self.actor,
            verified_parameter_refs={k:message.message_id for k in changes},
            verified_case_refs={"nominal":message.message_id} if cases else {},
        )
        # If the operation has already committed, get its receipt before CAS.
        prior=repo.get_interaction_receipt(operation_id,design_id,intent)
        if prior:
            return prior,self.show_state(design_id)
        try:
            committed=self.manager.apply_patch(
                design_id,current.state_version,patch,context=context,
                interaction=(operation_id,intent,message.message_id),
            )
        except (VersionConflictError,StateConflictError):
            # Another thread may have completed this exact operation.
            prior=repo.get_interaction_receipt(operation_id,design_id,intent)
            if prior:
                return prior,self.show_state(design_id)
            raise
        receipt=InteractionReceipt(
            operation_id=operation_id,design_id=design_id,
            message_id=message.message_id,state_version=committed.state_version,
        )
        return receipt,build_view(self.manager,design_id,uncertain)

    def correct_parameter(
        self, design_id: str, parameter_id: str, revision: int,
        replacement: str, operation_id: str,
    ):
        """Revision-bound explicit correction; old evidence stays in StateEvent."""
        if not replacement.strip():
            raise ValueError("Replacement evidence must not be empty")
        repo=self.manager.repository
        intent=hashlib.sha256(repr(
            ("correction",design_id,self.actor,parameter_id,revision,replacement,operation_id)
        ).encode("utf-8")).hexdigest()
        prior=repo.get_interaction_receipt(operation_id,design_id,intent)
        if prior:
            return prior,self.show_state(design_id)
        existing=self.manager.get_design(design_id)
        old=existing.parameters.get(parameter_id)
        if old is None or old.revision!=revision:
            raise VersionConflictError("Parameter revision has changed")
        message=UserTurn(
            operation_id=operation_id,message_id=str(uuid4()),
            design_id=design_id,actor=self.actor,received_at=datetime.now(UTC),
            content=replacement,content_sha256=hashlib.sha256(
                replacement.encode("utf-8")
            ).hexdigest(),
        )
        message=repo.save_user_message(message,intent)
        verified=[verify(message.content,p,self.manager.parameter_registry)
                  for p in self.extractor(message.content) if p.kind=="parameter"
                  and p.field_id==parameter_id]
        accepted=[v for v in verified if v.decision=="ACCEPT"]
        if len(accepted)!=1:
            raise StateManagerError("Correction requires one explicit verified value")
        value=accepted[0]
        record=old.model_copy(deep=True,update={
            "value":value.normalized_value,"unit":value.normalized_unit,
            "status":ParameterStatus.PROVIDED,"confirmed_by":None,
            "verified_source_ref":None,"source":"user","source_ref":message.message_id,
        })
        context=WriteContext(kind=WriterKind.USER,actor=self.actor,
            approved_parameter_ids=frozenset({parameter_id}),
            verified_parameter_refs={parameter_id:message.message_id})
        updated=self.manager.apply_patch(
            design_id,existing.state_version,
            StatePatch(source="user",actor=self.actor,parameter_changes={parameter_id:record}),
            context=context,interaction=(operation_id,intent,message.message_id),
        )
        return InteractionReceipt(operation_id=operation_id,design_id=design_id,
            message_id=message.message_id,state_version=updated.state_version),self.show_state(design_id)

    def confirm_parameter(self,design_id: str,parameter_id: str,revision: int):
        state=self.manager.get_design(design_id)
        record=state.parameters.get(parameter_id)
        if record is None or record.revision!=revision:
            raise VersionConflictError("Confirmation target is stale")
        return self.manager.confirm_parameter(
            design_id,state.state_version,parameter_id,
            context=WriteContext(kind=WriterKind.USER,actor=self.actor,
                approved_parameter_ids=frozenset({parameter_id})),
            reason="Explicit revision-bound CLI confirmation",
        )

    def approve_constraint(self,design_id: str,constraint_id: str,revision: int):
        state=self.manager.get_design(design_id)
        constraint=next((c for c in state.constraints if c.id==constraint_id),None)
        if constraint is None or constraint.revision!=revision or constraint.approved:
            raise VersionConflictError("Constraint is missing, stale or already approved")
        return self.manager.apply_patch(
            design_id,state.state_version,
            StatePatch(source="user",actor=self.actor,
                       constraint_changes=[constraint.model_copy(update={"approved":True})]),
            context=WriteContext(kind=WriterKind.USER,actor=self.actor,
                approved_constraint_ids=frozenset({constraint_id})),
        )

    def reject_proposal(self, design_id: str, proposal_id: str):
        state=self.manager.get_design(design_id)
        return self.manager.resolve_parameter_proposal(
            design_id,state.state_version,proposal_id,approve=False,
            context=WriteContext(kind=WriterKind.USER,actor=self.actor),
        )
