"""Shared incremental index logic used by CLI and watch mode.

Performs diff-based indexing: detect changed/added/deleted files,
classify changes as cosmetic or structural, patch the existing
SQLite store with only the affected nodes/edges (true incremental
write — no full replace), and save updated artifacts.

Cosmetic changes (comments, whitespace, docstrings only) are skipped
— only fingerprints.json is updated for these files.

Cross-file edge handling: when a file changes structurally, files
that import from it ("direct dependents") are also re-parsed so
that call edges to the changed symbols are correctly resolved.
"""

import time
from pathlib import Path

from pydantic import TypeAdapter

from codegraph.graph.models import GraphEdge, GraphNode
from codegraph.indexer.graph_builder import build_index_from_paths
from codegraph.indexer.fingerprint import FingerprintStore
from codegraph.indexer.status import detect_status_with_classification, StatusResult
from codegraph.storage.file_store import FileStore
from codegraph.storage.sqlite_store import SqliteStore
from codegraph.storage.state_store import IndexStateStore
from codegraph.storage.writer import (
    write_incremental_patch,
    update_fingerprints_incremental,
    SqliteWriteError,
)

# Threshold for recommending a full rebuild
FULL_REBUILD_FILE_THRESHOLD = 30
FULL_REBUILD_RATIO_THRESHOLD = 0.3


def _file_to_module(rel_path: str) -> str:
    """Convert a relative file path to a Python module name.

    ``app/api/auth.py`` → ``app.api.auth``
    ``app/api/__init__.py`` → ``app.api``
    """
    return rel_path.replace("\\", "/").removesuffix(".py").removesuffix("/__init__").replace("/", ".")


def _find_direct_dependents(
    file_paths: list[str],
    sqlite_path: Path,
) -> list[str]:
    """Find files that import from any of the given *file_paths*.

    Uses the SQLite import index: for each file, derives its module name,
    then queries for other files that have ``imports`` edges pointing to
    symbols under that module.

    Args:
        file_paths: List of relative file paths (e.g. ``["app/api/auth.py"]``).
        sqlite_path: Path to ``index.sqlite``.

    Returns:
        Sorted list of relative file paths (excluding those already in
        *file_paths*) that import from the given files.
    """
    if not file_paths or not sqlite_path.exists():
        return []

    module_names = [_file_to_module(f) for f in file_paths]
    store = SqliteStore(sqlite_path)
    try:
        store.initialize()
        dependents = store.get_dependent_files(module_names)
    finally:
        store.close()

    # Exclude files already in the input set
    input_set = set(file_paths)
    return sorted(f for f in dependents if f not in input_set)


class IncrementalResult:
    """Structured result from an incremental index run."""

    def __init__(
        self,
        status: str,  # "fresh" | "updated" | "missing" | "error"
        status_result: StatusResult | None = None,
        nodes_removed: int = 0,
        nodes_added: int = 0,
        edges_added: int = 0,
        total_symbols: int = 0,
        total_edges: int = 0,
        total_files: int = 0,
        error: str | None = None,
        cosmetic_count: int = 0,
        structural_count: int = 0,
        change_summary: dict[str, int] | None = None,
        recommend_full_rebuild: bool = False,
        # Incremental patch stats
        reparsed_files: int = 0,
        dependent_files: int = 0,
        deleted_nodes_count: int = 0,
        inserted_nodes_count: int = 0,
        deleted_edges_count: int = 0,
        inserted_edges_count: int = 0,
        duration_ms: float = 0,
    ) -> None:
        self.status = status
        self.status_result = status_result
        self.nodes_removed = nodes_removed
        self.nodes_added = nodes_added
        self.edges_added = edges_added
        self.total_symbols = total_symbols
        self.total_edges = total_edges
        self.total_files = total_files
        self.error = error
        self.cosmetic_count = cosmetic_count
        self.structural_count = structural_count
        self.change_summary = change_summary or {
            "none": 0,
            "cosmetic": 0,
            "structural": 0,
            "added": 0,
            "deleted": 0,
        }
        self.recommend_full_rebuild = recommend_full_rebuild
        # Incremental patch performance stats
        self.reparsed_files = reparsed_files
        self.dependent_files = dependent_files
        self.deleted_nodes_count = deleted_nodes_count
        self.inserted_nodes_count = inserted_nodes_count
        self.deleted_edges_count = deleted_edges_count
        self.inserted_edges_count = inserted_edges_count
        self.duration_ms = duration_ms

    @property
    def changed_count(self) -> int:
        if self.status_result is None:
            return 0
        return len(self.status_result.changed_files)

    @property
    def added_count(self) -> int:
        if self.status_result is None:
            return 0
        return len(self.status_result.added_files)

    @property
    def deleted_count(self) -> int:
        if self.status_result is None:
            return 0
        return len(self.status_result.deleted_files)


