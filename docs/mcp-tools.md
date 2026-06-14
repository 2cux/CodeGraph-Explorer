# MCP Tools Reference

CodeGraph Explorer exposes 13 MCP tools for AI coding agents to query the code graph.

## Tool Overview

| Tool | Purpose | Key Parameters |
|------|---------|---------------|
| `codegraph_find` | Find symbols + details in one call (preferred entry point) | `query`, `types`, `paths`, `include_details`, `limit`, `mode` |
| `codegraph_search_symbols` | Search symbols by name, type, tag, or path | `query`, `types`, `paths`, `exact`, `fuzzy`, `limit` |
| `codegraph_get_symbol` | Get symbol details (location, signature, metadata) | `symbol_id`, `include_source`, `source_mode` |
| `codegraph_get_callers` | Query upstream callers of a symbol | `symbol_id`, `depth`, `include_tests`, `mode` |
| `codegraph_get_callees` | Query downstream callees of a symbol | `symbol_id`, `depth`, `mode` |
| `codegraph_get_neighbors` | Get local subgraph around a symbol | `symbol_id`, `depth`, `direction`, `edge_types`, `mode` |
| `codegraph_get_impact` | Analyze modification impact for a specific symbol | `symbol_id`, `depth`, `impact_mode`, `mode` |
| `codegraph_pre_edit_check` | Check impact before editing planned files/symbols (task-level entry point) | `files`, `symbols`, `change_type`, `include_tests`, `limit` |
| `codegraph_explain` | Structured, evidence-backed explanation of a symbol or file | `symbol`, `file`, `include_snippet`, `include_tests`, `max_snippet_lines` |
| `codegraph_repo_status` | Check index freshness | — |
| `codegraph_repo_summary` | Repository graph statistics | — |
| `codegraph_coverage_gaps` | List production symbols/files without test coverage | `paths`, `types`, `include_low_confidence`, `limit` |
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

### codegraph_find

Use `codegraph_find` when you want symbol search plus enough detail to decide the next step.
This is the preferred entry point for common find-and-inspect workflows.

Examples:

```text
codegraph_find(query="login", types=["function"])
codegraph_find(query="MemoryService", include_details=true)
codegraph_find(query="api", types=["route"], paths=["src/**"])
codegraph_find(query="ReceiptService", mode="review")
```

`codegraph_find` fuses `codegraph_search_symbols` + `codegraph_get_symbol` into a single call.
It returns top matches with optional details (signature, docstring, tags, framework) and
optional source snippets (capped at 40 lines per snippet, with a `truncated` boolean flag).

`codegraph_find` is the preferred entry point for common find-and-inspect workflows.
It is backend-only — it does not use LLMs, does not open a dashboard, and does not
replace reading exact source when needed.

Parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | (required) | Symbol name to search for |
| `types` | string | `null` | Comma-separated node types, e.g. `"function,method,class"` |
| `paths` | string | `null` | Comma-separated path glob patterns, e.g. `"src/**,app/api/**"` |
| `limit` | int | 5 | Maximum results (max 20) |
| `include_details` | bool | true | Include signature, docstring, tags, framework per result |
| `include_snippets` | bool | false | Include limited source code snippets per result |
| `mode` | string | `"quick"` | `"quick"` (lightweight) or `"review"` (richer details with snippets) |
| `response_mode` | string | `"compact"` | `"compact"` or `"standard"` |

Mode presets:

| Mode | Purpose | Characteristics |
|------|---------|----------------|
| `quick` | Fast lookup, grep replacement | details=true, snippets=false, compact, limit=5 |
| `review` | Richer context before code changes | details=true, snippets=true, compact, limit=5 |

Each result includes `symbol`, `type`, `file`, `line_start`, `line_end`, `score`, and `reason`.
When `include_details=true`, each result also includes `details` (signature, doc, framework, tags).
When `include_details=false`, `details` is `null` in every result.
When `include_snippets=true` or `mode=review`, each result also includes a `snippet` block
with `file`, `snippet`, `line_start`, `line_end`, and `truncated` (boolean). Snippets are
capped at 40 lines per result; the `truncated` flag indicates whether content was cut off.

