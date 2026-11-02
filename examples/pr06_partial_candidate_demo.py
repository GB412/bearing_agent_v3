"""Demonstrate an evidence-bound, incomplete candidate and an independent precheck."""

import json
import tempfile
from pathlib import Path

from bearing_agents.core.state_manager import StateManager
from bearing_agents.design.agent import DesignAgent
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.workflow import open_runtime
from bearing_agents.requirements.interaction import InteractionService
from bearing_agents.validation.service import ValidationService


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        manager = StateManager(SQLiteStateRepository(root / "domain.sqlite"))
        service = InteractionService(manager, actor="demo-engineer")
        design = service.create_design("圆柱径向动压滑动轴承初步设计")
        service.submit_turn(
            design.design_id,
            "油润滑圆柱径向动压滑动轴承，轴径100mm，载荷12kN，转速1500rpm，单一稳态",
            "turn-1",
        )
        snapshot = manager.get_design(design.design_id)
        manager.apply_patch(
            design.design_id,
            snapshot.state_version,
            {
                "source": "demo-user",
                "parameter_changes": {
                    "bearing_width": {
                        "value": 60,
                        "unit": "mm",
                        "role": "DESIGN_VARIABLE",
                        "status": "PROVIDED",
                    }
                },
            },
            context=WriteContext(
                kind=WriterKind.USER,
                actor="demo-engineer",
                verified_parameter_refs={"bearing_width": "demo-user-width"},
            ),
        )
        design_agent = DesignAgent()
        with open_runtime(
            manager,
            root / "graph.sqlite",
            agents={"conditions_fake": design_agent, "design_fake": design_agent},
        ) as runtime:
            result = runtime.invoke(design.design_id)
        state = manager.get_design(design.design_id)
        assert len(state.candidate_designs) == 1
        candidate = state.candidate_designs[-1]
        report = ValidationService(manager).assess(
            design.design_id, candidate.candidate_id, candidate.version
        )
        print(json.dumps({
            "runtime": result["termination_reason"],
            "candidate_id": candidate.candidate_id,
            "candidate_version": candidate.version,
            "completeness": candidate.completeness_status,
            "missing_variables": candidate.unresolved_parameters,
            "precheck": report.status.value,
            "missing_rules": report.uncovered_rules,
            "engineering_approved": False,
        }, ensure_ascii=False, indent=2))
        assert candidate.completeness_status == "PARTIAL"
        assert report.status.value == "REVIEW_REQUIRED"
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
