"""Synthetic-only probes: no source below is an approved engineering standard."""

import pytest

from bearing_agents.core.state_manager import StateManagerError, VersionConflictError
from bearing_agents.domain.agent_protocols import RuleRecord, TaskRecord
from bearing_agents.domain.candidates import CandidateDesign
from bearing_agents.domain.constraints import ConstraintRecord
from bearing_agents.domain.enums import (
    ConstraintOperator,
    ConstraintSeverity,
    ParameterRole,
    ParameterStatus,
    PrecheckStatus,
    RuleStatus,
    TaskStatus,
)
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.tasks import TaskCommand, engineering_digest
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.knowledge.catalog import KnowledgeRepository, SourceCatalog
from bearing_agents.knowledge.defaults import KnowledgeBase
from bearing_agents.knowledge.models import SourceDocument
from bearing_agents.knowledge.repositories import RuleRepository, TableRepository
from bearing_agents.validation.agent import RuleCoverageSpec, ValidationAgent


SYSTEM = WriteContext(kind=WriterKind.SYSTEM, actor="pr06-synthetic-test")


def complete_candidate():
    return CandidateDesign(
        candidate_id="full-synthetic",
        version=1,
        parameters={
            "bearing_width": ParameterRecord(
                value=50, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
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


def synthetic_validation():
    source = SourceDocument(
        source_id="synthetic-source",
        title="TEST FIXTURE - not a real standard",
        document_number="TEST-ONLY",
        version="fixture-v1",
        document_status="PUBLISHED",
        review_status=RuleStatus.EXPERT_APPROVED,
        locator="tests/design/test_pr06_precheck_logic.py",
    )
    catalog = SourceCatalog([source])
    rule = RuleRecord(
        rule_id="fixture-width-max",
        source_document="synthetic-source",
        source_version="fixture-v1",
        section="fixture-only",
        scope="cylindrical_radial_hydrodynamic",
        inputs=["bearing_width"],
        operation="PARAMETER_COMPARE",
        operator=ConstraintOperator.LE,
        target=100,
        target_unit="mm",
        status=RuleStatus.ACTIVE,
        version="fixture-v1",
        reviewer="synthetic-test-only",
        tests=["test_synthetic_limit_passes_when_complete"],
    )
    knowledge = KnowledgeBase(
        sources=catalog,
        knowledge=KnowledgeRepository([], catalog),
        rules=RuleRepository([rule], catalog),
        tables=TableRepository([], catalog),
    )
    return ValidationAgent(
        knowledge,
        coverage=RuleCoverageSpec(required_rule_ids=("fixture-width-max",)),
    )


def test_synthetic_limit_passes_when_complete_and_covered(manager, ready):
    state = manager.apply_patch(
        ready.design_id,
        ready.state_version,
        {"source": "synthetic", "candidate_additions": [complete_candidate()]},
    )
    candidate = state.candidate_designs[0]
    assert candidate.completeness_status == "COMPLETE"
    assert candidate.unresolved_parameters == []
    result = synthetic_validation().evaluate(state, candidate)
    assert result.status == PrecheckStatus.PRECHECK_PASS
    assert result.checks[0]["status"] == "PASS"
    stored = manager.record_candidate_precheck(
        state.design_id, state.state_version, result, context=SYSTEM,
    )
    assert stored.candidate_designs[0].precheck_status == PrecheckStatus.PRECHECK_PASS


def test_user_hard_constraint_failure_overrides_other_missing_coverage(manager, ready):
    state = manager.apply_patch(
        ready.design_id,
        ready.state_version,
        {"source": "fixture", "candidate_additions": [complete_candidate()]},
    )
    state.constraints.append(ConstraintRecord(
        id="width-hard-limit",
        parameter="bearing_width",
        operator=ConstraintOperator.LE,
        target=30,
        unit="mm",
        severity=ConstraintSeverity.HARD,
        origin="user",
        approved=True,
    ))
    result = ValidationAgent().evaluate(state, state.candidate_designs[0])
    assert result.status == PrecheckStatus.PRECHECK_FAIL
    assert result.uncovered_rules
    assert any(
        item["rule_id"] == "constraint:width-hard-limit" and item["status"] == "FAIL"
        for item in result.checks
    )


def test_synthetic_rule_set_mismatch_disallows_pass(manager, ready):
    state = manager.apply_patch(
        ready.design_id,
        ready.state_version,
        {"source": "fixture", "candidate_additions": [complete_candidate()]},
    )
    state.knowledge_rule_set_version = "stale-external-rule-version"
    result = synthetic_validation().evaluate(state, state.candidate_designs[0])
    assert result.status == PrecheckStatus.REVIEW_REQUIRED
    assert any("version does not match" in issue for issue in result.issues)


def test_atomic_candidate_commit_replays_exact_intent(manager, ready):
    digest = engineering_digest(ready)
    task = TaskRecord(
        id="design-task-test", action="generate_candidate", agent="design_fake",
        status=TaskStatus.PENDING, input_version=ready.state_version,
    )
    registered = manager.apply_task_command(
        ready.design_id, ready.state_version,
        TaskCommand(
            operation_id="design-task-test:register",
            task_id=task.id,
            kind="register",
            task=task,
            reason="Synthetic design task",
            expected_input_digest=digest,
        ),
        context=SYSTEM,
    )
    started = manager.apply_task_command(
        ready.design_id, registered.state_version,
        TaskCommand(
            operation_id="design-task-test:start",
            task_id=task.id,
            kind="start",
            reason="Start synthetic design task",
            expected_input_digest=digest,
        ),
        context=SYSTEM,
    )
    command = TaskCommand(
        operation_id="design-task-test:complete",
        task_id=task.id,
        kind="complete",
        reason="Trusted synthetic candidate",
        expected_input_digest=digest,
        output_ref="candidate:full-synthetic@1",
    )
    first = manager.commit_candidate_task(
        ready.design_id, started.state_version,
        command, complete_candidate(), context=SYSTEM,
    )
    second = manager.commit_candidate_task(
        ready.design_id, started.state_version,
        command, complete_candidate(), context=SYSTEM,
    )
    assert second.replayed
    assert second.event_id == first.event_id
    persisted = manager.get_design(ready.design_id)
    assert len(persisted.candidate_designs) == 1
    assert persisted.candidate_designs[0].completeness_status == "COMPLETE"
    assert next(t for t in persisted.task_plan if t.id == task.id).status == TaskStatus.COMPLETED
    with pytest.raises(VersionConflictError):
        manager.commit_candidate_task(
            ready.design_id, started.state_version,
            TaskCommand(
                operation_id="stale-design-task:complete",
                task_id="stale-design-task", kind="complete", reason="stale",
                expected_input_digest=digest, output_ref="candidate:full-synthetic@1",
            ),
            complete_candidate(), context=SYSTEM,
        )
    with pytest.raises(StateManagerError, match="SYSTEM"):
        manager.commit_candidate_task(
            ready.design_id, started.state_version,
            command, complete_candidate(),
            context=WriteContext(kind=WriterKind.AGENT),
        )
