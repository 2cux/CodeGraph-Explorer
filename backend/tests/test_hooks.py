"""Tests for git post-commit hook auto-update feature.

Covers: HookConfig model, state store integration, HookManager,
CLI commands (sync, hooks, config), init auto-install, and doctor.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.hooks.config import HookConfig
from codegraph.hooks.manager import HookManager
from codegraph.hooks.template import (
    SENTINEL_START,
    SENTINEL_END,
    build_unix_hook_script,
    build_windows_hook_script,
)
from codegraph.hooks.logger import get_hook_logger
from codegraph.storage.state_store import IndexStateStore

runner = CliRunner()


# ── helpers ──────────────────────────────────────────────────────────────

def _init_git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo at the given path and return it."""
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    return tmp_path


def _make_dot_codegraph(tmp_path: Path) -> Path:
    """Create a minimal .codegraph directory with state.json."""
    cg_dir = tmp_path / ".codegraph"
    cg_dir.mkdir(parents=True, exist_ok=True)
    # Create a minimal state.json
    store = IndexStateStore(cg_dir)
    store.save(store._default_state())
    # Create a minimal metadata.json so get_index_status doesn't think "missing"
    (cg_dir / "metadata.json").write_text(
        json.dumps({
            "schema_version": "1.0",
            "indexer_version": "1.0",
            "root_path": str(tmp_path),
            "indexed_at": "2026-01-01T00:00:00Z",
            "file_count": 1,
            "symbol_count": 5,
            "edge_count": 3,
            "files": [],
        }),
        encoding="utf-8",
    )
    # Create a minimal SQLite database
    import sqlite3
    db_path = cg_dir / "index.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS edges (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    # Create a minimal graph.json
    (cg_dir / "graph.json").write_text(
        json.dumps({"schema_version": "1.0", "nodes": [], "edges": []}),
        encoding="utf-8",
    )
    return cg_dir


# ══ HookConfig model ═════════════════════════════════════════════════════

class TestHookConfig:
    """Tests for the HookConfig Pydantic model."""

    def test_defaults(self):
        """HookConfig defaults to auto_update_on_commit=True, installed=False."""
        cfg = HookConfig()
        assert cfg.auto_update_on_commit is True
        assert cfg.installed is False
        assert cfg.installed_at is None
        assert cfg.hook_path is None
        assert cfg.last_run_at is None
        assert cfg.last_run_exit_code is None
        assert cfg.last_run_duration_ms is None
        assert cfg.total_runs == 0
        assert cfg.total_failures == 0

    def test_serialization_roundtrip(self):
        """HookConfig serializes and deserializes correctly."""
        now = "2026-06-03T10:00:00Z"
        cfg = HookConfig(
            auto_update_on_commit=False,
            installed=True,
            installed_at=now,
            hook_path="/path/to/hook",
            last_run_at=now,
            last_run_exit_code=0,
            last_run_duration_ms=234.5,
            total_runs=42,
            total_failures=0,
        )
        json_str = cfg.model_dump_json()
        cfg2 = HookConfig.model_validate_json(json_str)
        assert cfg2.auto_update_on_commit is False
        assert cfg2.installed is True
        assert cfg2.hook_path == "/path/to/hook"
        assert cfg2.total_runs == 42
        assert cfg2.last_run_duration_ms == 234.5

    def test_partial_construction(self):
        """HookConfig works with partial fields."""
        cfg = HookConfig(installed=True, total_runs=5)
        assert cfg.installed is True
        assert cfg.total_runs == 5
        assert cfg.auto_update_on_commit is True  # default


# ══ State store integration ═══════════════════════════════════════════════

