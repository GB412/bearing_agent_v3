from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository


def test_readme_minimal_example_runs(tmp_path):
    manager = StateManager(SQLiteStateRepository(tmp_path / "bearing-designs.sqlite3"))
    design = manager.create_design(user_goal="Create a new bearing design")
    updated = manager.apply_patch(
        design.design_id,
        expected_version=design.state_version,
        patch={
            "source": "user",
            "parameters": {
                "journal_diameter": ParameterRecord(
                    value=100,
                    unit="mm",
                    role=ParameterRole.FIXED_INPUT,
                    status=ParameterStatus.PROVIDED,
                    source="user",
                )
            },
        },
        context=WriteContext(kind=WriterKind.USER, actor="designer"),
    )
    assert updated.parameters["journal_diameter"].value == 100
