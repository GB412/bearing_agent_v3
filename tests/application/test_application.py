from bearing_agents.application import open_application
from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository


def test_application_unifies_user_turn_requirements_and_supervisor(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "application-domain.sqlite"))

    with open_application(
        manager,
        tmp_path / "application-checkpoint.sqlite",
        actor="local-test-user",
    ) as application:
        design = application.create_design("圆柱径向动压滑动轴承初步设计")
        result = application.submit_turn(
            design.design_id,
            "轴径100mm，转速1500rpm，单一稳态",
            "application-turn-1",
        )

    assert result.receipt.design_id == design.design_id
    assert result.requirements.design_id == design.design_id
    assert not result.requirements.input_ready
    assert "load" not in manager.get_design(design.design_id).parameters
    assert result.execution["termination_reason"] == "MISSING_INPUT"
    assert result.execution["questions"]
    assert any(
        question["reason_code"] == "MISSING_LOAD"
        for question in result.execution["questions"]
    )


def test_requirements_agent_does_not_hold_a_state_manager():
    from bearing_agents.requirements.agent import RequirementsAgent

    agent = RequirementsAgent()
    assert not hasattr(agent, "manager")


def test_application_precheck_persists_the_exact_runtime_report(tmp_path):
    from bearing_agents.domain.enums import ParameterRole, ParameterStatus, PrecheckStatus
    from bearing_agents.domain.parameters import ParameterRecord
    from bearing_agents.domain.write_context import WriteContext, WriterKind

    manager = StateManager(SQLiteStateRepository(tmp_path / "precheck-domain.sqlite"))
    design = manager.create_design("precheck application integration")
    ready = manager.apply_patch(
        design.design_id,
        design.state_version,
        {
            "source": "SYNTHETIC_WORKFLOW",
            "parameter_changes": {
                "journal_diameter": {
                    "value": 100, "unit": "mm", "role": "FIXED_INPUT", "status": "PROVIDED",
                },
                "rotational_speed": {
                    "value": 1500, "unit": "rpm", "role": "FIXED_INPUT", "status": "PROVIDED",
                },
                "load": {
                    "value": 12000, "unit": "N", "role": "FIXED_INPUT", "status": "PROVIDED",
                },
            },
            "operating_case_changes": [{
                "case_id": "nominal", "is_steady_state": True,
                "journal_diameter_ref": "journal_diameter",
                "speed_ref": "rotational_speed", "load_ref": "load",
            }],
        },
        context=WriteContext(kind=WriterKind.USER, actor="precheck-user"),
    )
    ready = manager.apply_patch(
        design.design_id,
        ready.state_version,
        {"source": "trusted-user", "parameter_changes": {
            "bearing_width": ParameterRecord(
                value=60, unit="mm", role=ParameterRole.DESIGN_VARIABLE,
                status=ParameterStatus.PROVIDED,
            ),
        }},
        context=WriteContext(
            kind=WriterKind.USER,
            actor="precheck-user",
            verified_parameter_refs={"bearing_width": "width-evidence"},
        ),
    )

    with open_application(
        manager,
        tmp_path / "precheck-checkpoint.sqlite",
        actor="precheck-user",
    ) as application:
        generated = application.runtime.invoke(design.design_id)
        candidate = manager.get_design(design.design_id).candidate_designs[-1]
        result = application.precheck_candidate(
            design.design_id,
            f"candidate:{candidate.candidate_id}@{candidate.version}",
        )

    saved = manager.get_design(design.design_id).candidate_designs[-1]
    assert generated["termination_reason"] == "NEEDS_REVIEW"
    assert result["report"].status == PrecheckStatus.REVIEW_REQUIRED
    assert saved.precheck_status == PrecheckStatus.REVIEW_REQUIRED
    assert saved.precheck_report == result["report"]
    assert result["diagnosis"].candidate_ref == (
        f"candidate:{candidate.candidate_id}@{candidate.version}"
    )
    assert result["diagnosis"].precheck_status == PrecheckStatus.REVIEW_REQUIRED
    assert any(
        finding.kind == "RULE_COVERAGE_GAP"
        for finding in result["diagnosis"].findings
    )
