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

## Design Principles

- **Compact by default**: Tools return minimal JSON; request `standard` mode for full details
- **Confidence-aware**: All inferred edges carry `confidence` and `resolution` fields
- **No reading_plan / agent_instructions**: Tools don't tell agents how to work — they only provide structured code facts
- **Index freshness exposed**: Every response includes index status so agents know if data is current
