# Changelog

All notable changes to CodeGraph Explorer.

## v1.0.0-rc.1 (2026-06-03)

### Highlights

- **MCP-first** local code graph backend for AI coding agents
- **Python production support** — full AST parsing, import resolution, and call graph
- **TypeScript / JavaScript / Java / Go / C# beta support** — tree-sitter and regex-based parsers
- **Framework signals** for FastAPI, Flask, Django, Express, Next.js, NestJS, React, Spring Boot, Gin, Hertz, ASP.NET Core
- **SQLite / FTS storage** with JSON backup for debug/fallback
- **Incremental indexing** — cosmetic changes skip structural rebuild
- **Post-commit auto-update** — `codegraph init` installs a managed git hook by default
- **Evidence Pack** — optional task-scoped code evidence snapshots
- **Benchmark regression gate** — 36 checks across recall, tokens, edge quality, and MCP protocol health
- **Zero telemetry** — fully local, no network access required

### MCP Tools (9)

- `codegraph_search_symbols` — search symbols by name, type, tag, or path
- `codegraph_get_symbol` — get symbol details (location, signature, source)
- `codegraph_get_callers` — query upstream callers
- `codegraph_get_callees` — query downstream callees
- `codegraph_get_neighbors` — get local subgraph around a symbol
- `codegraph_get_impact` — analyze modification impact (confirmed / possible / tests)
- `codegraph_repo_status` — check index freshness and health
- `codegraph_repo_summary` — repository graph statistics
- `codegraph_build_context_pack` — generate Evidence Pack snapshot

### CLI Commands

- `codegraph init` — full or incremental index build
- `codegraph index` — index a project directory
- `codegraph search` — search symbols
- `codegraph explain` — symbol detail with callers/callees
- `codegraph callers` / `callees` — call graph traversal
- `codegraph neighbors` — local subgraph query
- `codegraph impact` — impact analysis
- `codegraph context` — Evidence Pack generation
- `codegraph serve --mcp` — MCP stdio server
- `codegraph configure` — MCP config for Claude Code / Cursor
- `codegraph doctor` — environment and index health check
- `codegraph watch` — file system watch for auto-indexing
- `codegraph hooks` — post-commit hook management
- `codegraph status` — index status overview

### Storage

- SQLite database (`.codegraph/index.sqlite`) with FTS5 full-text search
- JSON backup files (`.codegraph/nodes.json`, `.codegraph/edges.json`, `.codegraph/graph.json`)
- State tracking (`.codegraph/state.json`, `.codegraph/metadata.json`, `.codegraph/fingerprints.json`)
- Validation reports (`.codegraph/validation_report.json`)

### Benchmark Results

| Metric | Result | Threshold | Status |
|--------|--------|-----------|--------|
| Recall >= baseline | 10/12 (83.3%) | ≥ 58% | ✅ |
| grep/read reduction | 90.3% | ≥ 40% | ✅ |
| Files read reduction | 77.5% | ≥ 30% | ✅ |
| Token reduction | 74.6% | ≥ 10% | ✅ |
| Compact vs standard payload reduction | 68.1% | ≥ 30% | ✅ |
| Gate checks | 36 passed, 0 failed | — | ✅ |

> Results are based on bundled Python benchmark fixtures (12 tasks).

### Known Limitations

See **[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)** and **[docs/language-support.md](docs/language-support.md)** for details.

- Python is the only production-level language
- TypeScript, JavaScript, Java, Go, C# are Beta — call edges tiered as confirmed/possible/unresolved
- Static analysis only — no runtime, dynamic dispatch, or reflection coverage
- No cross-language call edges
- Benchmark results from built-in fixtures only

---

## Template

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
