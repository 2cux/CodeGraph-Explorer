"""File system scanner for discovering Python source files.

Path handling:
- All internal paths use POSIX forward slashes
- Input paths may use Windows backslashes (normalized on read)
- Non-ASCII paths (Chinese, spaces, etc.) are fully supported
- Symlinks pointing outside the repo root are skipped with a warning
"""

import hashlib
import os
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", "venv", ".venv", "node_modules",
    "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
}


def normalize_path(path: str | Path) -> str:
    """Normalize a path to POSIX forward-slash format."""
    return str(path).replace("\\", "/")


def _is_safe_path(path: Path, root: Path) -> tuple[bool, str | None]:
    """Check that *path*'s real location is inside *root*.

    Returns ``(is_safe, warning_message)``.
    """
    try:
        real_path = path.resolve(strict=False)
        real_root = root.resolve(strict=False)
        # Path.relative_to on Windows is case-insensitive but we need to
        # normalize to the same form for reliable prefix checks.
        try:
            real_path.relative_to(real_root)
            return True, None
        except ValueError:
            pass
        # Also try string prefix check for edge cases (different drives, etc.)
        rp = normalize_path(str(real_path))
        rr = normalize_path(str(real_root))
        if rp.startswith(rr + "/") or rp == rr:
            return True, None
        return False, f"symlink_outside_root: {path} resolves to {real_path} (outside {real_root})"
    except OSError:
        return False, f"path_outside_root: cannot resolve {path}"


def scan_python_files(root: Path, collect_warnings: list[dict] | None = None) -> list[Path]:
    """Discover all .py files under root, excluding common non-source directories.

    Files whose resolved real path falls outside *root* (e.g. symlinks to
    external locations) are skipped. Each skip appends a structured warning
    to *collect_warnings* if provided.
    """
    files: list[Path] = []
    root_resolved = root.resolve(strict=False)

    for path in root.rglob("*.py"):
        parts = path.relative_to(root).parts
        if any(part in EXCLUDE_DIRS for part in parts):
            continue
        # Symlink safety check
        is_safe, warning_msg = _is_safe_path(path, root)
        if not is_safe:
            if collect_warnings is not None:
                collect_warnings.append({
                    "type": "symlink_outside_root",
                    "severity": "warning",
                    "message": warning_msg or "Skipped: path outside repo root.",
                    "file": normalize_path(str(path)),
                })
            continue
        files.append(path)

    return sorted(files)


def read_file(path: Path) -> str:
    """Read and return the text content of a source file."""
    return path.read_text(encoding="utf-8")


def read_file_safe(path: Path, root: Path) -> str | None:
    """Read a file only if its realpath is within *root*.

    Returns the file content, or ``None`` if the path escapes the root.
    """
    is_safe, _ = _is_safe_path(path, root)
    if not is_safe:
        return None
    return path.read_text(encoding="utf-8")


def compute_fingerprint(path: Path) -> str:
    """Compute a SHA256 fingerprint of a file's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
