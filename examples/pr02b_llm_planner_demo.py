"""Opt-in PR-02B demo; disabled configuration reports REAL_LLM_PENDING."""

import os
import sys
import tempfile
from pathlib import Path

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.llm_planner import LLMPlanner, PlannerError
from bearing_agents.orchestration.workflow import open_runtime


def main() -> int:
    if os.getenv("BEARING_LLM_ENABLED", "").casefold() not in {"1", "true", "yes", "on"}:
        print("REAL_LLM_PENDING: set BEARING_LLM_ENABLED=true to run the real-model demo")
        return 0
    try:
        planner = LLMPlanner()
    except PlannerError as exc:
        print(f"REAL_LLM_PENDING: {exc.reason_code}")
        return 0
    with tempfile.TemporaryDirectory(prefix="pr02b-demo-") as directory:
        root = Path(directory)
        manager = StateManager(SQLiteStateRepository(root / "domain.sqlite"))
        design = manager.create_design()
        context = WriteContext(kind=WriterKind.USER, actor="local-demo-user")
        manager.apply_patch(design.design_id, 0, {
            "source": "SYNTHETIC_WORKFLOW",
            "parameter_changes": {
                "journal_diameter": {
                    "value": 100, "unit": "mm", "role": "FIXED_INPUT", "status": "PROVIDED",
                },
                "rotational_speed": {
                    "value": 1500, "unit": "rpm", "role": "FIXED_INPUT", "status": "PROVIDED",
                },
                "load": {
                    "value": 12000, "unit": "N", "role": "FIXED_INPUT", "status": "PROVIDED",
                },
            },
            "operating_case_changes": [{
                "case_id": "nominal", "is_steady_state": True,
                "journal_diameter_ref": "journal_diameter",
                "speed_ref": "rotational_speed", "load_ref": "load",
            }],
        }, context=context)
        with open_runtime(manager, root / "checkpoint.sqlite", planner=planner) as runtime:
            result = runtime.invoke(design.design_id)
        print({
            "termination_reason": result["termination_reason"],
            "trace": result["trace"],
            "planner_metadata": planner.last_metadata,
            "source_class": "SYNTHETIC_WORKFLOW",
            "domain_result": "DEMO_ONLY",
        })
        return 0 if result["termination_reason"] else 1


if __name__ == "__main__":
    sys.exit(main())
