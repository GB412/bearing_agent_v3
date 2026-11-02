import pytest

from bearing_agents.design.agent import DesignAgent
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.orchestration.workflow import open_runtime
from bearing_agents.validation.agent import ValidationAgent


def test_partial_candidate_commits_atomically_and_is_not_approved(
    manager, ready, tmp_path,
):
    current = manager.apply_patch(
        ready.design_id, ready.state_version,
        {"source": "trusted-user", "parameter_changes": {
            "bearing_width": ParameterRecord(
                value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.PROVIDED,
            ),
        }},
        context=WriteContext(
            kind=WriterKind.USER,
            actor="trusted-user",
            verified_parameter_refs={"bearing_width": "user-message-width"},
        ),
    )
    agent = DesignAgent()
    with open_runtime(
        manager,
        tmp_path / "pr06-checkpoint.sqlite",
        agents={"conditions_fake": agent, "design_fake": agent},
    ) as runtime:
        result = runtime.invoke(current.design_id)
    assert result["termination_reason"] == "NEEDS_REVIEW"
    state = manager.get_design(current.design_id)
    assert len(state.candidate_designs) == 1
    candidate = state.candidate_designs[0]
    assert candidate.completeness_status == "PARTIAL"
    assert candidate.precheck_status.value == "NOT_EVALUATED"
    commits = [
        event for event in state.event_history
        if event.details.get("output_ref", "").startswith("candidate:")
    ]
    assert len(commits) == 1
    assert set(commits[0].changed_fields) == {"candidate_designs", "task_plan"}
    assert any(
        task.status.value == "COMPLETED" and task.output_ref
        == f"candidate:{candidate.candidate_id}@1"
        for task in state.task_plan
    )
    report = ValidationAgent().evaluate(state, candidate)
    assert report.status.value == "REVIEW_REQUIRED"
    assert report.uncovered_rules
    with open_runtime(
        manager,
        tmp_path / "pr06-confirm.sqlite",
    ) as runtime:
        paused = runtime.invoke(
            state.design_id, goal="confirmation",
            target_ref=f"candidate:{candidate.candidate_id}@1",
        )
        assert paused["termination_reason"] == "WAITING_FOR_USER"
        with pytest.raises(PermissionError, match="cannot be confirmed"):
            runtime.resume(
                state.design_id, paused["confirmation"]["request_id"],
                accepted=True,
                context=WriteContext(kind=WriterKind.USER, actor="designer"),
            )