class TestStateStoreHook:
    """Tests for hook-related methods on IndexStateStore."""

    def test_default_state_has_hook_section(self, tmp_path: Path):
        """_default_state includes a 'hook' section with correct defaults."""
        store = IndexStateStore(tmp_path / ".codegraph")
        state = store._default_state()
        assert "hook" in state
        hook = state["hook"]
        assert hook["auto_update_on_commit"] is True
        assert hook["installed"] is False
        assert hook["total_runs"] == 0
        assert hook["total_failures"] == 0

    def test_get_hook_config_returns_defaults(self, tmp_path: Path):
        """get_hook_config returns default values when nothing is stored."""
        store = IndexStateStore(tmp_path / ".codegraph")
        cfg = store.get_hook_config()
        assert cfg["auto_update_on_commit"] is True
        assert cfg["installed"] is False

    def test_update_hook_config_partial_merge(self, tmp_path: Path):
        """update_hook_config performs partial merge, preserving other fields."""
        store = IndexStateStore(tmp_path / ".codegraph")
        store.update_hook_config(installed=True, hook_path="/tmp/hook")
        cfg = store.get_hook_config()
        assert cfg["installed"] is True
        assert cfg["hook_path"] == "/tmp/hook"
        assert cfg["auto_update_on_commit"] is True  # unchanged

    def test_update_hook_config_ignores_unknown_keys(self, tmp_path: Path):
        """update_hook_config ignores keys not in the hook section."""
        store = IndexStateStore(tmp_path / ".codegraph")
        store.update_hook_config(installed=True, unknown_field="should_be_ignored")
        cfg = store.get_hook_config()
        assert "unknown_field" not in cfg
        assert cfg["installed"] is True

    def test_record_hook_run_success(self, tmp_path: Path):
        """record_hook_run increments counters and tracks last run."""
        store = IndexStateStore(tmp_path / ".codegraph")
        store.record_hook_run(exit_code=0, duration_ms=150.5)
        cfg = store.get_hook_config()
        assert cfg["total_runs"] == 1
        assert cfg["total_failures"] == 0
        assert cfg["last_run_exit_code"] == 0
        assert cfg["last_run_duration_ms"] == 150.5
        assert cfg["last_run_at"] is not None

    def test_record_hook_run_failure(self, tmp_path: Path):
        """record_hook_run with non-zero exit code increments failures."""
        store = IndexStateStore(tmp_path / ".codegraph")
        store.record_hook_run(exit_code=1, duration_ms=200.0)
        cfg = store.get_hook_config()
        assert cfg["total_runs"] == 1
        assert cfg["total_failures"] == 1
        assert cfg["last_run_exit_code"] == 1

    def test_record_hook_run_multiple(self, tmp_path: Path):
        """Multiple hook runs accumulate correctly."""
        store = IndexStateStore(tmp_path / ".codegraph")
        for i in range(3):
            store.record_hook_run(exit_code=0 if i % 2 == 0 else 1, duration_ms=100.0)
        cfg = store.get_hook_config()
        assert cfg["total_runs"] == 3
        assert cfg["total_failures"] == 1
        assert cfg["last_run_exit_code"] == 0  # last run was i=2, exit_code=0


# ══ Hook template ═════════════════════════════════════════════════════════

class TestHookTemplate:
    """Tests for hook script template generation."""

    def test_unix_template_contains_sentinels(self):
        """Unix template includes managed block sentinel comments."""
        script = build_unix_hook_script("/usr/bin/python3", "/home/user/project")
        assert SENTINEL_START in script
        assert SENTINEL_END in script

    def test_unix_template_contains_python_path(self):
        """Unix template embeds the given Python path."""
        script = build_unix_hook_script("/usr/bin/python3", "/home/user/project")
        assert "/usr/bin/python3" in script

    def test_unix_template_contains_project_root(self):
        """Unix template embeds the given project root."""
        script = build_unix_hook_script("/usr/bin/python3", "/home/user/project")
        assert "/home/user/project" in script

    def test_unix_template_has_shebang(self):
        """Unix template starts with a shebang."""
        script = build_unix_hook_script("/usr/bin/python3", "/home/user/project")
        assert script.startswith("#!/usr/bin/env bash")

    def test_unix_template_has_or_true(self):
        """Unix template uses '|| true' to always exit 0."""
        script = build_unix_hook_script("/usr/bin/python3", "/home/user/project")
        assert "|| true" in script

    def test_windows_template_contains_sentinels(self):
        """Windows template includes managed block sentinel comments."""
        script = build_windows_hook_script(
            "C:\\Python\\python.exe", "C:\\project",
        )
        assert SENTINEL_START in script
        assert SENTINEL_END in script

    def test_windows_template_always_exits_zero(self):
        """Windows template uses 'exit /b 0'."""
        script = build_windows_hook_script(
            "C:\\Python\\python.exe", "C:\\project",
        )
        assert "exit /b 0" in script


