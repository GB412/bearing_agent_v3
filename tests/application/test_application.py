from bearing_agents.application import open_application
from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository


def test_application_unifies_user_turn_requirements_and_supervisor(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "application-domain.sqlite"))

    with open_application(
        manager,
        tmp_path / "application-checkpoint.sqlite",
        actor="local-test-user",
    ) as application:
        design = application.create_design("圆柱径向动压滑动轴承初步设计")
        result = application.submit_turn(
            design.design_id,
            "轴径100mm，转速1500rpm，单一稳态",
            "application-turn-1",
        )

    assert result.receipt.design_id == design.design_id
    assert result.requirements.design_id == design.design_id
    assert not result.requirements.input_ready
    assert "load" not in manager.get_design(design.design_id).parameters
    assert result.execution["termination_reason"] == "MISSING_INPUT"
    assert result.execution["questions"]
    assert any(
        question["reason_code"] == "MISSING_LOAD"
        for question in result.execution["questions"]
    )


def test_requirements_agent_does_not_hold_a_state_manager():
    from bearing_agents.requirements.agent import RequirementsAgent

    agent = RequirementsAgent()
    assert not hasattr(agent, "manager")
