from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bearing_agents.domain.enums import RuleStatus


class SourceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    document_number: str = Field(min_length=1)
    version: str = Field(min_length=1)
    document_status: Literal["DRAFT", "PUBLISHED", "REFERENCE_ONLY", "UNKNOWN"] = "UNKNOWN"
    review_status: RuleStatus = RuleStatus.DRAFT_EXTRACTED
    locator: str = Field(min_length=1)
    reference_standard: str | None = None
    description: str = ""


class KnowledgeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    section: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    bearing_scope: str = "cylindrical_radial_hydrodynamic"
    operating_scope: str | None = "steady_state"
    status: RuleStatus = RuleStatus.DRAFT_EXTRACTED


class KnowledgeHit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry: KnowledgeEntry
    source: SourceDocument
    score: int = Field(ge=1)


class NumericRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lower: float | None = None
    upper: float | None = None
    include_lower: bool = True
    include_upper: bool = False

    @model_validator(mode="after")
    def validate_bounds(self) -> "NumericRange":
        if self.lower is None and self.upper is None:
            raise ValueError("A table range must have at least one bound")
        if self.lower is not None and self.upper is not None:
            if self.lower > self.upper:
                raise ValueError("Range lower bound must not exceed upper bound")
            if self.lower == self.upper and not (self.include_lower and self.include_upper):
                raise ValueError("A zero-width range must include both bounds")
        return self

    def contains(self, value: float) -> bool:
        if self.lower is not None:
            if value < self.lower or (value == self.lower and not self.include_lower):
                return False
        if self.upper is not None:
            if value > self.upper or (value == self.upper and not self.include_upper):
                return False
        return True


class TableRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    row_id: str = Field(min_length=1)
    ranges: dict[str, NumericRange]
    values: dict[str, Any]


class EngineeringTable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    table_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    section: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: RuleStatus
    input_units: dict[str, str]
    output_units: dict[str, str]
    rows: list[TableRow] = Field(default_factory=list)
    reviewer: str | None = None
    description: str = ""

    @model_validator(mode="after")
    def validate_table(self) -> "EngineeringTable":
        if self.status == RuleStatus.ACTIVE:
            if not self.reviewer or not self.reviewer.strip():
                raise ValueError("An active table requires an expert reviewer")
            if not self.rows:
                raise ValueError("An active table requires reviewed rows")
        row_ids = [row.row_id for row in self.rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("Table row IDs must be unique")
        for row in self.rows:
            if set(row.ranges) != set(self.input_units):
                raise ValueError("Every table row must define every input axis exactly once")
            if set(row.values) != set(self.output_units):
                raise ValueError("Every table row must define every output value exactly once")
        return self


class TableLookupStatus(StrEnum):
    FOUND = "FOUND"
    BLOCKED_UNAPPROVED = "BLOCKED_UNAPPROVED"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    AMBIGUOUS = "AMBIGUOUS"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_FOUND = "NOT_FOUND"
    SOURCE_MISMATCH = "SOURCE_MISMATCH"


class TableLookupResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: TableLookupStatus
    table_id: str
    table_version: str | None = None
    row_id: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    source_ref: str | None = None
    message: str
