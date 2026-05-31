"""API dependencies — shared store instance."""
import os
import subprocess
from pathlib import Path

from codegraph.graph.store import GraphStore

_store: GraphStore | None = None
_codegraph_dir: Path | None = None
_project_root: Path | None = None


def _resolve_project_root() -> Path:
    """Resolve the project root from env var, stored codegraph_dir parent, or cwd."""
    global _project_root
    if _project_root:
        return _project_root
    env_root = os.environ.get("CODEGRAPH_PROJECT_ROOT", "")
    if env_root:
        _project_root = Path(env_root).resolve()
        return _project_root
    if _codegraph_dir:
        _project_root = _codegraph_dir.parent
        return _project_root
    _project_root = Path.cwd()
    return _project_root


def init_store(store: GraphStore, codegraph_dir: Path | None = None) -> None:
    global _store, _codegraph_dir
    _store = store
    if codegraph_dir:
        _codegraph_dir = codegraph_dir
        global _project_root
        _project_root = codegraph_dir.parent


def get_store() -> GraphStore:
    if _store is None:
        raise RuntimeError(
            "GraphStore not initialized. Run 'codegraph init' first."
        )
    return _store


def get_codegraph_dir() -> Path:
    if _codegraph_dir is None:
        root = _resolve_project_root()
        cg_dir = root / ".codegraph"
        cg_dir.mkdir(parents=True, exist_ok=True)
        return cg_dir
    return _codegraph_dir


def get_project_root() -> Path:
    return _resolve_project_root()


def get_commit_hash() -> str | None:
    """Try to read the current git commit hash."""
    root = _resolve_project_root()
    git_dir = root / ".git"
    if not git_dir.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(root),
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
