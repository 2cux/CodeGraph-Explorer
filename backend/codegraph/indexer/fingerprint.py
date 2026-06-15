"""Lightweight file fingerprint and change classifier.

Provides structural hashing for Python source files to distinguish
cosmetic changes (comments, whitespace, docstrings) from structural
changes (symbols, imports, calls).

Persists fingerprints to .codegraph/fingerprints.json for fast
stat-based pre-filtering and change classification.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ────────────────────────────────────────────────────────────────


class ChangeType(str, Enum):
    """Classification of file change severity."""

    NONE = "none"           # no change detected
    COSMETIC = "cosmetic"   # only comments / whitespace / docstring changes
    STRUCTURAL = "structural"  # function / class / method / signature / call changes
    ARCHITECTURE = "architecture"  # imports changed but symbols unchanged → dependency graph shift
    ADDED = "added"         # new file (not previously indexed)
    DELETED = "deleted"     # file removed since last index
    FULL_REINDEX_REQUIRED = "full_reindex_required"  # config files changed, metadata missing, or mass changes


class ReindexThreshold:
    """Thresholds that trigger FULL_REINDEX_REQUIRED status.

    When any threshold is crossed, the index should be fully rebuilt
    rather than incrementally updated.
    """

    PERCENT_FILES_CHANGED: float = 30.0  # >30% of files have structural/architecture changes
    CONFIG_EXTENSIONS: frozenset[str] = frozenset({
        ".toml", ".yaml", ".yml", ".json", ".cfg", ".ini",
        ".env", ".lock",
    })


# ── Models ────────────────────────────────────────────────────────────────


class FileFingerprint(BaseModel):
    """Per-file fingerprint for change detection and classification."""

    file_path: str
    mtime: float
    size: int
    sha256: str
    structural_hash: str
    symbols_hash: str
    imports_hash: str
    calls_hash: str
    is_config: bool = False  # True when file extension matches ReindexThreshold.CONFIG_EXTENSIONS


# ── Fingerprint Store ─────────────────────────────────────────────────────


class FingerprintStore:
    """Read/write .codegraph/fingerprints.json for per-file structural hashes."""

    def __init__(self, cg_dir: Path) -> None:
        self._path = cg_dir / "fingerprints.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, FileFingerprint]:
        """Load all fingerprints, returning empty dict if file is missing or corrupt."""
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        result: dict[str, FileFingerprint] = {}
        if isinstance(raw, dict):
            for key, value in raw.items():
                try:
                    result[key] = FileFingerprint.model_validate(value)
                except Exception:
                    continue
        return result

    def save(self, fingerprints: dict[str, FileFingerprint]) -> None:
        """Atomically write all fingerprints to disk."""
        data: dict[str, dict[str, Any]] = {}
        for key, fp in fingerprints.items():
            data[key] = fp.model_dump()
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, self._path)

    def get(self, file_path: str) -> FileFingerprint | None:
        """Get fingerprint for a single file."""
        return self.load().get(file_path)

    def update(self, file_path: str, fp: FileFingerprint) -> None:
        """Insert or update a single fingerprint."""
        current = self.load()
        current[file_path] = fp
        self.save(current)

    def remove(self, file_path: str) -> None:
        """Remove a single fingerprint entry."""
        current = self.load()
        current.pop(file_path, None)
        self.save(current)

    def remove_many(self, file_paths: set[str]) -> None:
        """Remove multiple fingerprint entries at once."""
        current = self.load()
        for fp in file_paths:
            current.pop(fp, None)
        self.save(current)

    def count(self) -> int:
        """Return number of fingerprints stored."""
        return len(self.load())


# ── Change Classifier ─────────────────────────────────────────────────────


class ChangeClassifier:
    """Classify file changes by comparing current vs stored fingerprints."""

    @staticmethod
    def classify(
        current_fp: FileFingerprint | None,
        stored_fp: FileFingerprint | None,
    ) -> ChangeType:
        """Classify a file change given its current and stored fingerprints.

        Args:
            current_fp: Current fingerprint from disk (None if file deleted).
            stored_fp: Previously stored fingerprint (None if new file).

        Returns:
            ChangeType classification.
        """
        # New file
        if current_fp is not None and stored_fp is None:
            return ChangeType.ADDED

        # Deleted file
        if current_fp is None and stored_fp is not None:
            return ChangeType.DELETED

        # Neither exists (shouldn't happen)
        if current_fp is None and stored_fp is None:
            return ChangeType.NONE

        # Both exist — compare hashes
        # Full content match → no change
        if current_fp.sha256 == stored_fp.sha256:  # type: ignore[union-attr]
            return ChangeType.NONE

        # All structural hashes match → only cosmetic change
        if (current_fp.structural_hash == stored_fp.structural_hash  # type: ignore[union-attr]
                and current_fp.symbols_hash == stored_fp.symbols_hash  # type: ignore[union-attr]
                and current_fp.imports_hash == stored_fp.imports_hash  # type: ignore[union-attr]
                and current_fp.calls_hash == stored_fp.calls_hash):  # type: ignore[union-attr]
            return ChangeType.COSMETIC

        # Symbols + structure match, but only imports differ → architecture change
        # (dependency graph shifts without code logic changes)
        # IMPORTANT: calls_hash must also match — if calls changed too, it's STRUCTURAL
        if (current_fp.structural_hash == stored_fp.structural_hash  # type: ignore[union-attr]
                and current_fp.symbols_hash == stored_fp.symbols_hash  # type: ignore[union-attr]
                and current_fp.calls_hash == stored_fp.calls_hash  # type: ignore[union-attr]
                and current_fp.imports_hash != stored_fp.imports_hash):  # type: ignore[union-attr]
            return ChangeType.ARCHITECTURE

        # Any structural hash differs → structural change
        return ChangeType.STRUCTURAL


# ── Reindex Threshold Check ─────────────────────────────────────────────


def check_reindex_threshold(
    change_summary: dict[str, int],
    total_files: int,
    config_changed: bool = False,
    metadata_missing: bool = False,
) -> bool:
    """Return True if a full reindex is required rather than incremental update.

    Triggers when:
    - metadata.json is missing (never indexed)
    - Any config/definition file changed (pyproject.toml, .yaml, etc.)
    - More than ReindexThreshold.PERCENT_FILES_CHANGED of files have structural
      or architecture changes
    """
    if metadata_missing:
        return True
    if config_changed:
        return True
    changed = (
        change_summary.get("structural", 0)
        + change_summary.get("architecture", 0)
    )
    if total_files > 0 and (changed / total_files * 100) > ReindexThreshold.PERCENT_FILES_CHANGED:
        return True
    return False


# ── Hash Computation ──────────────────────────────────────────────────────


def compute_file_hashes(path: Path) -> FileFingerprint:
    """Compute all hashes for a single Python source file.

    Reads the file once, computes:
    - sha256 of raw bytes
    - structural_hash (signatures of functions/classes/methods)
    - symbols_hash (symbol names + types)
    - imports_hash (normalized import statements)
    - calls_hash (normalized call targets)

    If the file cannot be parsed as Python (syntax error), structural
    hashes fall back to the SHA256 content hash so the file is always
    classified as STRUCTURAL on change.
    """
    raw_bytes = path.read_bytes()
    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
    stat = path.stat()
    mtime = stat.st_mtime
    size = stat.st_size
    is_config = path.suffix in ReindexThreshold.CONFIG_EXTENSIONS

    try:
        text = raw_bytes.decode("utf-8")
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        # Unparseable file — use content hash as fallback for all structural hashes
        return FileFingerprint(
            file_path="",  # caller sets this
            mtime=mtime,
            size=size,
            sha256=sha256_hash,
            structural_hash=sha256_hash,
            symbols_hash=sha256_hash,
            imports_hash=sha256_hash,
            calls_hash=sha256_hash,
            is_config=is_config,
        )

    structural_hash = hashlib.sha256(
        _extract_structural_signature(tree).encode("utf-8")
    ).hexdigest()

    symbols_hash = hashlib.sha256(
        _extract_symbol_signatures(tree).encode("utf-8")
    ).hexdigest()

    imports_hash = hashlib.sha256(
        _extract_import_signatures(tree).encode("utf-8")
    ).hexdigest()

    calls_hash = hashlib.sha256(
        _extract_call_signatures(tree).encode("utf-8")
    ).hexdigest()

    return FileFingerprint(
        file_path="",  # caller sets this
        mtime=mtime,
        size=size,
        sha256=sha256_hash,
        structural_hash=structural_hash,
        symbols_hash=symbols_hash,
        imports_hash=imports_hash,
        calls_hash=calls_hash,
        is_config=is_config,
    )


def compute_fingerprints(
    root: Path, files: list[Path],
) -> dict[str, FileFingerprint]:
    """Compute FileFingerprint for every file in the list.

    Args:
        root: Project root (for computing relative paths).
        files: List of absolute paths to .py files.

    Returns:
        Dict mapping relative file path → FileFingerprint.
    """
    result: dict[str, FileFingerprint] = {}
    for f in files:
        rel = _normalize_path(f.relative_to(root))
        fp = compute_file_hashes(f)
        fp.file_path = rel
        result[rel] = fp
    return result


def compute_fingerprints_for_paths(
    root: Path, paths: list[Path],
) -> dict[str, FileFingerprint]:
    """Compute fingerprints for a subset of files (used in incremental updates)."""
    result: dict[str, FileFingerprint] = {}
    for p in paths:
        abs_path = root / p
        if not abs_path.exists():
            continue
        rel = _normalize_path(p)
        fp = compute_file_hashes(abs_path)
        fp.file_path = rel
        result[rel] = fp
    return result


# ── AST Signature Extractors ──────────────────────────────────────────────


def _extract_structural_signature(tree: ast.Module) -> str:
    """Extract a signature string capturing all structural elements.

    Includes: function/method/class names + argument names (no body/docstring).
    Sorted for stability.
    """
    lines: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            args = _format_args(node.args)
            lines.append(f"func:{node.name}({args})")
        elif isinstance(node, ast.AsyncFunctionDef):
            args = _format_args(node.args)
            lines.append(f"async_func:{node.name}({args})")
        elif isinstance(node, ast.ClassDef):
            bases = _format_bases(node)
            lines.append(f"class:{node.name}({bases})")

    lines.sort()
    return "\n".join(lines)


def _extract_symbol_signatures(tree: ast.Module) -> str:
    """Extract symbol names and types for symbol-level hash.

    Top-level and nested symbols are included (sorted by name).
    """
    lines: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef):
            lines.append(f"func:{node.name}")
        elif isinstance(node, ast.AsyncFunctionDef):
            lines.append(f"async_func:{node.name}")
        elif isinstance(node, ast.ClassDef):
            lines.append(f"class:{node.name}")
            # Include methods
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    lines.append(f"method:{node.name}.{item.name}")
                elif isinstance(item, ast.AsyncFunctionDef):
                    lines.append(f"async_method:{node.name}.{item.name}")

    lines.sort()
    return "\n".join(lines)


def _extract_import_signatures(tree: ast.Module) -> str:
    """Extract normalized import statements for import-level hash."""
    lines: list[str] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                normalized = f"import {alias.name}"
                if alias.asname:
                    normalized += f" as {alias.asname}"
                lines.append(normalized)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            level = "." * (node.level or 0)
            for alias in node.names:
                normalized = f"from {level}{module} import {alias.name}"
                if alias.asname:
                    normalized += f" as {alias.asname}"
                lines.append(normalized)

    lines.sort()
    return "\n".join(lines)


def _extract_call_signatures(tree: ast.Module) -> str:
    """Extract call target names for call-level hash.

    Captures simple name calls (func()), attribute calls (obj.method()),
    and subscription calls (dict['key']()).
    """
    lines: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            target = _resolve_call_target(node.func)
            if target:
                lines.append(target)

    lines.sort()
    return "\n".join(lines)


# ── AST Helpers ───────────────────────────────────────────────────────────


def _format_args(args: ast.arguments) -> str:
    """Format function arguments as comma-separated names (no annotations)."""
    parts: list[str] = []

    # Positional args
    for arg in args.args:
        parts.append(arg.arg)

    # vararg: *args
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")

    # Keyword-only args
    for arg in args.kwonlyargs:
        parts.append(arg.arg)

    # kwarg: **kwargs
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")

    return ", ".join(parts)


def _format_bases(node: ast.ClassDef) -> str:
    """Format class base names."""
    bases: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(_format_attribute(base))
    return ", ".join(bases)


def _resolve_call_target(func: ast.expr) -> str:
    """Resolve a call target to a string representation."""
    if isinstance(func, ast.Name):
        return func.id
    elif isinstance(func, ast.Attribute):
        return _format_attribute(func)
    elif isinstance(func, ast.Subscript):
        # e.g., dict['key']()
        inner = _resolve_call_target(func.value)
        return f"{inner}[...]"
    return ""


def _format_attribute(node: ast.Attribute) -> str:
    """Format an Attribute node as dotted string."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    parts.reverse()
    return ".".join(parts)


