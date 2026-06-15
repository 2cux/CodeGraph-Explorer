# CodeGraph Test Audit Workflow

Use this workflow to find production symbols or files that appear to lack
test coverage signals.

## Rules

- Do not start with Glob/Read over tests.
- First check index health with `codegraph_repo_status`.
- Then call `codegraph_coverage_gaps`.
- Use `codegraph_explain` for unclear production symbols.
- Use `codegraph_get_neighbors` to inspect `tested_by` or related edges.
- Read test files only after CodeGraph identifies likely gaps.
- Remember: CodeGraph coverage gaps are heuristic graph signals, not runtime
  line coverage. They indicate which symbols lack `tested_by` edges in the
  code graph — not which lines are actually exercised at runtime.

## Expected Flow

1. `codegraph_repo_status` — verify index is fresh
2. `codegraph_coverage_gaps` — get the list of symbols without test signal
3. `codegraph_explain(symbol="...")` or `codegraph_get_neighbors(symbol="...")`
   — for the top uncovered symbols
4. Read — only the exact test files or source lines when needed
5. Summarize missing coverage candidates

## Anti-Patterns

- ❌ Glob for `test_*.py` or `*.test.ts`, then Read each one
- ❌ Assume `coverage_gaps` result means runtime line coverage is missing
- ❌ Ignore low-confidence `tested_by` edges entirely
- ❌ Open every uncovered file at once — prioritize by risk

## Degradation

If `codegraph_coverage_gaps` returns empty but you suspect gaps exist:
- Check `codegraph_repo_status` for index staleness
- Try `codegraph_find` for specific symbols you suspect are untested
- Use `codegraph_get_neighbors` on key production symbols to inspect
  `tested_by` edges manually
