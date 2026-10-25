"""Serial, bounded LangGraph execution with idempotent task effects only."""

from contextlib import contextmanager
from inspect import Parameter
from inspect import signature as inspect_signature
from uuid import uuid4

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from bearing_agents.core.state_manager import StateManager, StateManagerError, VersionConflictError
from bearing_agents.domain.agent_protocols import PlanDecision, TaskRecord
from bearing_agents.domain.enums import TaskStatus
from bearing_agents.domain.tasks import TaskCommand, engineering_digest, fingerprint
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import StateConflictError
from bearing_agents.orchestration.contracts import (
    CATALOG,
    FakeAgent,
    FakePlanner,
    GraphState,
    PlannerContext,
    observe_state,
    policy_guard,
    target_exists,
    validate_result,
)

SYSTEM = WriteContext(kind=WriterKind.SYSTEM, actor="pr02-runtime")


class Runtime:
    def __init__(
        self, manager: StateManager, checkpointer, *, planner=None, agents=None,
        max_steps=12, max_same_action=3, max_errors=3, catalog=None,
    ):
        if min(max_steps, max_same_action, max_errors) < 1:
            raise ValueError("Budgets must be positive")
        self.manager = manager
        self.planner = planner or FakePlanner()
        self.catalog = dict(CATALOG if catalog is None else catalog)
        self.agents = dict(agents) if agents is not None else {
            spec.executor_id: FakeAgent() for spec in self.catalog.values()
            if spec.effect_class == "READ_ONLY"
        }
        self.max_steps, self.max_same_action, self.max_errors = (
            max_steps, max_same_action, max_errors,
        )
        builder = StateGraph(GraphState)
        for name in ("observe", "plan", "guard", "prepare", "execute", "wait_user"):
            builder.add_node(name, getattr(self, f"_{name}"))
        builder.add_edge(START, "observe")
        builder.add_conditional_edges("observe", self._continue, {"next": "plan", "end": END})
        builder.add_conditional_edges("plan", self._continue, {"next": "guard", "end": END})
        builder.add_conditional_edges("guard", self._after_guard,
                                      {"next": "prepare", "retry": "observe", "end": END})
        builder.add_conditional_edges("prepare", self._after_prepare,
                                      {"next": "execute", "retry": "observe", "end": END})
        builder.add_conditional_edges("execute", self._after_execute,
                                      {"next": "observe", "wait": "wait_user", "end": END})
        builder.add_conditional_edges("wait_user", self._continue,
                                      {"next": "observe", "end": END})
        self.graph = builder.compile(checkpointer=checkpointer)

    def _config(self, design_id):
        state = self.manager.get_design(design_id)
        return {"configurable": {"thread_id": state.thread_id or f"pr02:{design_id}"},
                "recursion_limit": max(100, self.max_steps * 8 + 20)}

    def invoke(self, design_id, *, goal="demo", target_ref=None):
        config = self._config(design_id)
        previous = self.graph.get_state(config)
        if previous.values and previous.values["design_id"] != design_id:
            raise PermissionError("Checkpoint thread is bound to another design")
        if previous.next:
            raise ValueError("An unfinished run exists; use resume() or recover()")
        return self._output(self.graph.invoke({
            "design_id": design_id, "thread_id": config["configurable"]["thread_id"],
            "run_id": str(uuid4()), "goal": goal, "target_ref": target_ref,
            "steps": 0, "errors": 0, "same_action_count": 0, "last_signature": "",
            "termination_reason": None, "confirmation": None, "trace": [],
            "current_task_id": "", "last_result_ref": "",
        }, config, durability="sync"))

    @staticmethod
    def _output(result):
        if result.get("__interrupt__"):
            return dict(result, termination_reason="WAITING_FOR_USER")
        return result

    def recover(self, design_id):
        config = self._config(design_id)
        snapshot = self.graph.get_state(config)
        if snapshot.values and snapshot.values["design_id"] != design_id:
            raise PermissionError("Checkpoint thread is bound to another design")
        if not snapshot.values:
            raise ValueError("No persistent run to recover")
        if not snapshot.next:
            return snapshot.values
        return self._output(self.graph.invoke(None, config, durability="sync"))

    @staticmethod
    def _continue(state):
        return "end" if state.get("termination_reason") else "next"

    def _after_guard(self, state):
        if state.get("termination_reason"):
            return "end"
        return "retry" if state["trace"][-1].get("guard") == "BLOCK" else "next"

    def _after_prepare(self, state):
        if state.get("termination_reason"):
            return "end"
        return "retry" if state["trace"][-1].get("stage") == "conflict" else "next"

    def _after_execute(self, state):
        if state.get("termination_reason"):
            return "end"
        return "wait" if state.get("confirmation") else "next"

    @staticmethod
    def _trace(state, **entry):
        return [*state.get("trace", []), entry]

    @staticmethod
    def _decision(state):
        return PlanDecision(
            action=state["action"], selected_agent=state["executor"],
            rationale=state["rationale"], expected_result="DEMO_ONLY",
            state_version=state["decision_version"],
            requires_confirmation=state.get("requires_confirmation", False),
            input_refs=state.get("input_refs", []),
        )

    def _observe(self, state):
        domain = self.manager.get_design(state["design_id"])
        reason = None
        if state["errors"] >= self.max_errors:
            reason = "TOOL_ERROR"
        elif state["steps"] >= self.max_steps:
            reason = "BUDGET_EXHAUSTED"
        return {"observed_domain_version": domain.state_version,
                "termination_reason": reason}

    def _plan(self, state):
        domain = self.manager.get_design(state["design_id"])
        summary = observe_state(domain, state["goal"], state["target_ref"])
        context = PlannerContext(
            action_descriptions=tuple(
                (name, spec.effect_class, spec.required_gate, spec.supported)
                for name, spec in sorted(self.catalog.items())
            ),
            recent_failures=tuple(
                str(row.get("reason") or row.get("error"))
                for row in state.get("trace", [])
                if row.get("stage") in {
                    "planner_error", "agent_error", "conflict", "dispatch_blocked",
                } or row.get("guard") == "BLOCK"
            )[-3:],
            remaining_steps=max(0, self.max_steps - state["steps"]),
            remaining_errors=max(0, self.max_errors - state["errors"]),
        )
        try:
            plan_method = self.planner.plan
            parameters = inspect_signature(plan_method).parameters.values()
            accepts_context = any(
                parameter.kind == Parameter.VAR_KEYWORD or parameter.name == "context"
                for parameter in parameters
            )
            proposed = (
                plan_method(summary, context=context)
                if accepts_context else plan_method(summary)
            )
            decision = PlanDecision.model_validate(
                proposed.model_dump() if isinstance(proposed, PlanDecision) else proposed,
            )
        except Exception as exc:
            return {"errors": state["errors"] + 1, "steps": state["steps"] + 1,
                    "termination_reason": "TOOL_ERROR",
                    "trace": self._trace(
                        state, stage="planner_error",
                        error=getattr(exc, "reason_code", type(exc).__name__),
                    )}
        signature = fingerprint([decision.action, summary.input_digest])
        repeats = state["same_action_count"] + 1 if signature == state["last_signature"] else 1
        return {
            "action": decision.action, "executor": decision.selected_agent,
            "rationale": decision.rationale, "decision_version": decision.state_version,
            "requires_confirmation": decision.requires_confirmation,
            "input_refs": decision.input_refs,
            "input_digest": summary.input_digest, "steps": state["steps"] + 1,
            "last_signature": signature, "same_action_count": repeats,
            "termination_reason": "NO_PROGRESS" if repeats >= self.max_same_action else None,
            "trace": self._trace(state, stage="plan", action=decision.action,
                                 domain_version=decision.state_version, reason=decision.rationale),
        }

    def _guard(self, state):
        domain = self.manager.get_design(state["design_id"])
        result = policy_guard(self._decision(state), domain, state["target_ref"], self.catalog)
        return {"trace": self._trace(
            state, stage="guard", action=state["action"], guard=result.verdict,
            reason=result.reason_code, domain_version=domain.state_version,
        )}

    def _task_command(
        self, state, kind, *, task=None, reason=None, output_ref=None, expected_version=None,
    ):
        command = TaskCommand(
            operation_id=f"{state['current_task_id']}:{kind}",
            task_id=state["current_task_id"], kind=kind, task=task,
            expected_input_digest=state["input_digest"],
            reason=reason or f"Offline {state['action']}: {kind}", output_ref=output_ref,
        )
        return self.manager.apply_task_command(
            state["design_id"], state["decision_version"]
            if expected_version is None else expected_version,
            command, context=SYSTEM,
        )

    def _expire_running_task(self, state, reason):
        """Make an unsafe or unretryable dispatch terminal without changing engineering data."""
        for _ in range(3):
            domain = self.manager.get_design(state["design_id"])
            task = next((item for item in domain.task_plan
                         if item.id == state["current_task_id"]), None)
            if task is None or task.status != TaskStatus.RUNNING:
                return
            command = TaskCommand(
                operation_id=f"{task.id}:expire:{fingerprint(reason)[:12]}",
                task_id=task.id, kind="expire",
                reason=reason,
            )
            try:
                self.manager.apply_task_command(
                    state["design_id"], domain.state_version, command, context=SYSTEM,
                )
                return
            except (VersionConflictError, StateConflictError):
                continue
        raise StateManagerError("Could not expire running task after 3 CAS attempts")

    def _completion_still_allowed(self, state, domain):
        if engineering_digest(domain) != state["input_digest"]:
            return False
        task = next((item for item in domain.task_plan
                     if item.id == state["current_task_id"]), None)
        if task is None or task.status != TaskStatus.RUNNING:
            return False
        decision = self._decision(state).model_copy(update={"state_version": domain.state_version})
        return policy_guard(decision, domain, state["target_ref"], self.catalog).verdict == "ALLOW"

    def _prepare(self, state):
        task_id = fingerprint([state["run_id"], state["steps"], state["action"],
                               state["input_digest"]])
        local = dict(state, current_task_id=task_id)
        record = TaskRecord(
            id=task_id, action=state["action"], agent=state["executor"],
            status=TaskStatus.PENDING, input_version=state["decision_version"],
        )
        try:
            registered = self._task_command(local, "register", task=record,
                                            reason=state["rationale"])
            receipt = self._task_command(local, "start", expected_version=registered.state_version)
        except (VersionConflictError, StateConflictError, StateManagerError) as exc:
            return {"errors": state["errors"] + 1,
                    "trace": self._trace(state, stage="conflict", reason=str(exc))}
        return {"current_task_id": task_id, "decision_version": receipt.state_version,
                "trace": self._trace(state, stage="task_started", task_id=task_id,
                                     domain_version=receipt.state_version)}

    def _execute(self, state):
        domain = self.manager.get_design(state["design_id"])
        prior = next((e for e in domain.event_history if e.details.get("operation_id")
                      == f"{state['current_task_id']}:complete"), None)
        if prior:
            receipt = self._task_command(state, "complete",
                                         output_ref=f"demo:{state['current_task_id']}")
            return self._completed(state, domain, receipt)
        waited = any(e.details.get("operation_id") == f"{state['current_task_id']}:wait"
                     for e in domain.event_history)
        # Bookkeeping advanced the CAS version. Check the action AND engineering digest again.
        guard = policy_guard(self._decision(state), domain, state["target_ref"], self.catalog)
        if not waited and (
            guard.verdict == "BLOCK" or engineering_digest(domain) != state["input_digest"]
        ):
            self._expire_running_task(
                state, f"VERSION_STALE: dispatch guard blocked ({guard.reason_code})",
            )
            return {"termination_reason": "VERSION_STALE",
                    "trace": self._trace(state, stage="dispatch_blocked", reason=guard.reason_code)}
        if waited or guard.verdict == "NEEDS_USER":
            request = {
                "request_id": f"{state['current_task_id']}:confirmation",
                "design_id": state["design_id"], "thread_id": state["thread_id"],
                "task_id": state["current_task_id"], "target_ref": state["target_ref"],
                "input_digest": state["input_digest"],
                "rule_set_version": domain.knowledge_rule_set_version,
            }
            receipt = self._task_command(state, "wait", output_ref=request["request_id"])
            return {"confirmation": request, "last_result_ref": receipt.event_id,
                    "trace": self._trace(state, stage="waiting", request_id=request["request_id"],
                                         domain_version=receipt.state_version)}
        try:
            task = next(t for t in domain.task_plan if t.id == state["current_task_id"])
            result = self.agents[state["executor"]].run(domain.model_copy(deep=True),
                                                        task.model_copy(deep=True))
            validate_result(result, task.id)
        except Exception as exc:
            # No engineering patch was committed. Record failure only if inputs are still current.
            try:
                self._task_command(state, "fail",
                                   reason=f"FakeAgent rejected: {type(exc).__name__}")
            except (StateManagerError, StateConflictError):
                self._expire_running_task(
                    state, "VERSION_STALE: agent failure could not be safely recorded",
                )
            return {"errors": state["errors"] + 1,
                    "trace": self._trace(state, stage="agent_error", reason=str(exc),
                                         demo_only=True)}

        receipt = None
        for _ in range(3):
            current = self.manager.get_design(state["design_id"])
            if not self._completion_still_allowed(state, current):
                break
            try:
                receipt = self._task_command(
                    state, "complete", output_ref=f"demo:{task.id}",
                    expected_version=current.state_version,
                )
                break
            except (VersionConflictError, StateConflictError):
                continue
        if receipt is None:
            self._expire_running_task(
                state,
                "VERSION_STALE: engineering inputs changed or task completion could not retry",
            )
            return {"termination_reason": "VERSION_STALE",
                    "trace": self._trace(state, stage="task_blocked", task_id=task.id,
                                         reason="VERSION_STALE")}
        return self._completed(state, domain, receipt)

    def _completed(self, state, domain, receipt):
        reason = {"clarify_requirement": "MISSING_INPUT", "produce_summary": "GOAL_REACHED",
                  "simulation_unavailable": "UNSUPPORTED_ACTION"}.get(state["action"])
        if domain.target_scope != "cylindrical_radial_hydrodynamic":
            reason = "UNSUPPORTED_ACTION"
        return {"last_result_ref": receipt.event_id, "termination_reason": reason,
                "trace": self._trace(state, stage="committed", action=state["action"],
                                     task_id=state["current_task_id"],
                                     operation_id=receipt.operation_id,
                                     domain_version=receipt.state_version,
                                     replayed=receipt.replayed,
                                     demo_only=True,
                                     simulation_status="NOT_AVAILABLE" if state["action"]
                                     == "simulation_unavailable" else None)}

    def _wait_user(self, state):
        # This node has NO writes before or after interrupt; authority stays in resume().
        interrupt(state["confirmation"])
        domain = self.manager.get_design(state["design_id"])
        task = next(t for t in domain.task_plan if t.id == state["confirmation"]["task_id"])
        if task.status == TaskStatus.STALE:
            reason = "VERSION_STALE"
        elif task.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
            reason = "GOAL_REACHED" if task.status == TaskStatus.COMPLETED else "USER_REJECTED"
        else:
            reason = "PERMISSION_DENIED"
        return {"termination_reason": reason,
                "trace": self._trace(state, stage="resumed", reason=reason,
                                     domain_version=domain.state_version)}

    def resume(self, design_id, request_id, *, accepted: bool, context: WriteContext):
        """Trusted offline gateway. Never build context from Command/resume JSON."""
        if context.kind != WriterKind.USER or type(accepted) is not bool:
            raise PermissionError("Trusted USER identity and explicit boolean decision required")
        config = self._config(design_id)
        snapshot = self.graph.get_state(config)
        request = snapshot.values.get("confirmation")
        if (not request or request["request_id"] != request_id
            or request["design_id"] != design_id
            or request["thread_id"] != config["configurable"]["thread_id"]):
            raise PermissionError("Confirmation request does not belong to this design/thread")
        domain = self.manager.get_design(design_id)
        command = TaskCommand(
            operation_id=f"{request_id}:resume", task_id=request["task_id"], kind="resume",
            reason="Explicit offline user decision", accepted=accepted,
            expected_input_digest=request["input_digest"],
        )
        intent = fingerprint({
            "command": command.model_dump(mode="json"),
            "writer_kind": context.kind.value, "actor": context.actor,
        })
        prior = self.manager.repository.get_task_operation(
            command.operation_id, design_id, intent,
        )
        pending_interrupt = bool(snapshot.next) and any(
            getattr(interrupt_record, "value", None) == request
            for task in snapshot.tasks for interrupt_record in task.interrupts
        )
        if not pending_interrupt:
            if prior is None:
                raise PermissionError("Confirmation request has no pending interruption")
            reason = "GOAL_REACHED" if accepted else "USER_REJECTED"
            return dict(snapshot.values, duplicate=True, termination_reason=reason)
        # StateManager looks up receipts BEFORE CAS/freshness. Duplicate processed requests
        # still resolve to the old result even if newer domain data exists.
        try:
            self.manager.apply_task_command(
                design_id, domain.state_version, command, context=context,
            )
        except (VersionConflictError, StateManagerError):
            if (engineering_digest(domain) == request["input_digest"]
                and target_exists(domain, request["target_ref"])):
                raise
            self.manager.apply_task_command(design_id, domain.state_version, TaskCommand(
                operation_id=f"{request_id}:expire", task_id=request["task_id"], kind="expire",
                reason="ConfirmationExpired: target or engineering dependencies changed",
            ), context=SYSTEM)
        return self._output(self.graph.invoke(Command(resume={"request_id": request_id}), config,
                                              durability="sync"))


@contextmanager
def open_runtime(manager, checkpoint_path, **kwargs):
    with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        yield Runtime(manager, saver, **kwargs)
