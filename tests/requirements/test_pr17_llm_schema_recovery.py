"""Typed natural-language extraction: format, validation, trustworthy state and recovery."""

import json
from types import SimpleNamespace

import pytest

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.enums import ConstraintSeverity
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.requirements.extraction import LLMExtractor
from bearing_agents.requirements.interaction import InteractionService


def _reply(proposals, *, malformed=False):
    envelope = {"proposals": proposals}
    return {
        "raw": SimpleNamespace(content=json.dumps(envelope, ensure_ascii=False)),
        "parsed": None if malformed else envelope,
        "parsing_error": ValueError("wrong proposal kind") if malformed else None,
    }


def _rig(tmp_path, payload, *, malformed=False):
    extractor = LLMExtractor(SimpleNamespace(
        invoke=lambda _: _reply(payload, malformed=malformed),
    ))
    manager = StateManager(SQLiteStateRepository(tmp_path / "design.sqlite"))
    service = InteractionService(manager, actor="engineer", extractor=extractor.extract)
    design = service.create_design()
    return extractor, manager, service, design


def test_valid_json_without_spans_records_scope_parameters_and_steady_case(tmp_path):
    text = (
        "圆柱径向动压滑动轴承，轴径100mm，"
        "载荷12kN，转速1500rpm，单一稳态"
    )
    items = [
        {"kind": "scope", "field_id": "supported",
         "value": "cylindrical_radial_hydrodynamic"},
        {"kind": "parameter", "field_id": "journal_diameter",
         "value": 100, "unit": "mm"},
        {"kind": "parameter", "field_id": "load",
         "value": 12, "unit": "kN"},
        {"kind": "parameter", "field_id": "rotational_speed",
         "value": 1500, "unit": "rpm"},
        {"kind": "steady_state", "field_id": "steady", "value": "true"},
    ]
    extractor, manager, service, design = _rig(tmp_path, items)
    receipt, view = service.submit_turn(design.design_id, text, "first-turn")
    state = manager.get_design(design.design_id)
    assert view.input_ready
    assert state.target_scope == "cylindrical_radial_hydrodynamic"
    assert state.parameters["load"].value == 12000
    assert state.parameters["journal_diameter"].value == 100
    assert state.parameters["rotational_speed"].value == 1500
    assert all(p.verified_source_ref == receipt.message_id for p in state.parameters.values())
    assert state.operating_cases[0].verified_source_ref == receipt.message_id
    assert extractor.last_recovery is None


def test_valid_model_omissions_are_supplemented_from_explicit_input(tmp_path):
    text = (
        "先按油润滑圆柱径向动压滑动轴承考虑。"
        "轴径100mm，载荷12kN，转速1500rpm，单一稳态。"
    )
    extractor, manager, service, design = _rig(tmp_path, [])
    _, view = service.submit_turn(design.design_id, text, "omitted")
    assert view.input_ready
    assert set(manager.get_design(design.design_id).parameters) == {
        "journal_diameter", "load", "rotational_speed",
    }
    assert extractor.last_recovery == {
        "invalid_proposals": 0, "recovered_from_text": 5,
    }


def test_invalid_kinds_are_rejected_but_known_original_facts_recovered(tmp_path):
    text = (
        "先按油润滑圆柱径向动压滑动轴承考虑。"
        "轴径是100毫米，转速1500转/分，载荷我还没查到。"
    )
    items = [
        {"kind": "scope", "field_id": "supported",
         "value": "cylindrical_radial_hydrodynamic"},
        {"kind": "diameter", "field_id": "journal_diameter",
         "value": 100, "unit": "mm"},
        {"kind": "speed", "field_id": "rotational_speed",
         "value": 1500, "unit": "rpm"},
    ]
    extractor, manager, service, design = _rig(tmp_path, items, malformed=True)
    _, view = service.submit_turn(design.design_id, text, "second-turn")
    state = manager.get_design(design.design_id)
    assert state.parameters["journal_diameter"].value == 100
    assert state.parameters["rotational_speed"].value == 1500
    assert "load" not in state.parameters
    assert state.target_scope == "cylindrical_radial_hydrodynamic"
    assert not view.input_ready
    assert extractor.last_recovery == {
        "invalid_proposals": 2, "recovered_from_text": 2,
    }


