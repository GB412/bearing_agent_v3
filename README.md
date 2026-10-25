# Bearing Agents

PR-01 domain foundation, PR-02 controlled LangGraph runtime and PR-03 trusted
multi-turn requirements gathering for a cylindrical radial hydrodynamic journal
bearing design assistant. FakePlanner/FakeAgent demonstrate
safe workflow execution. Real LLM planning is opt-in; the default execution stays
fully offline. The project does not load engineering limits, recommend bearing
geometry/materials, perform formal prechecks, or connect DLAP.

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


## PR-03 trusted requirements interaction

PR-03 adds local multi-turn requirement capture (not a production login system).
New language-first designs begin with `target_scope="unknown"`; they cannot
silently assume the PR-01 default V1 design scope. Parameter values from users
are extracted as *untrusted proposals*, verified against the immutable original
message and unit registry, then committed through StateManager. Missing inputs
drive bounded, deterministic questions.

```powershell
python examples/pr03_multiturn_demo.py
python examples/pr03_requirements_cli.py --db pr03_requirements.sqlite
python -m pytest -q tests/requirements tests/orchestration
```

The CLI prints the design ID. Reopen its database and pass
`--design-id <id>` to continue after a restart. Commands include
`:show`, `:correct journal_diameter 1 轴径120mm`,
`:confirm journal_diameter 2`, `:approve <constraint-id> 1`,
`:reject <constraint-id> 1`, and `:quit`. Explicit revision numbers
protect against stale confirmations and corrections.

Default requirement extraction is deterministic and offline. For explicitly
opt-in real-model extraction, install `.[llm]`, configure the existing
`BEARING_LLM_ENABLED`, `BEARING_LLM_API_KEY` and
`BEARING_LLM_BASE_URL` variables plus `BEARING_REQUIREMENTS_MODEL`
(or `BEARING_PLANNER_MODEL`), and add `--llm` to the CLI command.
Provider compatibility and extraction accuracy are **not** established by
stub/offline tests. LLM output cannot grant identity, approval, trusted
provenance or engineering readiness.

`InteractionService.submit_turn` stores the immutable message first.
After deterministic evidence verification, StateManager validates the patch.
The engineering state, StateEvent and interaction receipt are stored in one
business SQLite transaction with operation-ID deduplication. Retrying an
already committed user turn does not duplicate engineering effects.
Ordinary chat turns never call LangGraph's confirmation `resume()`.

`Runtime` can accept `RequirementsAgent` in the existing
`requirements_fake` executor slot; the runtime exposes bounded
`questions` as visible output when `clarify_requirement` executes.
No new supervisor or engineering state machine was created. See
`docs/pr03_acceptance.md` for R01–R20, recovery tests and limitations.

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

## PR-02B real LLMPlanner (opt-in)

Install the optional adapter with `python -m pip install -e ".[dev,llm]"`.
The default Runtime uses `FakePlanner` and never calls an external API.
For a real model, configure these **process-local** environment variables:

- `BEARING_LLM_ENABLED=true` (required opt-in)
- `BEARING_LLM_API_KEY` (secret; never store in Git, chat or console command history)
- `BEARING_LLM_BASE_URL` (OpenAI-compatible Chat Completions endpoint, e.g. `https://api.deepseek.com`)
- `BEARING_PLANNER_MODEL` (a model ID supported by the provider)

In PowerShell, set the non-secret values with `$env:BEARING_LLM_ENABLED = "true"`
and analogous assignments. Input the key interactively with
`Read-Host "API Key" -AsSecureString`, then securely convert it to the
process environment variable. Do not paste a literal key into the terminal command.
This adapter uses `json_mode` structured output with Pydantic validation,
`timeout=120` seconds, and zero SDK retries (the planner itself allows at most
one bounded retry). Provider compatibility still requires real smoke testing.

Run `python examples/pr02b_llm_planner_demo.py` for a synthetic LangGraph run, or
`python examples/pr02b_real_experiment.py .venv/pr02b_results.jsonl` to run
B01–B07 manually. The latter makes paid API calls, records real Guard verdicts,
and reports **interface validation separately from planner oracle accuracy**.
`REAL_LLM_VALIDATED` means the model responded with valid proposals for all
fixtures; `planning_acceptance` reports the independent small-sample ≥85%
prototype reference threshold. Neither implies engineering validation.
See `docs/pr02b_acceptance.md` for reproducibility and known limitations.
