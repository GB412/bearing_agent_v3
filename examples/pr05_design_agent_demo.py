"""Run the PR-05 DesignAgent through the existing LangGraph Runtime.

The bundled draft knowledge contains no ACTIVE numeric tables. The expected
result is therefore INSUFFICIENT_RULES, not a fabricated bearing design.
"""
import json
import tempfile
from pathlib import Path

from bearing_agents.core.state_manager import StateManager
from bearing_agents.design.agent import DesignAgent
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.workflow import open_runtime
from bearing_agents.requirements.interaction import InteractionService


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = StateManager(SQLiteStateRepository(root / "domain.sqlite"))
        interaction = InteractionService(manager, actor="pr05-demo-user")
        design = interaction.create_design("圆柱径向动压滑动轴承初步设计")
        interaction.submit_turn(
            design.design_id,
            "油润滑圆柱径向动压滑动轴承，轴径100mm，载荷12kN，转速1500rpm，单一稳态",
            "pr05-demo-turn",
        )
        agent = DesignAgent()
        with open_runtime(
            manager, root / "checkpoint.sqlite",
            agents={"conditions_fake": agent, "design_fake": agent},
        ) as runtime:
            result = runtime.invoke(design.design_id)
        print(json.dumps({
            "termination_reason": result["termination_reason"],
            "agent_outputs": result.get("agent_outputs", []),
            "engineering_state_version": manager.get_design(design.design_id).state_version,
        }, ensure_ascii=False, indent=2))
        assert result["termination_reason"] == "INSUFFICIENT_RULES"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
