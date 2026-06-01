# Storage

`.codegraph/index.sqlite` is the primary query store for CLI, API, and MCP
reads. It is initialized with WAL mode and, when the local SQLite build supports
it, an FTS5 `symbols_fts` table for fast symbol search.

The JSON files (`nodes.json`, `edges.json`, `metadata.json`, `graph.json`) are
retained for debug/export compatibility and as a fallback when SQLite is
unavailable. Run `codegraph doctor` to inspect WAL, FTS5, schema version, and
JSON/SQLite count consistency.
