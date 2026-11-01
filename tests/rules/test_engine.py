from bearing_agents.domain.agent_protocols import RuleRecord
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    ConstraintOperator,
    ConstraintSeverity,
    ParameterRole,
    ParameterStatus,
    RuleStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.knowledge.catalog import SourceCatalog
from bearing_agents.knowledge.models import SourceDocument
from bearing_agents.knowledge.repositories import RuleRepository
from bearing_agents.rules.engine import RuleEngine, RuleEvaluationStatus


def source(review_status=RuleStatus.SOURCE_CHECKED):
    return SourceDocument(
        source_id="test-source",
        title="Reviewed test source",
        document_number="TEST-1",
        version="test-v1",
        document_status="PUBLISHED",
        review_status=review_status,
        locator="tests/fixture",
    )


def comparison_rule(operator=ConstraintOperator.LE, target=50, target_unit="mm"):
    return RuleRecord(
        rule_id="width-limit",
        source_document="test-source",
        source_version="test-v1",
        section="test",
        scope="cylindrical_radial_hydrodynamic",
        bearing_scope="cylindrical_radial_hydrodynamic",
        operating_scope="steady_state",
        inputs=["bearing_width"],
        operation="PARAMETER_COMPARE",
        operator=operator,
        target=target,
        target_unit=target_unit,
        status=RuleStatus.ACTIVE,
        version="1",
        reviewer="test-reviewer",
    )


def parameter(
    value,
    unit="mm",
    role=ParameterRole.DESIGN_VARIABLE,
    status=ParameterStatus.SUGGESTED,
):
    return ParameterRecord(value=value, unit=unit, role=role, status=status)


def make_engine(rule=None, source_record=None):
    source_record = source_record or source()
    catalog = SourceCatalog([source_record])
    repository = RuleRepository([rule or comparison_rule()], catalog)
    return RuleEngine(repository, catalog)


def test_approved_numeric_rule_passes_and_fails_deterministically():
    engine = make_engine()
    passed = engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(40)},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )
    failed = engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(60)},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )

    assert passed.status == RuleEvaluationStatus.PASS
    assert failed.status == RuleEvaluationStatus.FAIL
    assert passed == engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(40)},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )


def test_numeric_rule_compares_after_unit_normalization():
    engine = make_engine(comparison_rule(target=0.05, target_unit="m"))
    result = engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(60, unit="mm")},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )

    assert result.status == RuleEvaluationStatus.FAIL


def test_unapproved_rule_and_unverified_source_cannot_execute():
    draft_rule = comparison_rule().model_copy(update={"status": RuleStatus.DRAFT_EXTRACTED})
    engine = make_engine(draft_rule)
    result = engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(40)},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )
    assert result.status == RuleEvaluationStatus.BLOCKED_UNAPPROVED

    unverified_engine = make_engine(source_record=source(RuleStatus.DRAFT_EXTRACTED))
    result = unverified_engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(40)},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )
    assert result.status == RuleEvaluationStatus.BLOCKED_UNAPPROVED


def test_rule_scope_and_unknown_operating_regime_are_not_assumed():
    engine = make_engine()
    unsupported = engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(40)},
        target_scope="tilting_pad",
        is_steady_state=True,
    )
    unknown_regime = engine.evaluate_rule(
        "width-limit",
        {"bearing_width": parameter(40)},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=None,
    )

    assert unsupported.status == RuleEvaluationStatus.NOT_APPLICABLE
    assert unknown_regime.status == RuleEvaluationStatus.REVIEW_REQUIRED


def test_unverified_fixed_input_is_blocked_from_rule_evaluation():
    rule = RuleRecord(
        rule_id="diameter-min",
        source_document="test-source",
        source_version="test-v1",
        section="test",
        scope="cylindrical_radial_hydrodynamic",
        inputs=["journal_diameter"],
        operation="PARAMETER_COMPARE",
        operator=ConstraintOperator.GE,
        target=1,
        target_unit="mm",
        status=RuleStatus.ACTIVE,
        version="1",
        reviewer="test-reviewer",
    )
    engine = make_engine(rule)
    unverified = parameter(
        100,
        role=ParameterRole.FIXED_INPUT,
        status=ParameterStatus.PROVIDED,
    )
    result = engine.evaluate_rule(
        "diameter-min",
        {"journal_diameter": unverified},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )

    assert result.status == RuleEvaluationStatus.REVIEW_REQUIRED


def test_category_membership_rule_is_supported():
    source_record = source()
    catalog = SourceCatalog([source_record])
    rule = RuleRecord(
        rule_id="allowed-material",
        source_document="test-source",
        source_version="test-v1",
        section="test",
        scope="cylindrical_radial_hydrodynamic",
        inputs=["material"],
        operation="PARAMETER_COMPARE",
        operator=ConstraintOperator.IN,
        target=["CuSn10", "AlSn20"],
        status=RuleStatus.ACTIVE,
        version="1",
        reviewer="test-reviewer",
    )
    engine = RuleEngine(RuleRepository([rule], catalog), catalog)
    result = engine.evaluate_rule(
        "allowed-material",
        {"material": ParameterRecord(
            value="CuSn10", unit="1", role=ParameterRole.DESIGN_VARIABLE,
            status=ParameterStatus.SUGGESTED,
        )},
        target_scope="cylindrical_radial_hydrodynamic",
        is_steady_state=True,
    )

    assert result.status == RuleEvaluationStatus.PASS


def test_user_constraint_is_evaluated_separately_from_engineering_rules():
    engine = make_engine()
    pending = ConstraintRecord(
        id="width-cap",
        parameter="bearing_width",
        operator=ConstraintOperator.LE,
        target=50,
        unit="mm",
        severity=ConstraintSeverity.HARD,
        origin="user",
        approved=False,
    )
    approved = pending.model_copy(update={"approved": True, "revision": 2})

    pending_result = engine.evaluate_constraint(
        pending, {"bearing_width": parameter(60)}
    )
    approved_result = engine.evaluate_constraint(
        approved, {"bearing_width": parameter(60)}
    )

    assert pending_result.status == RuleEvaluationStatus.REVIEW_REQUIRED
    assert approved_result.status == RuleEvaluationStatus.FAIL
    assert approved_result.source_ref == "user-constraint:width-cap@2"
