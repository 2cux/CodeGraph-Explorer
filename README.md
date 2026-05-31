# CodeGraph Explorer

**AI Agent-first code context and exploration tool**

CodeGraph Explorer is an Agent-first local code context plugin. It provides AI coding agents with task-aware code context packs (Context Packs), helping agents quickly understand codebase structure, call relationships, and impact surfaces — rather than blindly searching files on their own.

> **Agent-first, Dashboard-second.** The CLI is the primary interface. The Dashboard is a human verification entry point.

---

## Features

| Command | Description |
|---------|-------------|
| `codegraph index` | Scan codebase, parse AST, build code graph index |
| `codegraph context` | Generate task-aware Context Pack (core feature) |
| `codegraph search` | Search code symbols across the indexed codebase |
| `codegraph explain` | Explain a symbol's call relationships |
| `codegraph impact` | Analyze the impact surface of modifying a symbol |
| `codegraph dashboard` | Launch local Dashboard with graph visualization |

### Context Pack — The Core Differentiator

A Context Pack is a structured, task-aware package containing:

- **Entry Points** — Most relevant symbols for the task, ranked by relevance
- **Related Symbols** — Callers, callees, and dependent symbols
- **Call Graph** — Subgraph centered on entry points with confidence scoring
- **Impact Analysis** — Risk assessment and affected files/symbols
- **Recommended Context** — Prioritized code snippets with token budgeting
- **Reading Plan** — Ordered reading steps (not unordered file list)
- **Agent Instructions** — Summary, strategy, and warnings for the AI agent

Each relationship includes a **confidence score** (0.0–1.0) and **resolution strategy**, so agents can weigh the reliability of each inference.

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

# 5. Generate a Context Pack for a task
codegraph context "add MFA to login flow" --root "$DEMO"

# 6. Launch the Dashboard (navigate to the demo project)
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

Analyze what is affected when modifying a symbol. Includes risk assessment, affected symbols/files, and recommendations.

```bash
codegraph impact app/api/auth.py::login
codegraph impact login --depth 3
codegraph impact login --json
```

Risk levels: `low`, `medium`, `high`, `critical` — based on caller count, callee chain depth, sensitive paths (auth/payment/security), test coverage, cross-module reach, and confidence levels.

### `codegraph context <task>`

**The core command.** Generate a Context Pack for a natural language task. The pack is designed to be consumed by AI coding agents.

```bash
codegraph context "add MFA to login flow"
codegraph context "refactor user authentication" --max-tokens 8000
codegraph context "fix bug in token validation" --depth 3
codegraph context "add pagination to user list" --json
codegraph context "update API error handling" --no-tests
```

Context Packs are exported to `.codegraph/context_packs/` as both JSON and Markdown.

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

## Dashboard

The Dashboard provides 6 pages for human verification:

| Page | Description |
|------|-------------|
| **Project Overview** | Index stats, file/symbol counts, confidence ratios |
| **Symbol Search** | Search and filter indexed symbols |
| **Symbol Detail** | Full symbol information with callers and callees |
| **Graph Explorer** | Interactive subgraph visualization (React Flow) |
| **Impact View** | Impact analysis results with risk assessment |
| **Context Pack Viewer** | Explore generated Context Packs with reasoning |

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
├── context/        # Context Pack generation
│   ├── models.py   # Context Pack schema
│   ├── pack_builder.py    # Generation pipeline
│   ├── ranking.py         # Entry point relevance scoring
│   ├── reading_plan.py    # Stub (deprecated in Evidence Pack)
│   └── markdown_exporter.py
├── api/            # FastAPI HTTP API
│   ├── main.py
│   ├── routes_repo.py
│   ├── routes_symbols.py
│   ├── routes_graph.py
│   ├── routes_context.py
│   └── routes_dashboard.py
├── storage/        # Storage layer
│   ├── file_store.py      # JSON file storage
│   └── sqlite_store.py    # SQLite storage
└── __main__.py
```

### Design Principles

- **Layered isolation**: indexer → graph → context → API — each layer has single responsibility
- **Confidence scoring**: All inferred relationships include `confidence` and `resolution` fields
- **Stable Node IDs**: Format `file.py::function_name` — no UUIDs
- **Token budgeting**: Context Pack prioritizes content when over token budget
- **No premature abstraction**: Three similar lines is better than a premature abstraction

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10+, FastAPI, Pydantic v2 |
| Graph Analysis | NetworkX |
| Storage | SQLite + JSON files |
| AST Parsing | Python `ast` standard library |
| CLI Framework | Typer |
| Frontend | TypeScript, React 18, Vite |
| Graph Visualization | React Flow |
| Styling | Tailwind CSS |

---

## Development

### Backend Tests

```bash
pip install -e backend          # Install in editable mode
pip install pytest              # Install test runner
pytest backend/tests/ -v       # Run tests
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

Run the demo walkthrough above to see all features in action.

---

## Project Status

**Phase 0 — MVP Complete.** The full pipeline is implemented:
- [x] Code indexing with AST parsing
- [x] Symbol extraction and call graph construction
- [x] Graph storage (in-memory + SQLite + JSON)
- [x] Symbol search, explain, impact analysis
- [x] Context Pack generation with all required fields
- [x] CLI (Typer) with all 6 commands
- [x] Dashboard (React Frontend) with 6 pages

---

## License

MIT
