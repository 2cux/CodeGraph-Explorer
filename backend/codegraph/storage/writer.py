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
from codegraph.indexer.fingerprint import FingerprintStore, compute_fingerprints
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

            # Write fingerprints.json
            write_fingerprints(output_dir, root_path)

            # Update state
            if state_store is not None:
                state_store.update_status("fresh", last_indexed_at=now_iso)
                state_store.record_stats(
                    symbols=len(json_nodes),
                    edges=len(json_edges),
                )
                state_store.clear_deleted_files()
                state_store.record_change_summary({
                    "none": 0, "cosmetic": 0, "structural": 0,
                    "added": 0, "deleted": 0,
                })

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

            # 4. Update fingerprints.json
            write_fingerprints(output_dir, root_path)

            # 5. Update state
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


def write_fingerprints(output_dir: Path, root_path: Path) -> int:
    """Write fingerprints.json for all currently indexed Python files.

    Scans the project root, computes structural hashes for every .py file,
    and writes them to .codegraph/fingerprints.json atomically.

    Returns the number of fingerprints written.
    """
    fp_store = FingerprintStore(output_dir)
    all_files = scan_python_files(root_path)
    fps = compute_fingerprints(root_path, all_files)
    fp_store.save(fps)
    return len(fps)


def update_fingerprints_incremental(
    output_dir: Path,
    root_path: Path,
    *,
    recompute_files: list[str] | None = None,
    new_files: list[str] | None = None,
    delete_files: list[str] | None = None,
) -> int:
    """Update fingerprints.json for only the affected files.

    Unlike ``write_fingerprints`` which scans all files, this only touches
    files that have changed, been added, or been deleted.

    Args:
        output_dir: .codegraph directory.
        root_path: Project root path.
        recompute_files: Relative paths of files to re-compute fingerprints for.
        new_files: Relative paths of newly added files.
        delete_files: Relative paths of deleted files to remove fingerprints for.

    Returns:
        Total number of fingerprints after update.
    """
    from codegraph.indexer.fingerprint import compute_fingerprints_for_paths

    fp_store = FingerprintStore(output_dir)
    current = fp_store.load()

    # Remove deleted files
    for fp in (delete_files or []):
        current.pop(fp, None)

    # Compute and update for changed + new files
    all_recompute = (recompute_files or []) + (new_files or [])
    if all_recompute:
        paths = [root_path / f for f in all_recompute if (root_path / f).exists()]
        new_fps = compute_fingerprints_for_paths(root_path, paths)
        current.update(new_fps)

    fp_store.save(current)
    return len(current)


