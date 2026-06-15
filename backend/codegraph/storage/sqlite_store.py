"""SQLite-based storage for graph data.

Stores nodes and edges in a local SQLite database at ``.codegraph/index.sqlite``.

All batch writes are automatically chunked to avoid hitting SQLite's
``SQLITE_MAX_VARIABLE_NUMBER`` limit.
"""

import json
import difflib
import re
import sqlite3
from pathlib import Path
from typing import Any

from codegraph.storage.sqlite_utils import safe_executemany
from codegraph.utils.path_utils import is_test_path, is_production_path, is_test_intent_query, is_framework_entry_point

SUPPORTED_SCHEMA_VERSION = "1.1.0"

# Pre-compiled regex for named seed injection (used in search_symbols hot path)
_SEED_PASCAL_RE = re.compile(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b')
_SEED_SNAKE_RE = re.compile(r'\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b')


def _row_to_node(row: sqlite3.Row) -> dict:
    data = dict(row)
    if isinstance(data.get("location"), str):
        data["location"] = json.loads(data["location"])
    if isinstance(data.get("metadata"), str):
        data["metadata"] = json.loads(data["metadata"])
    if isinstance(data.get("tags"), str):
        try:
            data["tags"] = json.loads(data["tags"])
        except json.JSONDecodeError:
            data["tags"] = [data["tags"]] if data["tags"] else []
    # Phase 1: normalize language_id — fall back to legacy 'language' column
    if not data.get("language_id"):
        data["language_id"] = data.get("language", "python")
    # Schema 1.1.0: deserialize enrichment JSON columns
    for json_col in ("responsibilities", "edge_cases", "enrichment_evidence"):
        if isinstance(data.get(json_col), str):
            try:
                data[json_col] = json.loads(data[json_col])
            except json.JSONDecodeError:
                data[json_col] = [] if json_col != "enrichment_evidence" else []
    return data


def _row_to_edge(row: sqlite3.Row) -> dict:
    data = dict(row)
    if isinstance(data.get("source_location"), str):
        data["source_location"] = json.loads(data["source_location"])
    if isinstance(data.get("edge_metadata"), str):
        meta = json.loads(data.pop("edge_metadata"))
        # Normalize provenance: may be stored in edge_metadata JSON
        # or as a top-level column (future migration).
        data["metadata"] = meta
    else:
        data.pop("edge_metadata", None)
    # If provenance is stored as top-level column, pass it through
    if "provenance" in data and data.get("metadata") and not data["metadata"].get("provenance"):
        data["metadata"]["provenance"] = data["provenance"]
    return data



def _assign_search_layer(file_path: str) -> str:
    normalized = file_path.replace("\\", "/").lower()
    layer_map: list[tuple[str, str]] = [
        ("codegraph/graph/", "graph"), ("codegraph/graph_", "graph"),
        ("codegraph/indexer", "indexer"), ("indexer/", "indexer"),
        ("codegraph/storage/", "storage"), ("storage/", "storage"),
        ("codegraph/context/", "context"),
        ("codegraph/mcp/", "mcp"), ("mcp_server", "mcp"),
        ("api/", "api"), ("routes", "api"), ("router", "api"),
        ("service", "service"), ("services", "service"),
        ("store/", "storage"),
        ("context/", "context"), ("evidence", "context"),
        ("test", "tests"), ("test_", "tests"),
        ("config", "config"), ("settings", "config"),
        ("model", "models"), ("schema", "models"),
        ("persistence", "persistence"), ("repository", "persistence"),
        ("cli/", "indexer"), ("cli_", "indexer"),
    ]
    for pattern, layer in layer_map:
        if pattern in normalized:
            return layer
    return "unknown"


CREATE_NODES = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT DEFAULT '',
    display_name TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    module TEXT DEFAULT '',
    language TEXT DEFAULT 'python',
    language_id TEXT DEFAULT 'python',
    framework_id TEXT,
    location TEXT,
    signature TEXT,
    docstring TEXT,
    code_preview TEXT,
    visibility TEXT DEFAULT 'public',
    tags TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
);
"""

# Migration DDL for databases created before Phase 1 multi-language refactoring.
MIGRATE_NODES_LANGUAGE_ID = """
ALTER TABLE nodes ADD COLUMN language_id TEXT DEFAULT 'python';
"""

MIGRATE_NODES_FRAMEWORK_ID = """
ALTER TABLE nodes ADD COLUMN framework_id TEXT;
"""

# ── Enrichment column migrations (schema 1.1.0) ──────────────────────

MIGRATE_NODES_ENRICH_SUMMARY = """
ALTER TABLE nodes ADD COLUMN summary TEXT DEFAULT '';
"""

MIGRATE_NODES_ENRICH_ROLE = """
ALTER TABLE nodes ADD COLUMN role TEXT DEFAULT '';
"""

MIGRATE_NODES_ENRICH_RESPONSIBILITIES = """
ALTER TABLE nodes ADD COLUMN responsibilities TEXT DEFAULT '[]';
"""

MIGRATE_NODES_ENRICH_EDGE_CASES = """
ALTER TABLE nodes ADD COLUMN edge_cases TEXT DEFAULT '[]';
"""

MIGRATE_NODES_ENRICH_TEST_RELEVANCE = """
ALTER TABLE nodes ADD COLUMN test_relevance TEXT DEFAULT '';
"""

MIGRATE_NODES_ENRICH_CONFIDENCE = """
ALTER TABLE nodes ADD COLUMN enrichment_confidence TEXT DEFAULT '';
"""

MIGRATE_NODES_ENRICH_EVIDENCE = """
ALTER TABLE nodes ADD COLUMN enrichment_evidence TEXT DEFAULT '[]';
"""

MIGRATE_NODES_ENRICH_STATUS = """
ALTER TABLE nodes ADD COLUMN enrichment_status TEXT DEFAULT '';
"""

MIGRATE_NODES_ENRICH_AT = """
ALTER TABLE nodes ADD COLUMN enriched_at TEXT DEFAULT '';
"""

ENRICH_MIGRATIONS = [
    ("summary", MIGRATE_NODES_ENRICH_SUMMARY),
    ("role", MIGRATE_NODES_ENRICH_ROLE),
    ("responsibilities", MIGRATE_NODES_ENRICH_RESPONSIBILITIES),
    ("edge_cases", MIGRATE_NODES_ENRICH_EDGE_CASES),
    ("test_relevance", MIGRATE_NODES_ENRICH_TEST_RELEVANCE),
    ("enrichment_confidence", MIGRATE_NODES_ENRICH_CONFIDENCE),
    ("enrichment_evidence", MIGRATE_NODES_ENRICH_EVIDENCE),
    ("enrichment_status", MIGRATE_NODES_ENRICH_STATUS),
    ("enriched_at", MIGRATE_NODES_ENRICH_AT),
]

CREATE_EDGES = """
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source_location TEXT,
    edge_metadata TEXT
);
"""

CREATE_NODE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(name);
"""

