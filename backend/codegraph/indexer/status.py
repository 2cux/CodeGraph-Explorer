"""Index status detection — fresh / stale / missing.

Compares current filesystem state against metadata.json fingerprints
to determine which files have changed, been added, or been deleted.

When fingerprints.json is available, uses stat pre-filter (mtime+size)
and structural hash comparison to classify changes as cosmetic vs
structural, avoiding expensive re-indexing of comment-only changes.
"""

from pathlib import Path

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