def run_incremental_index(
    root_path: Path,
    output_dir: Path,
    store: FileStore,
    no_sqlite: bool = False,
    state_store: IndexStateStore | None = None,
) -> IncrementalResult:
    """Run incremental index update and return structured result.

    Does NOT hold the index lock — callers must acquire the lock before
    calling this function.

    Uses fingerprint-based classification when fingerprints.json is
    available, skipping cosmetic changes and only re-indexing files
    with structural changes.

    True incremental SQLite write: only affected nodes/edges are deleted
    and re-inserted. Cross-file edges are preserved by re-parsing direct
    dependents of changed files.
    """
    t0 = time.monotonic()

    if state_store is None:
        state_store = IndexStateStore(output_dir)

    metadata = store.load_metadata()

    # Try classification-based detection
    fp_store = FingerprintStore(output_dir)
    stored_fps = fp_store.load()

    if stored_fps:
        # Use fingerprint-based classification
        status_result = detect_status_with_classification(
            root_path, metadata, fp_store,
        )
    else:
        # Fallback: use basic SHA256 detection
        from codegraph.indexer.status import detect_status
        status_result = detect_status(root_path, metadata)

    if status_result.status == "missing":
        return IncrementalResult(
            status="missing",
            status_result=status_result,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    if status_result.status == "fresh":
        return IncrementalResult(
            status="fresh",
            status_result=status_result,
            total_symbols=metadata.symbol_count if metadata else 0,
            total_edges=metadata.edge_count if metadata else 0,
            total_files=metadata.file_count if metadata else 0,
            change_summary=status_result.change_summary,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    # Check for full rebuild recommendation
    structural_count = len(status_result.structural_files)
    total_indexed = metadata.file_count if metadata else 1
    recommend_full_rebuild = (
        structural_count > FULL_REBUILD_FILE_THRESHOLD
        or structural_count > FULL_REBUILD_RATIO_THRESHOLD * max(total_indexed, 1)
    )

    # ── Cross-file edge handling: find direct dependents ──────────────
    dependent_files: list[str] = []
    sqlite_path = output_dir / "index.sqlite"
    if structural_count > 0 and not no_sqlite and sqlite_path.exists():
        dependent_files = _find_direct_dependents(
            status_result.structural_files, sqlite_path,
        )

    # ── Determine which files to re-parse and which to remove ─────────
    files_to_reparse_rel: list[str] = list(status_result.structural_files)
    files_to_reparse_rel.extend(status_result.added_files)
    files_to_reparse_rel.extend(dependent_files)

    # Files whose old data must be deleted before inserting new data
    files_to_remove: set[str] = set(status_result.structural_files)
    files_to_remove.update(status_result.deleted_files)
    files_to_remove.update(dependent_files)

    # ── Re-index affected files ───────────────────────────────────────
    files_to_reparse: list[Path] = []
    for rel in files_to_reparse_rel:
        p = root_path / rel
        if p.exists():
            files_to_reparse.append(p)

    new_nodes: list[GraphNode] = []
    new_edges: list[GraphEdge] = []
    if files_to_reparse:
        new_nodes, new_edges = build_index_from_paths(
            root_path, files_to_reparse,
        )

    # ── Save via incremental SQLite patch ─────────────────────────────
    try:
        counts = write_incremental_patch(
            output_dir, new_nodes, new_edges, root_path,
            removed_files=files_to_remove,
            no_sqlite=no_sqlite, state_store=state_store,
        )
    except SqliteWriteError:
        return IncrementalResult(
            status="error",
            status_result=status_result,
            error="SQLite write failed. Re-run with --no-sqlite or check disk space.",
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    # ── Update fingerprints incrementally ─────────────────────────────
    try:
        update_fingerprints_incremental(
            output_dir, root_path,
            recompute_files=(
                status_result.structural_files + dependent_files
            ),
            new_files=status_result.added_files,
            delete_files=status_result.deleted_files,
        )
    except Exception:
        # Non-fatal: fingerprints can be rebuilt on next init
        pass

    # ── Record change summary in state ────────────────────────────────
    change_summary = status_result.change_summary
    state_store.record_change_summary(change_summary)

    # ── Record incremental performance stats ──────────────────────────
    duration_ms = (time.monotonic() - t0) * 1000
    incremental_stats = {
        "changed_files": structural_count,
        "reparsed_files": len(files_to_reparse),
        "dependent_files": len(dependent_files),
        "deleted_nodes": counts.get("nodes_removed", 0),
        "inserted_nodes": counts.get("nodes_inserted", 0),
        "deleted_edges": counts.get("edges_removed", 0),
        "inserted_edges": counts.get("edges_inserted", 0),
        "duration_ms": round(duration_ms, 1),
        "full_replace": False,
    }
    state_store.record_incremental_stats(incremental_stats)

    # ── Graph validation after incremental update ─────────────────────
    try:
        from codegraph.graph.validation import (
            validate_graph, save_validation_report,
        )
        from codegraph.storage.sqlite_store import SqliteStore

        val_store = SqliteStore(output_dir / "index.sqlite")
        val_store.initialize()
        report = validate_graph(
            cg_dir=output_dir, project_root=root_path, store=val_store,
        )
        if report["status"] == "error":
            save_validation_report(output_dir, report)
            state_store.update_status(
                "error", last_error="Graph validation found fatal issues"
            )
        elif report["status"] == "warning":
            save_validation_report(output_dir, report)
        val_store.close()
    except Exception:
        pass  # non-fatal

    # ── Build result ──────────────────────────────────────────────────
    result = IncrementalResult(
        status="updated",
        status_result=status_result,
        nodes_removed=counts.get("nodes_removed", 0),
        nodes_added=len(new_nodes),
        edges_added=len(new_edges),
        total_symbols=counts["nodes"],
        total_edges=counts["edges"],
        total_files=counts.get("total_files", 0),
        cosmetic_count=len(status_result.cosmetic_files),
        structural_count=structural_count,
        change_summary=change_summary,
        recommend_full_rebuild=recommend_full_rebuild,
        reparsed_files=len(files_to_reparse),
        dependent_files=len(dependent_files),
        deleted_nodes_count=counts.get("nodes_removed", 0),
        inserted_nodes_count=counts.get("nodes_inserted", 0),
        deleted_edges_count=counts.get("edges_removed", 0),
        inserted_edges_count=counts.get("edges_inserted", 0),
        duration_ms=round(duration_ms, 1),
    )
    return result
