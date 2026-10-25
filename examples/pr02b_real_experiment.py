"""Manually run B01-B07 against a real model and the existing PolicyGuard."""

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.agent_protocols import TaskRecord
from bearing_agents.domain.enums import TaskStatus
from bearing_agents.domain.tasks import TaskCommand, engineering_digest
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.contracts import (
    CATALOG,
    PlannerContext,
    observe_state,
    policy_guard,
)
from bearing_agents.orchestration.llm_planner import LLMPlanner, PlannerError

USER = WriteContext(kind=WriterKind.USER, actor="synthetic-fixture-author")
SYSTEM = WriteContext(kind=WriterKind.SYSTEM, actor="synthetic-fixture-author")


def seed_state(manager, *, missing_load=False):
    """Trusted local fixture author, not model-supplied user facts."""
    design = manager.create_design()
    parameters = {
        name: {"value": value, "unit": unit, "role": "FIXED_INPUT", "status": "PROVIDED"}
        for name, value, unit in (
            ("journal_diameter", 100, "mm"),
            ("rotational_speed", 1500, "rpm"),
            ("load", 12000, "N"),
        ) if not (missing_load and name == "load")
    }
    return manager.apply_patch(design.design_id, 0, {
        "source": "SYNTHETIC_WORKFLOW",
        "parameter_changes": parameters,
        "operating_case_changes": [{
            "case_id": "nominal", "is_steady_state": True,
            "journal_diameter_ref": "journal_diameter",
            "speed_ref": "rotational_speed", "load_ref": "load",
        }],
    }, context=USER)


def build_cases(manager):
    empty = manager.create_design()
    missing = seed_state(manager, missing_load=True)
    ready = seed_state(manager)
    analyzed = seed_state(manager)
    task_id = "synthetic-analysis"
    task = TaskRecord(
        id=task_id, action="analyze_conditions", agent=CATALOG["analyze_conditions"].executor_id,
        status=TaskStatus.PENDING, input_version=analyzed.state_version,
    )
    for kind in ("register", "start", "complete"):
        manager.apply_task_command(
            analyzed.design_id, analyzed.state_version,
            TaskCommand(
                operation_id=f"{task_id}:{kind}", task_id=task_id, kind=kind,
                task=task if kind == "register" else None,
                reason="SYNTHETIC_WORKFLOW completed analysis fixture, not a performance result",
                expected_input_digest=engineering_digest(analyzed),
                output_ref="demo:synthetic-analysis" if kind == "complete" else None,
            ), context=SYSTEM,
        )
        analyzed = manager.get_design(analyzed.design_id)
    candidate = seed_state(manager)
    candidate = manager.apply_patch(candidate.design_id, candidate.state_version, {
        "source": "SYNTHETIC_WORKFLOW",
        "candidate_additions": [{"candidate_id": "c1", "version": 1}],
    })
    return (
        ("B01", empty, "demo", None, {"clarify_requirement"}),
        ("B02", missing, "demo", None, {"clarify_requirement"}),
        ("B03", ready, "demo", None, {"analyze_conditions"}),
        ("B04", analyzed, "demo", None, {"generate_candidate"}),
        ("B05", candidate, "summary", None, {"produce_summary"}),
        ("B06", candidate, "confirmation", "candidate:c1@1", {"request_confirmation"}),
        ("B07", ready, "simulation", None, {"simulation_unavailable"}),
    )


def run_cases(manager, planner):
    """Separate decision accuracy from Guard safety; never execute a fixture proposal."""
    records = []
    for fixture_id, state, goal, target_ref, oracle in build_cases(manager):
        summary = observe_state(state, goal, target_ref)
        context = PlannerContext(
            action_descriptions=tuple(
                (name, spec.effect_class, spec.required_gate, spec.supported)
                for name, spec in sorted(planner.catalog.items())
            ),
            recent_failures=(),
            remaining_steps=12,
            remaining_errors=3,
        )
        record = {
            "fixture_id": fixture_id, "fixture_version": "1",
            "source_class": "SYNTHETIC_WORKFLOW", "demo_only": True,
            "UTC_timestamp": datetime.now(UTC).isoformat(),
            "oracle_acceptable_actions": sorted(oracle),
            "input_domain_version": summary.domain_version,
            "remaining_steps": context.remaining_steps,
            "remaining_errors": context.remaining_errors,
            "selected_action": None, "planner_oracle_match": False,
            "parsed_ok": False, "guard_verdict": "NOT_EVALUATED",
            "guard_reason_code": "PLANNER_ERROR",
        }
        try:
            decision = planner.plan(summary, context=context)
            guard = policy_guard(decision, state, target_ref, planner.catalog)
            record.update(
                selected_action=decision.action, rationale=decision.rationale,
                parsed_ok=True, planner_oracle_match=decision.action in oracle,
                guard_verdict=guard.verdict, guard_reason_code=guard.reason_code,
            )
        except PlannerError as exc:
            record["reason_code"] = exc.reason_code
        record["planner_metadata"] = dict(planner.last_metadata)
        records.append(record)
    verdicts = {}
    for record in records:
        verdict = record["guard_verdict"]
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
    parsed = sum(record["parsed_ok"] for record in records)
    oracle_matches = sum(record["planner_oracle_match"] for record in records)
    match_rate = oracle_matches / len(records) if records else 0.0
    totals = {
        "fixture_count": len(records), "valid_proposals": parsed,
        "planner_oracle_matches": oracle_matches,
        "planner_oracle_match_rate": round(match_rate, 4),
        "guard_verdict_counts": verdicts,
        "guard_block_count": verdicts.get("BLOCK", 0),
        # Prototype reference criterion, not an engineering acceptance certificate.
        "planning_acceptance": (
            "PASS" if parsed == len(records) and match_rate >= 0.85 else "FAIL"
        ),
        "experiment_complete": parsed == len(records),
        "real_model_status": (
            "REAL_LLM_VALIDATED" if parsed == len(records) and planner.provider != "injected"
            else "OFFLINE_ONLY" if planner.provider == "injected" else "REAL_LLM_PENDING"
        ),
    }
    return records, totals


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pr02b_real_experiment.jsonl")
    try:
        planner = LLMPlanner()
    except PlannerError as exc:
        print(f"REAL_LLM_PENDING: {exc.reason_code}; no model calls made")
        return 0
    with tempfile.TemporaryDirectory(prefix="pr02b-experiment-") as directory:
        manager = StateManager(SQLiteStateRepository(Path(directory) / "domain.sqlite"))
        records, totals = run_cases(manager, planner)
    with output.open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        stream.write(json.dumps({"summary": totals}) + "\n")
    print(json.dumps(totals))
    print(f"Wrote {output}")
    return 0 if totals["experiment_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
