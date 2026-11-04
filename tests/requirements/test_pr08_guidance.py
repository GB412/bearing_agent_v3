"""PR-08: advisory scene understanding and bounded adaptive questions."""

import json

import pytest

from bearing_agents.application import open_application
from bearing_agents.core.readiness import StageRequirementRegistry
from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.requirements.interaction import InteractionService
from bearing_agents.requirements.question_ranker import (
    QuestionRanker,
    QuestionRankingError,
)


def _service(tmp_path, *, goal=None, stage_registry=None):
    manager = StateManager(
        SQLiteStateRepository(tmp_path / "requirements08.sqlite"),
        stage_registry=stage_registry,
    )
    service = InteractionService(manager, actor="designer")
    design = service.create_design(goal)
    return manager, service, design


def test_scenario_is_only_an_unverified_hint_from_user_text(tmp_path):
    manager, service, design = _service(tmp_path)
    _, view = service.submit_turn(
        design.design_id,
        "我要给齿轮箱设计滑动轴承，可靠性优先，温升尽量低。",
        "pr08-intent-1",
    )
    guidance = view.guidance
    assert guidance.scenario_hint == "gearbox"
    assert guidance.scenario_confirmed is False
    assert guidance.objective_hints == ["reliability", "temperature"]
    assert guidance.next_step == "CLARIFY_SCOPE"
    assert manager.get_design(design.design_id).parameters == {}
    assert "MISSING_BEARING_WIDTH" not in {q.reason_code for q in view.questions}


def test_dynamic_question_priority_responds_to_user_goal(tmp_path):
    _, service, design = _service(tmp_path, goal="高速轴承，温升优先")
    view = service.show_state(design.design_id)
    assert [question.reason_code for question in view.questions] == [
        "SCOPE_UNKNOWN", "MISSING_ROTATIONAL_SPEED", "MISSING_LOAD",
    ] or [question.reason_code for question in view.questions] == [
        "SCOPE_UNKNOWN", "MISSING_ROTATIONAL_SPEED", "MISSING_JOURNAL_DIAMETER",
    ]
    assert all(question.why_needed for question in view.questions)


def test_r2_registry_controls_requirements_and_design_variables_stay_optional(tmp_path):
    registry = StageRequirementRegistry({"R2": ("load",)})
    _, service, design = _service(tmp_path, stage_registry=registry)
    view = service.show_state(design.design_id)
    assert view.guidance.required_external_missing == ["load"]
    assert "bearing_width" in view.guidance.proposable_design_variables
    assert "radial_clearance" in view.guidance.proposable_design_variables
    assert "material" in view.guidance.proposable_design_variables
    assert "lubricant" in view.guidance.proposable_design_variables
    assert "bearing_width" not in view.guidance.required_external_missing
    assert "radial_clearance" not in view.guidance.required_external_missing


def test_untrusted_estimate_remains_unverified_and_requires_clarification(tmp_path):
    manager, service, design = _service(tmp_path)
    _, view = service.submit_turn(
        design.design_id,
        "载荷估计12kN，不确定，齿轮箱可靠性优先。",
        "pr08-uncertain",
    )
    assert "load" not in manager.get_design(design.design_id).parameters
    assert any(item.reason_code == "CLARIFY_INPUT" for item in view.questions)
    assert "load" in view.guidance.required_external_missing


class RankedStub:
    def __init__(self, *, forged=False, reverse=False):
        self.forged = forged
        self.reverse = reverse
        self.calls = []

    def invoke(self, prompt):
        self.calls.append(prompt)
        ids = [item["question_id"] for item in json.loads(prompt)["options"]]
        if self.forged:
            ids = ["invented:parameter:confirmed"]
        elif self.reverse:
            ids = ids[::-1]
        return {"ordered_question_ids": ids}


def test_ranker_can_only_reorder_a_known_immutable_question_set(tmp_path):
    _, service, design = _service(tmp_path)
    view = service.show_state(design.design_id)
    original = {q.question_id: q.model_dump() for q in view.questions}
    ranker = QuestionRanker(RankedStub(reverse=True))
    ranked = ranker.reorder(view.questions, view.guidance)
    assert {q.question_id: q.model_dump() for q in ranked} == original
    assert [q.question_id for q in ranked] == list(reversed(list(original)))


def test_ranker_rejects_forged_question_id_without_fallback(tmp_path):
    _, service, design = _service(tmp_path)
    view = service.show_state(design.design_id)
    with pytest.raises(QuestionRankingError, match="QUESTION_ID_NOT_ALLOWED"):
        QuestionRanker(RankedStub(forged=True)).reorder(view.questions, view.guidance)


def test_unified_application_supplies_read_only_turn_history_and_ranker(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "pr08-app.sqlite"))
    model = RankedStub()
    with open_application(
        manager,
        tmp_path / "pr08-runtime.sqlite",
        actor="designer",
        requirements_question_ranker=QuestionRanker(model),
    ) as application:
        design = application.create_design()
        output = application.submit_turn(
            design.design_id, "齿轮箱可靠性优先，轴径100mm，转速1500rpm",
            "pr08-real-turn",
        )
    assert output.requirements.guidance.scenario_hint == "gearbox"
    assert "reliability" in output.requirements.guidance.objective_hints
    assert model.calls
    assert output.execution["termination_reason"] == "MISSING_INPUT"
    trace = next(
        item for item in output.execution["trace"] if item["stage"] == "committed"
    )
    assert any(call["tool_id"] == "last_user_turn" for call in trace["tool_calls"])
    assert "load" not in manager.get_design(design.design_id).parameters


def test_bad_opted_in_model_does_not_get_trusted_fallback(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "pr08-bad.sqlite"))
    with open_application(
        manager,
        tmp_path / "pr08-bad-runtime.sqlite",
        actor="designer",
        requirements_question_ranker=QuestionRanker(RankedStub(forged=True)),
    ) as application:
        design = application.create_design()
        output = application.submit_turn(
            design.design_id, "帮我设计滑动轴承", "pr08-bad-turn",
        )
    assert output.execution["termination_reason"] == "TOOL_ERROR"
    assert any(
        event["stage"] == "agent_error"
        for event in output.execution["trace"]
    )
    assert manager.get_design(design.design_id).parameters == {}