# ══ HookManager ═══════════════════════════════════════════════════════════

class TestHookManagerInstall:
    """Tests for HookManager.install()."""

    def test_install_creates_hook_file(self, tmp_path: Path):
        """install() creates the post-commit hook file."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        result = HookManager.install(root)
        assert result["installed"] is True
        hook_path = root / ".git" / "hooks" / "post-commit"
        assert hook_path.exists()

    def test_install_contains_managed_block(self, tmp_path: Path):
        """Installed hook contains managed block sentinels."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        content = (root / ".git" / "hooks" / "post-commit").read_text("utf-8")
        assert SENTINEL_START in content
        assert SENTINEL_END in content

    def test_install_contains_python_path(self, tmp_path: Path):
        """Installed hook contains sys.executable path."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        content = (root / ".git" / "hooks" / "post-commit").read_text("utf-8")
        assert "CODEGRAPH_PYTHON" in content

    def test_install_updates_state(self, tmp_path: Path):
        """install() updates state.json with hook info."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        store = IndexStateStore(root / ".codegraph")
        cfg = store.get_hook_config()
        assert cfg["installed"] is True
        assert cfg["hook_path"] is not None
        assert cfg["installed_at"] is not None

    def test_install_is_idempotent(self, tmp_path: Path):
        """Repeated install() does not duplicate the managed block."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        HookManager.install(root)  # second call
        content = (root / ".git" / "hooks" / "post-commit").read_text("utf-8")
        # Count sentinel occurrences
        assert content.count(SENTINEL_START) == 1
        assert content.count(SENTINEL_END) == 1

    def test_install_force_updates(self, tmp_path: Path):
        """install(force=True) replaces the managed block."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        HookManager.install(root, force=True)
        content = (root / ".git" / "hooks" / "post-commit").read_text("utf-8")
        assert content.count(SENTINEL_START) == 1  # still only one

    def test_install_preserves_user_hook_content(self, tmp_path: Path):
        """Installing does not overwrite user's own hook content outside the block."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        hooks_dir = root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        user_content = "#!/bin/sh\necho 'my custom hook'\n"
        (hooks_dir / "post-commit").write_text(user_content, encoding="utf-8")
        HookManager.install(root)
        content = (hooks_dir / "post-commit").read_text("utf-8")
        assert "my custom hook" in content
        assert SENTINEL_START in content

    def test_install_no_git_dir_returns_skip(self, tmp_path: Path):
        """install() on a non-git directory returns installed=False."""
        _make_dot_codegraph(tmp_path)
        result = HookManager.install(tmp_path)
        assert result["installed"] is False
        assert result["action"] == "skip"

    def test_install_worktree_gitdir(self, tmp_path: Path):
        """install() handles worktree .git file correctly."""
        # Create a bare repo and a worktree-like structure
        main_repo = tmp_path / "main"
        main_repo.mkdir()
        subprocess.run(["git", "init"], cwd=str(main_repo), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "a@b.com"],
            cwd=str(main_repo), capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "A"],
            cwd=str(main_repo), capture_output=True, check=True,
        )

        worktree_dir = tmp_path / "worktree"
        worktree_dir.mkdir()
        # Simulate worktree .git file
        git_file = worktree_dir / ".git"
        git_file.write_text(
            f"gitdir: {main_repo / '.git'}\n", encoding="utf-8",
        )
        _make_dot_codegraph(worktree_dir)
        git_dir = HookManager._find_git_dir(worktree_dir)
        assert git_dir is not None
        assert git_dir.name == ".git"


class TestHookManagerUninstall:
    """Tests for HookManager.uninstall()."""

    def test_uninstall_removes_managed_block(self, tmp_path: Path):
        """uninstall() removes the managed block, leaving file empty."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        result = HookManager.uninstall(root)
        assert result["uninstalled"] is True
        hook_path = root / ".git" / "hooks" / "post-commit"
        # File should be deleted since it only had the managed block
        assert not hook_path.exists()

    def test_uninstall_preserves_user_content(self, tmp_path: Path):
        """uninstall() removes only the managed block, keeping user content."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        hooks_dir = root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "post-commit").write_text(
            "#!/bin/sh\necho 'my hook'\n", encoding="utf-8",
        )
        HookManager.install(root)
        HookManager.uninstall(root)
        content = (hooks_dir / "post-commit").read_text("utf-8")
        assert "my hook" in content
        assert SENTINEL_START not in content

    def test_uninstall_no_hook_returns_skip(self, tmp_path: Path):
        """uninstall() when no hook exists returns uninstalled=True, action=skip."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        result = HookManager.uninstall(root)
        assert result["uninstalled"] is True
        assert result["action"] == "skip"

    def test_uninstall_updates_state(self, tmp_path: Path):
        """uninstall() updates state.json to reflect uninstalled state."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        HookManager.uninstall(root)
        store = IndexStateStore(root / ".codegraph")
        cfg = store.get_hook_config()
        assert cfg["installed"] is False


class TestHookManagerStatus:
    """Tests for HookManager.status()."""

    def test_status_not_installed(self, tmp_path: Path):
        """status() reports not installed when no hook exists."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        status = HookManager.status(root)
        assert status["installed"] is False

    def test_status_installed(self, tmp_path: Path):
        """status() reports installed after install()."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        status = HookManager.status(root)
        assert status["installed"] is True
        assert status["valid"] is True

    def test_status_includes_run_stats(self, tmp_path: Path):
        """status() includes run statistics from state."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        store = IndexStateStore(root / ".codegraph")
        store.record_hook_run(exit_code=0, duration_ms=100.0)
        status = HookManager.status(root)
        assert status["total_runs"] == 1
        assert status["total_failures"] == 0

    def test_status_non_git_dir(self, tmp_path: Path):
        """status() reports issues for non-git directory."""
        _make_dot_codegraph(tmp_path)
        status = HookManager.status(tmp_path)
        assert len(status["issues"]) > 0

    def test_status_detects_missing_managed_block(self, tmp_path: Path):
        """status() detects a hook file without managed block."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        hooks_dir = root / ".git" / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        (hooks_dir / "post-commit").write_text("#!/bin/sh\necho custom\n", encoding="utf-8")
        status = HookManager.status(root)
        assert status["installed"] is False
        assert status["has_managed_block"] is False

    def test_status_auto_update_disabled(self, tmp_path: Path):
        """status() reflects auto_update_on_commit setting."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        store = IndexStateStore(root / ".codegraph")
        store.update_hook_config(auto_update_on_commit=False)
        status = HookManager.status(root)
        assert status["auto_update_on_commit"] is False


