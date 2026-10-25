# Bearing Agents

PR-01 domain foundation and PR-02 controlled offline LangGraph runtime for a cylindrical
radial hydrodynamic journal bearing design assistant. FakePlanner/FakeAgent demonstrate
safe workflow execution. The project does not call an LLM, load engineering limits,
recommend bearing geometry/materials, perform formal prechecks, or connect DLAP.

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

## PR-02 offline runtime

```powershell
python examples/pr02_fake_dynamic_demo.py
python examples/pr02_interrupt_recovery.py
python -m pytest -q tests/orchestration
```

The first command runs empty, missing-load and input-ready synthetic workflows.
The second pauses a version-bound demo task in one process and resumes it in a
different process with official persistent SQLite checkpoints. No API key is needed.
Numbers in these examples are test fixtures, not recommended engineering values.

For integration, use `open_runtime(manager, checkpoint_path)` from
`bearing_agents.orchestration.workflow`, then `runtime.invoke(design_id)`.
`runtime.recover(design_id)` replays an unfinished run; `runtime.resume(...)`
requires a trusted USER WriteContext supplied outside Agent/resume JSON. Approval
only completes a demonstration task, never an engineering parameter or candidate.
Inspect the returned bounded `trace` and `termination_reason`; waiting returns
LangGraph `__interrupt__` plus a confirmation request. A task plan projection is
available through `task_plan_view(manager.get_design(design_id))`.

Use separate business/checkpoint files and one serial runtime per design. Stable
operation IDs deduplicate task effects, including after commit/checkpoint failures.
Parameter/candidate writes do not yet have this guarantee. The existing PR-01
public APIs remain available and unchanged.

See [the orchestration contract](docs/protocols/orchestration_contract_v1.md) and
[PR-02 acceptance evidence](docs/pr02_acceptance.md) for F01–F12, limits and recovery commands.
Python 3.14 currently emits an upstream langchain-core warning on its Pydantic v1
compatibility import; this project uses Pydantic v2. Python 3.11 is also a CI target.

