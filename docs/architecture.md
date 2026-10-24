# PR-01 Architecture

The `domain` package owns typed Pydantic v2 contracts. `core` validates writes, normalizes unit
dimensions, and tracks dependency invalidation. `tools` contains pure deterministic calculations.
`infra` persists the authoritative `DesignState` in SQLite using compare-and-swap on
`state_version`. `agent_protocols` defines typed patch/result contracts and protocols only; it
does not instantiate agents or a graph runtime.

Design state is independent of chat history and can later be supplied to LangGraph nodes. Source,
approval, rule and event references remain explicit. The initial state intentionally contains no
operating cases, parameter values, engineering limits, or recommendations.

