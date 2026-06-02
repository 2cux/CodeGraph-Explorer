# Development Guide

## Setup

```bash
git clone <repo-url>
cd CodeGraph-Explorer
pip install -e "backend[mcp,watch]"
```

## Project Structure

```
backend/
├── codegraph/
│   ├── indexer/      # Code indexing engine (AST parsing, symbol extraction)
│   ├── graph/        # Graph store, query, impact analysis, validation
│   ├── context/      # Evidence Pack generation
│   ├── storage/      # SQLite and file storage layer
│   ├── api/          # FastAPI HTTP routes (thin forwarding layer)
│   ├── cli/          # CLI commands (thin parameter parsing)
│   ├── mcp_server.py # MCP stdio server (9 tools)
│   └── configure.py  # MCP config generation for Claude Code / Cursor
└── tests/            # Test suite
```

## Layer Responsibilities

| Layer | Responsibility | Must NOT Do |
|-------|---------------|-------------|
| `indexer/` | Extract code facts from filesystem | Business decisions |
| `graph/` | Graph storage and query | Task understanding |
| `context/` | Evidence Pack generation | Filesystem operations |
| `api/` | HTTP route forwarding | Business logic |
| `storage/` | Data read/write | Business decisions |
| `cli/` | Command parsing and parameter passing | Core logic |
| `mcp_server.py` | MCP protocol handling | Graph query logic |

## Running Tests

```bash
# All tests
pytest backend/tests/

# Specific test file
pytest backend/tests/test_mcp_tools.py

# With coverage
pytest backend/tests/ --cov=codegraph

# Benchmark gate
python -m tests.agent_benchmark.gate
```

## Coding Conventions

- **Pydantic v2**: Use `model_validate`, not `parse_obj`
- **Type annotations**: Required on all functions, including return types
- **Node ID format**: `path/to/file.py::SymbolName` (not UUIDs)
- **Confidence**: All inferred relations must carry `confidence` and `resolution`
- **Imports**: Use relative imports within the package

## MCP-First Development

New features should:
1. Expose as MCP tools first (compact mode default)
2. CLI and API as secondary entry points
3. Preserve compact output discipline (no source/evidence/markdown in compact mode)
4. Include `index_status` and `index_health` in all MCP responses

## Before Submitting Changes

1. **Code review**: Run `/code-review` on the diff
2. **Tests pass**: `pytest backend/tests/`
3. **Benchmark gate passes**: `python -m tests.agent_benchmark.gate`
4. **CLI verification**: Test modified commands manually
5. **Schema check**: If graph/evidence schema changed, validate output matches PRD

## CLI Verification Commands

```bash
codegraph init
codegraph doctor
codegraph status
codegraph serve --mcp --check
codegraph configure show
```

## PRD Reference

Detailed design specs are in `docs/PRD/INDEX.md`. Key documents:

| Task | PRD Section |
|------|-------------|
| Graph schema changes | `docs/PRD/04-graph-schema.md` |
| MCP tool changes | `docs/PRD/03-commands.md` |
| Evidence Pack changes | `docs/PRD/05-evidence-pack-schema.md`, `06-evidence-pack-generation.md` |
| Indexing logic | `docs/PRD/08-indexing-and-impact.md` |
| Quality rules | `docs/PRD/09-rules-and-acceptance.md` |

## Known Pitfalls

- **Confidence fields**: Easy to forget when adding new edge types. Always set `confidence` and `resolution`.
- **Node ID consistency**: IDs must match across indexer/graph/context modules. Follow PRD Section 12.5.
- **Compact mode bloat**: Compact responses must NOT include full source, evidence, markdown body, or reason text. Tests verify this.
- **Evidence Pack boundaries**: Never add reading_plan, agent_instructions, or recommended_context to the schema.
