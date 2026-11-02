from bearing_agents.core.state_manager import StateManager
from bearing_agents.design.agent import DesignAgent
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.workflow import open_runtime
from bearing_agents.requirements.interaction import InteractionService


def test_design_agent_runs_through_existing_supervisor_and_exposes_rule_gap(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "domain.sqlite"))
    interaction = InteractionService(manager, actor="test-designer")
    design = interaction.create_design("圆柱径向动压滑动轴承初步设计")
    interaction.submit_turn(
        design.design_id,
        "油润滑圆柱径向动压滑动轴承，轴径100mm，载荷12kN，转速1500rpm，单一稳态",
        "turn-ready",
    )
    agent = DesignAgent()
    with open_runtime(
        manager, tmp_path / "checkpoint.sqlite",
        agents={"conditions_fake": agent, "design_fake": agent},
    ) as runtime:
        result = runtime.invoke(design.design_id)

    assert result["termination_reason"] == "INSUFFICIENT_RULES"
    assert len(result["agent_outputs"]) >= 1
    proposal = result["agent_outputs"][-1]
    assert proposal["status"] == "INSUFFICIENT_RULES"
    assert proposal["parameters"] == {}
    assert "bearing_width" in proposal["unresolved_parameters"]
    assert manager.get_design(design.design_id).candidate_designs == []
