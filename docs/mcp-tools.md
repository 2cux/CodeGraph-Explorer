# MCP Tools Reference

CodeGraph Explorer exposes 9 MCP tools for AI coding agents to query the code graph.

## Tool Overview

| Tool | Purpose | Key Parameters |
|------|---------|---------------|
| `codegraph_search_symbols` | Search symbols by name, type, tag, or path | `query`, `types`, `paths`, `exact`, `fuzzy`, `limit` |
| `codegraph_get_symbol` | Get symbol details (location, signature, metadata) | `symbol_id`, `include_source`, `source_mode` |
| `codegraph_get_callers` | Query upstream callers of a symbol | `symbol_id`, `depth`, `include_tests` |
| `codegraph_get_callees` | Query downstream callees of a symbol | `symbol_id`, `depth` |
| `codegraph_get_neighbors` | Get local subgraph around a symbol | `symbol_id`, `depth`, `direction`, `edge_types` |
| `codegraph_get_impact` | Analyze modification impact | `symbol_id`, `depth`, `impact_mode` |
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

Traverse call relationships. `get_callers` finds what calls the symbol (upstream), `get_callees` finds what the symbol calls (downstream).

```json
{
  "symbol_id": "app/api/auth.py::login",
  "depth": 2,
  "include_tests": false,
  "min_confidence": 0.6
}
```

### get_neighbors

Get the local subgraph centered on a symbol.

```json
{
  "symbol_id": "app/api/auth.py::login",
  "depth": 1,
  "direction": "both",
  "edge_types": "calls,tested_by,imports,references",
  "max_nodes": 25
}
```

Compact mode groups neighbors by role (callers, callees, tests, imports, external).

### get_impact

Analyze what might be affected by modifying a symbol.

```json
{
  "symbol_id": "app/api/auth.py::login",
  "depth": 2,
  "impact_mode": "conservative",
  "include_tests": true
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
| `codegraph_get_callers` | Finding who calls or references a symbol, instead of grep |
| `codegraph_get_callees` | Understanding what a symbol depends on or calls, instead of manual Read/grep |
| `codegraph_get_neighbors` | Exploring local relationships around a symbol, before reading multiple files |
| `codegraph_get_impact` | Before modifying shared code — understand confirmed and possible impact, tests, external dependencies |
| `Read` | Only when exact source text is needed beyond what CodeGraph returns |

## Design Principles

- **Compact by default**: Tools return minimal JSON; request `standard` mode for full details
- **Confidence-aware**: All inferred edges carry `confidence` and `resolution` fields
- **No reading_plan / agent_instructions**: Tools don't tell agents how to work — they only provide structured code facts
- **Index freshness exposed**: Every response includes index status so agents know if data is current