The response also includes:
- `summary`: A human-readable summary of findings
- `next_recommended_tools`: Suggests `get_neighbors` and `get_impact` when results found
- `codegraph_session`: Session tracking and hint
- `index_status` / `index_health`: Index freshness and health signals

Use `codegraph_search_symbols` when you only need a lightweight search result list.
Use `codegraph_get_symbol` when you already have an exact symbol and need detailed metadata.

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

### pre_edit_check

Use `codegraph_pre_edit_check` before editing files or symbols. It is the **task-level entry point** for impact analysis — you don't need to first map files to symbols manually.

**When to use:**
- Use `codegraph_pre_edit_check` when you know the files you plan to edit.
- Use `codegraph_get_impact` when you already know the exact symbol to analyze.

This is a backend MCP impact check. It does not edit files, run tests, install git hooks, or provide a dashboard.

Examples:

```text
codegraph_pre_edit_check(files="src/server.ts", change_type="refactor")
codegraph_pre_edit_check(symbols="startServer", change_type="cleanup")
codegraph_pre_edit_check(files="src/server.ts,src/toolSchemas.ts", description="extract tool schemas from server")
codegraph_pre_edit_check(symbols="login", include_tests=true, limit=50)
```

Parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `files` | string | `null` | Comma-separated file paths you plan to edit |
| `symbols` | string | `null` | Comma-separated symbol names you plan to modify |
| `change_type` | string | `"unknown"` | `"refactor"`, `"bugfix"`, `"feature"`, `"test"`, `"cleanup"`, or `"unknown"` |
| `description` | string | `null` | Optional short description (not parsed by LLM) |
| `include_tests` | bool | `true` | Whether to include affected tests |
| `limit` | int | `50` | Maximum results per category (max 200) |
| `response_mode` | string | `"compact"` | `"compact"` or `"standard"` |

At least one of `files` or `symbols` must be provided.

Response:

```json
{
  "ok": true,
  "tool": "codegraph_pre_edit_check",
  "data": {
    "change_type": "refactor",
    "description": "extract tool schemas from server",
    "planned_files": [
      {"file": "src/server.ts", "indexed": true, "symbols_found": 12},
      {"file": "src/toolSchemas.ts", "indexed": true, "symbols_found": 5}
    ],
    "planned_symbols": [
      {
        "symbol": "startServer",
        "symbol_id": "src/server.ts::startServer",
        "type": "function",
        "file": "src/server.ts",
        "line_start": 20,
        "line_end": 180,
        "reason": "Symbol is defined in a planned edit file."
      }
    ],
    "impact_summary": {
      "risk_level": "medium",
      "confidence": "medium",
      "summary": "[pre-edit heuristic] Editing 3 symbol(s), may affect 2 caller(s), 4 file(s) and 1 test(s)."
    },
    "affected_callers": [...],
    "affected_files": [...],
    "affected_tests": [...],
    "recommended_checks": [
      {"type": "read", "target": "src/server.ts", "reason": "Read exact source before editing the planned file."},
      {"type": "test", "target": "tests/server.test.ts", "reason": "Likely covers affected behavior of planned changes."}
    ],
    "next_recommended_tools": [
      {"tool": "codegraph_get_neighbors", "reason": "Inspect local relationships around the highest-risk planned symbol before editing."},
      {"tool": "codegraph_get_impact", "reason": "Run focused impact analysis on a specific planned symbol if more detail is needed."}
    ]
  },
  "codegraph_session": {...},
  "index_status": {...},
  "index_health": {...}
}
```

**Risk levels:**

| Level | Meaning |
|-------|---------|
| `high` | Planned symbols have multiple callers, affected files/tests are numerous, or involve routes/public APIs/shared services |
| `medium` | Some callers or affected tests exist, but scope is limited |
| `low` | Only local symbols affected, no significant callers or tests |
| `unknown` | Index is missing, files are unindexed, symbols cannot be resolved, or confidence is insufficient |

