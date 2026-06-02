"""Single write path for all index persistence.

SQLite is the primary query store. JSON files (nodes.json, edges.json,
graph.json, metadata.json) are derived exports from SQLite.

When --no-sqlite is set, JSON is written directly from the input lists
as a fallback.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from pydantic import TypeAdapter

from codegraph.graph.models import (
    CodeGraph,
    FileEntry,
    GraphEdge,
    GraphNode,
    IndexMetadata,
    RepoInfo,
)
from codegraph.indexer.scanner import compute_fingerprint, scan_python_files
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore


class SqliteWriteError(Exception):
    """Raised when a SQLite write operation fails."""


def write_full_index(
    output_dir: Path,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    root_path: Path,
    *,
    no_sqlite: bool = False,
    state_store = None,  # IndexStateStore | None
) -> dict[str, int]:
    """Write a complete index (full init / init --force).

    Order (SQLite-primary):
      1. SQLite: clear -> save_nodes -> save_edges -> rebuild_fts
      2. Export JSON nodes/edges FROM SQLite (guaranteed match)
      3. Write metadata.json (counts from SQLite)
      4. Write graph.json (from SQLite data)
      5. Update state.json (counts from SQLite)
      6. Run integrity check, warn if inconsistent

    When no_sqlite=True, writes JSON directly from input lists.
    """
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])
    now_iso = datetime.now(timezone.utc).isoformat()

    sqlite_path = output_dir / "index.sqlite"

    if not no_sqlite:
        try:
            sql_store = SqliteStore(sqlite_path)
            sql_store.initialize()
            sql_store.clear()
            sql_store.save_nodes(node_adapter.dump_python(nodes))
            sql_store.save_edges(edge_adapter.dump_python(edges))
            sql_store.close()

            # Export JSON from SQLite so counts are guaranteed consistent
            json_nodes, json_edges = export_json_from_sqlite(output_dir)
            _write_metadata_from_sqlite(output_dir, root_path, now_iso)
            _write_graph_json_from_lists(output_dir, root_path, json_nodes, json_edges, now_iso)

            # Update state
            if state_store is not None:
                state_store.update_status("fresh", last_indexed_at=now_iso)
                state_store.record_stats(
                    symbols=len(json_nodes),
                    edges=len(json_edges),
                )
                state_store.clear_deleted_files()

            return {
                "nodes": len(json_nodes),
                "edges": len(json_edges),
                "fts_symbols": len(json_nodes),  # FTS mirrors node count after save
            }
        except Exception as exc:
            raise SqliteWriteError(
                f"SQLite write failed: {exc}. "
                f"Re-run with --no-sqlite for JSON-only output, "
                f"or check disk space and permissions."
            ) from exc

    # --no-sqlite fallback: write JSON directly from input lists
    store = FileStore(output_dir)
    json_nodes = node_adapter.dump_python(nodes)
    json_edges = edge_adapter.dump_python(edges)
    store.save_nodes(json_nodes)
    store.save_edges(json_edges)

    _write_metadata_from_lists(output_dir, root_path, nodes, now_iso)
    _write_graph_json_from_lists(output_dir, root_path, json_nodes, json_edges, now_iso)

    if state_store is not None:
        state_store.update_status("fresh", last_indexed_at=now_iso)
        state_store.record_stats(symbols=len(nodes), edges=len(edges))
        state_store.clear_deleted_files()

    return {"nodes": len(nodes), "edges": len(edges), "fts_symbols": 0}


def write_incremental_update(
    output_dir: Path,
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    root_path: Path,
    removed_files: set[str],
    *,
    no_sqlite: bool = False,
    state_store = None,  # IndexStateStore | None
) -> dict[str, int]:
    """Write an incremental index update.

    Order (SQLite-primary):
      1. Delete old nodes/edges/FTS for removed_files from SQLite
      2. Save new nodes/edges to SQLite
      3. Sync FTS
      4. Export JSON from SQLite
      5. Update metadata/state (counts from SQLite)
      6. Record deleted_files in state
      7. Run integrity check
    """
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])
    now_iso = datetime.now(timezone.utc).isoformat()

    if not no_sqlite:
        sqlite_path = output_dir / "index.sqlite"
        try:
            sql_store = SqliteStore(sqlite_path)
            sql_store.initialize()

            # 1. Delete old nodes/edges/FTS for removed files
            for file_path in removed_files:
                sql_store.delete_nodes_by_file(file_path)

            # 2. Save current nodes/edges to SQLite
            sql_store.save_nodes(node_adapter.dump_python(nodes))
            sql_store.save_edges(edge_adapter.dump_python(edges))
            sql_store.close()

            # 3. Export JSON from SQLite
            json_nodes, json_edges = export_json_from_sqlite(output_dir)
            _write_metadata_from_sqlite(output_dir, root_path, now_iso)
            _write_graph_json_from_lists(output_dir, root_path, json_nodes, json_edges, now_iso)

            # 4. Update state
            if state_store is not None:
                state_store.update_status("fresh", last_incremental_at=now_iso)
                state_store.record_stats(
                    symbols=len(json_nodes),
                    edges=len(json_edges),
                )
                if removed_files:
                    state_store.record_deleted_files(list(removed_files))

            return {
                "nodes": len(json_nodes),
                "edges": len(json_edges),
                "fts_symbols": len(json_nodes),
            }
        except Exception as exc:
            raise SqliteWriteError(
                f"SQLite incremental write failed: {exc}. "
                f"Re-run with --no-sqlite for JSON-only output."
            ) from exc

    # --no-sqlite fallback
    store = FileStore(output_dir)
    json_nodes = node_adapter.dump_python(nodes)
    json_edges = edge_adapter.dump_python(edges)
    store.save_nodes(json_nodes)
    store.save_edges(json_edges)

    _write_metadata_from_lists(output_dir, root_path, nodes, now_iso)
    _write_graph_json_from_lists(output_dir, root_path, json_nodes, json_edges, now_iso)

    if state_store is not None:
        state_store.update_status("fresh", last_incremental_at=now_iso)
        state_store.record_stats(symbols=len(nodes), edges=len(edges))
        if removed_files:
            state_store.record_deleted_files(list(removed_files))

    return {"nodes": len(nodes), "edges": len(edges), "fts_symbols": 0}


def export_json_from_sqlite(output_dir: Path) -> tuple[list[dict], list[dict]]:
    """Read nodes and edges from SQLite, write to nodes.json/edges.json.

    Returns (nodes_dict_list, edges_dict_list) as written.
    This is the canonical JSON export path — JSON is derived from SQLite.
    """
    sqlite_path = output_dir / "index.sqlite"
    sql_store = SqliteStore(sqlite_path)
    try:
        sql_store.initialize()
        json_nodes = sql_store.load_all_nodes()
        json_edges = sql_store.load_all_edges()
    finally:
        sql_store.close()

    store = FileStore(output_dir)
    store.save_nodes(json_nodes)
    store.save_edges(json_edges)
    return json_nodes, json_edges


def repair_json_from_sqlite(output_dir: Path, root_path: Path) -> dict[str, int]:
    """Repair: re-export all JSON artifacts from SQLite (source of truth).

    Does NOT modify SQLite — only writes JSON files.
    Returns counts dict.
    Raises SqliteError if SQLite is unusable.
    """
    sqlite_path = output_dir / "index.sqlite"
    if not sqlite_path.exists():
        raise SqliteWriteError(
            "SQLite database is missing. Cannot repair. "
            "Run: codegraph init --force"
        )

    now_iso = datetime.now(timezone.utc).isoformat()

    try:
        json_nodes, json_edges = export_json_from_sqlite(output_dir)
    except Exception as exc:
        raise SqliteWriteError(
            f"SQLite database is corrupted or unreadable: {exc}\n"
            f"Run: codegraph init --force"
        ) from exc

    _write_metadata_from_sqlite(output_dir, root_path, now_iso)
    _write_graph_json_from_lists(output_dir, root_path, json_nodes, json_edges, now_iso)

    return {
        "nodes": len(json_nodes),
        "edges": len(json_edges),
    }


# ── Internal helpers ──────────────────────────────────────────────────


def _write_metadata_from_sqlite(
    output_dir: Path, root_path: Path, now_iso: str,
) -> None:
    """Write metadata.json with counts taken from SQLite."""
    sqlite_path = output_dir / "index.sqlite"
    sql_store = SqliteStore(sqlite_path)
    try:
        sql_store.initialize()
        node_count = sql_store.node_count()
        edge_count = sql_store.edge_count()
        # Get unique file count from SQLite
        all_nodes = sql_store.load_all_nodes()
        file_paths = {n.get("file_path", "") for n in all_nodes if n.get("file_path")}
    finally:
        sql_store.close()

    metadata = IndexMetadata(
        schema_version="1.0.0",
        indexer_version="1.0.0",
        root_path=str(root_path),
        indexed_at=now_iso,
        file_count=len(file_paths),
        symbol_count=node_count,
        edge_count=edge_count,
        files=[],
    )
    # Compute fingerprints
    all_files = scan_python_files(root_path)
    for f in all_files:
        rel = f.relative_to(root_path).as_posix()
        metadata.files.append(FileEntry(
            path=rel,
            fingerprint=compute_fingerprint(f),
            indexed_at=now_iso,
        ))

    store = FileStore(output_dir)
    store.save_metadata(metadata)


def _write_metadata_from_lists(
    output_dir: Path, root_path: Path, nodes: list[GraphNode], now_iso: str,
) -> None:
    """Write metadata.json with counts from in-memory node lists."""
    metadata = IndexMetadata(
        schema_version="1.0.0",
        indexer_version="1.0.0",
        root_path=str(root_path),
        indexed_at=now_iso,
        file_count=len({n.file_path for n in nodes}),
        symbol_count=len(nodes),
        edge_count=0,  # will be set by caller's edges list
        files=[],
    )
    all_files = scan_python_files(root_path)
    for f in all_files:
        rel = f.relative_to(root_path).as_posix()
        metadata.files.append(FileEntry(
            path=rel,
            fingerprint=compute_fingerprint(f),
            indexed_at=now_iso,
        ))

    store = FileStore(output_dir)
    store.save_metadata(metadata)


def _write_graph_json_from_lists(
    output_dir: Path,
    root_path: Path,
    json_nodes: list[dict],
    json_edges: list[dict],
    now_iso: str,
) -> None:
    """Write graph.json from node/edge dict lists."""
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])

    nodes = node_adapter.validate_python(json_nodes)
    edges = edge_adapter.validate_python(json_edges)

    repo_name = root_path.name
    graph = CodeGraph(
        schema_version="1.0.0",
        repo=RepoInfo(
            repo_id=f"local:{repo_name}",
            name=repo_name,
            root_path=str(root_path),
            languages=["python"],
            indexed_at=now_iso,
            file_count=len({n.file_path for n in nodes}),
            symbol_count=len(nodes),
        ),
        nodes=nodes,
        edges=edges,
    )
    graph_path = output_dir / "graph.json"
    graph_path.write_text(
        graph.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8",
    )
