# Decision Records

## PR-01-001: SQLite as local state repository

SQLite keeps state persistent without introducing a server dependency. Repository writes use an
expected-version condition so concurrent or stale updates cannot silently overwrite current state.

## PR-01-002: Explicit parameter unit registry

Known physical parameter identifiers are checked against a small explicit unit/dimension registry.
Raw values and their units remain in `ParameterRecord`; the manager does not silently rewrite a
user's value into normalized units. Radial clearance and diametral clearance are separate IDs.

## PR-01-003: Missingness is template-driven and fail-closed

`StageRequirementRegistry` supplies the small, explicit R2 input template used by this PR. The
empty design therefore reports missing diameter, load and speed, and requires one resolvable
steady-state operating case. Unknown future templates return `not_configured=True`; they do not
silently pass. Width remains a design variable and is not an R2 input requirement.

