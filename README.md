# CodeGraph Explorer

**MCP-first local code graph evidence retrieval for AI coding agents**

CodeGraph Explorer is a Python-first local code graph index and MCP toolkit for AI coding agents. It helps agents query symbols, callers, callees, local subgraphs, impact signals, tests, and index status through structured tools instead of repeatedly grep/glob/read scanning the repository.

CodeGraph Explorer 是一个 Python-first 的本地代码图谱索引与 MCP 工具集，用于帮助 AI 编码 Agent 通过结构化工具查询符号、调用关系、局部子图、影响面、测试信号和索引状态，减少重复 grep、glob 和文件读取。

> **MCP-first, Dashboard as evidence verifier.** MCP fine-grained graph query tools are the primary agent entry point. The Dashboard is a human verification interface. Evidence Pack is an optional non-MCP snapshot.

---

## Core Capabilities

### Primary — MCP Fine-Grained Graph Queries

These are the main tools an AI agent calls at runtime:

| MCP Tool | Purpose |
|---|---|
| `search_symbols` | Search code symbols by name, type, path, or tag |
| `get_symbol` | Get symbol details: signature, location, relations summary |
| `get_callers` | Find all upstream callers of a symbol (transitive, depth-controlled) |
| `get_callees` | Find all downstream callees (separates internal vs external) |
| `get_neighbors` | Local subgraph centered on a symbol, grouped by role (callers/callees/tests/models/config/persistence) |
| `get_impact` | Analyze modification impact: risk level, confirmed/possible files, related tests |
| `repo_status` | Check index freshness, coverage, and low-confidence edge ratio |
| `repo_summary` | Repository overview: type breakdown, top modules, entry points, test coverage signal |

Every response supports **compact mode** (symbol_id, name, type, file_path, confidence, reason_codes — minimal tokens) and **standard mode** (full evidence). All inferred relationships carry `confidence` scores and `resolution` strategies so agents can weigh reliability.

### Secondary

- **Dashboard** — Human verification interface: 6 pages for exploring index quality, symbol details, call graphs, and impact surfaces.
- **Evidence Pack** — Optional task-scoped snapshot for humans or non-MCP agents. Summary-only by default. No reading plans, no agent instructions.

### Not a Goal

- Not an implementation planner
- Not a reading-plan generator
- Not a replacement for agent reasoning
- Not a full semantic runtime analyzer

---

## Benchmark Summary

We run an A/B comparison of a simulated agent using only grep/glob/read (baseline) vs an agent using CodeGraph MCP tools, across 3 fixture projects and 4 task types (locate, impact, modification_prep, test_discovery).

> These results are measured on the included Python benchmark fixtures and should be treated as directional, not universal.

| Metric | Before | After | Target |
|---|---:|---:|---:|
| Recall >= baseline | 6/12 (50%) | 11/12 (92%) | ≥ 8/12 |
| grep/read reduction | -100% | -90.3% | ≥ 30% |
| Files read reduction | -100% | -77.5% | ≥ 25% |
| Token reduction | +54% (worse) | -29.1% | ≥ 20% |
| MCP payload (discovery phase) | N/A | -60.5% | — |
| Full task estimate (discovery + reads) | N/A | -31.3% | — |

Phase-aware metrics separate the MCP discovery phase (payload-only, very cheap) from the full task cost (adds followup file reads for verification). The MCP payload alone is -60.5% vs baseline.

### Quality Gate

Benchmark tests enforce warning thresholds (not hard failures):

| Gate | Threshold | Current |
|---|---|---|
| Recall >= baseline | ≥ 8/12 tasks | 11/12 |
| Token reduction | ≥ 20% | 29.1% |
| Files read reduction | ≥ 25% | 77.5% |
| grep/read reduction | ≥ 30% | 90.3% |

Run: `python -m tests.agent_benchmark.runner --mode both` then `pytest tests/agent_benchmark/ -v`

### Regression Notes

Known failure patterns that degrade benchmark results:

- **Single-keyword search** — Searching only the first keyword misses files. Fix: search all keywords, combine results.
- **`__init__` selected over business method** — `__init__` methods have no callers/callees. Fix: deprioritize `__init__` in symbol selection.
- **Class-level impact misses method callers** — A class node may have no direct edges while its methods do. Fix: aggregate from class methods when the class itself has no callers.
- **Config/model/store deps missing** — Config files connected only via imports, not calls. Fix: traverse callee file imports for config/model/store classes.
- **Compact payload grows too large** — MCP responses accumulating full evidence. Fix: compact mode must exclude reason_text, evidence, and source code.

---

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for Dashboard)

### Installation

```bash
# Backend (CLI + API)
pip install -e backend

# Frontend (Dashboard)
cd frontend && npm install && cd ..
```

### Demo Walkthrough

```bash
# 0. Set a shortcut for the demo project root
DEMO=./examples/demo_python_project

# 1. Index the demo project
codegraph index "$DEMO"

# 2. Search for symbols
codegraph search login --root "$DEMO"

# 3. Explain a symbol's relationships
codegraph explain app/api/auth.py::login --root "$DEMO"

# 4. Analyze impact of modifying a symbol
codegraph impact app/api/auth.py::login --root "$DEMO"

# 5. Generate an Evidence Pack (optional snapshot)
codegraph evidence "add MFA to login flow" --root "$DEMO"

# 6. Launch the Dashboard
codegraph dashboard --root "$DEMO"
```

---

## CLI Commands

### `codegraph index <root>`

Scan a Python codebase, parse AST, extract symbols and call relationships, and build the code graph.

```bash
codegraph index ./my_project
codegraph index ./my_project --force    # Re-index if already exists
codegraph index ./my_project --no-sqlite  # Skip SQLite output
```

Output: `.codegraph/graph.json`, `.codegraph/nodes.json`, `.codegraph/edges.json`, `.codegraph/index.sqlite`

### `codegraph search <query>`

Search for code symbols by name, file path, qualified name, or docstring.

```bash
codegraph search login
codegraph search user --json
codegraph search auth --root ./my_project
```

### `codegraph explain <symbol>`

Explain a symbol's call relationships — who calls it and what it calls.

```bash
codegraph explain app/api/auth.py::login
codegraph explain login                  # Partial name auto-resolved
codegraph explain login --depth 3        # Control call chain depth
codegraph explain login --json           # JSON output
```

### `codegraph impact <symbol>`

Analyze what is affected when modifying a symbol. Includes risk assessment, affected symbols/files, and related tests.

```bash
codegraph impact app/api/auth.py::login
codegraph impact login --depth 3
codegraph impact login --json
```

Risk levels: `low`, `medium`, `high`, `critical` — based on caller count, callee chain depth, sensitive paths (auth/payment/security), test coverage, cross-module reach, and confidence levels.

### `codegraph context <task>`

Generate an Evidence Pack — an optional task-scoped snapshot for humans or non-MCP agents. Does NOT include reading plans or agent instructions.

```bash
codegraph context "add MFA to login flow"
codegraph context "refactor user authentication" --max-tokens 8000
codegraph context "fix bug in token validation" --depth 3
codegraph context "add pagination to user list" --json
codegraph context "update API error handling" --no-tests
```

Evidence Packs are exported to `.codegraph/context_packs/` as both JSON and Markdown.

### `codegraph dashboard`

Launch the local Dashboard (FastAPI backend + React frontend).

```bash
codegraph dashboard                      # Default: http://localhost:8765
codegraph dashboard --port 8080
codegraph dashboard --host 0.0.0.0
codegraph dashboard --dev                # Vite dev mode with HMR
codegraph dashboard --no-open            # Don't auto-open browser
```

---

## MCP Server

Start the MCP server for direct agent integration (Claude Code, Cursor, etc.):

```bash
codegraph mcp
# or
python -m codegraph.mcp_server
```

