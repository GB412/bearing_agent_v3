"""Subprocess harness: fault injection is test-only, never a production saver."""

import argparse
import json
import os
import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.workflow import Runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("crash", "fail", "recover", "pause", "resume"))
    parser.add_argument("domain")
    parser.add_argument("checkpoint")
    parser.add_argument("design_id")
    parser.add_argument("--request-id")
    args = parser.parse_args()
    manager = StateManager(SQLiteStateRepository(args.domain))

    class FaultSaver(SqliteSaver):
        def _fault(self):
            state = manager.get_design(args.design_id)
            if args.mode in {"crash", "fail"} and any(
                e.details.get("task_command") == "complete" for e in state.event_history
            ):
                print("TASK_COMMITTED_CHECKPOINT_NOT_SAVED", flush=True)
                if args.mode == "crash":
                    os._exit(71)
                raise RuntimeError("injected checkpoint write failure")

        def put(self, *positional, **kwargs):
            self._fault()
            return super().put(*positional, **kwargs)

        def put_writes(self, *positional, **kwargs):
            self._fault()
            return super().put_writes(*positional, **kwargs)

    with sqlite3.connect(args.checkpoint, check_same_thread=False) as connection:
        saver = (FaultSaver(connection) if args.mode in {"crash", "fail"}
                 else SqliteSaver(connection))
        runtime = Runtime(manager, saver)
        if args.mode in {"crash", "fail"}:
            result = runtime.invoke(args.design_id)
        elif args.mode == "pause":
            result = runtime.invoke(args.design_id, goal="confirmation",
                                    target_ref="parameter:journal_diameter@1")
        elif args.mode == "resume":
            result = runtime.resume(args.design_id, args.request_id, accepted=True,
                                    context=WriteContext(kind=WriterKind.USER,
                                                         actor="offline-user"))
        else:
            result = runtime.recover(args.design_id)
    state = manager.get_design(args.design_id)
    print(json.dumps({"termination_reason": result.get("termination_reason"),
                      "confirmation": result.get("confirmation"), "trace": result["trace"],
                      "state_version": state.state_version,
                      "event_count": len(state.event_history)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
