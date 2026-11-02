import pytest
from pydantic import ValidationError

from bearing_agents.domain.enums import RuleStatus
from bearing_agents.knowledge.catalog import SourceCatalog
from bearing_agents.knowledge.defaults import build_default_knowledge_base
from bearing_agents.knowledge.models import (
    EngineeringTable,
    NumericRange,
    SourceDocument,
    TableLookupStatus,
    TableRow,
)
from bearing_agents.knowledge.repositories import TableRepository


def reviewed_source():
    return SourceDocument(
        source_id="test-source",
        title="Test source",
        document_number="TEST-1",
        version="test-v1",
        document_status="PUBLISHED",
        review_status=RuleStatus.SOURCE_CHECKED,
        locator="tests/fixture",
    )


def make_table(rows):
    return EngineeringTable(
        table_id="test-table",
        title="Reviewed test table",
        source_id="test-source",
        source_version="test-v1",
        section="test",
        version="1",
        status=RuleStatus.ACTIVE,
        reviewer="test-reviewer",
        input_units={"journal_diameter": "mm", "surface_speed": "m/s"},
        output_units={"clearance_ratio": "‰"},
        rows=rows,
    )


def test_draft_table_is_visible_but_cannot_return_values():
    knowledge = build_default_knowledge_base()

    result = knowledge.tables.lookup(
        "draft-09-table-5-clearance-ratio",
        {"journal_diameter": (100, "mm"), "surface_speed": (7.8, "m/s")},
    )

    assert result.status == TableLookupStatus.BLOCKED_UNAPPROVED
    assert result.values == {}


def test_table_lookup_converts_units_and_uses_half_open_boundaries():
    source = reviewed_source()
    catalog = SourceCatalog([source])
    table = make_table(
        [
            TableRow(
                row_id="low-speed",
                ranges={
                    "journal_diameter": NumericRange(lower=50, upper=150),
                    "surface_speed": NumericRange(lower=5, upper=7),
                },
                values={"clearance_ratio": 1.6},
            ),
            TableRow(
                row_id="high-speed",
                ranges={
                    "journal_diameter": NumericRange(lower=50, upper=150),
                    "surface_speed": NumericRange(lower=7, upper=10, include_upper=True),
                },
                values={"clearance_ratio": 1.9},
            ),
        ]
    )
    repository = TableRepository([table], catalog)

    result = repository.lookup(
        "test-table",
        {"journal_diameter": (0.1, "m"), "surface_speed": (7, "m/s")},
    )

    assert result.status == TableLookupStatus.FOUND
    assert result.row_id == "high-speed"
    assert result.values == {"clearance_ratio": 1.9}
    assert result.units == {"clearance_ratio": "‰"}


def test_table_lookup_does_not_extrapolate():
    source = reviewed_source()
    catalog = SourceCatalog([source])
    table = make_table(
        [
            TableRow(
                row_id="range",
                ranges={
                    "journal_diameter": NumericRange(lower=50, upper=150),
                    "surface_speed": NumericRange(lower=5, upper=10, include_upper=True),
                },
                values={"clearance_ratio": 1.6},
            )
        ]
    )
    repository = TableRepository([table], catalog)

    result = repository.lookup(
        "test-table",
        {"journal_diameter": (100, "mm"), "surface_speed": (10.1, "m/s")},
    )

    assert result.status == TableLookupStatus.OUT_OF_RANGE
    assert result.values == {}


def test_overlapping_table_rows_return_ambiguous_instead_of_choosing_one():
    source = reviewed_source()
    catalog = SourceCatalog([source])
    table = make_table(
        [
            TableRow(
                row_id="first",
                ranges={
                    "journal_diameter": NumericRange(lower=50, upper=150),
                    "surface_speed": NumericRange(lower=5, upper=8),
                },
                values={"clearance_ratio": 1.6},
            ),
            TableRow(
                row_id="second",
                ranges={
                    "journal_diameter": NumericRange(lower=50, upper=150),
                    "surface_speed": NumericRange(lower=7, upper=10, include_upper=True),
                },
                values={"clearance_ratio": 1.9},
            ),
        ]
    )
    repository = TableRepository([table], catalog)

    result = repository.lookup(
        "test-table",
        {"journal_diameter": (100, "mm"), "surface_speed": (7.5, "m/s")},
    )

    assert result.status == TableLookupStatus.AMBIGUOUS


def test_table_rejects_source_version_mismatch():
    source = reviewed_source()
    catalog = SourceCatalog([source])
    table = make_table(
        [
            TableRow(
                row_id="row",
                ranges={
                    "journal_diameter": NumericRange(lower=50, upper=150),
                    "surface_speed": NumericRange(lower=5, upper=10, include_upper=True),
                },
                values={"clearance_ratio": 1.6},
            )
        ]
    ).model_copy(update={"source_version": "test-v2"})

    try:
        TableRepository([table], catalog)
    except ValueError as exc:
        assert "version mismatch" in str(exc)
    else:
        raise AssertionError("A mismatched source version must be rejected.")



def test_table_rejects_non_finite_ranges_and_outputs():
    with pytest.raises(ValidationError):
        NumericRange(lower=float("nan"), upper=10)
    with pytest.raises(ValidationError):
        NumericRange(lower=0, upper=float("inf"))
    with pytest.raises(ValidationError):
        TableRow(
            row_id="bad",
            ranges={
                "journal_diameter": NumericRange(lower=50, upper=150),
                "surface_speed": NumericRange(lower=5, upper=10),
            },
            values={"clearance_ratio": float("nan")},
        )


def test_table_repository_rejects_unknown_output_units():
    source = reviewed_source()
    catalog = SourceCatalog([source])
    table = make_table([
        TableRow(
            row_id="row",
            ranges={
                "journal_diameter": NumericRange(lower=50, upper=150),
                "surface_speed": NumericRange(lower=5, upper=10, include_upper=True),
            },
            values={"clearance_ratio": 1.6},
        )
    ]).model_copy(update={"output_units": {"clearance_ratio": "unknown-unit"}})
    try:
        TableRepository([table], catalog)
    except ValueError as exc:
        assert "Unknown table unit" in str(exc)
    else:
        raise AssertionError("Unknown output units must be rejected.")