Claude Code config (`.claude/settings.local.json`):

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "python",
      "args": ["-m", "codegraph.mcp_server"],
      "env": {
        "CODEGRAPH_PROJECT_ROOT": "/path/to/project"
      }
    }
  }
}
```

---

## Dashboard

The Dashboard provides 6 pages for human verification:

| Page | Description |
|------|-------------|
| **Project Overview** | Index stats, file/symbol counts, confidence ratios |
| **Symbol Search** | Search and filter indexed symbols |
| **Symbol Detail** | Full symbol information with callers and callees |
| **Graph Explorer** | Interactive subgraph visualization (React Flow) |
| **Impact View** | Impact analysis results with risk assessment |
| **Evidence Pack Viewer** | Explore generated Evidence Packs with reasoning |

All call edges display confidence scores; edges below 0.6 are visually flagged.

---

## Architecture

```
backend/codegraph/
├── cli/            # CLI command definitions (Typer)
├── indexer/        # Code indexing engine
│   ├── scanner.py          # File discovery
│   ├── parser_python.py    # AST parsing
│   ├── symbol_extractor.py # Symbol extraction
│   ├── call_extractor.py   # Call relationship extraction
│   └── graph_builder.py    # Graph construction
├── graph/          # Graph layer
│   ├── models.py   # Node/Edge schema (Pydantic)
│   ├── store.py    # In-memory graph store
│   ├── query.py    # Search, callers, callees, subgraph
│   └── impact.py   # Impact surface analysis
├── mcp_server.py   # MCP server — primary agent entry point
├── context/        # Evidence Pack generation (secondary)
│   ├── models.py           # Evidence Pack schema
│   ├── pack_builder.py     # Generation pipeline
│   ├── ranking.py          # Entry point relevance scoring
│   ├── reading_plan.py     # Stub (deprecated — always returns [])
│   └── markdown_exporter.py
├── api/            # FastAPI HTTP API (for Dashboard)
├── storage/        # Storage layer (JSON + SQLite)
└── __main__.py
```

### Design Principles

- **MCP-first** — The MCP server is the primary product surface. All graph queries are exposed as structured MCP tools.
- **Compact by default** — All MCP responses default to compact mode: symbol_id, name, type, file_path, confidence, reason_codes. Standard mode and source inclusion are opt-in.
- **Confidence scoring** — Every inferred relationship carries `confidence` and `resolution` fields so agents can weigh reliability.
- **Stable Node IDs** — Format `file.py::function_name` — no UUIDs.
- **Layered isolation** — indexer → graph → MCP/API — each layer has single responsibility.
- **No reading plans** — Evidence Pack is a factual snapshot, not a task planner. It contains selected_context, warnings, and pack_notes — never reading_plan or agent_instructions.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Pydantic v2 |
| Graph Analysis | NetworkX |
| Storage | SQLite + JSON files |
| AST Parsing | Python `ast` standard library |
| CLI Framework | Typer |
| MCP Protocol | FastMCP |
| Frontend | TypeScript, React 18, Vite |
| Graph Visualization | React Flow |
| Styling | Tailwind CSS |

---

## Development

### Backend Tests

```bash
pip install -e backend          # Install in editable mode
pip install pytest              # Install test runner
pytest backend/tests/ -v       # Run tests (666+ tests)
```

### Benchmark Tests

```bash
# Run both modes
python -m tests.agent_benchmark.runner --mode both

# Run quality gate checks
pytest tests/agent_benchmark/ -v
```

### Frontend Build

```bash
cd frontend && npm run dev      # Development server with HMR
cd frontend && npm run build    # Production build
```

---

## Demo Project

The repository includes a demo Python project at `examples/demo_python_project/`:

```
demo_python_project/
├── main.py              # Entry point: orchestrates login flow
├── app/
│   ├── api/
│   │   ├── auth.py      # login(), logout() — authentication logic
│   │   └── users.py     # get_users(), get_user_by_name()
│   ├── models/
│   │   └── user.py      # User dataclass
│   └── store/
│       └── token_store.py  # Token storage (save, revoke, validate)
```

---

## Project Status

**MVP Complete.** The full pipeline is implemented:
- [x] Code indexing with AST parsing
- [x] Symbol extraction and call graph construction
- [x] Graph storage (in-memory + SQLite + JSON)
- [x] MCP server with 8 fine-grained query tools
- [x] Symbol search, explain, impact analysis
- [x] Evidence Pack generation (summary-only, no reading plans)
- [x] CLI (Typer) with all commands
- [x] Dashboard (React Frontend) with 6 pages
- [x] Agent A/B benchmark with quality gate

---

## License

MIT
