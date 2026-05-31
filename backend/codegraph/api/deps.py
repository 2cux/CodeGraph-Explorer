"""API dependencies — shared store instance."""
import subprocess
from pathlib import Path

from codegraph.graph.store import GraphStore

_store: GraphStore | None = None
_codegraph_dir: Path | None = None


def init_store(store: GraphStore, codegraph_dir: Path | None = None) -> None:
    global _store, _codegraph_dir
    _store = store
    if codegraph_dir:
        _codegraph_dir = codegraph_dir


def get_store() -> GraphStore:
    if _store is None:
        raise RuntimeError(
            "GraphStore not initialized. Run 'codegraph init' first."
        )
    return _store


def get_codegraph_dir() -> Path:
    if _codegraph_dir is None:
        cg_dir = Path.cwd() / ".codegraph"
        cg_dir.mkdir(parents=True, exist_ok=True)
        return cg_dir
    return _codegraph_dir


def get_commit_hash() -> str | None:
    """Try to read the current git commit hash."""
    git_dir = Path.cwd() / ".git"
    if not git_dir.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
