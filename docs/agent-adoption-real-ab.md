# Real Agent A/B

## Goal

Do not infer adoption from feel or one-off anecdotes. Run a real A/B:

- `with_codegraph`: the agent is explicitly guided to use CodeGraph-first workflows
- `without_codegraph`: the control arm does not use CodeGraph

This complements `tests.agent_benchmark.runner`, which is still a synthetic benchmark.

## Required Task Set

Each round should include at least these 6 task types:

1. `bug_locate` — Use CodeGraph to locate likely code paths
2. `shared_type_refactor` — Use CodeGraph before refactoring shared type
3. `coverage_audit` — Find production symbols lacking tests
4. `explain_module` — Explain symbol/file before reading source
5. `trace_flow` — How does X reach Y
6. `route_service_impact` — Check impact before editing route/service

The fixed catalog lives in [tests/agent_benchmark/adoption_cases.json](../tests/agent_benchmark/adoption_cases.json).

## Metrics

Record these fields for every task in both arms:

- `first_tool`
- `codegraph_call_count`
- `consecutive_codegraph_calls`
- `read_grep_glob_before_codegraph`
- `read_grep_glob_after_codegraph`
- `workflow_used`
- `followed_next_recommended_tools`
- `fallback_used`
- `fallback_reason`
- `immediate_fallback_after_codegraph`
- `read_after_codegraph_targeted`
- `task_completed_seconds`
- `error_count`
- `test_failure_count`
- `control_repo_regressed`

## Workflow

1. Generate a blank observation sheet:

```bash
python -m tests.agent_benchmark.adoption --write-template --run-id 2026-06-15 --project your-project --agent codex
```

This writes `tests/agent_benchmark/results/agent_adoption_observations.json`.

2. Fill the rows while running the real A/B tasks.

3. Generate the report:

```bash
python -m tests.agent_benchmark.adoption
```

Output:

- `reports/agent_adoption_ab.md`

## Acceptance

The report evaluates these conditions per round:

- At least 3 task categories have `consecutive_codegraph_calls >= 2`
- The first CodeGraph call is not followed by immediate broad Read/Grep fallback
- Reads happen only after CodeGraph points to concrete files
- With-CodeGraph uses fewer manual scan calls than Without-CodeGraph
- The control repo did not regress

## Tool Surface Convergence

Do not remove tools before the A/B data exists.

Current rule:

- Small projects should expose only the main entry tools first
- Old tools can be soft-deprecated later
- Tool descriptions should keep steering agents toward higher-level entry points
- Workflows may continue reusing lower-level primitives internally

Keep these low-level primitives:

- `search_symbols`
- `get_symbol`
- `callers`
- `callees`
- `neighbors`
- `impact`

Prefer these high-level defaults:

- `find`
- `explain`
- `coverage_gaps`
- `pre_edit_check`
- `context_pack`
