# PR-02 orchestration contract v1

The human-approved reduced PR-02 scope takes precedence over the earlier plan.
DesignState/StateManager remain authoritative. GraphState contains references,
versions and bounded execution summaries; checkpoint data cannot replace domain facts.

## Task writes and legacy data

`TaskRecord.dependencies` remains a list of input field IDs. The additive
`depends_on_task_ids` contains plain task IDs only. Unknown/empty legacy input
dependencies invalidate conservatively on engineering changes; ambiguous legacy
dependencies cannot be used to start a task. No typed consumed refs or migration
framework is introduced. Task-only bookkeeping does not stale engineering results.

`StateManager.apply_task_command` is the only new task write entrypoint. SYSTEM
registers/starts/completes/fails/waits/expires tasks. USER may only resolve a bound
waiting task; AGENT cannot manage tasks. New tasks are PENDING, reference existing
predecessors, and cannot replace old records. At most three tasks may be active.
An interrupted RUNNING task is replayed, not started again. Failed/stale tasks are
retained; replanning uses a new task ID. StateEvent records plan revisions/reasons.

Each command has a stable operation ID. The existing business SQLite gains only
`task_operations`: operation_id, design_id, intent_hash, receipt. Task state, event,
version CAS and receipt commit in one transaction. Check receipt before CAS; reuse
with different intent/actor is an error. This guarantee is limited to task effects.
Existing engineering patches/parameter confirmations are NOT made idempotent here.

## Runtime and user boundary

Reuse PlanDecision and AgentResult. The trusted action catalog fixes executor,
schema and allowed effects. Fake results are read-only DEMO_ONLY information;
SUCCESS never means PRECHECK_PASS. Result validation rejects engineering patches.
Guard rejects stale versions, invalid executors/actions and missing prerequisites.
After task bookkeeping the runtime reobserves before dispatch, then uses CAS.

Confirmation is permission to complete a demonstration task, not an engineering
parameter/candidate approval. A request is bound to design/thread, task, target
revision and a conservative engineering digest. Trusted offline gateway identity
is supplied separately from resume data. Replaying a processed request returns its
original receipt. Changing engineering inputs expires the request; bookkeeping
alone does not. Official candidate confirmation remains PR-07/08.

Six interaction semantics are reserved: UserTurn, UserCorrection, UserConfirmation,
UserRejection, ParameterChangeProposal, ConfirmationExpired. Message/actor/time
must come from trusted adapters, never Agent claims. This PR only implements the
minimum confirmation/rejection/expiration harness; full message handling is PR-03/08.

## Persistence and limits

Official synchronous SqliteSaver is separate from the business database, with
stable thread IDs and sync durability. Nodes may execute again; task effects do
not repeat. No cross-database exactly-once claim. Fake agents have no external
side effects. Future parameter/candidate writes must add atomic/idempotent tests.

Precise consumed-input tracing is PR-07. Real LLMPlanner is PR-02B; engineering
rules, recommendations and DLAP are outside this PR. SOFTWARE acceptance does not
establish engineering performance; all fixtures are SYNTHETIC_WORKFLOW.
