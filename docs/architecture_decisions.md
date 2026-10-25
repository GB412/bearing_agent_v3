# PR-01 review fixes: contract decisions

These decisions amend the original PR-01 contracts without starting PR-02.

1. Keep all original provenance, constraint and confirmation fields. Close nonempty
   `StatePatch.state_updates` completely. Named, typed operations replace arbitrary assignment.
   The legacy `parameters` name remains an alias operation, subject to the same validation.
2. Treat patch `source`/`actor` as attribution, never authorization. Add an independent
   `WriteContext` argument supplied by the trusted application boundary; default is AGENT.
   USER commands require an actor and explicit approval for locked inputs and hard constraints.
   Authentication and UI integration are deferred; never deserialize this context from model output.
3. Add explicit confirmation and role commands, revisioned constraints/cases, and candidate
   dependency snapshots (parameters, constraints, cases and rule-set version). On invalidation,
   preserve the previous precheck in history and make the current status STALE. Constraint and
   rule-set changes conservatively invalidate all candidate prechecks.
4. Add a small extensible ParameterSchemaRegistry. Store raw numeric values/units and expose
   validated quantity conversion. Category values are identifiers supplied by the caller; this
   registry supplies no material recommendations or engineering thresholds. Unknown populated
   parameter IDs fail until registered. Missing extension fields remain representable.
5. Add ReadinessResult and an injectable StageRequirementRegistry. Unknown/empty templates fail
   closed. The minimal R2 template checks D/F/n and one steady case with resolvable references;
   this is input availability only, not permission to recommend a design or a completed PR-03
   requirement specification. Bearing width may remain a design variable without a value.
6. Revalidate model-instance patches via a dumped representation and validate the complete final
   state before SQLite CAS. Keep the existing SQLite version predicate; event history and
   candidate precheck history preserve the domain changes required by PR-01. Full immutable
   per-version snapshots remain outside this PR.

Existing local SQLite payloads remain readable with defaults for additive fields. The next managed
write applies the stricter schema; invalid legacy content must be explicitly corrected rather than
silently coerced. Backfill a pre-upgrade current snapshot on the first managed write.


## PR-01 final guard: confirmed inputs and single steady operating case

1. A confirmed parameter is authoritative **regardless of whether its role is
   FIXED_INPUT or DESIGN_VARIABLE**. An agent may not overwrite or unconfirm it.
   Such changes require a trusted USER WriteContext with an explicit approval ID.
2. Agents may propose an alternative through
   `StatePatch.parameter_change_proposals`. The proposal records the previous
   parameter revision and stays out of `DesignState.parameters`. A trusted USER
   can explicitly approve or reject it with
   `StateManager.resolve_parameter_proposal(..., context=WriteContext(...))`.
   Approving requires that the parameter ID be in `approved_parameter_ids`;
   changed parameter revisions invalidate outstanding proposals. This remains
   an in-process authorization contract: authenticate the USER at the future
   API/UI boundary, never construct USER context from an LLM output.
3. `OperatingCase.is_steady_state` defaults to `None` (unknown). R2
   requires **exactly one** case with `is_steady_state is True` and valid
   parameter references. A new case can remain unknown pending clarification.
   The state manager disallows more than one case in V1.
4. `OperatingCase.confirmed_by` records explicit user confirmation. An Agent
   cannot assign that identity or overwrite an already confirmed case.
   A trusted user may update and reconfirm the case; dependency invalidation
   marks prior candidate prechecks stale.
5. These safeguards do not assert completed simulation or final validation.
   They are PR-01 domain invariants, not a generic auth service.


## PR-01 verified external-input boundary (R2)

- `ParameterStatus.PROVIDED` is not self-authorizing: an Agent's
  `StatePatch.source="user"`, `ParameterRecord.source_ref`, or
  `OperatingCase.is_steady_state=True` alone never establishes trusted input.
- `StateManager` stamps the domain `verified_source_ref` on a parameter or
  case only from a trusted `WriteContext`. A USER context represents a direct
  authenticated user edit and generates an audit-bound user-input reference.
  For extraction from a user message, an untrusted Agent sends its parsed
  `StatePatch`; the **trusted application boundary** must separately verify
  the quoted value and steady-state assertion against the actual stored
  message, and then populate `verified_parameter_refs` and
  `verified_case_refs` with that source message ID. The Agent cannot set
  `verified_source_ref` directly through `StatePatch`.
- Agent-provided fixed inputs and hard constraints cannot enter
  `PROVIDED` without the trusted source assertion. Unverified suggestions
  remain `SUGGESTED`. Verification applies to each specific parameter/case,
  not to an entire message indiscriminately.
- R2 now checks correct fixed-input roles, acceptable status, trusted provenance
  or user confirmation, exactly one explicitly steady case with trusted
  evidence, valid parameter references, and matching case scope. R2 does NOT
  assert engineering fitness, approved material limits, or completed simulation.
- `get_quantity()` does not return provisional `SUGGESTED` parameters by
  default. Callers doing explicitly exploratory calculations may opt in with
  `allow_suggested=True`; unverified fixed external inputs remain disallowed.