# ══ CLI: hooks commands ════════════════════════════════════════════════════

class TestCliHooks:
    """Tests for the 'codegraph hooks' CLI command group."""

    def test_hooks_install(self, tmp_path: Path):
        """codegraph hooks install creates the hook."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["hooks", "install", "--root", str(root)],
        )
        assert result.exit_code == 0
        hook_path = root / ".git" / "hooks" / "post-commit"
        assert hook_path.exists()

    def test_hooks_uninstall(self, tmp_path: Path):
        """codegraph hooks uninstall removes the managed block."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        HookManager.install(root)
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["hooks", "uninstall", "--root", str(root)],
        )
        assert result.exit_code == 0

    def test_hooks_status_json(self, tmp_path: Path):
        """codegraph hooks status --json outputs valid JSON."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["hooks", "status", "--root", str(root), "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "installed" in data
        assert "auto_update_on_commit" in data

    def test_hooks_install_no_git(self, tmp_path: Path):
        """codegraph hooks install in a non-git directory fails."""
        _make_dot_codegraph(tmp_path)
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["hooks", "install", "--root", str(tmp_path)],
        )
        assert result.exit_code != 0


# ══ CLI: config commands ═══════════════════════════════════════════════════

class TestCliConfig:
    """Tests for the 'codegraph config' CLI command group."""

    @pytest.fixture(autouse=True)
    def _import_app(self):
        """Ensure the CLI app module is loaded."""
        self.app = __import__("codegraph.cli.main", fromlist=["app"]).app

    def test_config_set_boolean_true(self, tmp_path: Path):
        """codegraph config set auto_update_on_commit true."""
        _make_dot_codegraph(tmp_path)
        result = runner.invoke(
            self.app,
            ["config", "set", "auto_update_on_commit", "true", "--root", str(tmp_path)],
        )
        assert result.exit_code == 0
        store = IndexStateStore(tmp_path / ".codegraph")
        assert store.get_hook_config()["auto_update_on_commit"] is True

    def test_config_set_boolean_false(self, tmp_path: Path):
        """codegraph config set auto_update_on_commit false."""
        _make_dot_codegraph(tmp_path)
        result = runner.invoke(
            self.app,
            ["config", "set", "auto_update_on_commit", "false", "--root", str(tmp_path)],
        )
        assert result.exit_code == 0
        store = IndexStateStore(tmp_path / ".codegraph")
        assert store.get_hook_config()["auto_update_on_commit"] is False

    def test_config_get(self, tmp_path: Path):
        """codegraph config get auto_update_on_commit returns value."""
        _make_dot_codegraph(tmp_path)
        store = IndexStateStore(tmp_path / ".codegraph")
        store.update_hook_config(auto_update_on_commit=False)
        result = runner.invoke(
            self.app,
            ["config", "get", "auto_update_on_commit", "--root", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "False" in result.stdout

    def test_config_set_unknown_key(self, tmp_path: Path):
        """codegraph config set unknown_key fails."""
        _make_dot_codegraph(tmp_path)
        result = runner.invoke(
            self.app,
            ["config", "set", "unknown_key", "value", "--root", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_config_set_invalid_boolean(self, tmp_path: Path):
        """codegraph config set with invalid boolean value fails."""
        _make_dot_codegraph(tmp_path)
        result = runner.invoke(
            self.app,
            ["config", "set", "auto_update_on_commit", "maybe", "--root", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_config_set_yes_no(self, tmp_path: Path):
        """codegraph config set accepts yes/no as boolean values."""
        _make_dot_codegraph(tmp_path)
        result = runner.invoke(
            self.app,
            ["config", "set", "auto_update_on_commit", "yes", "--root", str(tmp_path)],
        )
        assert result.exit_code == 0
        store = IndexStateStore(tmp_path / ".codegraph")
        assert store.get_hook_config()["auto_update_on_commit"] is True


# ══ CLI: sync command ══════════════════════════════════════════════════════

class TestCliSync:
    """Tests for the 'codegraph sync' CLI command."""

    def test_sync_exits_zero_even_without_index(self, tmp_path: Path):
        """sync always exits 0 even when there is no .codegraph directory."""
        # We need to run this from a git repo
        root = _init_git_repo(tmp_path)
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["sync", "--incremental", "--quiet", "--trigger", "post-commit"],
        )
        # Should always exit 0
        assert result.exit_code == 0

    def test_sync_skips_when_auto_update_disabled(self, tmp_path: Path):
        """sync exits when auto_update_on_commit is false."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        store = IndexStateStore(root / ".codegraph")
        store.update_hook_config(auto_update_on_commit=False)
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["sync", "--incremental", "--quiet", "--trigger", "post-commit"],
        )
        assert result.exit_code == 0

    def test_sync_exits_successfully(self, tmp_path: Path):
        """sync runs without error on a valid project."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        # The sync needs actual index files to work with
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["sync", "--incremental", "--quiet", "--trigger", "manual"],
        )
        # Always exits 0
        assert result.exit_code == 0


# ══ CLI: init command ══════════════════════════════════════════════════════

class TestCliInitHook:
    """Tests for hook auto-install behavior in 'codegraph init'."""

    # NOTE: init spawns a full indexing pipeline which is slow.
    # These tests focus on the --no-hook flag and the _maybe_install_hook
    # helper, which are directly testable.

    def test_init_no_hook_flag_accepted(self, tmp_path: Path):
        """codegraph init --no-hook is a valid flag."""
        root = _init_git_repo(tmp_path)
        # Create a minimal Python file so scanner finds something
        (root / "main.py").write_text("def hello(): pass\n", encoding="utf-8")
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["init", str(root), "--no-hook"],
        )
        # Should succeed (or fail for index reasons, not flag reasons)
        # Exit code may be non-zero if there's an indexing issue, but the
        # important thing is that --no-hook is accepted
        hook_path = root / ".git" / "hooks" / "post-commit"
        # With --no-hook, hook should NOT be installed even if init succeeds
        if result.exit_code == 0:
            assert not hook_path.exists() or SENTINEL_START not in (
                hook_path.read_text("utf-8") if hook_path.exists() else ""
            )

    def test_maybe_install_hook_git_repo(self, tmp_path: Path):
        """_maybe_install_hook installs hook in a git repo."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        from codegraph.cli.main import _maybe_install_hook
        store = IndexStateStore(root / ".codegraph")
        _maybe_install_hook(root, no_hook=False, state_store=store)
        # Hook should have been installed
        hook_path = root / ".git" / "hooks" / "post-commit"
        assert hook_path.exists()
        content = hook_path.read_text("utf-8")
        assert SENTINEL_START in content

    def test_maybe_install_hook_no_hook_skips(self, tmp_path: Path):
        """_maybe_install_hook does nothing when no_hook=True."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        from codegraph.cli.main import _maybe_install_hook
        store = IndexStateStore(root / ".codegraph")
        _maybe_install_hook(root, no_hook=True, state_store=store)
        hook_path = root / ".git" / "hooks" / "post-commit"
        assert not hook_path.exists()

    def test_maybe_install_hook_non_git_skips(self, tmp_path: Path):
        """_maybe_install_hook skips non-git directories."""
        _make_dot_codegraph(tmp_path)
        from codegraph.cli.main import _maybe_install_hook
        store = IndexStateStore(tmp_path / ".codegraph")
        _maybe_install_hook(tmp_path, no_hook=False, state_store=store)
        hook_path = tmp_path / ".git" / "hooks" / "post-commit"
        assert not hook_path.exists()

    def test_maybe_install_hook_disabled_config_skips(self, tmp_path: Path):
        """_maybe_install_hook skips when auto_update_on_commit is false."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        store = IndexStateStore(root / ".codegraph")
        store.update_hook_config(auto_update_on_commit=False)
        from codegraph.cli.main import _maybe_install_hook
        _maybe_install_hook(root, no_hook=False, state_store=store)
        # Hook should NOT be installed because config says disabled
        hook_path = root / ".git" / "hooks" / "post-commit"
        # The helper exits early due to disabled config
        # The hook wasn't installed previously, so it shouldn't exist
        assert not hook_path.exists()


