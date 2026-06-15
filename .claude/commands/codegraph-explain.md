# CodeGraph Explain Workflow

Use this workflow to understand a symbol or file before opening full source.

## Rules

- Do not start by reading the whole file.
- First check index health with `codegraph_repo_status`.
- Then call `codegraph_explain`.
- If relationships are needed, call `codegraph_get_neighbors`.
- If you plan to edit the symbol or file, call `codegraph_pre_edit_check`.
- Use Read only for exact source text after CodeGraph identifies the relevant
  lines.

## Expected Flow

1. `codegraph_repo_status` — verify index is fresh
2. `codegraph_explain(symbol="...")` or `codegraph_explain(file="...")`
   — get a structured, evidence-backed explanation
3. `codegraph_get_neighbors(symbol="...")` — if you need relationship context
4. `codegraph_pre_edit_check(files=[...])` — if you plan to edit
5. Read — only the exact source lines you need after the explanation

## Anti-Patterns

- ❌ Read the entire file, then call `codegraph_explain` to confirm what
  you already read
- ❌ Skip `codegraph_explain` and jump to `codegraph_get_neighbors`
- ❌ Edit without running `codegraph_pre_edit_check` first

## Degradation

If `codegraph_explain` returns low confidence or insufficient evidence:
- Use `codegraph_get_neighbors` to pull in more relationship context
- Read the exact source identified by `codegraph_explain`'s location data
- Do not fall back to reading the entire file from scratch
