"""PR-03 integration: verified messages, domain state, questions, idempotency."""

import pytest
from pydantic import ValidationError

from bearing_agents.core.state_manager import StateManager, VersionConflictError
from bearing_agents.domain.enums import ParameterStatus
from bearing_agents.infra.state_repository import SQLiteStateRepository, StateConflictError
from bearing_agents.requirements.contracts import RequirementProposal
from bearing_agents.requirements.evidence import verify
from bearing_agents.requirements.interaction import InteractionService


@pytest.fixture
def env(tmp_path):
    manager=StateManager(SQLiteStateRepository(tmp_path/"pr03.sqlite"))
    service=InteractionService(manager,actor="local-designer")
    design=service.create_design("Design a bearing")
    return manager,service,design


def test_clear_v1_turn_records_provided_inputs_with_exact_message_evidence(env):
    manager,service,design=env
    receipt,view=service.submit_turn(
        design.design_id,
        "圆柱径向动压滑动轴承，轴径100mm，载荷12kN，转速1500r/min，单一稳态",
        "turn-1",
    )
    assert not receipt.replayed
    assert view.scope=="cylindrical_radial_hydrodynamic"
    assert view.input_ready
    state=manager.get_design(design.design_id)
    assert state.parameters["load"].value==12000
    assert state.parameters["rotational_speed"].unit=="rpm"
    assert all(p.status==ParameterStatus.PROVIDED for p in state.parameters.values())
    assert all(p.verified_source_ref==receipt.message_id for p in state.parameters.values())
    assert state.operating_cases[0].is_steady_state is True
    assert state.operating_cases[0].verified_source_ref==receipt.message_id
    assert not any(p.confirmed_by for p in state.parameters.values())


def test_missing_load_questions_and_duplicate_replay(env):
    manager,service,design=env
    before=manager.get_design(design.design_id).state_version
    receipt,view=service.submit_turn(design.design_id,"轴径100mm，转速1500rpm","op-1")
    assert not view.input_ready
    assert "MISSING_LOAD" in [q.reason_code for q in view.questions]
    version=manager.get_design(design.design_id).state_version
    repeated,again=service.submit_turn(design.design_id,"轴径100mm，转速1500rpm","op-1")
    assert repeated.replayed
    assert repeated.message_id==receipt.message_id
    assert manager.get_design(design.design_id).state_version==version==before+1
    with pytest.raises(StateConflictError):
        service.submit_turn(design.design_id,"轴径200mm","op-1")


def test_unsupported_scope_is_not_silent_default(env):
    manager,service,design=env
    assert manager.get_design(design.design_id).target_scope=="unknown"
    receipt,view=service.submit_turn(design.design_id,"我要设计滚动轴承","scope-turn")
    assert view.scope=="unsupported"
    assert not view.input_ready
    assert "UNSUPPORTED_SCOPE" in [q.reason_code for q in view.questions]


def test_uncertain_load_does_not_become_provided(env):
    manager,service,design=env
    _,view=service.submit_turn(design.design_id,"载荷大约12kN，不确定","uncertain")
    assert "load" not in manager.get_design(design.design_id).parameters
    assert not view.input_ready


@pytest.mark.parametrize("text",[
    "轴径100mm，载荷12Nm，转速1500rpm",
    "转速1500",
    "载荷不是12kN",
    "轴径不对，应该是120mm",
])
def test_bad_input_does_not_invent_a_verified_load(env,text):
    manager,service,design=env
    service.submit_turn(design.design_id,text,text)
    assert "load" not in manager.get_design(design.design_id).parameters


