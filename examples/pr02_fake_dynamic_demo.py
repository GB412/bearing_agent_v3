"""Offline SYNTHETIC_WORKFLOW paths; numbers are fixtures, never recommendations."""

import argparse
import json
import tempfile
from pathlib import Path

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.workflow import open_runtime


def demo():
    results = []
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        manager = StateManager(SQLiteStateRepository(root / "domain.sqlite"))
        with open_runtime(manager, root / "checkpoint.sqlite") as runtime:
            for scenario in ("empty", "missing_load", "input_ready"):
                design = manager.create_design()
                if scenario != "empty":
                    values = [("journal_diameter", 100, "mm"), ("rotational_speed", 1500, "rpm")]
                    if scenario == "input_ready":
                        values.append(("load", 12000, "N"))
                    design = manager.apply_patch(design.design_id, 0, {
                        "source": "SYNTHETIC_WORKFLOW",
                        "parameter_changes": {
                            key: {"value": value, "unit": unit,
                                  "role": "FIXED_INPUT", "status": "PROVIDED"}
                            for key, value, unit in values
                        },
                        "operating_case_changes": [{
                            "case_id": "nominal", "is_steady_state": True,
                            "journal_diameter_ref": "journal_diameter", "load_ref": "load",
                            "speed_ref": "rotational_speed",
                        }],
                    }, context=WriteContext(kind=WriterKind.USER, actor="offline-fixture-user"))
                result = runtime.invoke(design.design_id)
                results.append({"scenario": scenario, "source_class": "SYNTHETIC_WORKFLOW",
                                "termination_reason": result["termination_reason"],
                                "trace": result["trace"]})
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = json.dumps(demo(), indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
    print(output)