CREATE_EDGE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
"""

CREATE_META = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CREATE_SYMBOLS_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    symbol_id UNINDEXED,
    name,
    qualified_name,
    file_path,
    signature,
    docstring,
    tags
);
"""


class SqliteStore:
    """Read/write graph data to a local SQLite database.

    The database file is created at *db_path* (e.g. ``.codegraph/index.sqlite``).
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self.wal_warning: str | None = None
        self.fts_warning: str | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._apply_pragmas(self._conn)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def initialize(self) -> None:
        """Create tables and indexes if they don't exist."""
        c = self.conn
        c.executescript(CREATE_NODES)
        c.executescript(CREATE_EDGES)
        c.executescript(CREATE_META)
        c.executescript(CREATE_NODE_INDEXES)
        c.executescript(CREATE_EDGE_INDEXES)
        # Phase 1 multi-language migration: add columns to existing databases
        self._migrate_schema(c)
        if self.supports_fts5():
            try:
                c.executescript(CREATE_SYMBOLS_FTS)
                if self.fts_count() != self.node_count():
                    self.rebuild_fts()
            except sqlite3.DatabaseError as e:
                self.fts_warning = f"FTS5 unavailable: {e}"
        else:
            self.fts_warning = "FTS5 unavailable; falling back to LIKE search"
        self.set_meta("schema_version", SUPPORTED_SCHEMA_VERSION)
        c.commit()

    def _migrate_schema(self, c: sqlite3.Connection) -> None:
        """Add columns introduced in later schema versions.

        Uses ALTER TABLE ADD COLUMN which is a no-cost metadata operation
        in SQLite when a default is provided.
        """
        existing_cols = {
            row[1] for row in
            c.execute("PRAGMA table_info('nodes')").fetchall()
        }
        if "language_id" not in existing_cols:
            try:
                c.execute(MIGRATE_NODES_LANGUAGE_ID)
            except sqlite3.DatabaseError:
                pass  # column already exists or table doesn't exist yet
        if "framework_id" not in existing_cols:
            try:
                c.execute(MIGRATE_NODES_FRAMEWORK_ID)
            except sqlite3.DatabaseError:
                pass
        # Schema 1.1.0: enrichment columns
        for col_name, migration_ddl in ENRICH_MIGRATIONS:
            if col_name not in existing_cols:
                try:
                    c.execute(migration_ddl)
                except sqlite3.DatabaseError:
                    pass

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if str(mode).lower() != "wal":
                self.wal_warning = f"SQLite WAL requested but journal_mode is {mode}"
        except sqlite3.DatabaseError as e:
            self.wal_warning = f"SQLite WAL unavailable: {e}"
        conn.execute("PRAGMA synchronous=NORMAL")

    def get_journal_mode(self) -> str | None:
        try:
            row = self.conn.execute("PRAGMA journal_mode").fetchone()
            return str(row[0]) if row else None
        except sqlite3.DatabaseError:
            return None

    def supports_fts5(self) -> bool:
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS temp._codegraph_fts_probe USING fts5(x)"
            )
            self.conn.execute("DROP TABLE IF EXISTS temp._codegraph_fts_probe")
            return True
        except sqlite3.DatabaseError:
            return False

    def has_fts_table(self) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'symbols_fts'"
        ).fetchone()
        return row is not None

    def fts_count(self) -> int | None:
        if not self.has_fts_table():
            return None
        row = self.conn.execute("SELECT COUNT(*) AS cnt FROM symbols_fts").fetchone()
        return row["cnt"] if row else 0

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            [key, value],
        )

    def get_meta(self, key: str) -> str | None:
        try:
            row = self.conn.execute("SELECT value FROM meta WHERE key = ?", [key]).fetchone()
            return row["value"] if row else None
        except sqlite3.DatabaseError:
            return None

    def schema_version_status(self) -> tuple[str, str]:
        version = self.get_meta("schema_version")
        if not version:
            return "warning", "SQLite schema_version missing. Run: codegraph init --force"
        if version != SUPPORTED_SCHEMA_VERSION:
            return "error", f"SQLite schema_version {version} is unsupported. Run: codegraph init --force"
        return "ok", version

    # ── Nodes ──────────────────────────────────────────────────────────

    def save_nodes(self, nodes: list[dict], commit: bool = True) -> None:
        """Insert or replace a batch of nodes.

        Each dict should have keys matching the GraphNode model fields.

        Args:
            nodes: List of node dicts to upsert.
            commit: If True (default), commit after saving. Set to False
                    when calling inside a larger transaction.
        """
        c = self.conn
        safe_executemany(
            c,
            """INSERT OR REPLACE INTO nodes
               (id, type, name, qualified_name, display_name, file_path,
                module, language, language_id, framework_id, location, signature, docstring,
                code_preview, visibility, tags, metadata,
                summary, role, responsibilities, edge_cases, test_relevance,
                enrichment_confidence, enrichment_evidence, enrichment_status, enriched_at)
               VALUES
               (:id, :type, :name, :qualified_name, :display_name, :file_path,
                :module, :language, :language_id, :framework_id, :location, :signature, :docstring,
                :code_preview, :visibility, :tags, :metadata,
                :summary, :role, :responsibilities, :edge_cases, :test_relevance,
                :enrichment_confidence, :enrichment_evidence, :enrichment_status, :enriched_at)""",
            [
                {
                    "id": n["id"],
                    "type": n["type"].value if hasattr(n["type"], "value") else n["type"],
                    "name": n["name"],
                    "qualified_name": n.get("qualified_name", ""),
                    "display_name": n.get("display_name", ""),
                    "file_path": n.get("file_path", ""),
                    "module": n.get("module", ""),
                    "language": n.get("language", "python"),
                    "language_id": n.get("language_id", n.get("language", "python")),
                    "framework_id": n.get("framework_id"),
                    "location": json.dumps(n["location"]) if n.get("location") else None,
                    "signature": n.get("signature"),
                    "docstring": n.get("docstring"),
                    "code_preview": n.get("code_preview"),
                    "visibility": n.get("visibility", "public"),
                    "tags": n["tags"] if isinstance(n.get("tags"), str) else json.dumps(n.get("tags", []), ensure_ascii=False),
                    "metadata": n["metadata"] if isinstance(n.get("metadata"), str) else json.dumps(n.get("metadata", {}), ensure_ascii=False),
                    # Enrichment fields (schema 1.1.0)
                    "summary": n.get("summary", ""),
                    "role": n.get("role", ""),
                    "responsibilities": n.get("responsibilities") if isinstance(n.get("responsibilities"), str) else json.dumps(n.get("responsibilities", []), ensure_ascii=False),
                    "edge_cases": n.get("edge_cases") if isinstance(n.get("edge_cases"), str) else json.dumps(n.get("edge_cases", []), ensure_ascii=False),
                    "test_relevance": n.get("test_relevance", ""),
                    "enrichment_confidence": n.get("enrichment_confidence", ""),
                    "enrichment_evidence": n.get("enrichment_evidence") if isinstance(n.get("enrichment_evidence"), str) else json.dumps(n.get("enrichment_evidence", []), ensure_ascii=False),
                    "enrichment_status": n.get("enrichment_status", ""),
                    "enriched_at": n.get("enriched_at", ""),
                }
                for n in nodes
            ],
        )
        self._sync_fts(nodes)
        if commit:
            c.commit()

    def _sync_fts(self, nodes: list[dict]) -> None:
        if not self.has_fts_table():
            return
        c = self.conn
        for n in nodes:
            c.execute("DELETE FROM symbols_fts WHERE symbol_id = ?", [n["id"]])
        safe_executemany(
            c,
            """INSERT INTO symbols_fts
               (symbol_id, name, qualified_name, file_path, signature, docstring, tags)
               VALUES
               (:symbol_id, :name, :qualified_name, :file_path, :signature, :docstring, :tags)""",
            [
                {
                    "symbol_id": n["id"],
                    "name": n.get("name", ""),
                    "qualified_name": n.get("qualified_name", ""),
                    "file_path": n.get("file_path", ""),
                    "signature": n.get("signature") or "",
                    "docstring": n.get("docstring") or "",
                    "tags": n.get("tags", "") if isinstance(n.get("tags"), str) else " ".join(n.get("tags", []) or []),
                }
                for n in nodes
            ],
        )

    def rebuild_fts(self) -> None:
        """Rebuild symbols_fts from existing nodes when FTS5 is available."""
        if not self.has_fts_table():
            return
        c = self.conn
        c.execute("DELETE FROM symbols_fts")
        rows = c.execute("SELECT * FROM nodes").fetchall()
        self._sync_fts([_row_to_node(r) for r in rows])

    def query_nodes(
        self, filters: dict | None = None
    ) -> list[dict]:
        """Query nodes with optional filters.

        Supported filter keys:
          type       — exact match on node type string
          file_path  — substring match
          name       — substring match
          limit      — max rows (default 200)
          offset     — row offset
        """
        where_clauses: list[str] = []
        params: list = []

        if filters:
            if "type" in filters:
                where_clauses.append("type = ?")
                params.append(filters["type"])
            if "file_path" in filters:
                where_clauses.append("file_path LIKE ?")
                params.append(f"%{filters['file_path']}%")
            if "name" in filters:
                where_clauses.append("name LIKE ?")
                params.append(f"%{filters['name']}%")

        where = ""
        if where_clauses:
            where = " WHERE " + " AND ".join(where_clauses)

        limit = filters.get("limit", 200) if filters else 200
        offset = filters.get("offset", 0) if filters else 0

        c = self.conn
        rows = c.execute(
            f"SELECT * FROM nodes{where} ORDER BY id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        return [_row_to_node(r) for r in rows]

    def get_node(self, node_id: str) -> dict | None:
        c = self.conn
        row = c.execute(
            "SELECT * FROM nodes WHERE id = ?", [node_id]
        ).fetchone()
        return _row_to_node(row) if row else None

    def search_symbols(
        self,
        query: str = "",
        type_filter: str | None = None,
        types: list[str] | None = None,
        file_filter: str | None = None,
        file_path: str | None = None,
        path_prefix: str | None = None,
        layer: str | None = None,
        include_tests: bool = True,
        exclude_external: bool = True,
        min_score: float = 0.2,
        limit: int = 50,
        offset: int = 0,
        use_fts: bool = True,
        fuzzy: bool = True,
        language_id: str | None = None,
    ) -> dict[str, Any]:
        """Search symbols in SQLite using exact, FTS5, LIKE, then fuzzy passes."""
        q = query.strip()
        requested_limit = max(1, min(limit, 100))
        scan_limit = max(requested_limit + offset, 100)
        fuzzy_scan_limit = max(scan_limit, 1000)
        merged: dict[str, dict[str, Any]] = {}
        query_mentions_test = is_test_intent_query(q)
        include_test_only = bool(types) and set(types) <= {"test"}

        def add_rows(rows: list[sqlite3.Row], score: float, source: str, layer_name: str) -> None:
            for row in rows:
                data = _row_to_node(row)
                if not self._passes_search_filters(data, layer, include_tests, exclude_external):
                    continue
                self._merge_result(merged, data, score, source, layer_name)

        base_where, base_params = self._node_filter_sql(
            type_filter=type_filter,
            types=types,
            file_filter=file_filter,
            file_path=file_path,
            path_prefix=path_prefix,
            exclude_external=exclude_external,
            language_id=language_id,
        )
        c = self.conn

        if q:
            # 0. Named seed injection — extract CamelCase/PascalCase names from query
            #    and do exact name lookups BEFORE the normal pipeline
            _seen_seeds: set[str] = set()
            for _name in _SEED_PASCAL_RE.findall(q) + _SEED_SNAKE_RE.findall(q):
                _name_lower = _name.lower()
                if _name_lower in _seen_seeds:
                    continue
                _seen_seeds.add(_name_lower)
                # Skip short names and common words
                if len(_name) < 4:
                    continue
                _seed_rows = c.execute(
                    f"SELECT * FROM nodes WHERE {' AND '.join(base_where + ['name = ?'])} LIMIT 3",
                    [*base_params, _name],
                ).fetchall()
                if _seed_rows:
                    add_rows(_seed_rows, 0.98, "seed_name", "seed_name")

            # 1. exact symbol_id
            rows = c.execute(
                f"SELECT * FROM nodes WHERE {' AND '.join(base_where + ['id = ?'])} LIMIT ?",
                [*base_params, q, scan_limit],
            ).fetchall()
            add_rows(rows, 1.0, "exact_symbol_id", "exact_symbol_id")

            # 2. exact name
            rows = c.execute(
                f"SELECT * FROM nodes WHERE {' AND '.join(base_where + ['name = ?'])} LIMIT ?",
                [*base_params, q, scan_limit],
            ).fetchall()
            add_rows(rows, 0.9, "exact_name", "exact_name")

            # 3. exact qualified_name
            rows = c.execute(
                f"SELECT * FROM nodes WHERE {' AND '.join(base_where + ['qualified_name = ?'])} LIMIT ?",
                [*base_params, q, scan_limit],
            ).fetchall()
            add_rows(rows, 0.95, "exact_qualified_name", "exact_qualified_name")

            # 4. FTS5 MATCH
            if use_fts and self.has_fts_table():
                fts_query = self._fts_query(q)
                if fts_query:
                    fts_where = [
                        w.replace("type", "n.type").replace("file_path", "n.file_path")
                        for w in base_where
                    ]
                    rows = c.execute(
                        f"""SELECT n.*, bm25(symbols_fts) AS rank
                            FROM symbols_fts JOIN nodes n ON n.id = symbols_fts.symbol_id
                            WHERE symbols_fts MATCH ? {' AND ' + ' AND '.join(fts_where) if fts_where else ''}
                            ORDER BY rank LIMIT ?""",
                        [fts_query, *base_params, scan_limit],
                    ).fetchall()
                    for row in rows:
                        data = _row_to_node(row)
                        if not self._passes_search_filters(data, layer, include_tests, exclude_external):
                            continue
                        fts_score, sources = self._score_fts_match(data, q)
                        for source in sources:
                            self._merge_result(merged, data, fts_score, source, "fts")

            # 5. LIKE fallback
            like = f"%{q}%"
            like_where = base_where + [
                "(id LIKE ? OR name LIKE ? OR qualified_name LIKE ? OR file_path LIKE ? OR signature LIKE ? OR docstring LIKE ? OR tags LIKE ?)"
            ]
            rows = c.execute(
                f"SELECT * FROM nodes WHERE {' AND '.join(like_where)} ORDER BY name LIMIT ?",
                [*base_params, like, like, like, like, like, like, like, scan_limit],
            ).fetchall()
            for row in rows:
                data = _row_to_node(row)
                if not self._passes_search_filters(data, layer, include_tests, exclude_external):
                    continue
                like_score, sources = self._score_like_match(data, q)
                for source in sources:
                    self._merge_result(merged, data, like_score, source, "like")

            # 6. fuzzy fallback, only when previous layers found nothing useful.
            best_score = max((item["score"] for item in merged.values()), default=0.0)
            if fuzzy and (not merged or best_score < 0.4):
                rows = c.execute(
                    f"SELECT * FROM nodes WHERE {' AND '.join(base_where or ['1=1'])} "
                    "ORDER BY name LIMIT ?",
                    [*base_params, fuzzy_scan_limit],
                ).fetchall()
                for row in rows:
                    data = _row_to_node(row)
                    if not self._passes_search_filters(data, layer, include_tests, exclude_external):
                        continue
                    score = self._score_fuzzy_match(data.get("name", ""), q)
                    if score >= min_score:
                        self._merge_result(merged, data, score, "fuzzy_name", "fuzzy")
        else:
            rows = c.execute(
                f"SELECT * FROM nodes WHERE {' AND '.join(base_where or ['1=1'])} ORDER BY id LIMIT ?",
                [*base_params, scan_limit],
            ).fetchall()
            add_rows(rows, 0.5, "all", "all")

        results = [
            item for item in merged.values()
            if item.get("score", 0.0) >= min_score
        ]
        exact_name_paths = {
            item.get("file_path", "")
            for item in results
            if "exact_name" in item.get("match_sources", [])
        }
        ambiguous = self._is_ambiguous(results, exact_name_paths)
        results.sort(
            key=lambda item: self._search_sort_key(
                item,
                query_mentions_test=query_mentions_test,
                include_test_only=include_test_only,
            )
        )
        total = len(results)
        paginated = results[offset:offset + requested_limit]
        for item in paginated:
            item["truncated"] = total > offset + requested_limit
        response: dict[str, Any] = {
            "results": paginated,
            "total": total,
            "ambiguous": ambiguous,
        }
        if ambiguous:
            response["candidates"] = results[:3]
            response["warning"] = "Ambiguous symbol match. Use symbol_id for exact lookup."
        return response

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = [t.replace('"', "") for t in query.split() if t.strip()]
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _node_result(node: dict, score: float, sources: list[str]) -> dict[str, Any]:
        location = node.get("location") or {}
        docstring = node.get("docstring") or ""
        return {
            "id": node["id"],
            "symbol_id": node["id"],
            "name": node["name"],
            "qualified_name": node.get("qualified_name", ""),
            "type": node["type"],
            "file_path": node.get("file_path", ""),
            "language_id": node.get("language_id", node.get("language", "python")),
            "framework_id": node.get("framework_id"),
            "support_level": node.get("support_level", "production"),
            "score": round(max(0.0, min(float(score), 1.0)), 4),
            "match_sources": sources,
            "tags": node.get("tags", []),
            "line_start": location.get("line_start"),
            "line_end": location.get("line_end"),
            "confidence": float(node.get("confidence", 1.0) or 1.0),
            "layer": _assign_search_layer(node.get("file_path", "")),
            "signature": node.get("signature"),
            "docstring_excerpt": docstring[:200] if docstring else None,
            "truncated": False,
        }

    @staticmethod
    def _node_filter_sql(
        type_filter: str | None,
        types: list[str] | None = None,
        file_filter: str | None = None,
        file_path: str | None = None,
        path_prefix: str | None = None,
        exclude_external: bool = True,
        language_id: str | None = None,
    ) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        effective_types = list(types or [])
        if type_filter and type_filter not in effective_types:
            effective_types.append(type_filter)
        if effective_types:
            placeholders = ", ".join("?" for _ in effective_types)
            where.append(f"type IN ({placeholders})")
            params.extend(effective_types)
        elif type_filter:
            where.append("type = ?")
            params.append(type_filter)
        if exclude_external:
            where.append("type != ?")
            params.append("external_symbol")
        if file_path:
            where.append("file_path = ?")
            params.append(file_path)
        if file_filter:
            where.append("file_path LIKE ?")
            params.append(f"%{file_filter}%")
        if path_prefix:
            normalized = path_prefix.replace("\\", "/").rstrip("/")
            where.append("file_path LIKE ?")
            params.append(f"{normalized}/%")
        if language_id:
            where.append("(language_id = ? OR (language_id IS NULL AND language = ?))")
            params.append(language_id)
            params.append(language_id)
        return where, params

    @classmethod
    def _merge_result(
        cls,
        merged: dict[str, dict[str, Any]],
        node: dict,
        score: float,
        source: str,
        layer_name: str,
    ) -> None:
        symbol_id = node["id"]
        if symbol_id not in merged:
            result = cls._node_result(node, score, [source])
            result["search_layer"] = layer_name
            merged[symbol_id] = result
            return
        current = merged[symbol_id]
        current["score"] = round(max(float(current.get("score", 0.0)), score), 4)
        if source not in current["match_sources"]:
            current["match_sources"].append(source)
        current["search_layer"] = cls._best_layer(current.get("search_layer", ""), layer_name)

    @staticmethod
    def _best_layer(current: str, candidate: str) -> str:
        order = {
            "exact_symbol_id": 6,
            "exact_qualified_name": 5,
            "exact_name": 4,
            "fts": 3,
            "like": 2,
            "fuzzy": 1,
            "all": 0,
        }
        return candidate if order.get(candidate, 0) > order.get(current, 0) else current

    @staticmethod
    def _passes_search_filters(
        node: dict,
        layer: str | None,
        include_tests: bool,
        exclude_external: bool,
    ) -> bool:
        node_type = node.get("type")
        file_path = node.get("file_path", "")
        if exclude_external and node_type == "external_symbol":
            return False
        if not include_tests and (node_type == "test" or is_test_path(file_path)):
            return False
        if layer and _assign_search_layer(file_path) != layer:
            return False
        return True

    @staticmethod
    def _score_fts_match(node: dict, query: str) -> tuple[float, list[str]]:
        q = query.lower()
        tags = " ".join(node.get("tags", []) or []).lower()
        fields = {
            "fts_name": (node.get("name") or "").lower(),
            "fts_qualified_name": (node.get("qualified_name") or "").lower(),
            "fts_path": (node.get("file_path") or "").lower(),
            "fts_signature": (node.get("signature") or "").lower(),
            "fts_docstring": (node.get("docstring") or "").lower(),
            "fts_tags": tags,
        }
        weights = {
            "fts_name": 0.8,
            "fts_qualified_name": 0.78,
            "fts_path": 0.65,
            "fts_signature": 0.55,
            "fts_docstring": 0.45,
            "fts_tags": 0.45,
        }
        sources = [source for source, value in fields.items() if q in value]
        if not sources:
            sources = ["fts"]
        score = max(weights.get(source, 0.6) for source in sources)
        return score, sources

    @staticmethod
    def _score_like_match(node: dict, query: str) -> tuple[float, list[str]]:
        q = query.lower()
        tags = " ".join(node.get("tags", []) or []).lower()
        checks = [
            ("like_symbol_id", node.get("id", ""), 0.7),
            ("like_name", node.get("name", ""), 0.68),
            ("like_qualified_name", node.get("qualified_name", ""), 0.62),
            ("like_path", node.get("file_path", ""), 0.55),
            ("like_signature", node.get("signature", ""), 0.5),
            ("like_docstring", node.get("docstring", ""), 0.45),
            ("like_tags", tags, 0.45),
        ]
        matched = [
            (source, score)
            for source, value, score in checks
            if q in str(value).lower()
        ]
        if not matched:
            return 0.4, ["like"]
        return max(score for _, score in matched), [source for source, _ in matched]

    @staticmethod
    def _score_fuzzy_match(name: str, query: str) -> float:
        compact_name = name.replace("_", "").lower()
        compact_query = "".join(query.split()).replace("_", "").lower()
        if not compact_query:
            return 0.2
        ratio = difflib.SequenceMatcher(None, compact_query, compact_name).ratio()
        return round(0.2 + (0.4 * ratio), 4)

    @staticmethod
    def _search_sort_key(
        item: dict[str, Any],
        query_mentions_test: bool,
        include_test_only: bool,
    ) -> tuple[Any, ...]:
        sources = item.get("match_sources", [])
        exact_rank = 99
        if "exact_symbol_id" in sources:
            exact_rank = 0
        elif "exact_qualified_name" in sources:
            exact_rank = 1
        elif "exact_name" in sources:
            exact_rank = 2
        elif "seed_name" in sources:
            exact_rank = 3
        is_test = item.get("type") == "test" or is_test_path(item.get("file_path", ""))
        is_external = item.get("type") == "external_symbol"
        is_init = item.get("name") == "__init__" or item.get("file_path", "").endswith("__init__.py")
        tags = item.get("tags", []) or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = [tags] if tags else []
        is_fw_entry = is_framework_entry_point(
            node_type=item.get("type", ""),
            tags=tags,
            framework_id=item.get("framework_id"),
            name=item.get("name", ""),
            file_path=item.get("file_path", ""),
        )
        is_prod = is_production_path(item.get("file_path", "")) and not is_test and not is_external
        path = item.get("file_path", "")
        return (
            exact_rank,
            0 if (query_mentions_test or include_test_only or not is_test) else 1,
            0 if not is_external else 1,
            0 if is_fw_entry else 1,
            0 if is_prod else 1,
            -(item.get("confidence", 1.0) or 0.0),
            -(item.get("score", 0.0) or 0.0),
            len(path),
            1 if is_init else 0,
            1 if is_test else 0,
            item.get("symbol_id", ""),
        )

    @staticmethod
    def _is_ambiguous(results: list[dict[str, Any]], exact_name_paths: set[str]) -> bool:
        if len(exact_name_paths) > 1:
            return True
        if len(results) < 2:
            return False
        sorted_results = sorted(results, key=lambda item: item.get("score", 0.0), reverse=True)
        top = sorted_results[:3]
        if len(top) >= 2 and (top[0].get("score", 0.0) - top[-1].get("score", 0.0)) < 0.05:
            return True
        return False

    def _count_nodes_where(self, where: list[str], params: list[Any]) -> int:
        row = self.conn.execute(
            f"SELECT COUNT(*) AS cnt FROM nodes WHERE {' AND '.join(where or ['1=1'])}",
            params,
        ).fetchone()
        return row["cnt"] if row else 0

    def node_count(self) -> int:
        c = self.conn
        row = c.execute("SELECT COUNT(*) AS cnt FROM nodes").fetchone()
        return row["cnt"] if row else 0

    # ── Edges ──────────────────────────────────────────────────────────

    def save_edges(self, edges: list[dict], commit: bool = True) -> None:
        """Insert or replace a batch of edges.

        Args:
            edges: List of edge dicts to upsert.
            commit: If True (default), commit after saving. Set to False
                    when calling inside a larger transaction.
        """
        c = self.conn
        safe_executemany(
            c,
            """INSERT OR REPLACE INTO edges
               (id, type, source, target, confidence, source_location, edge_metadata)
               VALUES
               (:id, :type, :source, :target, :confidence, :source_location, :edge_metadata)""",
            [
                {
                    "id": e["id"],
                    "type": e["type"].value if hasattr(e["type"], "value") else e["type"],
                    "source": e["source"],
                    "target": e["target"],
                    "confidence": e.get("confidence", 1.0),
                    "source_location": json.dumps(e["source_location"]) if e.get("source_location") else None,
                    "edge_metadata": json.dumps(e.get("metadata") or e.get("edge_metadata")) if (e.get("metadata") or e.get("edge_metadata")) else None,
                }
                for e in edges
            ],
        )
        if commit:
            c.commit()

    def query_edges(
        self, filters: dict | None = None
    ) -> list[dict]:
        """Query edges with optional filters.

        Supported filter keys:
          type    — exact match on edge type
          source  — exact match on source node ID
          target  — exact match on target node ID
          limit   — max rows (default 500)
          offset  — row offset
        """
        where_clauses: list[str] = []
        params: list = []

        if filters:
            if "type" in filters:
                where_clauses.append("type = ?")
                params.append(filters["type"])
            if "source" in filters:
                where_clauses.append("source = ?")
                params.append(filters["source"])
            if "target" in filters:
                where_clauses.append("target = ?")
                params.append(filters["target"])

        where = ""
        if where_clauses:
            where = " WHERE " + " AND ".join(where_clauses)

        limit = filters.get("limit", 500) if filters else 500
        offset = filters.get("offset", 0) if filters else 0

        c = self.conn
        rows = c.execute(
            f"SELECT * FROM edges{where} ORDER BY id LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        return [_row_to_edge(r) for r in rows]

    def edge_count(self) -> int:
        c = self.conn
        row = c.execute("SELECT COUNT(*) AS cnt FROM edges").fetchone()
        return row["cnt"] if row else 0

    # ── Bulk operations ────────────────────────────────────────────────

    def load_all_nodes(self) -> list[dict]:
        """Load all nodes from the database."""
        c = self.conn
        rows = c.execute("SELECT * FROM nodes ORDER BY id").fetchall()
        return [_row_to_node(r) for r in rows]

    def load_all_edges(self) -> list[dict]:
        """Load all edges from the database."""
        c = self.conn
        rows = c.execute("SELECT * FROM edges ORDER BY id").fetchall()
        return [_row_to_edge(r) for r in rows]

    def delete_nodes_by_file(self, file_path: str) -> int:
        """Delete all nodes for a specific file. Returns count removed."""
        c = self.conn
        # Collect node IDs for this file before deleting
        rows = c.execute(
            "SELECT id FROM nodes WHERE file_path = ?", [file_path]
        ).fetchall()
        node_ids = [r["id"] for r in rows]
        if not node_ids:
            return 0
        c.execute("DELETE FROM nodes WHERE file_path = ?", [file_path])
        if self.has_fts_table():
            for nid in node_ids:
                c.execute("DELETE FROM symbols_fts WHERE symbol_id = ?", [nid])
        # Delete edges touching any of those nodes
        for nid in node_ids:
            c.execute("DELETE FROM edges WHERE source = ? OR target = ?", [nid, nid])
        c.commit()
        return len(node_ids)

    def delete_edges_by_file(self, file_path: str) -> int:
        """Delete all edges touching nodes in *file_path*. Returns count removed."""
        c = self.conn
        rows = c.execute(
            "SELECT id FROM nodes WHERE file_path = ?", [file_path]
        ).fetchall()
        node_ids = [r["id"] for r in rows]
        if not node_ids:
            return 0
        removed = 0
        for nid in node_ids:
            cur = c.execute("DELETE FROM edges WHERE source = ? OR target = ?", [nid, nid])
            removed += cur.rowcount
        c.commit()
        return removed

    def clear(self) -> None:
        """Delete all data from tables."""
        c = self.conn
        c.execute("DELETE FROM nodes")
        c.execute("DELETE FROM edges")
        if self.has_fts_table():
            c.execute("DELETE FROM symbols_fts")
        c.commit()

    # ── Incremental / patch operations ─────────────────────────────────

    def delete_nodes_by_ids(self, node_ids: list[str]) -> int:
        """Delete specific nodes and their FTS entries. Returns count removed.

        Does NOT commit — caller must commit/rollback.
        """
        if not node_ids:
            return 0
        c = self.conn
        # Delete FTS entries first
        if self.has_fts_table():
            for nid in node_ids:
                c.execute("DELETE FROM symbols_fts WHERE symbol_id = ?", [nid])
        # Delete nodes (use chunking for large lists)
        for nid in node_ids:
            c.execute("DELETE FROM nodes WHERE id = ?", [nid])
        return len(node_ids)

    def delete_edges_touching_nodes(self, node_ids: list[str]) -> int:
        """Delete all edges where source OR target is in *node_ids*.

        Does NOT commit — caller must commit/rollback.
        Returns total count of edges removed.
        """
        if not node_ids:
            return 0
        c = self.conn
        removed = 0
        for nid in node_ids:
            cur = c.execute(
                "DELETE FROM edges WHERE source = ? OR target = ?", [nid, nid]
            )
            removed += cur.rowcount
        return removed

    def delete_symbols_fts(self, symbol_ids: list[str]) -> int:
        """Delete specific FTS entries. Returns count removed.

        Does NOT commit — caller must commit/rollback.
        """
        if not self.has_fts_table() or not symbol_ids:
            return 0
        c = self.conn
        removed = 0
        for sid in symbol_ids:
            cur = c.execute("DELETE FROM symbols_fts WHERE symbol_id = ?", [sid])
            removed += cur.rowcount
        return removed

    def upsert_symbols_fts(self, nodes: list[dict]) -> int:
        """Insert or update FTS entries for the given nodes.

        Public wrapper around ``_sync_fts``. Does NOT commit.
        Returns count of nodes upserted.
        """
        self._sync_fts(nodes)
        return len(nodes)

    def dangling_edge_count(self) -> int:
        """Count edges whose source or target doesn't exist in the nodes table."""
        c = self.conn
        row = c.execute(
            "SELECT COUNT(*) AS cnt FROM edges "
            "WHERE source NOT IN (SELECT id FROM nodes) "
            "   OR target NOT IN (SELECT id FROM nodes)"
        ).fetchone()
        return row["cnt"] if row else 0

    def get_node_ids_by_files(self, file_paths: list[str]) -> list[str]:
        """Get all node IDs belonging to the given file paths."""
        if not file_paths:
            return []
        c = self.conn
        node_ids: list[str] = []
        for fp in file_paths:
            rows = c.execute(
                "SELECT id FROM nodes WHERE file_path = ?", [fp]
            ).fetchall()
            node_ids.extend(r["id"] for r in rows)
        return node_ids

    def get_dependent_files(
        self, module_names: list[str],
    ) -> list[str]:
        """Find files that import from any of the given module names.

        A file "depends on" a module if it has an ``imports`` edge whose
        target is an import node with a qualified_name under that module.

        Args:
            module_names: List of module name prefixes, e.g. ``["app.api.auth"]``.

        Returns:
            Sorted list of unique file paths (relative) that depend on the modules.
        """
        if not module_names:
            return []
        c = self.conn
        dependents: set[str] = set()
        for mod in module_names:
            # Find import nodes whose qualified_name starts with this module
            like_pattern = f"{mod}.%"
            rows = c.execute(
                """SELECT DISTINCT e.source
                   FROM edges e
                   JOIN nodes n ON e.target = n.id
                   WHERE e.type = 'imports'
                     AND (n.qualified_name = ? OR n.qualified_name LIKE ?)""",
                [mod, like_pattern],
            ).fetchall()
            for row in rows:
                dependents.add(row["source"])
        return sorted(dependents)

    def node_count_by_files(self, file_paths: list[str]) -> int:
        """Count total nodes across the given file paths."""
        if not file_paths:
            return 0
        c = self.conn
        total = 0
        for fp in file_paths:
            row = c.execute(
                "SELECT COUNT(*) AS cnt FROM nodes WHERE file_path = ?", [fp]
            ).fetchone()
            total += row["cnt"] if row else 0
        return total

    # ── Enrichment operations (schema 1.1.0) ───────────────────────────

    def get_enrichment_status(self) -> dict[str, Any]:
        """Return enrichment statistics across all nodes.

        Returns counts by enrichment_status, confidence breakdown,
        and enriched file count.
        """
        c = self.conn
        total = self.node_count()
        status_counts: dict[str, int] = {}
        for row in c.execute(
            "SELECT enrichment_status, COUNT(*) AS cnt FROM nodes GROUP BY enrichment_status"
        ).fetchall():
            key = row["enrichment_status"] or "pending"
            status_counts[key] = row["cnt"]

        enriched = status_counts.get("analyzed", 0)
        pending = status_counts.get("pending", 0)
        skipped = status_counts.get("skipped", 0)
        error = status_counts.get("error", 0)

        # Confidence breakdown for analyzed nodes
        conf_breakdown: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
        for row in c.execute(
            "SELECT enrichment_confidence, COUNT(*) AS cnt FROM nodes "
            "WHERE enrichment_status = 'analyzed' "
            "GROUP BY enrichment_confidence"
        ).fetchall():
            key = row["enrichment_confidence"] or "medium"
            if key in conf_breakdown:
                conf_breakdown[key] = row["cnt"]

        # Count distinct files with at least one enriched node
        enriched_files_row = c.execute(
            "SELECT COUNT(DISTINCT file_path) AS cnt FROM nodes "
            "WHERE enrichment_status = 'analyzed' AND file_path != ''"
        ).fetchone()
        enriched_files = enriched_files_row["cnt"] if enriched_files_row else 0

        total_files_row = c.execute(
            "SELECT COUNT(DISTINCT file_path) AS cnt FROM nodes WHERE file_path != ''"
        ).fetchone()
        total_files = total_files_row["cnt"] if total_files_row else 0

        last_enriched = self.get_meta("enrichment_last_import") or ""

        return {
            "total_nodes": total,
            "enriched_nodes": enriched,
            "pending_nodes": pending,
            "skipped_nodes": skipped,
            "error_nodes": error,
            "enriched_files": enriched_files,
            "total_files": total_files,
            "confidence_breakdown": conf_breakdown,
            "last_enriched_at": last_enriched,
        }

    def clear_enrichment(self) -> int:
        """Reset all enrichment columns to defaults on all nodes.

        Returns count of nodes cleared.
        """
        c = self.conn
        row = c.execute("SELECT COUNT(*) AS cnt FROM nodes").fetchone()
        total = row["cnt"] if row else 0
        c.execute(
            """UPDATE nodes SET
               summary = '', role = '', responsibilities = '[]',
               edge_cases = '[]', test_relevance = '',
               enrichment_confidence = '', enrichment_evidence = '[]',
               enrichment_status = '', enriched_at = ''"""
        )
        # Remove enrichment meta keys
        c.execute("DELETE FROM meta WHERE key LIKE 'enrichment_%'")
        c.commit()
        return total

    def update_node_enrichment(
        self,
        node_id: str,
        summary: str = "",
        role: str = "",
        responsibilities: list[str] | None = None,
        edge_cases: list[str] | None = None,
        test_relevance: str = "",
        enrichment_confidence: str = "",
        enrichment_evidence: list[dict] | None = None,
        enrichment_status: str = "analyzed",
        enriched_at: str = "",
        commit: bool = True,
    ) -> None:
        """Update enrichment fields for a single node.

        Args:
            commit: If True (default), commit after updating. Set to False
                    when calling inside a larger transaction.
        """
        c = self.conn
        c.execute(
            """UPDATE nodes SET
               summary = ?, role = ?,
               responsibilities = ?, edge_cases = ?,
               test_relevance = ?, enrichment_confidence = ?,
               enrichment_evidence = ?, enrichment_status = ?,
               enriched_at = ?
               WHERE id = ?""",
            [
                summary,
                role,
                json.dumps(responsibilities or [], ensure_ascii=False),
                json.dumps(edge_cases or [], ensure_ascii=False),
                test_relevance,
                enrichment_confidence,
                json.dumps(enrichment_evidence or [], ensure_ascii=False),
                enrichment_status,
                enriched_at,
                node_id,
            ],
        )
        if commit:
            c.commit()
