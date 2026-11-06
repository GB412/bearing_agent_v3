"""PR-15: bounded, auditable multi-turn bearing-design verification.

Offline by default. Real API requires explicit --live AND environment variables.
No API keys, model prompts, or raw user messages are written to the report.
This is a software workflow experiment, NOT hydrodynamic engineering approval.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from bearing_agents.application import open_application
from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.llm_planner import LLMPlanner
from bearing_agents.requirements.extraction import LLMExtractor

# Normal, imperfect real-world descriptions—not prompts that dictate Agent names.
SCENARIOS: dict[str, tuple[str, ...]] = {
    "missing_load": (
        "老师让我做个齿轮箱的圆柱径向动压滑动轴承初步方案，我不太熟，先告诉我最要紧的信息。",
        "轴径100毫米，转速1500rpm。载荷这会儿没查到，先看看能做什么。",
        "径向载荷后来查到了，是12kN，先按单一稳态工况分析。",
    ),
    "space_limit": (
        "我做一个圆柱径向动压滑动轴承，设备空间有点紧，可靠性更重要。",
        "轴径100mm，径向载荷12kN，转速1500rpm，先按单一稳态工况考虑。",
        "宽度最好不能超过70mm。材料和润滑油暂时别替我拍板。",
    ),
    "uncertain_design": (
        "有个油润滑圆柱径向动压滑动轴承需要初步评估，材料和润滑油我都还没定。",
        "轴颈直径100mm，载荷12kN，转速1500rpm，先按单一稳态工况评估。",
        "你先说清楚哪些参数已有依据，哪些必须找老师或资料再确认。",
    ),
}


def require_live_config() -> None:
    """Fail before starting a real run; never display secrets or raw env values."""
    if os.environ.get("BEARING_LLM_ENABLED", "").lower() not in {
        "1", "true", "yes", "on",
    }:
        raise ValueError("Set BEARING_LLM_ENABLED=true to enable real verification")
    required = (
        "BEARING_LLM_API_KEY", "BEARING_LLM_BASE_URL", "BEARING_PLANNER_MODEL",
    )
    missing = [name for name in required if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("Missing required environment variable(s): " + ", ".join(missing))


def summarize_run(
    execution: dict, state, *, scenario: str, turn: int,
    input_ready: bool | None = None,
) -> dict:
    """Persist a bounded, privacy-conscious observation; no message bodies or keys."""
    plans = []
    guards = []
    for step in execution.get("trace", []):
        if step.get("stage") == "plan":
            audit = step.get("planner_metadata") or {}
            plans.append({
                "action": step.get("action"),
                "target_ref": step.get("target_ref"),
                "finding_ref": step.get("finding_ref"),
                "model_id": audit.get("model_id"),
                "latency_ms": audit.get("latency_ms"),
                "token_usage": audit.get("token_usage"),
            })
        elif step.get("stage") == "guard":
            guards.append({
                "action": step.get("action"),
                "verdict": step.get("guard"),
                "reason": step.get("reason"),
            })
    return {
        "scenario": scenario,
        "turn": turn,
        "termination": execution.get("termination_reason"),
        "r2_input_ready": input_ready,
        "planned_actions": plans,
        "guards": guards,
        "trusted_parameter_ids": sorted(state.parameters),
        "approved_constraints": sum(bool(c.approved) for c in state.constraints),
        "pending_constraints": sum(not c.approved for c in state.constraints),
        "candidates": [
            {
                "ref": f"candidate:{c.candidate_id}@{c.version}",
                "completeness": c.completeness_status,
                "precheck": c.precheck_status.value,
            }
            for c in state.candidate_designs
        ],
        "engineering_acceptance": "DOMAIN_PENDING",
        "dlap": "NOT_AVAILABLE",
    }


def run_scenario(name: str, *, live: bool, max_steps: int = 4) -> list[dict]:
    """Run one independent design; budget is bounded per turn."""
    if name not in SCENARIOS:
        raise ValueError("Unknown scenario")
    if not 1 <= max_steps <= 8:
        raise ValueError("max_steps must be in [1, 8]")
    if live:
        require_live_config()
    with tempfile.TemporaryDirectory(prefix="bearing-pr15-") as directory:
        root = Path(directory)
        manager = StateManager(SQLiteStateRepository(root / "design.sqlite"))
        planner = LLMPlanner(max_retries=0) if live else None
        extractor = LLMExtractor.from_environment().extract if live else None
        with open_application(
            manager, root / "checkpoint.sqlite", actor="pr15-local-verifier",
            planner=planner, extractor=extractor,
            max_steps=max_steps, max_errors=2,
        ) as application:
            design = application.create_design("油润滑圆柱径向动压滑动轴承初步设计")
            records = []
            for i, message in enumerate(SCENARIOS[name], 1):
                receipt = application.submit_turn(
                    design.design_id, message,
                    f"pr15:{name}:{i}:{uuid4()}", goal="design",
                )
                state = manager.get_design(design.design_id)
                view = application.show_state(design.design_id)
                records.append(summarize_run(
                    receipt.execution, state, scenario=name, turn=i,
                    input_ready=view.input_ready,
                ))
            return records


def evaluate_records(records: list[dict], *, live: bool) -> dict:
    """Report what actually happened; never infer correctness from action count."""
    paths = [tuple(
        p["action"] for row in rows
        for p in row["planned_actions"]
    ) for rows in (
        [r for r in records if r["scenario"] == name]
        for name in SCENARIOS
        if any(r["scenario"] == name for r in records)
    )]
    observed_real = any(
        p.get("model_id") not in {None, "injected", "unknown"}
        for record in records for p in record["planned_actions"]
    )
    return {
        "api_mode": "REAL_API_ATTEMPTED" if live else "OFFLINE",
        "real_api_observed": observed_real if live else False,
        "independent_scenarios": len(paths),
        "distinct_action_sequences": len(set(paths)),
        "terminated_with": [row["termination"] for row in records],
        "candidate_counts": [len(row["candidates"]) for row in records],
        "engineering_approval": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PR-15 多轮动态框架验证")
    parser.add_argument("--live", action="store_true", help="Explicitly use real paid API")
    parser.add_argument(
        "--scenario", choices=("all", *SCENARIOS), default="all",
    )
    parser.add_argument("--max-steps", type=int, default=4)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.live:
        require_live_config()
    selected = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    records = []
    for name in selected:
        try:
            rows = run_scenario(name, live=args.live, max_steps=args.max_steps)
        except Exception as exc:
            # Do not disclose provider exceptions: some SDKs embed request headers.
            print(f"SCENARIO_FAILED {name}: {type(exc).__name__}")
            return 2
        records.extend(rows)
        print(f"{name}: " + " / ".join(r["termination"] or "unknown" for r in rows))
    summary = evaluate_records(records, live=args.live)
    payload = {"summary": summary, "turns": records}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"Sanitized results: {args.output}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.live and not summary["real_api_observed"]:
        print("REAL_API_PENDING: no authenticated model invocation was observed")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
