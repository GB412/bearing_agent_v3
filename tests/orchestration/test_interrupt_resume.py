import pytest
from langgraph.types import Command

from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import StateConflictError

USER = WriteContext(kind=WriterKind.USER, actor="offline-user")


def pause(runtime, ready):
    result = runtime.invoke(ready.design_id, goal="confirmation",
                            target_ref="parameter:journal_diameter@1")
    assert "__interrupt__" in result
    request = result["confirmation"]
    assert request["target_ref"] == "parameter:journal_diameter@1"
    return request


def test_f10_duplicate_resume_has_one_task_effect(manager, ready, runtime_factory):
    runtime = runtime_factory()
    request = pause(runtime, ready)
    before = manager.get_design(ready.design_id)
    result = runtime.resume(ready.design_id, request["request_id"], accepted=True, context=USER)
    assert result["termination_reason"] == "GOAL_REACHED"
    after = manager.get_design(ready.design_id)
    duplicate = runtime.resume(ready.design_id, request["request_id"], accepted=True, context=USER)
    assert duplicate["duplicate"]
    assert manager.get_design(ready.design_id) == after
    assert after.state_version == before.state_version + 1
    assert len([e for e in after.event_history if e.details.get("task_command") == "resume"]) == 1
    assert after.parameters == ready.parameters  # task approval is NOT parameter confirmation
    with pytest.raises(StateConflictError, match="different task intent"):
        runtime.resume(ready.design_id, request["request_id"], accepted=False, context=USER)


@pytest.mark.parametrize("change", ["target", "dependency", "rule_set"])
def test_f09_changed_inputs_expire_old_request(manager, ready, runtime_factory, change):
    runtime = runtime_factory()
    request = pause(runtime, ready)
    before = manager.get_design(ready.design_id)
    patch = {"source": "user"}
    if change == "rule_set":
        patch["rule_set_change"] = {"version": "test-rule-v2", "source_ref": "synthetic"}
        context = USER
    else:
        key = "journal_diameter" if change == "target" else "load"
        original = before.parameters[key]
        patch["parameter_changes"] = {
            key: original.model_copy(update={"value": original.value + 1}),
        }
        context = WriteContext(kind=WriterKind.USER, actor="offline-user",
                               approved_parameter_ids=frozenset({key}))
    changed = manager.apply_patch(ready.design_id, before.state_version, patch, context=context)
    result = runtime.resume(ready.design_id, request["request_id"], accepted=True, context=USER)
    assert result["termination_reason"] == "VERSION_STALE"
    after = manager.get_design(ready.design_id)
    assert after.parameters == changed.parameters
    assert not any(e.details.get("task_command") == "resume" for e in after.event_history)
    assert any(e.details.get("reason", "").startswith("ConfirmationExpired")
               for e in after.event_history)


def test_rejection_is_audited_without_parameter_mutation(manager, ready, runtime_factory):
    runtime = runtime_factory()
    request = pause(runtime, ready)
    result = runtime.resume(ready.design_id, request["request_id"], accepted=False, context=USER)
    assert result["termination_reason"] == "USER_REJECTED"
    after = manager.get_design(ready.design_id)
    assert after.parameters == ready.parameters
    assert after.event_history[-1].details["accepted"] is False


def test_untrusted_resume_cannot_approve_a_task(manager, ready, runtime_factory):
    runtime = runtime_factory()
    request = pause(runtime, ready)
    before = manager.get_design(ready.design_id)
    with pytest.raises(PermissionError):
        runtime.resume(ready.design_id, request["request_id"],
                       accepted=True, context=WriteContext())
    with pytest.raises(PermissionError):
        runtime.resume(ready.design_id, "another-request", accepted=True, context=USER)
    result = runtime.graph.invoke(Command(resume={"actor": "user", "accepted": True}),
                                  runtime._config(ready.design_id), durability="sync")
    assert result["termination_reason"] == "PERMISSION_DENIED"
    assert manager.get_design(ready.design_id) == before


def test_unrelated_design_cannot_reuse_checkpoint_thread(manager, runtime_factory):
    first = manager.create_design(thread_id="shared-test-thread")
    second = manager.create_design(thread_id="shared-test-thread")
    runtime = runtime_factory()
    runtime.invoke(first.design_id)
    with pytest.raises(PermissionError, match="another design"):
        runtime.invoke(second.design_id)
    with pytest.raises(PermissionError, match="another design"):
        runtime.recover(second.design_id)
