# Bearing Agents

PR-01 domain foundation for a cylindrical radial hydrodynamic journal bearing design assistant.
The project does not call an LLM, implement Agents or a LangGraph workflow, load engineering
limits, or connect DLAP.

## Requirements

- Python 3.11 or newer

## Install and test

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pytest
ruff check .
```

## Minimal use

```python
from bearing_agents.core.state_manager import StateManager
from bearing_agents.infra.state_repository import SQLiteStateRepository
from bearing_agents.domain.parameters import ParameterRecord
from bearing_agents.domain.enums import ParameterRole, ParameterStatus
from bearing_agents.domain.write_context import WriteContext, WriterKind

manager = StateManager(SQLiteStateRepository("bearing-designs.sqlite3"))
design = manager.create_design(user_goal="Create a new bearing design")
design = manager.apply_patch(
    design.design_id,
    expected_version=design.state_version,
    patch={
        "source": "user",
        "parameter_changes": {
            "journal_diameter": ParameterRecord(
                value=100,
                unit="mm",
                role=ParameterRole.FIXED_INPUT,
                status=ParameterStatus.PROVIDED,
                source="user",
            )
        }
    },
    context=WriteContext(kind=WriterKind.USER, actor="designer"),
)
print(manager.get_design(design.design_id).parameters["journal_diameter"])
```

The same example can be exercised offline with `python -m pytest -q tests/test_readme_smoke.py`.

All engineering values must carry explicit units and provenance. An empty design contains no
invented geometry, load, speed, or operating case. The SQLite file is the local authoritative
domain-state repository; it is not a conversational memory implementation.

