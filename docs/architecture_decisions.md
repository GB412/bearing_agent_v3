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
