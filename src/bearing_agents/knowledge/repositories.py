from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping

from bearing_agents.core.unit_normalizer import UNITS, UnitError, normalize
from bearing_agents.domain.agent_protocols import RuleRecord
from bearing_agents.domain.enums import RuleStatus
from bearing_agents.knowledge.catalog import SourceCatalog
from bearing_agents.knowledge.models import (
    EngineeringTable,
    TableLookupResult,
    TableLookupStatus,
)


class RuleRepository:
    """Versioned in-memory repository for rule metadata and executable definitions."""

    def __init__(self, rules: Iterable[RuleRecord], sources: SourceCatalog):
        self._rules: dict[str, RuleRecord] = {}
        self._sources = sources
        for rule in rules:
            if rule.rule_id in self._rules:
                raise ValueError(f"Duplicate rule ID: {rule.rule_id}")
            source = sources.get(rule.source_document)
            if source is None:
                raise ValueError(f"Unknown source for rule: {rule.rule_id}")
            if rule.source_version and source.version != rule.source_version:
                raise ValueError(f"Source version mismatch for rule: {rule.rule_id}")
            self._rules[rule.rule_id] = rule
        payload = [
            rule.model_dump(mode="json")
            for rule in sorted(self._rules.values(), key=lambda item: item.rule_id)
        ]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.version = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def get(self, rule_id: str) -> RuleRecord | None:
        return self._rules.get(rule_id)

    def list(self) -> list[RuleRecord]:
        return [self._rules[key] for key in sorted(self._rules)]

    def for_scope(self, bearing_scope: str) -> list[RuleRecord]:
        return [
            rule for rule in self.list()
            if (rule.bearing_scope or rule.scope) in {"*", bearing_scope}
        ]


class TableRepository:
    """Versioned table lookup with explicit units and no interpolation or extrapolation."""

    def __init__(self, tables: Iterable[EngineeringTable], sources: SourceCatalog):
        self._tables: dict[str, EngineeringTable] = {}
        self._sources = sources
        for table in tables:
            if table.table_id in self._tables:
                raise ValueError(f"Duplicate table ID: {table.table_id}")
            source = sources.get(table.source_id)
            if source is None:
                raise ValueError(f"Unknown source for table: {table.table_id}")
            if source.version != table.source_version:
                raise ValueError(f"Source version mismatch for table: {table.table_id}")
            for unit in table.input_units.values():
                if unit not in UNITS:
                    raise ValueError(f"Unknown table input unit: {unit}")
            self._tables[table.table_id] = table
        payload = [
            table.model_dump(mode="json")
            for table in sorted(self._tables.values(), key=lambda item: item.table_id)
        ]
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self.version = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def get(self, table_id: str) -> EngineeringTable | None:
        return self._tables.get(table_id)

    def list(self) -> list[EngineeringTable]:
        return [self._tables[key] for key in sorted(self._tables)]

    def lookup(
        self,
        table_id: str,
        coordinates: Mapping[str, tuple[float, str]],
    ) -> TableLookupResult:
        table = self.get(table_id)
        if table is None:
            return TableLookupResult(
                status=TableLookupStatus.NOT_FOUND,
                table_id=table_id,
                message="Table does not exist in the current repository.",
            )
        if table.status != RuleStatus.ACTIVE:
            return TableLookupResult(
                status=TableLookupStatus.BLOCKED_UNAPPROVED,
                table_id=table_id,
                table_version=table.version,
                message=f"Table status is {table.status}; only ACTIVE tables can return values.",
            )
        source = self._sources.get(table.source_id)
        if source is None or source.version != table.source_version:
            return TableLookupResult(
                status=TableLookupStatus.SOURCE_MISMATCH,
                table_id=table_id,
                table_version=table.version,
                message="Table source is missing or its version no longer matches.",
            )
        if source.review_status not in {
            RuleStatus.SOURCE_CHECKED, RuleStatus.EXPERT_APPROVED, RuleStatus.ACTIVE
        }:
            return TableLookupResult(
                status=TableLookupStatus.BLOCKED_UNAPPROVED,
                table_id=table_id,
                table_version=table.version,
                message="The source has not passed source verification.",
            )
        if set(coordinates) != set(table.input_units):
            return TableLookupResult(
                status=TableLookupStatus.INVALID_INPUT,
                table_id=table_id,
                table_version=table.version,
                message="Lookup coordinates must match the table input axes exactly.",
            )

        converted: dict[str, float] = {}
        try:
            for key, target_unit in table.input_units.items():
                value, input_unit = coordinates[key]
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"Coordinate {key} must be numeric.")
                source_unit = UNITS.get(input_unit)
                target_definition = UNITS.get(target_unit)
                if source_unit is None or target_definition is None:
                    raise UnitError(f"Unknown unit for table coordinate {key}.")
                base_value, _ = normalize(value, input_unit, target_definition.dimension)
                target_factor, _ = normalize(1.0, target_unit, target_definition.dimension)
                converted[key] = base_value / target_factor
        except (KeyError, TypeError, ValueError, UnitError) as exc:
            return TableLookupResult(
                status=TableLookupStatus.INVALID_INPUT,
                table_id=table_id,
                table_version=table.version,
                message=f"Invalid table coordinates: {exc}",
            )

        matches = [
            row for row in table.rows
            if all(row.ranges[key].contains(value) for key, value in converted.items())
        ]
        source_ref = f"{table.source_id}@{table.source_version}#{table.section}"
        if not matches:
            return TableLookupResult(
                status=TableLookupStatus.OUT_OF_RANGE,
                table_id=table_id,
                table_version=table.version,
                source_ref=source_ref,
                message=(
                    "Coordinates are outside the reviewed table domain; "
                    "extrapolation is forbidden."
                ),
            )
        if len(matches) > 1:
            return TableLookupResult(
                status=TableLookupStatus.AMBIGUOUS,
                table_id=table_id,
                table_version=table.version,
                source_ref=source_ref,
                message="More than one table row matches; boundary definitions need review.",
            )
        row = matches[0]
        return TableLookupResult(
            status=TableLookupStatus.FOUND,
            table_id=table_id,
            table_version=table.version,
            row_id=row.row_id,
            values=row.values,
            units=table.output_units,
            source_ref=source_ref,
            message="A single reviewed table row matched; no interpolation was performed.",
        )
