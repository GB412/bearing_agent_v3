"""Regression tests for malformed real-model JSON without real API or fake planner fallback."""

import json
from types import SimpleNamespace

import pytest

from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.requirements.extraction import LLMExtractor
from bearing_agents.requirements.interaction import InteractionService


def _raw_reply(payload):
    return {
        "raw": SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)),
        "parsed": None,
        "parsing_error": ValueError("invalid model proposal kind"),
    }


def _spanned(text, quote, **fields):
    index = text.index(quote)
    return {"quote": quote, "start": index, "end": index + len(quote), **fields}


def test_invalid_model_kinds_allow_only_verified_original_text_recovery(tmp_path):
    text = (
        "先按油润滑圆柱径向动压滑动轴承考虑。"
        "轴径是100毫米，转速1500转/分，载荷我还没查到。"
    )
    payload = {"proposals": [
        _spanned(
            text, "圆柱径向动压滑动轴承", kind="scope", field_id="supported",
            value="cylindrical_radial_hydrodynamic",
        ),
        _spanned(
            text, "轴径是100毫米", kind="diameter", field_id="journal_diameter",
            value=100, unit="mm",
        ),
        _spanned(
            text, "转速1500转/分", kind="speed", field_id="rotational_speed",
            value=1500, unit="rpm",
        ),
    ]}
    model = SimpleNamespace(invoke=lambda _: _raw_reply(payload))
    extractor = LLMExtractor(model)
    manager = StateManager(SQLiteStateRepository(tmp_path / "model.sqlite"))
    interaction = InteractionService(manager, actor="engineer", extractor=extractor.extract)
    design = interaction.create_design()
    _, view = interaction.submit_turn(design.design_id, text, "second-user-turn")
    state = manager.get_design(design.design_id)
    assert state.target_scope == "cylindrical_radial_hydrodynamic"
    assert state.parameters["journal_diameter"].value == 100
    assert state.parameters["rotational_speed"].value == 1500
    assert all(item.verified_source_ref for item in state.parameters.values())
    assert "load" not in state.parameters
    assert not view.input_ready
    assert extractor.last_recovery == {
        "invalid_proposals": 2, "recovered_from_text": 2,
    }


def test_recovery_never_promotes_an_uncertain_model_value(tmp_path):
    text = "载荷大约12kN，轴径100mm"
    payload = {"proposals": [
        _spanned(
            text, "载荷大约12kN", kind="parameter", field_id="load",
            value=12, unit="kN", modality="EXPLICIT",
        ),
        _spanned(text, "轴径100mm", kind="diameter", field_id="journal_diameter",
                 value=100, unit="mm"),
    ]}
    extractor = LLMExtractor(SimpleNamespace(invoke=lambda _: _raw_reply(payload)))
    manager = StateManager(SQLiteStateRepository(tmp_path / "uncertain.sqlite"))
    interaction = InteractionService(manager, actor="engineer", extractor=extractor.extract)
    design = interaction.create_design()
    interaction.submit_turn(design.design_id, text, "uncertain-turn")
    state = manager.get_design(design.design_id)
    assert "load" not in state.parameters
    assert state.parameters["journal_diameter"].value == 100
    assert not state.parameters["journal_diameter"].confirmed_by


def test_malformed_non_json_model_output_remains_a_failure():
    reply = {
        "raw": SimpleNamespace(content="invalid json response"),
        "parsed": None,
        "parsing_error": ValueError("cannot parse"),
    }
    extractor = LLMExtractor(SimpleNamespace(invoke=lambda _: reply))
    with pytest.raises(ValueError, match="JSON response invalid"):
        extractor.extract("轴径100mm")
    assert extractor.last_recovery is None


def test_model_connection_error_is_not_swallowed_or_faked():
    def offline(_prompt):
        raise RuntimeError("remote-model-failure")

    extractor = LLMExtractor(SimpleNamespace(invoke=offline))
    with pytest.raises(RuntimeError, match="remote-model-failure"):
        extractor.extract("轴径100mm")
    assert extractor.last_recovery is None


def test_oversized_raw_proposal_batch_is_rejected():
    reply = _raw_reply({"proposals": [{"kind": "unknown"} for _ in range(25)]})
    extractor = LLMExtractor(SimpleNamespace(invoke=lambda _: reply))
    with pytest.raises(ValueError, match="JSON envelope invalid"):
        extractor.extract("轴径100mm")
    assert extractor.last_recovery is None
