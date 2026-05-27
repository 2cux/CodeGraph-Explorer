"""API dependencies — shared store instance."""
import subprocess
from pathlib import Path

from codegraph.graph.store import GraphStore

_store: GraphStore | None = None


def init_store(store: GraphStore) -> None:
    global _store
    _store = store


def get_store() -> GraphStore:
    if _store is None:
        raise RuntimeError(
            "GraphStore not initialized. Run 'codegraph index' first."
        )
    return _store


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