def test_forged_value_and_authority_are_rejected(env):
    manager,service,design=env
    text="轴径100mm"
    fake=RequirementProposal(
        kind="parameter",field_id="journal_diameter",quote=text,
        start=0,end=len(text),value=200,unit="mm",role="FIXED_INPUT",
    )
    assert verify(text,fake,manager.parameter_registry).decision=="REJECT"
    with pytest.raises(ValidationError):
        RequirementProposal.model_validate({**fake.model_dump(),"confirmed_by":"designer"})
    malicious_service=InteractionService(
        manager,actor="local-designer",extractor=lambda _:[fake],
    )
    _,view=malicious_service.submit_turn(design.design_id,text,"forged")
    assert "journal_diameter" not in manager.get_design(design.design_id).parameters
    assert not view.input_ready


def test_user_correction_is_revision_bound_and_audited(env):
    manager,service,design=env
    service.submit_turn(design.design_id,"轴径100mm","old")
    old=manager.get_design(design.design_id).parameters["journal_diameter"]
    receipt,view=service.correct_parameter(
        design.design_id,"journal_diameter",old.revision,"轴径120mm","new",
    )
    assert view.parameters["journal_diameter"]["value"]==120
    assert view.parameters["journal_diameter"]["verified_source_ref"]==receipt.message_id
    with pytest.raises(VersionConflictError):
        service.correct_parameter(design.design_id,"journal_diameter",old.revision,
                                  "轴径140mm","other")


def test_ambiguous_confirmation_never_escalates_state(env):
    manager,service,design=env
    service.submit_turn(design.design_id,"轴径100mm","old")
    service.submit_turn(design.design_id,"我确认","confirm-text")
    state=manager.get_design(design.design_id)
    assert state.parameters["journal_diameter"].status==ParameterStatus.PROVIDED
    revision=state.parameters["journal_diameter"].revision
    with pytest.raises(VersionConflictError):
        service.confirm_parameter(design.design_id,"journal_diameter",revision+1)
    service.confirm_parameter(design.design_id,"journal_diameter",revision)
    assert manager.get_design(design.design_id).parameters["journal_diameter"].status==(
        ParameterStatus.CONFIRMED
    )


def test_width_limit_is_pending_until_explicit_approval(env):
    manager,service,design=env
    _,view=service.submit_turn(design.design_id,"安装宽度不超过80mm","limit")
    assert len(view.pending_constraints)==1
    saved=manager.get_design(design.design_id).constraints[0]
    assert saved.approved is False
    service.approve_constraint(design.design_id,saved.id,saved.revision)
    assert manager.get_design(design.design_id).constraints[0].approved


def test_reopen_sqlite_and_continue(tmp_path):
    path=tmp_path/"shared.sqlite"
    first=StateManager(SQLiteStateRepository(path))
    service=InteractionService(first,"local-designer")
    design=service.create_design()
    receipt,_=service.submit_turn(design.design_id,"轴径100mm，转速1500rpm","round-1")
    other=StateManager(SQLiteStateRepository(path))
    resumed=InteractionService(other,"local-designer")
    assert resumed.resume_session(design.design_id).parameters["journal_diameter"]["value"]==100
    replay,_=resumed.submit_turn(design.design_id,"轴径100mm，转速1500rpm","round-1")
    assert replay.replayed and replay.message_id==receipt.message_id
    _,view=resumed.submit_turn(
        design.design_id,"载荷12kN，单一稳态，圆柱径向动压滑动轴承","round-2",
    )
    assert view.input_ready


def test_duplicate_parameter_claims_do_not_silently_pick_last(env):
    manager,service,design=env
    _,view=service.submit_turn(design.design_id,"轴径100mm，轴径120mm","duplicate")
    assert "journal_diameter" not in manager.get_design(design.design_id).parameters
    assert view.unresolved


def test_no_result_from_untrusted_model_cannot_grant_user_privilege(env):
    manager,service,design=env
    class BadModel:
        def invoke(self,prompt):
            return '[{"kind":"parameter","field_id":"journal_diameter",'
    from bearing_agents.requirements.extraction import LLMExtractor
    with pytest.raises(ValueError):
        LLMExtractor(BadModel()).extract("轴径100mm")