def _normalize_path(path: Path | str) -> str:
    """Normalize to POSIX forward-slash format."""
    return str(path).replace("\\", "/")


# ── Stat Pre-Filter ───────────────────────────────────────────────────────


def stat_prefilter(
    current_files: list[Path],
    root: Path,
    stored_fps: dict[str, FileFingerprint],
) -> tuple[list[Path], list[Path], list[str]]:
    """Quick pre-filter using mtime and size before computing hashes.

    Args:
        current_files: List of absolute paths to current .py files.
        root: Project root.
        stored_fps: Previously stored fingerprints keyed by relative path.

    Returns:
        Tuple of (unchanged_paths, needs_hash_paths, deleted_rels).
        - unchanged_paths: files whose mtime+size match stored values → NONE
        - needs_hash_paths: files whose mtime+size differ → need full hash
        - deleted_rels: relative paths in stored_fps but not on disk → DELETED
    """
    current_rels: set[str] = set()
    unchanged: list[Path] = []
    needs_hash: list[Path] = []

    for f in current_files:
        rel = _normalize_path(f.relative_to(root))
        current_rels.add(rel)

        stored = stored_fps.get(rel)
        if stored is None:
            # New file — needs full hash computation
            needs_hash.append(f)
            continue

        try:
            stat = f.stat()
        except OSError:
            # Can't stat — treat as needing hash
            needs_hash.append(f)
            continue

        if stat.st_mtime == stored.mtime and stat.st_size == stored.size:
            unchanged.append(f)
        else:
            needs_hash.append(f)

    # Detect deleted files
    stored_rels = set(stored_fps.keys())
    deleted_rels = sorted(stored_rels - current_rels)

    return unchanged, needs_hash, deleted_rels