**Note:** When no data is available, `risk_level` is `unknown` — never `low`.

**recommended_checks types:**

| Type | Meaning |
|------|---------|
| `read` | Read exact source before editing the file |
| `test` | Run the referenced test file to verify behavior |
| `impact` | Run deeper impact analysis |
| `neighbors` | Inspect local relationships |

Recommended checks are advisory only — the tool does not execute tests or modify files. Checks are capped at 5 entries and never reference non-existent test files.

**Relationship to `codegraph_get_impact`:**

`codegraph_pre_edit_check` is the task-level entry point — use it when you know the files you plan to edit but not all affected symbols. `codegraph_get_impact` is the symbol-level entry point — use it when you already know the exact symbol to analyze. Neither is deprecated; they serve different workflows.

### codegraph_explain

Use `codegraph_explain` when you need a short, evidence-backed explanation of a symbol or file before opening full source.

`codegraph_explain` is deterministic and backend-only. It uses indexed metadata, relationships, docstrings, and limited snippets. It does not use LLMs, does not open a dashboard, does not edit files, and does not replace reading exact source when needed.

Examples:

```text
codegraph_explain(symbol="ReceiptService.rowToRecord")
codegraph_explain(file="src/receiptService.ts")
codegraph_explain(symbol="getTokenStats", include_tests=true)
codegraph_explain(symbol="login", file="app/api/auth.py")
```

Parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | `null` | Symbol name to explain |
| `file` | string | `null` | File path to explain (acts as path_hint when combined with symbol) |
| `include_snippet` | bool | `true` | Include bounded source code snippet |
| `include_tests` | bool | `true` | Include test coverage signal |
| `include_relationships` | bool | `true` | Include top callers and callees |
| `max_snippet_lines` | int | `40` | Maximum snippet lines (capped at 80) |
| `response_mode` | string | `"compact"` | `"compact"` or `"standard"` |

At least one of `symbol` or `file` must be provided.

Response (symbol-level):

```json
{
  "ok": true,
  "tool": "codegraph_explain",
  "data": {
    "target": {
      "kind": "symbol",
      "symbol": "rowToRecord",
      "symbol_id": "...::rowToRecord",
      "type": "method",
      "file": "app/services/receipt_service.py",
      "line_start": 20,
      "line_end": 35
    },
    "explanation": {
      "summary": "Converts a database row into a receipt record object.",
      "confidence": "medium",
      "basis": ["docstring", "signature", "callees"]
    },
    "implementation_signals": {
      "uses_json": false,
      "uses_database": true,
      "uses_io": false,
      "uses_network": false,
      "has_error_handling": false,
      "is_framework_entry": false,
      "is_test_code": false,
      "uses_async": false
    },
    "relationships": {
      "callers_count": 0,
      "callees_count": 1,
      "top_callers": [],
      "top_callees": [...]
    },
    "test_signal": {
      "status": "high_confidence",
      "tested_by_count": 1,
      "related_tests": [...]
    },
    "source_snippet": {
      "file": "app/services/receipt_service.py",
      "line_start": 20,
      "line_end": 35,
      "snippet": "...",
      "truncated": false
    },
    "evidence": [
      {"type": "symbol_metadata", "reason": "Symbol type is method. ..."},
      {"type": "docstring", "reason": "Converts a database row into a receipt record object."},
      {"type": "callees", "reason": "Top callees: executeQuery."}
    ],
    "warnings": []
  },
  "codegraph_session": {...},
  "index_status": {...},
  "index_health": {...}
}
```

**Key fields:**

