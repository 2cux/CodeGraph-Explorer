"""SQLite-based storage for graph data.

Stores nodes and edges in a local SQLite database at ``.codegraph/index.sqlite``.

All batch writes are automatically chunked to avoid hitting SQLite's
``SQLITE_MAX_VARIABLE_NUMBER`` limit.
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

from codegraph.storage.sqlite_utils import safe_executemany

SUPPORTED_SCHEMA_VERSION = "1.0.0"


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
    return data


def _row_to_edge(row: sqlite3.Row) -> dict:
    data = dict(row)
    if isinstance(data.get("source_location"), str):
        data["source_location"] = json.loads(data["source_location"])
    if isinstance(data.get("edge_metadata"), str):
        data["metadata"] = json.loads(data.pop("edge_metadata"))
    else:
        data.pop("edge_metadata", None)
    return data


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
    location TEXT,
    signature TEXT,
    docstring TEXT,
    code_preview TEXT,
    visibility TEXT DEFAULT 'public',
    tags TEXT DEFAULT '[]',
    metadata TEXT DEFAULT '{}'
);
"""

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

    def save_nodes(self, nodes: list[dict]) -> None:
        """Insert or replace a batch of nodes.

        Each dict should have keys matching the GraphNode model fields.
        """
        c = self.conn
        safe_executemany(
            c,
            """INSERT OR REPLACE INTO nodes
               (id, type, name, qualified_name, display_name, file_path,
                module, language, location, signature, docstring,
                code_preview, visibility, tags, metadata)
               VALUES
               (:id, :type, :name, :qualified_name, :display_name, :file_path,
                :module, :language, :location, :signature, :docstring,
                :code_preview, :visibility, :tags, :metadata)""",
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
                    "location": json.dumps(n["location"]) if n.get("location") else None,
                    "signature": n.get("signature"),
                    "docstring": n.get("docstring"),
                    "code_preview": n.get("code_preview"),
                    "visibility": n.get("visibility", "public"),
                    "tags": n["tags"] if isinstance(n.get("tags"), str) else json.dumps(n.get("tags", []), ensure_ascii=False),
                    "metadata": n["metadata"] if isinstance(n.get("metadata"), str) else json.dumps(n.get("metadata", {}), ensure_ascii=False),
                }
                for n in nodes
            ],
        )
        self._sync_fts(nodes)
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
        file_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
        use_fts: bool = True,
    ) -> dict[str, Any]:
        """Search symbols in SQLite using exact, FTS5, LIKE, then fuzzy passes."""
        q = query.strip()
        seen: set[str] = set()
        results: list[dict[str, Any]] = []

        def add_rows(rows: list[sqlite3.Row], score: float, source: str) -> None:
            for row in rows:
                data = _row_to_node(row)
                if data["id"] in seen:
                    continue
                seen.add(data["id"])
                results.append(self._node_result(data, score, [source]))

        base_where, base_params = self._node_filter_sql(type_filter, file_filter)
        c = self.conn

        if q:
            exact_where = base_where + ["(id = ? OR name = ? OR qualified_name = ?)"]
            rows = c.execute(
                f"SELECT * FROM nodes WHERE {' AND '.join(exact_where)} ORDER BY name LIMIT ?",
                [*base_params, q, q, q, limit + offset],
            ).fetchall()
            for row in rows:
                data = _row_to_node(row)
                if data["id"] in seen:
                    continue
                seen.add(data["id"])
                source = "node_id" if data["id"] == q else "exact_name"
                if data.get("qualified_name") == q:
                    source = "qualified_name"
                results.append(self._node_result(data, 1.0, [source]))

            if use_fts and self.has_fts_table():
                fts_query = self._fts_query(q)
                if fts_query:
                    fts_where = [w.replace("type", "n.type").replace("file_path", "n.file_path") for w in base_where]
                    rows = c.execute(
                        f"""SELECT n.*, bm25(symbols_fts) AS rank
                            FROM symbols_fts JOIN nodes n ON n.id = symbols_fts.symbol_id
                            WHERE symbols_fts MATCH ? {' AND ' + ' AND '.join(fts_where) if fts_where else ''}
                            ORDER BY rank LIMIT ?""",
                        [fts_query, *base_params, limit + offset],
                    ).fetchall()
                    for row in rows:
                        data = _row_to_node(row)
                        if data["id"] in seen:
                            continue
                        seen.add(data["id"])
                        results.append(self._node_result(data, 0.85, ["fts5"]))

            if len(results) < limit + offset:
                like = f"%{q}%"
                like_where = base_where + [
                    "(id LIKE ? OR name LIKE ? OR qualified_name LIKE ? OR file_path LIKE ? OR docstring LIKE ?)"
                ]
                rows = c.execute(
                    f"SELECT * FROM nodes WHERE {' AND '.join(like_where)} ORDER BY name LIMIT ?",
                    [*base_params, like, like, like, like, like, limit + offset],
                ).fetchall()
                add_rows(rows, 0.7, "like")

            if len(results) < limit + offset:
                fuzzy = f"%{''.join(q.split())}%"
                rows = c.execute(
                    f"SELECT * FROM nodes WHERE {' AND '.join(base_where or ['1=1'])} "
                    "AND replace(name, '_', '') LIKE ? ORDER BY name LIMIT ?",
                    [*base_params, fuzzy, limit + offset],
                ).fetchall()
                add_rows(rows, 0.45, "fuzzy")
        else:
            rows = c.execute(
                f"SELECT * FROM nodes WHERE {' AND '.join(base_where or ['1=1'])} ORDER BY id LIMIT ? OFFSET ?",
                [*base_params, limit, offset],
            ).fetchall()
            add_rows(rows, 0.5, "all")
            total = self._count_nodes_where(base_where, base_params)
            return {"results": results, "total": total}

        total = len(results)
        return {"results": results[offset:offset + limit], "total": total}

    @staticmethod
    def _fts_query(query: str) -> str:
        tokens = [t.replace('"', "") for t in query.split() if t.strip()]
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _node_result(node: dict, score: float, sources: list[str]) -> dict[str, Any]:
        location = node.get("location") or {}
        return {
            "id": node["id"],
            "symbol_id": node["id"],
            "name": node["name"],
            "type": node["type"],
            "file_path": node.get("file_path", ""),
            "score": score,
            "match_sources": sources,
            "tags": node.get("tags", []),
            "line_start": location.get("line_start"),
            "line_end": location.get("line_end"),
        }

    @staticmethod
    def _node_filter_sql(
        type_filter: str | None,
        file_filter: str | None,
    ) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        if type_filter:
            where.append("type = ?")
            params.append(type_filter)
        if file_filter:
            where.append("file_path LIKE ?")
            params.append(f"%{file_filter}%")
        return where, params

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

    def save_edges(self, edges: list[dict]) -> None:
        """Insert or replace a batch of edges."""
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
