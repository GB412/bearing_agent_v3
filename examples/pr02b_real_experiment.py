"""Run the opt-in B01-B07 real-model experiment and emit JSONL evidence."""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from bearing_agents.orchestration.contracts import PlannerContext, StateSummary
from bearing_agents.orchestration.llm_planner import LLMPlanner, PlannerError


CASES = (
    ("B01", "clarify_requirement", {
        "input_ready": False,
        "missing_inputs": ("journal_diameter", "load", "rotational_speed"),
    }),
    ("B02", "clarify_requirement", {"input_ready": False, "missing_inputs": ("load",)}),
    ("B03", "analyze_conditions", {"input_ready": True, "missing_inputs": ()}),
    ("B04", "generate_candidate", {
        "input_ready": True,
        "completed_actions": frozenset({"analyze_conditions"}),
    }),
    ("B05", "produce_summary", {"input_ready": True, "candidate_ref": "candidate:c1@1"}),
    ("B06", "request_confirmation", {
        "input_ready": True,
        "goal": "confirmation",
        "target_ref": "candidate:c1@1",
    }),
    ("B07", "simulation_unavailable", {"input_ready": True, "goal": "simulation"}),
)


def case_summary(updates):
    base = StateSummary(
        domain_version=1,
        input_digest="fixture",
        input_ready=False,
        missing_inputs=("load",),
        supported_scope=True,
        completed_actions=frozenset(),
        candidate_ref=None,
        target_ref=None,
        goal="demo",
    )
    return StateSummary(**{**base.__dict__, **updates})


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pr02b_real_experiment.jsonl")
    timestamp = datetime.now(timezone.utc).isoformat()
    if not os.getenv("OPENAI_API_KEY"):
        print("REAL_LLM_PENDING: OPENAI_API_KEY is not configured; no model calls made")
        return 0
    try:
        planner = LLMPlanner()
    except PlannerError as exc:
        print(f"REAL_LLM_PENDING: {exc.reason_code}")
        return 0

    actions = tuple(
        (name, spec.effect_class, spec.required_gate, spec.supported)
        for name, spec in sorted(planner.catalog.items())
    )
    with output.open("w", encoding="utf-8") as stream:
        for fixture_id, oracle, updates in CASES:
            summary = case_summary(updates)
            record = {
                "experiment_id": "pr02b-b01-b07",
                "fixture_id": fixture_id,
                "oracle_acceptable_actions": [oracle],
                "UTC_timestamp": timestamp,
                "model_provider": "openai",
                "model_id": os.getenv("BEARING_PLANNER_MODEL", "gpt-4o-mini"),
                "input_domain_version": summary.domain_version,
            }
            try:
                decision = planner.plan(
                    summary, context=PlannerContext(action_descriptions=actions)
                )
                record.update({
                    "selected_action": decision.action,
                    "parsed_ok": True,
                    "match_oracle": decision.action == oracle,
                    "guard_verdict": "NOT_RUN_IN_SUMMARY_EXPERIMENT",
                    **planner.last_metadata,
                })
            except PlannerError as exc:
                record.update({"parsed_ok": False, "reason_code": exc.reason_code})
            stream.write(json.dumps(record, ensure_ascii=True) + "\n")
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
