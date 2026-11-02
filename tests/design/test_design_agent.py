from bearing_agents.design.agent import DesignAgent
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.operating_cases import OperatingCase
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.state import DesignState


def ready_state():
    state = DesignState(design_id="design-test")
    state.parameters = {
        "journal_diameter": ParameterRecord(value=100, unit="mm", role=ParameterRole.FIXED_INPUT,
            status=ParameterStatus.PROVIDED, verified_source_ref="user-message-1"),
        "load": ParameterRecord(value=12000, unit="N", role=ParameterRole.FIXED_INPUT,
            status=ParameterStatus.PROVIDED, verified_source_ref="user-message-1"),
        "rotational_speed": ParameterRecord(value=1500, unit="rpm", role=ParameterRole.FIXED_INPUT,
            status=ParameterStatus.PROVIDED, verified_source_ref="user-message-1"),
    }
    state.operating_cases = [OperatingCase(case_id="steady-1",
        journal_diameter_ref="journal_diameter", load_ref="load", speed_ref="rotational_speed",
        is_steady_state=True, verified_source_ref="user-message-1")]
    return state


def test_condition_analysis_derives_surface_speed_without_engineering_verdict():
    result = DesignAgent().analyze_conditions(ready_state())
    assert result.input_ready
    assert abs(result.derived_metrics["surface_speed"]["value"] - 7.853981633974483) < 1e-12
    assert "not a pass/fail limit" in result.derived_metrics["surface_speed"]["meaning"]
    assert result.knowledge_refs


def test_default_draft_rules_do_not_generate_numeric_recommendations():
    agent = DesignAgent()
    state = ready_state()
    proposal = agent.propose_candidate(state, agent.build_strategy(state))
    assert proposal.status == "INSUFFICIENT_RULES"
    assert proposal.parameters == {}
    assert set(proposal.unresolved_parameters) == {
        "bearing_width", "radial_clearance", "material", "lubricant",
    }


def test_mean_pressure_is_not_calculated_without_width():
    result = DesignAgent().analyze_conditions(ready_state())
    assert "mean_pressure" not in result.derived_metrics


def test_mean_pressure_is_explicitly_projected_mean_pressure():
    state = ready_state()
    state.parameters["bearing_width"] = ParameterRecord(value=50, unit="mm",
        role=ParameterRole.DESIGN_VARIABLE, status=ParameterStatus.SUGGESTED)
    result = DesignAgent().analyze_conditions(state)
    assert result.derived_metrics["mean_pressure"]["value"] == 2_400_000
    assert "not local maximum" in result.derived_metrics["mean_pressure"]["meaning"]
