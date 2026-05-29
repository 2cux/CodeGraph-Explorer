"""File system scanner for discovering Python source files."""

import hashlib
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", "venv", ".venv", "node_modules",
    "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache",
}


def scan_python_files(root: Path) -> list[Path]:
    """Discover all .py files under root, excluding common non-source directories."""
    files: list[Path] = []
    for path in root.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.relative_to(root).parts):
            continue
        files.append(path)
    return sorted(files)


def read_file(path: Path) -> str:
    """Read and return the text content of a source file."""
    return path.read_text(encoding="utf-8")


def compute_fingerprint(path: Path) -> str:
    """Compute a SHA256 fingerprint of a file's content."""
    return hashlib.sha256(path.read_bytes()).hexdigest()
