"""Index status detection — fresh / stale / missing.

Two tiers are provided:

1. ``detect_status()`` — full filesystem scan + fingerprint comparison
   (expensive; for ``codegraph init`` and ``codegraph status`` CLI).
2. ``get_index_status()`` — lightweight, reads only persistent metadata
   files (state.json, metadata.json, fingerprints.json,
   validation_report.json). Never scans project files or computes
   hashes. Suitable for every MCP request.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codegraph.graph.models import FileEntry, IndexMetadata
from codegraph.indexer.scanner import scan_python_files, compute_fingerprint, normalize_path


class StatusResult:
    """Result of index status detection."""

    def __init__(
        self,
        status: str,  # "fresh" | "stale" | "missing"
        indexed_at: str = "",
        changed_files: list[str] | None = None,
        added_files: list[str] | None = None,
        deleted_files: list[str] | None = None,
        recommendation: str = "",
        cosmetic_files: list[str] | None = None,
        structural_files: list[str] | None = None,
        change_summary: dict[str, int] | None = None,
    ) -> None:
        self.status = status
        self.indexed_at = indexed_at
        self.changed_files = changed_files or []
        self.added_files = added_files or []
        self.deleted_files = deleted_files or []
        self.recommendation = recommendation or _default_recommendation(status)
        # Classification fields (populated when fingerprints.json is available)
        self.cosmetic_files = cosmetic_files or []
        self.structural_files = structural_files or []
        self.change_summary = change_summary or {
            "none": 0,
            "cosmetic": 0,
            "structural": 0,
            "added": 0,
            "deleted": 0,
        }
        # Backward compat: if classification was used, changed_files is derived
        if not changed_files and (cosmetic_files or structural_files):
            self.changed_files = sorted(
                set(cosmetic_files or []) | set(structural_files or [])
            )

    @property
    def is_fresh(self) -> bool:
        return self.status == "fresh"

    @property
    def is_stale(self) -> bool:
        return self.status == "stale"

    @property
    def total_changes(self) -> int:
        return len(self.changed_files) + len(self.added_files) + len(self.deleted_files)


def _default_recommendation(status: str) -> str:
    if status == "missing":
        return "Run codegraph init"
    if status == "stale":
        return "Run codegraph init --incremental"
    return ""


def detect_status(root: Path, metadata: IndexMetadata | None) -> StatusResult:
    """Compare filesystem against metadata to determine index freshness.

    Returns a ``StatusResult`` with one of three statuses:

    * ``fresh`` — all files match their fingerprints
    * ``stale`` — some files changed, were added, or were deleted
    * ``missing`` — no metadata.json exists (never indexed)
    """
    if metadata is None:
        return StatusResult(status="missing")

    # Try to use classification when fingerprints.json is available
    try:
        from codegraph.indexer.fingerprint import FingerprintStore
        cg_dir = root / ".codegraph"
        fp_store = FingerprintStore(cg_dir)
        stored_fps = fp_store.load()
        if stored_fps:
            return detect_status_with_classification(root, metadata, fp_store)
    except Exception:
        pass

    # Fallback: SHA256 comparison (original behavior)
    current_files = scan_python_files(root)
    current_rel = {normalize_path(f.relative_to(root)) for f in current_files}

    metadata_map: dict[str, str] = {f.path: f.fingerprint for f in metadata.files}
    metadata_rel = set(metadata_map.keys())

    changed_files: list[str] = []
    deleted_files: list[str] = []
    added_files: list[str] = []

    # Check existing + new files
    for f in current_files:
        rel = normalize_path(f.relative_to(root))
        if rel not in metadata_rel:
            added_files.append(rel)
        else:
            current_fp = compute_fingerprint(f)
            if current_fp != metadata_map[rel]:
                changed_files.append(rel)

    # Check deleted files
    for rel in sorted(metadata_rel - current_rel):
        deleted_files.append(rel)

    if changed_files or added_files or deleted_files:
        return StatusResult(
            status="stale",
            indexed_at=metadata.indexed_at,
            changed_files=sorted(changed_files),
            added_files=sorted(added_files),
            deleted_files=sorted(deleted_files),
            change_summary={
                "none": 0,
                "cosmetic": 0,
                "structural": len(changed_files),
                "added": len(added_files),
                "deleted": len(deleted_files),
            },
        )

    return StatusResult(
        status="fresh",
        indexed_at=metadata.indexed_at,
    )


def detect_status_with_classification(
    root: Path,
    metadata: IndexMetadata | None,
    fp_store: "FingerprintStore",
) -> StatusResult:
    """Compare filesystem against metadata WITH change classification.

    Uses stat pre-filter (mtime + size) to skip hash computation for
    unchanged files, then classifies changes as cosmetic or structural.

    Args:
        root: Project root path.
        metadata: Index metadata from metadata.json.
        fp_store: FingerprintStore for reading/writing fingerprints.json.

    Returns:
        StatusResult with cosmetic_files and structural_files populated.
    """
    from codegraph.indexer.fingerprint import (
        ChangeClassifier,
        ChangeType,
        compute_file_hashes,
        stat_prefilter,
        _normalize_path as fp_normalize,
    )

    if metadata is None:
        return StatusResult(status="missing")

    stored_fps = fp_store.load()
    current_files = scan_python_files(root)

    # Stat pre-filter: separate unchanged from needs-hash from deleted
    unchanged, needs_hash, deleted_rels = stat_prefilter(
        current_files, root, stored_fps,
    )

    # Classify each changed file
    cosmetic_files: list[str] = []
    structural_files: list[str] = []
    added_files: list[str] = []

    metadata_rel = {f.path for f in metadata.files}
    current_rel_set: set[str] = set()

    for f in needs_hash:
        rel = fp_normalize(f.relative_to(root))
        current_rel_set.add(rel)

        current_fp = compute_file_hashes(f)
        current_fp.file_path = rel
        stored_fp = stored_fps.get(rel)

        change_type = ChangeClassifier.classify(current_fp, stored_fp)

        if change_type == ChangeType.ADDED:
            added_files.append(rel)
        elif change_type == ChangeType.STRUCTURAL:
            structural_files.append(rel)
        elif change_type == ChangeType.COSMETIC:
            cosmetic_files.append(rel)
        # NONE shouldn't happen after stat pre-filter but handle gracefully
        elif change_type == ChangeType.NONE:
            unchanged.append(f)

    # Also check for new files not in metadata_rel at all
    for f in current_files:
        rel = fp_normalize(f.relative_to(root))
        if rel not in metadata_rel and rel not in current_rel_set:
            added_files.append(rel)
            current_fp = compute_file_hashes(f)
            current_fp.file_path = rel
            # Update fingerprint store with initial fingerprint
            fp_store.update(rel, current_fp)

    # Update fingerprints for cosmetic files (no graph rebuild needed)
    for rel in cosmetic_files:
        abs_path = root / rel
        if abs_path.exists():
            fp = compute_file_hashes(abs_path)
            fp.file_path = rel
            fp_store.update(rel, fp)

    none_count = len(unchanged)
    cosmetic_count = len(cosmetic_files)
    structural_count = len(structural_files)
    added_count = len(added_files)
    deleted_count = len(deleted_rels)

    # Remove deleted files from fingerprint store
    if deleted_rels:
        fp_store.remove_many(set(deleted_rels))

    # Collect undeleted files from unchanged list for NONE count
    for f in unchanged:
        rel = fp_normalize(f.relative_to(root))
        current_rel_set.add(rel)

    change_summary = {
        "none": none_count,
        "cosmetic": cosmetic_count,
        "structural": structural_count,
        "added": added_count,
        "deleted": deleted_count,
    }

    if structural_files or added_files or deleted_rels or cosmetic_files:
        return StatusResult(
            status="stale",
            indexed_at=metadata.indexed_at,
            changed_files=sorted(set(structural_files + cosmetic_files)),
            added_files=sorted(added_files),
            deleted_files=sorted(deleted_rels),
            cosmetic_files=sorted(cosmetic_files),
            structural_files=sorted(structural_files),
            change_summary=change_summary,
        )

    return StatusResult(
        status="fresh",
        indexed_at=metadata.indexed_at,
        change_summary=change_summary,
    )


# ── Lite status (no file scanning) ──────────────────────────────────────────

def _suggested_fix(status: str) -> str | None:
    """Return a human-readable suggested fix command for a given status."""
    if status == "missing":
        return "codegraph init"
    if status == "stale":
        return "codegraph init --incremental"
    if status == "error":
        return "codegraph doctor; then codegraph init --force"
    return None


def get_index_status(project_root: str | Path) -> dict[str, Any]:
    """Return index status derived from persistent metadata only.

    Reads ``state.json``, ``metadata.json``, ``fingerprints.json``, and
    ``validation_report.json`` without scanning project files or computing
    hashes.  Safe to call on every MCP request.

    Returns a dict with keys:

    * ``status`` — ``"fresh"`` | ``"stale"`` | ``"missing"`` | ``"indexing"`` | ``"error"``
    * ``indexed_at`` — ISO-8601 timestamp or ``None``
    * ``index_files`` — booleans for sqlite / graph_json / metadata_json
    * ``stats`` — ``{files, symbols, edges}`` counts (may be 0)
    * ``fingerprint_health`` — ``{"present": bool, "count": int}`` or ``None``
    * ``index_health`` — ``{"status", "generated_at", "issue_counts"}`` or ``None``
    * ``last_change_summary`` — change-classification dict or ``None``
    * ``last_incremental_stats`` — incremental-run stats dict or ``None``
    * ``suggested_fix`` — human-readable fix command or ``None``
    * ``last_error`` — error string (only when status == ``"error"``)
    """
    root = Path(project_root)
    cg_dir = root / ".codegraph"

    if not cg_dir.exists():
        return {
            "status": "missing",
            "indexed_at": None,
            "index_files": {
                "graph_json": False,
                "sqlite": False,
                "metadata_json": False,
            },
            "stats": {"files": 0, "symbols": 0, "edges": 0},
            "fingerprint_health": None,
            "index_health": None,
            "last_change_summary": None,
            "last_incremental_stats": None,
            "suggested_fix": _suggested_fix("missing"),
        }

    # ── Read state.json ─────────────────────────────────────────────────
    state: dict[str, Any] = {}
    try:
        from codegraph.storage.state_store import IndexStateStore
        state_store = IndexStateStore(cg_dir)
        state = state_store.load()
    except Exception:
        pass

    watch_status = state.get("status", "missing")

    # ── Read metadata.json ──────────────────────────────────────────────
    metadata: IndexMetadata | None = None
    try:
        from codegraph.storage.file_store import FileStore
        file_store = FileStore(cg_dir)
        metadata = file_store.load_metadata()
    except Exception:
        pass

    # ── Index file presence ─────────────────────────────────────────────
    index_files = {
        "graph_json": (cg_dir / "graph.json").exists(),
        "sqlite": (cg_dir / "index.sqlite").exists(),
        "metadata_json": (cg_dir / "metadata.json").exists(),
    }

    # ── Derive aggregate status ─────────────────────────────────────────
    # Priority: state.json watch_status > metadata-based stale/fresh > missing

    if watch_status == "indexing":
        result_status = "indexing"
    elif watch_status == "error":
        result_status = "error"
    elif metadata is None:
        graph_exists = index_files.get("graph_json", False) or index_files.get("sqlite", False)
        result_status = "stale" if graph_exists else "missing"
    elif watch_status == "stale":
        result_status = "stale"
    elif watch_status == "fresh":
        result_status = "fresh"
    else:
        # Unknown state — if index files exist, assume stale
        graph_exists = index_files.get("graph_json", False) or index_files.get("sqlite", False)
        result_status = "stale" if graph_exists else "missing"

    # ── Stats (from metadata when available) ────────────────────────────
    stats: dict[str, int]
    if metadata is not None:
        stats = {
            "files": metadata.file_count,
            "symbols": metadata.symbol_count,
            "edges": metadata.edge_count,
        }
    else:
        stats = {"files": 0, "symbols": 0, "edges": 0}

    # ── Fingerprint health ──────────────────────────────────────────────
    fingerprint_health: dict[str, Any] | None = None
    fp_path = cg_dir / "fingerprints.json"
    if fp_path.exists():
        try:
            from codegraph.indexer.fingerprint import FingerprintStore
            fp_store = FingerprintStore(cg_dir)
            fps = fp_store.load()
            fingerprint_health = {"present": True, "count": len(fps)}
        except Exception:
            fingerprint_health = {"present": False}

    # ── Change summary & incremental stats from state ───────────────────
    last_change_summary = state.get("last_change_summary")
    last_incremental_stats = state.get("last_incremental_stats")

    # ── Graph validation health ─────────────────────────────────────────
    index_health: dict[str, Any] | None = None
    try:
        from codegraph.graph.validation import load_validation_report
        vr = load_validation_report(cg_dir)
        if vr is not None:
            index_health = {
                "status": vr["status"],
                "generated_at": vr.get("generated_at"),
                "issue_counts": vr.get("issue_counts", {}),
            }
    except Exception:
        pass

    # ── Hook status ────────────────────────────────────────────────────
    try:
        from codegraph.hooks.manager import HookManager
        manager_status = HookManager.status(root)
        hook_status: dict[str, Any] = {
            "state": manager_status.get("state"),
            "installed": manager_status.get("installed", False),
            "auto_update_on_commit": manager_status.get(
                "auto_update_on_commit", True,
            ),
            "valid": manager_status.get("valid", False),
            "issues": manager_status.get("issues", []),
            "hook_path": manager_status.get("hook_path"),
            "last_run_at": manager_status.get("last_run_at"),
            "last_run_status": (
                "success"
                if manager_status.get("last_run_exit_code") == 0
                else "error"
                if manager_status.get("last_run_exit_code") is not None
                else None
            ),
            "total_runs": manager_status.get("total_runs", 0),
            "total_failures": manager_status.get("total_failures", 0),
        }
    except Exception:
        hook_config: dict[str, Any] = state.get("hook", {})
        hook_status = {
            "state": "disabled"
            if not hook_config.get("auto_update_on_commit", True)
            else "enabled"
            if hook_config.get("installed", False)
            else "missing",
            "installed": hook_config.get("installed", False),
            "auto_update_on_commit": hook_config.get(
                "auto_update_on_commit", True,
            ),
            "last_run_at": hook_config.get("last_run_at"),
            "last_run_status": (
                "success"
                if hook_config.get("last_run_exit_code") == 0
                else "error"
                if hook_config.get("last_run_exit_code") is not None
                else None
            ),
            "total_runs": hook_config.get("total_runs", 0),
            "total_failures": hook_config.get("total_failures", 0),
        }

    # ── Build result ────────────────────────────────────────────────────
    result: dict[str, Any] = {
        "status": result_status,
        "indexed_at": metadata.indexed_at if metadata else None,
        "index_files": index_files,
        "stats": stats,
        "fingerprint_health": fingerprint_health,
        "index_health": index_health,
        "last_change_summary": last_change_summary,
        "last_incremental_stats": last_incremental_stats,
        "hook": hook_status,
        "suggested_fix": _suggested_fix(result_status),
    }

    if result_status == "error":
        result["last_error"] = state.get("last_error")

    return result
