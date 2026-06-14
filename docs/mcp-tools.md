# MCP Tools Reference

CodeGraph Explorer exposes 9 MCP tools for AI coding agents to query the code graph.

## Tool Overview

| Tool | Purpose | Key Parameters |
|------|---------|---------------|
| `codegraph_search_symbols` | Search symbols by name, type, tag, or path | `query`, `types`, `paths`, `exact`, `fuzzy`, `limit` |
| `codegraph_get_symbol` | Get symbol details (location, signature, metadata) | `symbol_id`, `include_source`, `source_mode` |
| `codegraph_get_callers` | Query upstream callers of a symbol | `symbol_id`, `depth`, `include_tests`, `mode` |
| `codegraph_get_callees` | Query downstream callees of a symbol | `symbol_id`, `depth`, `mode` |
| `codegraph_get_neighbors` | Get local subgraph around a symbol | `symbol_id`, `depth`, `direction`, `edge_types`, `mode` |
| `codegraph_get_impact` | Analyze modification impact | `symbol_id`, `depth`, `impact_mode`, `mode` |
| `codegraph_repo_status` | Check index freshness | — |
| `codegraph_repo_summary` | Repository graph statistics | — |
| `codegraph_build_context_pack` | Generate Evidence Pack snapshot | `task`, `max_tokens`, `depth`, `mode` |

## Response Modes

All tools support two response modes:

- **`compact`** (default): Returns minimal JSON with key fields only — `symbol_id`, `file_path`, `confidence`, `resolution`, `reason_codes`. Designed to minimize MCP payload.
- **`standard`**: Returns full details including evidence text, source code, and explanations.

## Symbol Resolution

Tools that accept a `symbol_id` support two input modes:

- **Direct**: Pass an exact symbol ID (e.g. `"app/api/auth.py::login"`)
- **Fuzzy**: Pass a symbol name with `resolve=true` and optional `expected_type`/`path_hint`

Example fuzzy lookup:

```json
{
  "symbol": "login",
  "resolve": true,
  "expected_type": "function",
  "path_hint": "app/api"
}
```

## Tool Details

### search_symbols

Search for code symbols by name, file path, or tags.

```json
{
  "query": "auth",
  "types": "function,method",
  "paths": "app/api/**",
  "exact": false,
  "fuzzy": true,
  "exclude_tests": true,
  "limit": 10
}
```

Uses FTS5 for exact/LIKE matching, falls back to fuzzy matching when needed.

### get_symbol

Get detailed information about a symbol.

```json
{
  "symbol_id": "app/api/auth.py::login",
  "include_source": false,
  "source_mode": "signature"
}
```

Source modes: `"signature"` (default), `"body"`, `"surrounding"`.

### get_callers / get_callees

Traverse call relationships. `get_callers` answers "Who calls this symbol?" — use instead of grep for reference and upstream dependency lookup. `get_callees` answers "What does this symbol call or depend on?" — use before manually reading implementation dependencies.

```json
{
  "symbol_id": "app/api/auth.py::login",
  "depth": 2,
  "include_tests": false,
  "min_confidence": 0.6,
  "mode": "quick"
}
```

### get_neighbors

Answers "What is connected to this symbol?" Get the local subgraph centered on a symbol. Use before reading multiple related files.

```json
{
  "symbol_id": "app/api/auth.py::login",
  "depth": 1,
  "direction": "both",
  "edge_types": "calls,tested_by,imports,references",
  "max_nodes": 25,
  "mode": "review"
}
```

Compact mode groups neighbors by role (callers, callees, tests, imports, external).

### get_impact

Answers "If I change this symbol, what might break?" Analyze what might be affected by modifying a symbol. Use before editing shared code, public APIs, routes, services, or framework entry points.

```json
{
  "symbol_id": "app/api/auth.py::login",
  "depth": 2,
  "impact_mode": "conservative",
  "include_tests": true,
  "mode": "review"
}
```

Returns:
- **Confirmed impact**: Direct upstream/downstream with high confidence
- **Possible impact**: Low-confidence or indirect relationships
- **Related tests**: Tests associated with affected symbols
- **External calls**: Unresolved references outside the indexed codebase

Impact modes:
- `"conservative"`: Direct relationships only
- `"balanced"`: Depth=2, includes config/model dependencies via imports

### repo_status

Check if the index is fresh, stale, missing, or has errors. Each MCP response also includes an `index_status` and `index_health` field so agents can detect stale data.

### repo_summary

Get high-level statistics: file count, symbol count, type breakdown, edge count, low-confidence edge ratio, top modules, entry point candidates, test coverage signal.

### build_context_pack

Generate an optional task-oriented evidence snapshot. See [Evidence Pack docs](evidence-pack.md).

Supports a progressive pipeline via the `mode` parameter:

| mode | Description |
|------|-------------|
| `summary` (default) | Key insights only — entry points, related symbols, call graph summary, impact, tests |
| `full` | Complete JSON output with all evidence fields |
| `markdown` | Export to markdown file, returns file path |
| `scan` | Lightweight entry point discovery (Stage 1 of progressive pipeline) |
| `deepen` | Local relationships and source snippets around scan entry points (Stage 2 of progressive pipeline) |

## Progressive Context Pack

`codegraph_build_context_pack` supports a progressive 3-stage pipeline: **scan → deepen → impact**. This lets agents start light with entry point discovery, progressively deepen local context, and finally check blast radius before editing — all without loading a full context pack up front.

Use scan mode when the task is broad and you want entry points first:

Use scan mode when the task is broad and you want entry points first:

```text
codegraph_build_context_pack(task="fix MemoryService bug", mode="scan")
```

Scan mode returns:

- **`entry_points`** (3–5): Likely entry point symbols with file, line range, reason, and confidence
- **`related_files`** (3–5): Files related to the entry points
- **`summary`**: Short human-readable summary of findings
- **`next_token`**: Opaque token for `mode=deepen` — pass this to the next stage

It avoids returning a large context pack up front — no subgraph, no impact analysis, no source snippets. The goal is to help the agent pick the right entry point before deepening.

### Deepen mode

After scan mode returns entry points and a `next_token`, use deepen mode to inspect local relationships and source snippets around the selected entry point.

```text
codegraph_build_context_pack(
  task="fix MemoryService bug",
  mode="deepen",
  next_token="..."
)
```

Deepen mode returns:

- **`selected_entry_points`**: Resolved entry point symbols with file and line range
- **`local_relationships`**: Local callers, callees, neighbors, and related tests around the entry points (each limited to ~5)
- **`related_files`**: Files related to the entry points and their relationships
- **`source_snippets`** (3–5): Bounded source snippets for entry points and high-confidence related symbols — each snippet includes symbol, file, line_start, line_end, reason, and snippet text
- **`summary`**: Short human-readable summary of what was found
- **`next_token`**: New token for a future impact-stage analysis (carries forward entry points + newly discovered relationship symbols)
- **`next_recommended_tools`**: Recommends `get_impact` and optionally `get_neighbors` — only existing tools, no unimplemented modes

It does NOT return full impact analysis, full subgraph, or complete source files. The output is more focused than `mode=full` but richer than `mode=scan`.

`mode=full` and `mode=summary` remain available for backward compatibility.

### Impact mode

After scan and deepen, use impact mode to check what may be affected before editing.

```text
codegraph_build_context_pack(
  task="fix MemoryService bug",
  mode="impact",
  next_token="..."
)
```

Impact mode returns:

- **`selected_symbols`**: Symbols carried forward from the deepen stage, with file and reason
- **`impact_summary`**: Aggregate risk assessment with `risk_level` (low/medium/high/critical/unknown), `confidence`, and a human-readable `summary`
- **`affected_callers`**: Upstream callers that would be affected by modifying the selected symbols (capped at 10)
- **`affected_files`**: Files that would be affected, with reason and priority (capped at 10)
- **`affected_tests`**: Related tests that may cover the affected behavior (capped at 5)
- **`source_snippets`** (0–3): Limited source snippets for selected symbols and highest-confidence affected callers/tests — each snippet includes symbol, file, line_start, line_end, reason, and snippet text
- **`recommended_verification`** (0–5): Suggested verification steps — either `type=test` (run existing tests) or `type=read` (read affected caller files). Never invents non-existent test files
- **`summary`**: Short human-readable summary
- **`next_recommended_tools`**: Recommends `get_neighbors` only if the impact picture is still insufficient — does NOT create scan/deepen/impact cycles

Impact mode reuses the existing `codegraph_get_impact` analysis under the hood, wrapping its results into the progressive context pack pipeline. It does NOT return full repository subgraph, unlimited call chains, or complete file source code.

The `next_token` must come from a `mode=deepen` call. If a `mode=scan` token is passed, impact mode degrades gracefully with a warning — it will still run the analysis but with less context than ideal.

## Recommended Agent Workflow

When working in a codebase indexed by CodeGraph, follow this workflow instead of grep/glob/read-heavy exploration:

1. **`codegraph_repo_status`** — First, confirm the index is available, fresh, and healthy before relying on results.
2. **`codegraph_build_context_pack`** — Default first tool for larger code investigation, bug fixing, feature implementation, refactoring, or impact analysis. Takes a natural language task description and returns relevant entry points, symbols, relationships, impact signals, and suggested tests.
3. **`codegraph_repo_summary`** — Understand repository structure, languages, frameworks, entry points, and symbol/edge breakdown.
4. **`codegraph_search_symbols`** — Find functions, classes, methods, routes, and framework entry points by name, type, tag, or path.
5. **`codegraph_get_neighbors`** — Inspect local relationships around a symbol (callers, callees, tests, models, config).
6. **`codegraph_get_callers` / `codegraph_get_callees`** — Trace call chains instead of grep for call/reference lookup.
7. **`codegraph_get_impact`** — Before modifying shared code, understand confirmed and possible impact, and what tests cover it.
8. **`Read`** — Only when exact source text is needed.