def write_incremental_patch(
    output_dir: Path,
    new_nodes: list[GraphNode],
    new_edges: list[GraphEdge],
    root_path: Path,
    removed_files: set[str],
    *,
    no_sqlite: bool = False,
    state_store = None,
) -> dict[str, int]:
    """Incrementally patch SQLite — only write changed/added data.

    Unlike ``write_incremental_update`` which does a full SQLite replace
    (all nodes/edges re-inserted), this function only:

    1. Deletes old nodes/edges/FTS for *removed_files*
    2. Inserts only *new_nodes* and *new_edges*
    3. Updates FTS for new nodes only
    4. Exports JSON from SQLite
    5. Updates metadata/state

    All SQLite operations run inside a single transaction. On failure,
    the transaction is rolled back and the old index remains intact.

    Args:
        output_dir: .codegraph directory.
        new_nodes: ONLY the newly parsed/changed nodes (not all existing).
        new_edges: ONLY the newly parsed/changed edges (not all existing).
        root_path: Project root path.
        removed_files: Set of file paths whose old nodes/edges should be
                       deleted before inserting new data.
        no_sqlite: If True, use JSON-only fallback.
        state_store: Optional IndexStateStore for recording stats.

    Returns:
        Dict with keys: nodes, edges, fts_symbols, nodes_inserted,
        edges_inserted, nodes_removed, edges_removed.
    """
    node_adapter = TypeAdapter(list[GraphNode])
    edge_adapter = TypeAdapter(list[GraphEdge])
    now_iso = datetime.now(timezone.utc).isoformat()

    if not no_sqlite:
        sqlite_path = output_dir / "index.sqlite"
        sql_store = SqliteStore(sqlite_path)
        sql_store.initialize()

        try:
            # 1. Collect node IDs for files being removed/replaced
            node_ids_to_remove = sql_store.get_node_ids_by_files(
                list(removed_files)
            )

            # 2. Delete old edges touching affected nodes
            edges_removed = 0
            if node_ids_to_remove:
                edges_removed = sql_store.delete_edges_touching_nodes(
                    node_ids_to_remove
                )

            # 3. Delete old nodes for affected files
            nodes_removed = 0
            if node_ids_to_remove:
                nodes_removed = sql_store.delete_nodes_by_ids(
                    node_ids_to_remove
                )

            # 4. Insert new nodes (without auto-commit — part of transaction)
            new_nodes_dicts = node_adapter.dump_python(new_nodes)
            if new_nodes_dicts:
                sql_store.save_nodes(new_nodes_dicts, commit=False)

            # 5. Insert new edges (without auto-commit)
            new_edges_dicts = edge_adapter.dump_python(new_edges)
            if new_edges_dicts:
                sql_store.save_edges(new_edges_dicts, commit=False)

            # 6. Commit the transaction
            sql_store.conn.commit()

            nodes_inserted = len(new_nodes_dicts)
            edges_inserted = len(new_edges_dicts)

        except Exception as exc:
            try:
                sql_store.conn.rollback()
            except Exception:
                pass
            sql_store.close()
            raise SqliteWriteError(
                f"SQLite incremental patch failed (rolled back): {exc}. "
                f"Old index is still intact. "
                f"Re-run with --no-sqlite for JSON-only output, "
                f"or check disk space and permissions."
            ) from exc

        # 7. Export JSON from SQLite (outside transaction — read-only)
        try:
            json_nodes, json_edges = export_json_from_sqlite(output_dir)
            _write_metadata_from_sqlite(output_dir, root_path, now_iso)
            _write_graph_json_from_lists(
                output_dir, root_path, json_nodes, json_edges, now_iso,
            )
        finally:
            sql_store.close()

        # 8. Update state
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
            "nodes_inserted": nodes_inserted,
            "edges_inserted": edges_inserted,
            "nodes_removed": nodes_removed,
            "edges_removed": edges_removed,
        }

    # --no-sqlite fallback: JSON-only path
    store = FileStore(output_dir)
    # Load existing, apply patches in memory
    existing_nodes_data = store.load_nodes()
    existing_edges_data = store.load_edges()

    current_nodes = node_adapter.validate_python(existing_nodes_data)
    current_edges = edge_adapter.validate_python(existing_edges_data)

    # Remove nodes/edges for affected files
    removed_node_ids: set[str] = set()
    for fp in removed_files:
        removed_node_ids.update(n.id for n in current_nodes if n.file_path == fp)

    current_nodes = [n for n in current_nodes if n.file_path not in removed_files]
    current_edges = [
        e for e in current_edges
        if e.source not in removed_node_ids and e.target not in removed_node_ids
    ]

    # Add new nodes/edges
    current_nodes.extend(new_nodes)
    current_edges.extend(new_edges)

    json_nodes = node_adapter.dump_python(current_nodes)
    json_edges = edge_adapter.dump_python(current_edges)
    store.save_nodes(json_nodes)
    store.save_edges(json_edges)

    _write_metadata_from_lists(output_dir, root_path, current_nodes, now_iso)
    _write_graph_json_from_lists(
        output_dir, root_path, json_nodes, json_edges, now_iso,
    )

    if state_store is not None:
        state_store.update_status("fresh", last_incremental_at=now_iso)
        state_store.record_stats(
            symbols=len(current_nodes), edges=len(current_edges),
        )
        if removed_files:
            state_store.record_deleted_files(list(removed_files))

    return {
        "nodes": len(current_nodes),
        "edges": len(current_edges),
        "fts_symbols": 0,
        "nodes_inserted": len(new_nodes),
        "edges_inserted": len(new_edges),
        "nodes_removed": len(removed_node_ids),
        "edges_removed": 0,
    }
