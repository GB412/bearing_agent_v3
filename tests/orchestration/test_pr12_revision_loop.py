"""PR-12: bounded design loop with synthetic data, never engineering approval."""

from bearing_agents.design.agent import DesignAgent
from bearing_agents.domain.agent_protocols import RuleRecord, StatePatch
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    ConstraintOperator,
    ConstraintSeverity,
    ParameterRole,
    ParameterStatus,
    PrecheckStatus,
    RuleStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.knowledge.catalog import KnowledgeRepository, SourceCatalog
from bearing_agents.knowledge.defaults import KnowledgeBase
from bearing_agents.knowledge.models import SourceDocument
from bearing_agents.knowledge.repositories import RuleRepository, TableRepository
from bearing_agents.requirements.agent import RequirementsAgent
from bearing_agents.validation.agent import RuleCoverageSpec, ValidationAgent


def synthetic_validator():
    """Single active *test* rule; no assertion about real bearing suitability."""
    source = SourceDocument(
        source_id="test-only", title="SYNTHETIC TEST RULE",
        document_number="DEMO_ONLY", version="fixture-1",
        document_status="PUBLISHED", review_status=RuleStatus.EXPERT_APPROVED,
        locator="tests/orchestration/test_pr12_revision_loop.py",
    )
    sources = SourceCatalog([source])
    rule = RuleRecord(
        rule_id="test-width-ceiling", source_document="test-only",
        source_version="fixture-1", section="fake",
        scope="cylindrical_radial_hydrodynamic",
        inputs=["bearing_width"], operation="PARAMETER_COMPARE",
        operator=ConstraintOperator.LE, target=100, target_unit="mm",
        status=RuleStatus.ACTIVE, version="fixture-1",
        reviewer="synthetic-fixture", tests=["test_repair_closes_synthetic_loop"],
    )
    knowledge = KnowledgeBase(
        sources=sources, knowledge=KnowledgeRepository([], sources),
        rules=RuleRepository([rule], sources),
        tables=TableRepository([], sources),
    )
    return ValidationAgent(
        knowledge, coverage=RuleCoverageSpec(
            required_rule_ids=("test-width-ceiling",),
        ),
    )


def candidate(width=80):
    return CandidateDesign(
        candidate_id="bearing-A", version=1,
        parameters={
            "bearing_width": ParameterRecord(
                value=width, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            ),
            "radial_clearance": ParameterRecord(
                value=0.1, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            ),
            "material": ParameterRecord(
                value="fixture-material", unit="1", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            ),
            "lubricant": ParameterRecord(
                value="fixture-oil", unit="1", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.SUGGESTED,
            ),
        },
    )


def with_hard_width_limit(manager, ready, *, locked=False):
    state = ready
    if locked:
        state = manager.apply_patch(
            state.design_id, state.state_version,
            StatePatch(
                source="user", parameter_changes={
                    "bearing_width": ParameterRecord(
                        value=80, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                        status=ParameterStatus.CONFIRMED,
                    ),
                },
                confirmation_events=[{
                    "parameter_id": "bearing_width", "confirmed_by": "designer",
                }],
            ),
            context=WriteContext(
                kind=WriterKind.USER, actor="designer",
                approved_parameter_ids=frozenset({"bearing_width"}),
            ),
        )
    state = manager.apply_patch(
        state.design_id, state.state_version,
        StatePatch(
            source="user",
            constraint_changes=[ConstraintRecord(
                id="max-width", parameter="bearing_width",
                operator=ConstraintOperator.LE, target=70, unit="mm",
                severity=ConstraintSeverity.HARD, origin="user", approved=True,
            )],
        ),
        context=WriteContext(
            kind=WriterKind.USER, actor="designer",
            approved_constraint_ids=frozenset({"max-width"}),
        ),
    )
    state = manager.apply_patch(
        state.design_id, state.state_version,
        StatePatch(source="fixture", candidate_additions=[candidate()]),
    )
    return state


def test_repair_closes_synthetic_loop(manager, ready, runtime_factory):
    state = with_hard_width_limit(manager, ready)
    validator = synthetic_validator()
    agents = {
        "validation_agent": validator,
        "design_fake": DesignAgent(),
        "requirements_fake": RequirementsAgent(),
    }
    result = runtime_factory(agents=agents).invoke(state.design_id, goal="design")
    persisted = manager.get_design(state.design_id)
    versions = persisted.candidate_designs
    assert result["termination_reason"] == "GOAL_REACHED"
    assert [(item.candidate_id, item.version) for item in versions] == [
        ("bearing-A", 1), ("bearing-A", 2),
    ]
    assert versions[0].parameters["bearing_width"].value == 80
    assert versions[0].precheck_status == PrecheckStatus.PRECHECK_FAIL
    assert versions[1].parameters["bearing_width"].value == 70
    assert versions[1].parent_candidate_version == 1
    assert versions[1].precheck_status == PrecheckStatus.PRECHECK_PASS
    assert versions[1].assumptions[-1].startswith("One variable adjusted")
    actions = [
        row["action"] for row in result["trace"]
        if row.get("stage") == "committed"
    ]
    assert actions == [
        "precheck_candidate", "revise_candidate",
        "precheck_candidate", "produce_summary",
    ]


def test_user_locked_width_triggers_clarification_instead_of_repair(
    manager, ready, runtime_factory,
):
    state = with_hard_width_limit(manager, ready, locked=True)
    result = runtime_factory(agents={
        "validation_agent": synthetic_validator(),
        "design_fake": DesignAgent(),
        "requirements_fake": RequirementsAgent(),
    }).invoke(state.design_id, goal="design")
    saved = manager.get_design(state.design_id)
    assert result["termination_reason"] == "MISSING_INPUT"
    assert len(saved.candidate_designs) == 1
    assert saved.parameters["bearing_width"].value == 80
    assert saved.candidate_designs[0].precheck_status == PrecheckStatus.PRECHECK_FAIL
    assert not any(
        row.get("action") == "revise_candidate"
        for row in result["trace"] if row.get("stage") == "committed"
    )


def test_missing_professional_rule_coverage_never_claims_pass(
    manager, ready, runtime_factory,
):
    state = manager.apply_patch(
        ready.design_id, ready.state_version,
        StatePatch(source="fixture", candidate_additions=[candidate(width=60)]),
    )
    result = runtime_factory(agents={
        "validation_agent": ValidationAgent(),
        "design_fake": DesignAgent(),
        "requirements_fake": RequirementsAgent(),
    }).invoke(state.design_id, goal="design")
    saved = manager.get_design(state.design_id)
    assert result["termination_reason"] == "MISSING_INPUT"
    assert len(saved.candidate_designs) == 1
    assert saved.candidate_designs[0].precheck_status == PrecheckStatus.REVIEW_REQUIRED
    assert result["questions"]
    assert not any(
        row.get("action") == "revise_candidate"
        for row in result["trace"] if row.get("stage") == "committed"
    )
