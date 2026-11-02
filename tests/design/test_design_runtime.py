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


def test_runtime_persists_only_candidate_additions_through_state_manager(tmp_path):
    from bearing_agents.domain.agent_protocols import AgentResult, StatePatch
    from bearing_agents.domain.candidates import CandidateDesign
    from bearing_agents.domain.enums import AgentResultStatus, ParameterRole, ParameterStatus
    from bearing_agents.domain.parameters import ParameterRecord

    manager = StateManager(SQLiteStateRepository(tmp_path / "domain-candidate.sqlite"))
    interaction = InteractionService(manager, actor="candidate-test-user")
    design = interaction.create_design("candidate persistence")
    interaction.submit_turn(
        design.design_id,
        "油润滑圆柱径向动压滑动轴承，轴径100mm，载荷12kN，转速1500rpm，单一稳态",
        "candidate-turn",
    )

    class CandidateAgent:
        def run(self, state, task):
            if task.action == "generate_candidate":
                candidate = CandidateDesign(
                    candidate_id="candidate-test-1",
                    version=1,
                    parameters={
                        "radial_clearance": ParameterRecord(
                            value=0.1,
                            unit="mm",
                            role=ParameterRole.DESIGN_VARIABLE,
                            status=ParameterStatus.SUGGESTED,
                            source="engineering_table",
                            source_ref="TEST-STD@v1#section-1",
                        )
                    },
                    assumptions=["Synthetic integration fixture only."],
                    rule_refs=["test-rule-1"],
                )
                return AgentResult(
                    task_id=task.id,
                    status=AgentResultStatus.SUCCESS,
                    state_patch=StatePatch(
                        candidate_additions=[candidate],
                        source="design_agent",
                    ),
                )
            return AgentResult(task_id=task.id, status=AgentResultStatus.SUCCESS)

    agent = CandidateAgent()
    with open_runtime(
        manager,
        tmp_path / "checkpoint-candidate.sqlite",
        agents={"conditions_fake": agent, "design_fake": agent},
    ) as runtime:
        runtime.invoke(design.design_id)

    saved = manager.get_design(design.design_id).candidate_designs
    assert len(saved) == 1
    assert saved[0].candidate_id == "candidate-test-1"
    assert saved[0].parameters["radial_clearance"].status == ParameterStatus.SUGGESTED
    assert saved[0].input_dependency_refs
