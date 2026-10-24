# Decision Records

## PR-01-001: SQLite as local state repository

SQLite keeps state persistent without introducing a server dependency. Repository writes use an
expected-version condition so concurrent or stale updates cannot silently overwrite current state.

## PR-01-002: Explicit parameter unit registry

Known physical parameter identifiers are checked against a small explicit unit/dimension registry.
Raw values and their units remain in `ParameterRecord`; the manager does not silently rewrite a
user's value into normalized units. Radial clearance and diametral clearance are separate IDs.

## PR-01-003: Missingness is metadata-driven

`list_missing_for(stage)` returns only parameters explicitly marked `MISSING` and tagged with that
stage in `required_for`. PR-01 has no reviewed design-completeness rules, so it does not prescribe
which fields must be present for a design stage.

