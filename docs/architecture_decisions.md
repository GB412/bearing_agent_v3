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