- `WriteContext` remains an **in-process authority assertion**, not a
  cryptographic credential or an authentication implementation. In PR-02,
  `Dispatcher/PolicyGuard` must mint it outside the LLM/Agent result, and
  API/UI layers must verify user sessions and source-message bindings. Never
  deserialize `WriteContext` from an LLM response. A claimed
  `StatePatch.source` is only descriptive; the trusted `writer_kind` is
  recorded separately in the state event details.
- Previously persisted `PROVIDED` records lacking a verified source now fail
  R2 closed. Do not backfill provenance from self-reported `source` strings;
  require a verified source or user confirmation when migrating legacy data.


## PR-01 lean-state consolidation before LangGraph

- `StatePatch.parameter_changes` is now the single parameter-write entrypoint.
  The old `parameters` alias, disabled `state_updates`, and user-supplied
  `authorized_fixed_input_ids` have been removed. Only a trusted
  `WriteContext.approved_parameter_ids` may grant authorization. This is an
  intentional **caller API break**; migrate old clients to parameter_changes.
- The authoritative current confirmation is `ParameterRecord.status/confirmed_by`;
  confirmations and changes remain auditable in `event_history`.
  `event_log_refs`, `confirmations`, and `stale_objects` are no longer
  persisted as duplicate caches. `DesignState` accepts and discards these
  obsolete keys when reading older SQLite JSON payloads. It does not modify
  or delete original SQLite databases during migration.
- Stage completeness is configured in `StageRequirementRegistry` only;
  `ParameterSchemaRegistry` concerns value types/units/status validity.
  Legacy `ParameterRecord.required_for` is read but ignored. The R2
  steady-state gate is only for R2; custom stage templates may be registered.
- Pure write guards in `core/write_guards.py` cover authority markers on
  candidate and proposal parameters, Agent-created constraints and
  unauthorized PROVIDED design/derived quantities. Derived PROVIDED quantities
  must be committed by a trusted SYSTEM calculator context.
- `StateRepository` is a typed repository protocol, implemented by SQLite.
  The unused EventRepository protocol and duplicate default registry instance
  were removed. No second DB, permission server, or Agent runtime was added.
- LangGraph in PR-02 owns ephemeral orchestration/checkpoints while
  DesignState owns bearing engineering facts and durable design events.
  A dispatcher must never construct USER/SYSTEM WriteContext from Agent text.
- Candidate input dependency maps are currently conservative and legacy-compatible.
  Precise consumed-dependency snapshots should be tackled together with
  PR-02 replanning, not by dropping dependencies without equivalent tracing.

## PR-02: reduced runtime and task-only idempotency (2026-10-25)

The user's explicit implementation adjustments supersede the earlier PR-02 plan.
`dependencies` remains legacy input fields; only `depends_on_task_ids` is added.
Typed consumed refs and precision tracking are deferred to PR-07. Old JSON reads
without writes. Ambiguous old dependencies are blocked at execution; engineering
changes conservatively stale tasks without a provable input dependency set.

`StateManager.apply_task_command` adds only register/start/complete/fail/wait/
resume/expire. It revalidates commands and trusted identity, enforces CAS, task
predecessors, state transitions and a three-active-task limit. SYSTEM manages
execution; USER only resolves a particular waiting request. Agents retain the
unchanged PR-01 patch contract. TaskPlanView is a disposable projection.

The existing business database adds one `task_operations` table. Operation intent
includes command and trusted actor; the external expected CAS version is not part
of the logical operation. State JSON, event and receipt commit atomically. Replay
checks receipt before freshness/CAS and rejects intent/actor collisions. This is
NOT a general transaction platform: parameter/candidate composite writes are not
part of this guarantee and need explicit tests when introduced in PR-03/05/07.
SQLite connections now close explicitly; `with connection` alone only committed
transactions and left Windows demo databases locked until garbage collection.

LangGraph 1.2.17 + checkpoint 4.3.0 + checkpoint-sqlite 3.1.2 + langchain-core
1.7.0 are pinned. Official synchronous SqliteSaver uses a separate file, stable
thread binding and `durability="sync"`. No second domain/task database, provider
model client, vector store or custom persistence runtime is introduced. The saver
package's sqlite-vec dependency is not used as a knowledge/memory service.

GraphState contains references and bounded trace, not writable engineering facts.
Planner/result contracts remain unchanged; trusted catalog/guard owns executor,
schema and permitted effects. FakeAgent receives isolated copies and has no
repository. All Agent state patches are rejected in this read-only fake runtime.
Only StateManager task commands write domain state. Task-start bookkeeping is
followed by a fresh Guard check; completion still uses the observed domain CAS.

Confirmation only completes/rejects a demo task. It does not confirm parameters
or candidates. Its request is checkpointed and bound to target revision, thread,
task and a conservative engineering digest excluding task/event bookkeeping.
Only the external trusted offline gateway supplies USER context. Raw LangGraph
resume content has no authority. Related changes expire the request; duplicate
decisions replay the task receipt. Formal candidate commands remain PR-07/08.

Recovery promises at-least-once node execution and idempotent task effects, not
cross-database exactly-once. Actual saver-write failure and hard process exit
after task commit are tested across independent processes; the receipt is reused.
Official SqliteSaver and current serial design are for local prototype workloads.