- **`explanation.summary`**: 1-2 sentences, backed by the listed `basis` sources. Confidence is always `high`, `medium`, `low`, or `unknown`. Never claims "high" based only on name heuristics.
- **`explanation.basis`**: Lists the evidence sources used (e.g., `docstring`, `symbol_name`, `callees`). Guarantees the summary is traceable.
- **`implementation_signals`**: 8 boolean flags (uses_json, uses_database, uses_io, uses_network, has_error_handling, is_framework_entry, is_test_code, uses_async). Detected heuristically from callee names, imports, and snippet content. Not absolute facts — use to decide whether deeper inspection is needed.
- **`evidence`**: Structured entries showing exactly what data each conclusion was based on. No conclusion without evidence.
- **`test_signal`**: `status` is one of `high_confidence`, `low_confidence`, `none`, or `unknown`. `related_tests` capped at 5 entries. Does not claim specific edge cases are covered.

Response (file-level, when only `file` is provided):

```json
{
  "target": {"kind": "file", "file": "app/api/auth.py"},
  "primary_symbols": [
    {"symbol_id": "...", "name": "login", "type": "function", "line_start": 6, "line_end": 15, "tags": ["route"]}
  ],
  "symbol_count": 8,
  "likely_role": "API endpoint / route handler",
  "likely_role_confidence": "medium",
  "implementation_signals": {...},
  "test_signal": {...}
}
```

**Agent guidance:**

- Use `codegraph_explain` before `Read` when you need a quick "what does this do?" answer.
- The `implementation_signals` help triage — if `uses_database` is true, inspect DB-related callees. If `has_error_handling` is false, check error paths.
- If `test_signal.status` is `none` or `low_confidence`, consider `codegraph_coverage_gaps` before writing tests.
- If `confidence` is `unknown`, treat the summary as placeholder — read the source directly.
- Always follow `next_recommended_tools` (typically `codegraph_get_neighbors`) for deeper context before editing.

### repo_status

Check if the index is fresh, stale, missing, or has errors. Each MCP response also includes an `index_status` and `index_health` field so agents can detect stale data.

### repo_summary

Get high-level statistics: file count, symbol count, type breakdown, edge count,
low-confidence edge ratio, top modules, entry point candidates, and a structured
**test coverage signal**.

#### Test Coverage Signal

`test_coverage_signal` is a heuristic backend signal that helps agents
distinguish between "no test files exist" and "test files exist but aren't
linked by the index." It prevents a misleading `test_files: 0` from eroding
agent trust in subsequent CodeGraph queries.

**Why this matters:** A bare `test_files: 0` response when test files actually
exist on disk causes agents to lose trust in CodeGraph and fall back to
Glob/Read/Grep. The structured signal provides enough context for agents to
calibrate their trust.

**Signal status values:**

| Status | Meaning |
|--------|---------|
| `ok` | High-confidence `tested_by` edges link tests to production symbols |
| `low_confidence` | `tested_by` edges exist but are mostly low-confidence heuristics |
| `incomplete` | Test files detected but no `tested_by` edges link them to production symbols |
| `unknown` | No test files detected by any method |

**Response fields:**

```json
{
  "test_coverage_signal": {
    "status": "ok | low_confidence | incomplete | unknown",
    "confidence": "high | medium | low | unknown",
    "message": "Human-readable summary for agent trust calibration",
    "warnings": ["Specific issues to be aware of"],
    "test_files_detected": 22,
    "tested_symbols_high_confidence": 8,
    "tested_symbols_low_confidence": 14,
    "tested_symbols_unknown_confidence": 0,
    "untested_symbols_estimate": 43,
    "tested_by_edges": 22,
    "test_files": 22,
    "tested_symbols": 22,
    "test_file_detection": {
      "method": "filesystem_heuristic",
      "count": 22,
      "sample_files": ["tests/test_auth.py", "..."],
      "patterns_used": ["tests"],
      "languages": {"python": 18, "typescript": 4}
    }
  }
}
```

**Backward compatibility:** The old `test_files` and `tested_symbols` integer
fields are preserved at the top level of `test_coverage_signal`.

**Agent guidance:**

- `status: ok` → Coverage signal is usable. Trust the `tested_by` links.
- `status: low_confidence` → Links exist but may be wrong. Verify each link.
- `status: incomplete` → Test files exist but aren't linked. Use CodeGraph for
  navigation, but verify coverage by reading relevant tests directly.
