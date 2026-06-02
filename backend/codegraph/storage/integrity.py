"""Storage integrity checks for .codegraph artifacts.

Compares SQLite, JSON, FTS, metadata, and state counts.
SQLite is the source of truth; JSON should mirror SQLite.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from codegraph.graph.models import IndexMetadata
from codegraph.storage.sqlite_store import SUPPORTED_SCHEMA_VERSION, SqliteStore


def check_storage_integrity(cg_dir: Path) -> dict[str, Any]:
    """Compare SQLite, JSON, metadata, state, and FTS counts.

    Returns:
        dict with keys:
          - status: "ok" | "warning" | "error"
          - consistency: "ok" | "warning" | "error"
          - suggestion: str | None (repair hint if inconsistent)
          - checks: list[dict] — individual check results
          - counts: dict — sqlite_nodes, sqlite_edges, json_nodes,
                    json_edges, fts_symbols, metadata_symbols, metadata_edges
    """
    checks: list[dict[str, Any]] = []

    def add(status: str, name: str, message: str, **details: Any) -> None:
        checks.append({"status": status, "name": name, "message": message, **details})

    # ── JSON counts ───────────────────────────────────────────────────
    nodes_json_count = _json_count(cg_dir / "nodes.json")
    edges_json_count = _json_count(cg_dir / "edges.json")
    if nodes_json_count is None:
        add("error", "nodes.json", "nodes.json missing or unreadable")
    else:
        add("ok", "nodes.json", f"nodes.json nodes={nodes_json_count}", count=nodes_json_count)
    if edges_json_count is None:
        add("error", "edges.json", "edges.json missing or unreadable")
    else:
        add("ok", "edges.json", f"edges.json edges={edges_json_count}", count=edges_json_count)

    # ── Metadata ──────────────────────────────────────────────────────
    metadata_path = cg_dir / "metadata.json"
    raw_metadata = _load_json_object(metadata_path)
    metadata = _load_metadata(metadata_path)
    if metadata is None:
        add("warning", "metadata", "metadata.json missing or unreadable")
    else:
        add("ok", "metadata", "metadata.json readable")
        _check_schema("metadata.schema_version", raw_metadata.get("schema_version") if raw_metadata else None, add)
        _compare_count("metadata.symbol_count", metadata.symbol_count, nodes_json_count, add)
        _compare_count("metadata.edge_count", metadata.edge_count, edges_json_count, add)
        add("ok", "build_version", f"indexer_version={metadata.indexer_version}")

    # ── State ─────────────────────────────────────────────────────────
    _check_state(cg_dir / "state.json", nodes_json_count, edges_json_count, add)

    # ── SQLite ────────────────────────────────────────────────────────
    sqlite_nodes: int | None = None
    sqlite_edges: int | None = None
    fts_count: int | None = None

    sqlite_path = cg_dir / "index.sqlite"
    if not sqlite_path.exists():
        add("warning", "index.sqlite", "index.sqlite missing; JSON fallback will be used")
    else:
        store = SqliteStore(sqlite_path)
        try:
            sqlite_nodes = store.node_count()
            sqlite_edges = store.edge_count()
            add("ok", "index.sqlite", "index.sqlite present")
            add("ok", "sqlite.nodes", f"SQLite nodes={sqlite_nodes}", count=sqlite_nodes)
            add("ok", "sqlite.edges", f"SQLite edges={sqlite_edges}", count=sqlite_edges)
            _compare_count("sqlite.nodes_vs_json", sqlite_nodes, nodes_json_count, add)
            _compare_count("sqlite.edges_vs_json", sqlite_edges, edges_json_count, add)
            journal = store.get_journal_mode()
            if journal == "wal":
                add("ok", "sqlite.wal", "SQLite WAL enabled")
            else:
                add("warning", "sqlite.wal", f"SQLite WAL not enabled (journal_mode={journal})")
            if store.wal_warning:
                add("warning", "sqlite.wal.warning", store.wal_warning)
            status, message = store.schema_version_status()
            add(status, "sqlite.schema_version", message)
            fts_count = store.fts_count()
            if fts_count is None:
                add("warning", "sqlite.fts", "symbols_fts missing; LIKE fallback will be used")
            else:
                add("ok", "sqlite.fts", f"symbols_fts rows={fts_count}", count=fts_count)
                if fts_count != sqlite_nodes:
                    add("warning", "sqlite.fts_count",
                        f"symbols_fts row count differs from nodes", fts=fts_count, nodes=sqlite_nodes)
            if store.fts_warning:
                add("warning", "sqlite.fts.warning", store.fts_warning)
        except Exception as e:
            add("error", "index.sqlite", f"index.sqlite unreadable: {e}")
        finally:
            store.close()

    # ── Consistency verdict ───────────────────────────────────────────
    status_order = {"ok": 0, "warning": 1, "error": 2}
    overall = max((c["status"] for c in checks), key=lambda s: status_order[s], default="ok")

    has_errors = any(c["status"] == "error" for c in checks)
    has_warnings = any(c["status"] == "warning" for c in checks)
    if has_errors:
        consistency = "error"
        suggestion = "codegraph init --force"
    elif has_warnings:
        consistency = "warning"
        suggestion = "codegraph doctor --repair  (or codegraph init --force)"
    else:
        consistency = "ok"
        suggestion = None

    return {
        "status": overall,
        "consistency": consistency,
        "suggestion": suggestion,
        "checks": checks,
        "counts": {
            "sqlite_nodes": sqlite_nodes,
            "sqlite_edges": sqlite_edges,
            "json_nodes": nodes_json_count,
            "json_edges": edges_json_count,
            "fts_symbols": fts_count,
            "metadata_symbols": metadata.symbol_count if metadata else None,
            "metadata_edges": metadata.edge_count if metadata else None,
        },
    }


# ── Internal helpers ──────────────────────────────────────────────────


def _json_count(path: Path) -> int | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return len(data) if isinstance(data, list) else None
    except Exception:
        return None


def _load_metadata(path: Path) -> IndexMetadata | None:
    try:
        if not path.exists():
            return None
        return IndexMetadata.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _check_schema(name: str, version: str | None, add) -> None:
    if not version:
        add("warning", name, f"{name} missing. Run: codegraph init --force")
    elif version != SUPPORTED_SCHEMA_VERSION:
        add("error", name, f"{name}={version} unsupported. Run: codegraph init --force")
    else:
        add("ok", name, f"{name}={version}")


def _compare_count(name: str, left: int | None, right: int | None, add) -> None:
    if left is None or right is None:
        return
    if left == right:
        add("ok", name, f"{name} matches ({left})")
    else:
        add("error", name, f"{name} mismatch: {left} != {right}", left=left, right=right)


def _check_state(
    state_path: Path,
    nodes_count: int | None,
    edges_count: int | None,
    add,
) -> None:
    """Check state.json for status and stats consistency."""
    if not state_path.exists():
        add("warning", "state", "state.json missing")
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        add("warning", "state", "state.json unreadable")
        return

    if not isinstance(state, dict):
        add("warning", "state", "state.json is not a valid object")
        return

    state_status = state.get("status", "unknown")
    last_indexed = state.get("last_indexed_at")
    deleted_files = state.get("deleted_files", [])

    add("ok", "state.status", f"state status={state_status}")
    if last_indexed:
        add("ok", "state.last_indexed", f"state last_indexed_at={last_indexed}")
    else:
        add("warning", "state.last_indexed", "state has no last_indexed_at")

    if deleted_files:
        add("ok", "state.deleted_files", f"state deleted_files={len(deleted_files)}")
    else:
        add("ok", "state.deleted_files", "state deleted_files=0")

    # Check stats if present
    stats = state.get("stats")
    if isinstance(stats, dict):
        _compare_count("state.symbols", stats.get("symbols"), nodes_count, add)
        _compare_count("state.edges", stats.get("edges"), edges_count, add)
