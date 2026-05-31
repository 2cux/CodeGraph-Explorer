"""SQLite-based storage for graph data.

Stores nodes and edges in a local SQLite database at ``.codegraph/index.sqlite``.

All batch writes are automatically chunked to avoid hitting SQLite's
``SQLITE_MAX_VARIABLE_NUMBER`` limit.
"""

import json
import sqlite3
from pathlib import Path

from codegraph.storage.sqlite_utils import safe_executemany


def _row_to_node(row: sqlite3.Row) -> dict:
    data = dict(row)
    if isinstance(data.get("location"), str):
        data["location"] = json.loads(data["location"])
    if isinstance(data.get("metadata"), str):
        data["metadata"] = json.loads(data["metadata"])
    return data


def _row_to_edge(row: sqlite3.Row) -> dict:
    data = dict(row)
    if isinstance(data.get("source_location"), str):
        data["source_location"] = json.loads(data["source_location"])
    if isinstance(data.get("edge_metadata"), str):
        data["edge_metadata"] = json.loads(data["edge_metadata"])
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


class SqliteStore:
    """Read/write graph data to a local SQLite database.

    The database file is created at *db_path* (e.g. ``.codegraph/index.sqlite``).
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
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
        c.executescript(CREATE_NODE_INDEXES)
        c.executescript(CREATE_EDGE_INDEXES)
        c.commit()

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
                    "tags": json.dumps(n.get("tags", []), ensure_ascii=False),
                    "metadata": json.dumps(n.get("metadata", {}), ensure_ascii=False),
                }
                for n in nodes
            ],
        )
        c.commit()

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
                    "edge_metadata": json.dumps(e["metadata"]) if e.get("metadata") else None,
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
        c.commit()