def test_uncertain_load_cannot_be_promoted_even_if_model_says_explicit(tmp_path):
    text = "载荷大约12kN，轴径100mm"
    items = [
        {"kind": "parameter", "field_id": "load",
         "value": 12, "unit": "kN", "modality": "EXPLICIT"},
        {"kind": "parameter", "field_id": "journal_diameter",
         "value": 100, "unit": "mm"},
    ]
    _, manager, service, design = _rig(tmp_path, items)
    service.submit_turn(design.design_id, text, "uncertain")
    state = manager.get_design(design.design_id)
    assert "load" not in state.parameters
    assert state.parameters["journal_diameter"].value == 100


@pytest.mark.parametrize("modality", [
    "UNCERTAIN", "NEGATED", "UNKNOWN", "CORRECTION", "AMBIGUOUS",
])
def test_nonexplicit_values_do_not_automatically_update_state(tmp_path, modality):
    items = [{"kind": "parameter", "field_id": "load",
              "value": 12, "unit": "kN", "modality": modality}]
    _, manager, service, design = _rig(tmp_path, items)
    service.submit_turn(design.design_id, "载荷12kN", "untrusted")
    assert "load" not in manager.get_design(design.design_id).parameters


def test_soft_preference_never_becomes_an_approved_hard_constraint(tmp_path):
    items = [{"kind": "preference", "field_id": "bearing_width",
              "value": 70, "unit": "mm", "operator": "LE"}]
    _, manager, service, design = _rig(tmp_path, items)
    service.submit_turn(design.design_id, "宽度最好不超过70mm", "soft")
    constraints = manager.get_design(design.design_id).constraints
    assert len(constraints) == 1
    assert constraints[0].severity == ConstraintSeverity.SOFT
    assert constraints[0].approved is False


def test_hard_constraint_is_pending_approval(tmp_path):
    items = [{"kind": "constraint", "field_id": "bearing_width",
              "value": 70, "unit": "mm", "operator": "LE"}]
    _, manager, service, design = _rig(tmp_path, items)
    service.submit_turn(design.design_id, "安装宽度必须不超过70mm", "hard")
    constraints = manager.get_design(design.design_id).constraints
    assert len(constraints) == 1
    assert constraints[0].severity == ConstraintSeverity.HARD
    assert constraints[0].approved is False


def test_forged_numeric_value_fails_business_consistency_check(tmp_path):
    items = [{"kind": "parameter", "field_id": "journal_diameter",
              "value": 200, "unit": "mm"}]
    _, manager, service, design = _rig(tmp_path, items)
    service.submit_turn(design.design_id, "轴径100mm", "conflict")
    assert "journal_diameter" not in manager.get_design(design.design_id).parameters


def test_bad_json_and_model_failure_are_not_silently_faked():
    raw = {"raw": SimpleNamespace(content="not json"),
           "parsed": None, "parsing_error": ValueError("bad")}
    extractor = LLMExtractor(SimpleNamespace(invoke=lambda _: raw))
    with pytest.raises(ValueError, match="JSON response invalid"):
        extractor.extract("轴径100mm")
    assert extractor.last_recovery is None

    def offline(_):
        raise RuntimeError("provider-unavailable")

    extractor = LLMExtractor(SimpleNamespace(invoke=offline))
    with pytest.raises(RuntimeError, match="provider-unavailable"):
        extractor.extract("轴径100mm")


def test_oversized_json_envelope_cannot_be_partially_applied():
    raw = {"raw": SimpleNamespace(content=json.dumps(
        {"proposals": [{"kind": "unknown"}] * 25,
    )), "parsed": None, "parsing_error": ValueError("bad")}
    extractor = LLMExtractor(SimpleNamespace(invoke=lambda _: raw))
    with pytest.raises(ValueError, match="envelope invalid"):
        extractor.extract("轴径100mm")