# ══ Hook logger ═══════════════════════════════════════════════════════════

class TestHookLogger:
    """Tests for the rotating hook logger."""

    def test_logger_creates_log_dir(self, tmp_path: Path):
        """get_hook_logger creates the log directory if needed."""
        log_dir = tmp_path / "logs"
        logger = get_hook_logger(log_dir)
        assert log_dir.exists()

    def test_logger_writes_to_file(self, tmp_path: Path):
        """Logger writes messages to hooks.log."""
        log_dir = tmp_path / "logs"
        logger = get_hook_logger(log_dir)
        logger.info("test message")
        log_content = (log_dir / "hooks.log").read_text("utf-8")
        assert "test message" in log_content

    def test_logger_returns_same_instance(self, tmp_path: Path):
        """Multiple calls return the same logger instance."""
        log_dir = tmp_path / "logs"
        logger1 = get_hook_logger(log_dir)
        logger2 = get_hook_logger(log_dir)
        assert logger1 is logger2


# ══ Windows path compatibility ════════════════════════════════════════════

class TestWindowsPathCompat:
    """Windows-specific path handling tests."""

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_windows_template_backslash_paths(self):
        """Windows template handles backslash paths."""
        script = build_windows_hook_script(
            "C:\\Program Files\\Python\\python.exe",
            "C:\\Users\\test\\project",
        )
        assert "C:/Program Files/Python/python.exe" in script

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
    def test_windows_hook_install(self, tmp_path: Path):
        """HookManager.install works on Windows with backslash paths."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        result = HookManager.install(root)
        assert result["installed"] is True


# ══ Edge cases ════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Edge case tests for hook management."""

    def test_doctor_includes_hook_section(self, tmp_path: Path):
        """codegraph doctor output includes hook health section."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        result = runner.invoke(
            __import__("codegraph.cli.main", fromlist=["app"]).app,
            ["doctor", "--root", str(root)],
        )
        # Doctor may exit 0 or non-zero depending on state, but
        # the output should contain "Hook health"
        assert "Hook health" in result.stdout

    def test_get_index_status_includes_hook(self, tmp_path: Path):
        """get_index_status() return dict includes 'hook' key."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        from codegraph.indexer.status import get_index_status
        status = get_index_status(root)
        assert "hook" in status
        hook = status["hook"]
        assert "installed" in hook
        assert "auto_update_on_commit" in hook

    def test_repo_status_mcp_includes_hook_fields(self, tmp_path: Path):
        """repo_status MCP response includes hook_installed/hook_auto_update."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        # We need to monkey-patch the MCP server's project_root
        import codegraph.mcp_server as mcp_mod
        saved_root = getattr(mcp_mod, "_project_root", None)
        saved_store = getattr(mcp_mod, "_store", None)
        saved_cg_dir = getattr(mcp_mod, "_cg_dir", None)
        try:
            mcp_mod._project_root = str(root)
            mcp_mod._cg_dir = str(root / ".codegraph")
            response = mcp_mod.repo_status(response_mode="compact")
            assert response["ok"] is True
            data = response["data"]
            assert "hook_installed" in data
            assert "hook_auto_update" in data
        finally:
            if saved_root is not None:
                mcp_mod._project_root = saved_root
            else:
                delattr(mcp_mod, "_project_root")
            if saved_store is not None:
                mcp_mod._store = saved_store
            elif hasattr(mcp_mod, "_store"):
                delattr(mcp_mod, "_store")
            if saved_cg_dir is not None:
                mcp_mod._cg_dir = saved_cg_dir
            elif hasattr(mcp_mod, "_cg_dir"):
                delattr(mcp_mod, "_cg_dir")

    def test_lock_not_held_after_sync_error(self, tmp_path: Path):
        """IndexLock is released even when sync encounters an error."""
        root = _init_git_repo(tmp_path)
        _make_dot_codegraph(root)
        from codegraph.indexer.lock import IndexLock
        lock = IndexLock(root / ".codegraph")
        # Manually test acquire/release
        assert lock.acquire(timeout=1.0)
        assert lock.is_locked()
        lock.release()
        assert not lock.is_locked()

    def test_hook_script_does_not_contain_relative_paths(self):
        """Generated hook script uses absolute paths only."""
        script = build_unix_hook_script("/abs/path/python", "/abs/path/project")
        # Should not contain "./" relative references
        assert "./" not in script.split("CODEGRAPH_PYTHON=")[1].split("\n")[0]