### When to use each tool

| Tool | Use when... |
|------|-------------|
| `codegraph_repo_status` | First, check index is available, fresh, and healthy before relying on results |
| `codegraph_build_context_pack` | Default first tool for larger code modification or investigation tasks — returns task-aware context instead of broad grep/glob |
| `codegraph_repo_summary` | Entering a repository, before glob/grep for structure overview |
| `codegraph_search_symbols` | Looking for functions, classes, methods, routes, before grep |
| `codegraph_get_symbol` | You need exact metadata and location for a symbol, after search_symbols |
| `codegraph_get_callers` | Finding who calls or references a symbol, instead of grep. Use `mode=quick` for fast lookup. |
| `codegraph_get_callees` | Understanding what a symbol depends on or calls, instead of manual Read/grep. Use `mode=deep` for broader exploration. |
| `codegraph_get_neighbors` | Exploring local relationships around a symbol, before reading multiple files. Use `mode=review` before code changes. |
| `codegraph_get_impact` | Before modifying shared code — understand confirmed and possible impact. Use `mode=review` before committing. |
| `Read` | Only when exact source text is needed beyond what CodeGraph returns |

## Common Modes

The four high-frequency query tools (`get_callers`, `get_callees`, `get_neighbors`, `get_impact`) support an optional `mode` parameter with three presets:

| Mode | Purpose | Characteristics |
|------|---------|----------------|
| `quick` | Fast lookup, good replacement for grep | Shallow depth, compact output, small result limit, no explanations |
| `deep` | Broader graph traversal for architecture or dependency exploration | Deeper depth, larger result limits, includes explanations |
| `review` | Richer context before code changes, useful for bug fixes, refactors, and code review | Medium depth, includes tests and explanations, medium result limits |

### Quick Examples

```text
Who calls this?
→ codegraph_get_callers(symbol="MemoryService", mode="quick")

What does this depend on?
→ codegraph_get_callees(symbol="MemoryService", mode="quick")

What is connected to this?
→ codegraph_get_neighbors(symbol="MemoryService", mode="quick")

What might break if I edit this?
→ codegraph_get_impact(symbol="MemoryService", mode="quick")
```

### Advanced Parameter Override

When `mode` is set, advanced parameters (e.g. `depth`, `min_confidence`, `include_tests`) can still override the mode defaults:

```json
{
  "symbol": "MemoryService",
  "mode": "quick",
  "depth": 3
}
```

### `next_recommended_tools` in Quick Mode

When `mode=quick` returns many results or potential impact, the response may include `next_recommended_tools` — lightweight suggestions (up to 2) for the next useful CodeGraph call. For example:

```json
{
  "next_recommended_tools": [
    {
      "tool": "codegraph_get_impact",
      "reason": "This symbol has 8 caller(s). Run impact analysis before editing."
    }
  ]
}
```

This helps agents discover the right follow-up tool without reading docs.

## Tool Description Style

CodeGraph tool descriptions are example-first because coding agents often respond better to concrete calls than long steering text.

Quick reference for common questions:

```text
Find a function:
→ codegraph_search_symbols(query="login", types="function")

Understand a symbol:
→ codegraph_get_neighbors(symbol="MemoryService")

Who calls this?
→ codegraph_get_callers(symbol="MemoryService.findRelatedCCRs")

What does this call?
→ codegraph_get_callees(symbol="MemoryService")

What might break if I edit this?
→ codegraph_get_impact(symbol="MemoryService")

Which project is this?
→ codegraph_repo_status()

What is this repo made of?
→ codegraph_repo_summary()

Start a larger task:
→ codegraph_build_context_pack(task="fix MemoryService bug")
```

## CodeGraph vs Grep / Read

Use CodeGraph for code navigation:
- finding symbols
- following callers and callees
- inspecting local relationships
- checking impact before edits
- avoiding broad file-by-file exploration

Use Grep / Read for:
- exact source text
- raw text patterns
- confirming implementation details
- editing a specific file

CodeGraph should guide what to read next; it does not replace reading exact source when needed.

## Design Principles

- **Compact by default**: Tools return minimal JSON; request `standard` mode for full details
- **Confidence-aware**: All inferred edges carry `confidence` and `resolution` fields
- **No reading_plan / agent_instructions**: Tools don't tell agents how to work — they only provide structured code facts
- **Index freshness exposed**: Every response includes index status so agents know if data is current