- `status: unknown` → No test files detected. This may mean the project truly
  has no tests, or the test files use an unrecognized naming convention.

**Detection method:** Test files are detected via filesystem path/name
heuristics independent of the CodeGraph index. Supported patterns include:
`tests/**`, `test/**`, `*_test.py`, `test_*.py`, `*.test.ts`, `*.spec.ts`,
`*Test.java`, `*_test.go`, `*Tests.cs`, and more. This means test files are
found even if they were never indexed or have no `tested_by` edges.

A low-confidence or incomplete signal does **not** mean the repository has no
tests. It means CodeGraph cannot confidently map tests to production symbols
with the current index data.

### codegraph_coverage_gaps

`codegraph_coverage_gaps` lists production symbols and files without confident `tested_by` coverage signals.

It is useful for test audit tasks such as:
- Which production modules appear untested?
- Which symbols only have low-confidence test links?
- Which files should I inspect before writing missing tests?

This is a heuristic graph signal, not runtime line coverage.
Use it to decide what to inspect next.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `scope` | string | `"production"` | Always `"production"` — only production symbols are checked |
| `paths` | string | `null` | Comma-separated path glob patterns, e.g. `"src/**,backend/**"` |
| `types` | string | `null` | Comma-separated node types, e.g. `"function,method"` (default: function, method, class, route, controller, service, component, module) |
| `include_low_confidence` | bool | `true` | Include `low_confidence_links` in the response |
| `limit` | int | `50` | Maximum `symbols_without_tests` entries (max 100) |
| `response_mode` | string | `"compact"` | `"compact"` or `"standard"` |

**Examples:**

```text
codegraph_coverage_gaps()
codegraph_coverage_gaps(paths="src/**", types="function,method")
codegraph_coverage_gaps(include_low_confidence=true, limit=30)
```

**Response fields:**

```json
{
  "summary": {
    "production_symbols_checked": 128,
    "symbols_with_high_confidence_tests": 42,
    "symbols_with_low_confidence_tests": 18,
    "symbols_with_unknown_confidence_tests": 3,
    "symbols_without_test_signal": 65,
    "production_files_checked": 31,
    "files_without_test_signal": 12,
    "confidence": "medium",
    "message": "65 production symbols have no confident tested_by coverage signal. This is a CodeGraph heuristic signal, not line coverage."
  },
  "symbols_without_tests": [
    {
      "symbol": "ReceiptService.rowToRecord",
      "type": "method",
      "file": "src/receiptService.ts",
      "line_start": 120,
      "line_end": 168,
      "reason": "No tested_by edge found for this production symbol.",
      "suggested_next_tool": "codegraph_get_neighbors"
    }
  ],
  "files_without_tests": [
    {
      "file": "src/receiptService.ts",
      "production_symbols": 8,
      "symbols_with_high_confidence_test": 0,
      "symbols_with_low_confidence_test": 3,
      "symbols_with_unknown_confidence_test": 0,
      "symbols_without_test_signal": 5,
      "reason": "5/8 production symbols have no tested_by signal."
    }
  ],
  "low_confidence_links": [
    {
      "production_symbol": "TokenStats.getTokenStats",
      "production_symbol_id": "src/TokenStats.ts::getTokenStats",
      "test_symbol": "tokenStats.test",
      "test_symbol_id": "tests/tokenStats.test.ts::tokenStats.test",
      "confidence": 0.42,
      "confidence_level": "low",
      "reason": "Confidence below high-confidence threshold."
    }
  ],
  "warnings": [
    "Coverage gaps are based on CodeGraph tested_by edges, not runtime line coverage."
  ],
  "next_recommended_tools": [
    {
      "tool": "codegraph_get_neighbors",
      "reason": "Inspect tested_by relationships around a specific uncovered symbol before reading test files."
    },
    {
      "tool": "codegraph_get_impact",
      "reason": "Check impact before adding or changing tests around shared production code."
    }
  ]
}
```

