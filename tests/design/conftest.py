from contextlib import ExitStack

import pytest

from bearing_agents.core.state_manager import StateManager
from bearing_agents.domain.write_context import WriteContext, WriterKind
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.orchestration.workflow import open_runtime

USER = WriteContext(kind=WriterKind.USER, actor="offline-user")


@pytest.fixture
def manager(tmp_path):
    return StateManager(SQLiteStateRepository(tmp_path / "domain.sqlite"))


def seed_ready(manager, *, missing_load=False):
    design = manager.create_design()
    parameters = {
        name: {"value": value, "unit": unit, "role": "FIXED_INPUT", "status": "PROVIDED"}
        for name, value, unit in (("journal_diameter", 100, "mm"),
                                  ("rotational_speed", 1500, "rpm"), ("load", 12000, "N"))
        if not (missing_load and name == "load")
    }
    return manager.apply_patch(design.design_id, 0, {
        "source": "SYNTHETIC_WORKFLOW", "parameter_changes": parameters,
        "operating_case_changes": [{"case_id": "nominal", "is_steady_state": True,
                                    "journal_diameter_ref": "journal_diameter",
                                    "speed_ref": "rotational_speed", "load_ref": "load"}],
    }, context=USER)


@pytest.fixture
def ready(manager):
    return seed_ready(manager)


@pytest.fixture
def missing_load(manager):
    return seed_ready(manager, missing_load=True)


@pytest.fixture
def runtime_factory(manager, tmp_path):
    with ExitStack() as stack:
        def factory(**kwargs):
            return stack.enter_context(open_runtime(
                manager, tmp_path / "checkpoint.sqlite", **kwargs,
            ))
        yield factory
