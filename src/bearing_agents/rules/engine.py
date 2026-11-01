import math
from enum import StrEnum
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from bearing_agents.core.unit_normalizer import UnitError, normalize
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    ConstraintOperator,
    ParameterRole,
    ParameterStatus,
    ParameterValueType,
    RuleStatus,
)
from bearing_agents.domain.parameter_registry import ParameterSchemaError, ParameterSchemaRegistry
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.knowledge.catalog import SourceCatalog
from bearing_agents.knowledge.models import TableLookupStatus
from bearing_agents.knowledge.repositories import RuleRepository, TableRepository


class RuleEvaluationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    VALUE_FOUND = "VALUE_FOUND"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    BLOCKED_UNAPPROVED = "BLOCKED_UNAPPROVED"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    AMBIGUOUS = "AMBIGUOUS"


class RuleEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    rule_version: str
    status: RuleEvaluationStatus
    source_ref: str | None = None
    parameter_id: str | None = None
    actual_value: Any = None
    actual_unit: str | None = None
    expected_value: Any = None
    expected_unit: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    message: str


class RuleEngine:
    """Deterministic evaluator. It returns evidence and never mutates DesignState."""

    def __init__(
        self,
        rules: RuleRepository,
        sources: SourceCatalog,
        *,
        tables: TableRepository | None = None,
        parameter_registry: ParameterSchemaRegistry | None = None,
    ):
        self._rules = rules
        self._sources = sources
        self._tables = tables
        self._parameters = parameter_registry or ParameterSchemaRegistry()

    def evaluate_rule(
        self,
        rule_id: str,
        parameters: Mapping[str, ParameterRecord],
        *,
        target_scope: str,
        is_steady_state: bool | None,
    ) -> RuleEvaluation:
        rule = self._rules.get(rule_id)
        if rule is None:
            return self._result(
                rule_id, "unknown", RuleEvaluationStatus.INVALID,
                "Rule does not exist in the current repository.",
            )
        if rule.status != RuleStatus.ACTIVE:
            return self._result(
                rule.rule_id, rule.version, RuleEvaluationStatus.BLOCKED_UNAPPROVED,
                f"Rule status is {rule.status}; only ACTIVE rules can be executed.",
            )
        source = self._sources.get(rule.source_document)
        if source is None or not rule.source_version or source.version != rule.source_version:
            return self._result(
                rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
                "Rule source is missing or the source version does not match.",
            )
        if source.review_status not in {
            RuleStatus.SOURCE_CHECKED, RuleStatus.EXPERT_APPROVED, RuleStatus.ACTIVE
        }:
            return self._result(
                rule.rule_id, rule.version, RuleEvaluationStatus.BLOCKED_UNAPPROVED,
                "The rule source has not passed source verification.",
            )

        bearing_scope = rule.bearing_scope or rule.scope
        if bearing_scope not in {"*", target_scope}:
            return self._result(
                rule.rule_id, rule.version, RuleEvaluationStatus.NOT_APPLICABLE,
                f"Rule scope {bearing_scope!r} does not match {target_scope!r}.",
            )
        if rule.operating_scope == "steady_state":
            if is_steady_state is None:
                return self._result(
                    rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
                    (
                        "The operating regime is unknown; "
                        "steady-state applicability cannot be assumed."
                    ),
                )
            if is_steady_state is False:
                return self._result(
                    rule.rule_id, rule.version, RuleEvaluationStatus.NOT_APPLICABLE,
                    "The rule is limited to steady-state operation.",
                )
        elif rule.operating_scope not in {None, "any"}:
            return self._result(
                rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
                f"Unsupported operating scope: {rule.operating_scope}.",
            )

        source_ref = f"{rule.source_document}@{rule.source_version}#{rule.section}"
        if rule.operation == "PARAMETER_COMPARE":
            if len(rule.inputs) != 1 or rule.operator is None or rule.target is None:
                return self._result(
                    rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
                    "The comparison rule definition is incomplete.", source_ref=source_ref,
                )
            parameter_id = rule.inputs[0]
            record = parameters.get(parameter_id)
            issue = self._parameter_issue(parameter_id, record)
            if issue:
                return self._result(
                    rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
                    issue, source_ref=source_ref, parameter_id=parameter_id,
                )
            return self._compare(
                rule.rule_id,
                rule.version,
                parameter_id,
                record,
                rule.operator,
                rule.target,
                rule.target_unit,
                source_ref,
            )

        if rule.operation == "TABLE_LOOKUP":
            if self._tables is None or not rule.table_ref or not rule.inputs:
                return self._result(
                    rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
                    (
                        "The table lookup rule is missing its table repository, "
                        "table reference or inputs."
                    ),
                    source_ref=source_ref,
                )
            coordinates: dict[str, tuple[float, str]] = {}
            for parameter_id in rule.inputs:
                record = parameters.get(parameter_id)
                issue = self._parameter_issue(parameter_id, record)
                if issue:
                    return self._result(
                        rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
                        issue, source_ref=source_ref, parameter_id=parameter_id,
                    )
                coordinates[parameter_id] = (record.value, record.unit)
            lookup = self._tables.lookup(rule.table_ref, coordinates)
            mapped_status = {
                TableLookupStatus.FOUND: RuleEvaluationStatus.VALUE_FOUND,
                TableLookupStatus.BLOCKED_UNAPPROVED: RuleEvaluationStatus.BLOCKED_UNAPPROVED,
                TableLookupStatus.OUT_OF_RANGE: RuleEvaluationStatus.OUT_OF_RANGE,
                TableLookupStatus.AMBIGUOUS: RuleEvaluationStatus.AMBIGUOUS,
                TableLookupStatus.INVALID_INPUT: RuleEvaluationStatus.INVALID,
                TableLookupStatus.NOT_FOUND: RuleEvaluationStatus.REVIEW_REQUIRED,
                TableLookupStatus.SOURCE_MISMATCH: RuleEvaluationStatus.REVIEW_REQUIRED,
            }[lookup.status]
            return RuleEvaluation(
                rule_id=rule.rule_id,
                rule_version=rule.version,
                status=mapped_status,
                source_ref=lookup.source_ref or source_ref,
                values=lookup.values,
                units=lookup.units,
                message=lookup.message,
            )

        return self._result(
            rule.rule_id, rule.version, RuleEvaluationStatus.REVIEW_REQUIRED,
            f"Unsupported rule operation: {rule.operation}.", source_ref=source_ref,
        )

    def evaluate_constraint(
        self,
        constraint: ConstraintRecord,
        parameters: Mapping[str, ParameterRecord],
    ) -> RuleEvaluation:
        """Evaluate a user constraint without reclassifying it as an ISO rule."""
        rule_id = f"constraint:{constraint.id}"
        version = str(constraint.revision)
        source_ref = constraint.rule_ref or f"user-constraint:{constraint.id}@{constraint.revision}"
        if not constraint.approved:
            return self._result(
                rule_id, version, RuleEvaluationStatus.REVIEW_REQUIRED,
                "The user constraint is pending approval.", source_ref=source_ref,
                parameter_id=constraint.parameter,
            )
        record = parameters.get(constraint.parameter)
        issue = self._parameter_issue(constraint.parameter, record)
        if issue:
            return self._result(
                rule_id, version, RuleEvaluationStatus.REVIEW_REQUIRED,
                issue, source_ref=source_ref, parameter_id=constraint.parameter,
            )
        return self._compare(
            rule_id,
            version,
            constraint.parameter,
            record,
            constraint.operator,
            constraint.target,
            constraint.unit,
            source_ref,
        )

    def _parameter_issue(
        self,
        parameter_id: str,
        record: ParameterRecord | None,
    ) -> str | None:
        if record is None or record.value is None:
            return f"Required parameter {parameter_id!r} is missing."
        if record.status in {
            ParameterStatus.MISSING,
            ParameterStatus.UNAVAILABLE,
            ParameterStatus.NOT_APPLICABLE,
            ParameterStatus.CONFLICT,
            ParameterStatus.STALE,
        }:
            return f"Parameter {parameter_id!r} has unusable status {record.status}."
        if (
            record.role == ParameterRole.FIXED_INPUT
            and record.status == ParameterStatus.PROVIDED
            and not record.verified_source_ref
        ):
            return f"Fixed input {parameter_id!r} has no verified source evidence."
        if record.status == ParameterStatus.CONFIRMED and not record.confirmed_by:
            return f"Parameter {parameter_id!r} has no trusted confirmation."
        if record.role == ParameterRole.FIXED_INPUT and record.status == ParameterStatus.SUGGESTED:
            return f"Fixed input {parameter_id!r} cannot be supplied as an unverified suggestion."
        try:
            self._parameters.validate_record(parameter_id, record)
        except ParameterSchemaError as exc:
            return f"Parameter {parameter_id!r} is invalid: {exc}"
        return None

    def _compare(
        self,
        rule_id: str,
        version: str,
        parameter_id: str,
        record: ParameterRecord,
        operator: ConstraintOperator,
        target: Any,
        target_unit: str | None,
        source_ref: str | None,
    ) -> RuleEvaluation:
        schema = self._parameters.get(parameter_id)
        if schema is None:
            return self._result(
                rule_id, version, RuleEvaluationStatus.INVALID,
                f"No parameter schema is registered for {parameter_id!r}.",
                source_ref=source_ref, parameter_id=parameter_id,
            )

        try:
            if schema.value_type in {
                ParameterValueType.POSITIVE_NUMBER,
                ParameterValueType.NON_NEGATIVE_NUMBER,
            }:
                if operator in {ConstraintOperator.IN, ConstraintOperator.NOT_IN}:
                    raise ValueError("IN/NOT_IN comparisons require a category parameter.")
                if isinstance(target, bool) or not isinstance(target, (int, float)):
                    raise ValueError("Numeric rules require a numeric target.")
                if target_unit is None:
                    raise ValueError("Numeric rules require an explicit target unit.")
                actual, actual_base_unit = normalize(record.value, record.unit, schema.dimension)
                expected, expected_base_unit = normalize(target, target_unit, schema.dimension)
                if actual_base_unit != expected_base_unit:
                    raise ValueError("Actual and expected values have incompatible dimensions.")
                passed = self._compare_numeric(float(actual), float(expected), operator)
            elif schema.value_type == ParameterValueType.CATEGORY:
                if operator in {
                    ConstraintOperator.LE, ConstraintOperator.GE,
                    ConstraintOperator.LT, ConstraintOperator.GT,
                }:
                    raise ValueError(
                        "Ordered comparisons are not supported for category parameters."
                    )
                if operator == ConstraintOperator.EQ:
                    if not isinstance(target, str):
                        raise ValueError("Category EQ requires a string target.")
                    passed = record.value == target
                else:
                    if not isinstance(target, (list, tuple, set)) or not all(
                        isinstance(item, str) for item in target
                    ):
                        raise ValueError("Category IN/NOT_IN requires a string collection.")
                    contains = record.value in target
                    passed = contains if operator == ConstraintOperator.IN else not contains
                actual = record.value
                expected = target
                actual_base_unit = None
            else:
                raise ValueError(
                    "Unsupported parameter type for rule evaluation: "
                    f"{schema.value_type}"
                )
        except (UnitError, TypeError, ValueError) as exc:
            return self._result(
                rule_id, version, RuleEvaluationStatus.INVALID,
                f"Rule comparison is invalid: {exc}",
                source_ref=source_ref, parameter_id=parameter_id,
            )

        return RuleEvaluation(
            rule_id=rule_id,
            rule_version=version,
            status=RuleEvaluationStatus.PASS if passed else RuleEvaluationStatus.FAIL,
            source_ref=source_ref,
            parameter_id=parameter_id,
            actual_value=record.value,
            actual_unit=record.unit,
            expected_value=target,
            expected_unit=target_unit,
            message=(
                f"Parameter {parameter_id!r} satisfies the comparison."
                if passed else f"Parameter {parameter_id!r} violates the comparison."
            ),
        )

    @staticmethod
    def _compare_numeric(actual: float, expected: float, operator: ConstraintOperator) -> bool:
        if operator == ConstraintOperator.EQ:
            return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
        if operator == ConstraintOperator.LE:
            return actual <= expected
        if operator == ConstraintOperator.GE:
            return actual >= expected
        if operator == ConstraintOperator.LT:
            return actual < expected
        if operator == ConstraintOperator.GT:
            return actual > expected
        raise ValueError(f"Unsupported numeric operator: {operator}")

    @staticmethod
    def _result(
        rule_id: str,
        version: str,
        status: RuleEvaluationStatus,
        message: str,
        *,
        source_ref: str | None = None,
        parameter_id: str | None = None,
    ) -> RuleEvaluation:
        return RuleEvaluation(
            rule_id=rule_id,
            rule_version=version,
            status=status,
            source_ref=source_ref,
            parameter_id=parameter_id,
            message=message,
        )