**Confidence tiers for `summary.confidence`:**

| Confidence | Meaning |
|------------|---------|
| `high` | Majority of production symbols have high-confidence tested_by coverage |
| `medium` | Some high-confidence coverage exists, but many symbols have low-confidence or no links |
| `low` | Tested_by edges are rare or mostly low-confidence |
| `unknown` | Not enough index data to determine coverage status |

**Coverage gap classification:**

- **`symbols_without_tests`**: Production symbols with NO tested_by edge at all
- **`symbols_with_low_confidence_tests`** (in summary): Production symbols with tested_by edges below 0.75 confidence
- **`symbols_with_unknown_confidence_tests`** (in summary): Production symbols with tested_by edges where confidence is 0 or unset
- **`low_confidence_links`**: Detailed list of tested_by edges with confidence < 0.75 (when `include_low_confidence=true`)

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
4. **`codegraph_find`** — Find symbols with details in one call. Preferred over search_symbols for common find-and-inspect workflows.
5. **`codegraph_search_symbols`** — Lightweight symbol search when you only need a result list without details.
6. **`codegraph_get_neighbors`** — Inspect local relationships around a symbol (callers, callees, tests, models, config).
7. **`codegraph_get_callers` / `codegraph_get_callees`** — Trace call chains instead of grep for call/reference lookup.
8. **`codegraph_explain`** — Before reading full source, get a short structured explanation of what a symbol or file does.
9. **`codegraph_pre_edit_check`** — Before editing files or symbols, check impact on callers, files, and tests in one call.
10. **`codegraph_get_impact`** — Before modifying a specific symbol, understand confirmed and possible impact, and what tests cover it.
11. **`Read`** — Only when exact source text is needed.

### When to use each tool

| Tool | Use when... |
|------|-------------|
| `codegraph_repo_status` | First, check index is available, fresh, and healthy before relying on results |
| `codegraph_build_context_pack` | Default first tool for larger code modification or investigation tasks — returns task-aware context instead of broad grep/glob |
| `codegraph_repo_summary` | Entering a repository, before glob/grep for structure overview |
| `codegraph_coverage_gaps` | Auditing test coverage — which production symbols/files lack tests? |
| `codegraph_find` | Finding symbols with basic details in one call — preferred over search_symbols + get_symbol chain |
| `codegraph_search_symbols` | Lightweight symbol search when you only need a result list without details |
| `codegraph_get_symbol` | You need exact metadata and location for a known symbol |
| `codegraph_get_callers` | Finding who calls or references a symbol, instead of grep. Use `mode=quick` for fast lookup. |
| `codegraph_get_callees` | Understanding what a symbol depends on or calls, instead of manual Read/grep. Use `mode=deep` for broader exploration. |
| `codegraph_get_neighbors` | Exploring local relationships around a symbol, before reading multiple files. Use `mode=review` before code changes. |
| `codegraph_explain` | Before reading full source — get a quick evidence-backed explanation of what a symbol or file does |
| `codegraph_pre_edit_check` | Before editing — when you know which files to modify but not all affected symbols. Task-level impact check. |
| `codegraph_get_impact` | Before modifying a specific shared symbol — understand confirmed and possible impact. Use `mode=review` before committing. |
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
Find a function with details:
→ codegraph_find(query="login", types="function")

Find a function (lightweight):
→ codegraph_search_symbols(query="login", types="function")

Understand a symbol:
→ codegraph_get_neighbors(symbol="MemoryService")

Explain what a symbol does:
→ codegraph_explain(symbol="MemoryService.rowToRecord")

Explain what a file does:
→ codegraph_explain(file="src/receiptService.ts")

Who calls this?
→ codegraph_get_callers(symbol="MemoryService.findRelatedCCRs")

What does this call?
→ codegraph_get_callees(symbol="MemoryService")

What might break if I edit these files?
→ codegraph_pre_edit_check(files="src/server.ts", change_type="refactor")

What might break if I edit this specific symbol?
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
