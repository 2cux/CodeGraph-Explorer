# CodeGraph Find Workflow

Use this workflow to find functions, classes, methods, routes, services, or
framework entry points.

## Rules

- Do not start with Grep.
- First check index health with `codegraph_repo_status`.
- Then call `codegraph_find`.
- If a symbol is found, inspect `codegraph_get_neighbors`.
- If you plan to modify it, call `codegraph_get_impact`.
- Use Read only after CodeGraph identifies the file and line range.
- If CodeGraph returns no results, adjust `query`, `types`, or `paths`
  before falling back to Grep.

## Expected Flow

1. `codegraph_repo_status` — verify index is fresh
2. `codegraph_find(query="...")` — locate the symbol
3. `codegraph_get_neighbors(symbol="...")` — explore relationships
4. `codegraph_get_impact(symbol="...")` — if you plan to edit
5. Read — only the exact source identified by CodeGraph

## Anti-Patterns

- ❌ Grep for a function name, then Read the file, then optionally call
  `codegraph_find` to confirm
- ❌ Use `codegraph_find` once, then ignore the result and Grep anyway
- ❌ Give up after one `codegraph_find` call with no results — try adjusting
  `types` or `paths` first

## Degradation

If `codegraph_find` returns no results:
1. Check `codegraph_repo_status` to confirm the index covers the right project
2. Try broadening the query or removing `paths`/`types` filters
3. Try `codegraph_search_symbols` with a different query strategy
4. Only then fall back to Grep as a last resort
