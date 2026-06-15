# CodeGraph Impact Workflow

Use this workflow before editing shared code, public APIs, routes, services,
types, or framework entry points.

## Rules

- Do not start with broad Grep/Glob/Read.
- First check index health with `codegraph_repo_status`.
- If planned files are known, call `codegraph_pre_edit_check`.
- If a specific symbol is known, call `codegraph_get_impact`.
- If relationships are unclear, call `codegraph_get_neighbors`.
- Use Read only after CodeGraph identifies the relevant files or symbols.
- If CodeGraph reports stale index or wrong project root, stop and ask the
  user to refresh or fix binding.
- Do not auto-edit code unless the user explicitly asks.

## Expected Flow

1. `codegraph_repo_status` — verify index is fresh and project root is correct
2. `codegraph_pre_edit_check(files=[...])` — if you have a list of planned files
   or `codegraph_get_impact(symbol="...")` — if you know the specific symbol
3. `codegraph_get_neighbors(symbol="...")` — if impact relationships are still unclear
4. Read — only for the highest-impact files, only the exact lines needed
5. Summarize risk before editing

## Anti-Patterns

- ❌ Grep for callers, then Grep for callees, then Read all files
- ❌ Call `codegraph_get_impact` once and then ignore the results, reading files manually
- ❌ Skip `codegraph_pre_edit_check` and go straight to editing
- ❌ Edit without understanding the blast radius

## Degradation

If `codegraph_repo_status` reports the index is missing or stale:
- Ask the user to run `codegraph init` or `codegraph init --incremental`
- Do not proceed with blind Grep/Read — the user needs a working index first

## CLI Fallback

If MCP tools are unavailable or fail to connect, use the backend CLI fallback:

```text
codegraph workflow impact --files <planned files> --change-type <type>
```

Prefer MCP tools inside Claude Code when available.
Use CLI fallback only when MCP is unavailable or when the user asks for a deterministic report.
