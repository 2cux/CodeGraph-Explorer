"""Index status detection — fresh / stale / missing.

Compares current filesystem state against metadata.json fingerprints
to determine which files have changed, been added, or been deleted.
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
    ) -> None:
        self.status = status
        self.indexed_at = indexed_at
        self.changed_files = changed_files or []
        self.added_files = added_files or []
        self.deleted_files = deleted_files or []
        self.recommendation = recommendation or _default_recommendation(status)

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
        )

    return StatusResult(
        status="fresh",
        indexed_at=metadata.indexed_at,
    )
