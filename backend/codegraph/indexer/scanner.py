"""File system scanner for discovering Python source files."""

from pathlib import Path


def scan_python_files(root: Path) -> list[Path]:
    """Discover all .py files under root, excluding venv and __pycache__."""
    ...


def read_file(path: Path) -> str:
    """Read and return the text content of a source file."""
    ...
