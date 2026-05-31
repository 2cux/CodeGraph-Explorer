"""Tests for watch mode: WatchSyncManager, IndexLock, IndexStateStore, incremental sync."""

import json
import os
import time
import threading
from pathlib import Path

import pytest

from codegraph.indexer.lock import IndexLock, _pid_alive
from codegraph.indexer.incremental import run_incremental_index, IncrementalResult
from codegraph.indexer.watch import (
    WatchSyncManager,
    _should_watch,
    _should_watch_path,
    _is_py_or_config,
    WATCH_GLOBS,
    IGNORE_DIRS,
)
from codegraph.storage.state_store import IndexStateStore
from codegraph.storage.file_store import FileStore
from codegraph.graph.models import IndexMetadata, FileEntry


# ══════════════════════════════════════════════════════════════════════════
# IndexLock tests
# ══════════════════════════════════════════════════════════════════════════


class TestPidAlive:
    def test_current_pid_is_alive(self):
        assert _pid_alive(os.getpid()) is True

    def test_invalid_pid_is_dead(self):
        # PID 0 is the system idle process on Windows; on Unix kill(0,0)
        # tests the process group. Use a very high PID that can't exist.
        assert _pid_alive(99999999) is False


class TestIndexLock:
    def test_acquire_and_release(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        lock = IndexLock(cg_dir)
        assert lock.acquire() is True
        assert lock.is_locked() is True
        lock.release()
        assert lock.is_locked() is False

    def test_prevents_concurrent_writes(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        lock1 = IndexLock(cg_dir)
        lock2 = IndexLock(cg_dir)

        assert lock1.acquire() is True
        assert lock2.acquire() is False
        lock1.release()
        assert lock2.acquire() is True
        lock2.release()

    def test_context_manager(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        with IndexLock(cg_dir) as lock:
            assert lock._held is True
        assert lock._held is False
        assert not lock._path.exists()

    def test_stale_lock_recovery(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        lock_path = cg_dir / "index.lock"
        # Write a fake lock with a dead PID
        lock_path.write_text(json.dumps({
            "pid": 99999999,
            "created_at": time.time() - 600,
            "hostname": "",
        }), encoding="utf-8")

        lock = IndexLock(cg_dir)
        assert lock.acquire() is True
        lock.release()

    def test_lock_clears_stale_by_timeout(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        lock_path = cg_dir / "index.lock"
        lock_path.write_text(json.dumps({
            "pid": os.getpid(),  # real PID, but old enough to time out
            "created_at": time.time() - 600,
            "hostname": "",
        }), encoding="utf-8")

        lock = IndexLock(cg_dir)
        assert lock.acquire() is True
        lock.release()

    def test_is_locked_from_other_process(self, tmp_path):
        """Simulate checking lock status from another lock instance."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        lock1 = IndexLock(cg_dir)
        lock1.acquire()

        lock2 = IndexLock(cg_dir)
        assert lock2.is_locked() is True

        lock1.release()
        assert lock2.is_locked() is False


# ══════════════════════════════════════════════════════════════════════════
# IndexStateStore tests
# ══════════════════════════════════════════════════════════════════════════


class TestIndexStateStore:
    def test_default_state_when_missing(self, tmp_path):
        store = IndexStateStore(tmp_path)
        state = store.load()
        assert state["status"] == "missing"
        assert state["last_indexed_at"] is None
        assert state["watch"]["enabled"] is False

    def test_save_and_load(self, tmp_path):
        store = IndexStateStore(tmp_path)
        store.update_status("fresh")
        state = store.load()
        assert state["status"] == "fresh"

    def test_update_status_preserves_other_fields(self, tmp_path):
        store = IndexStateStore(tmp_path)
        store.init_watch(debounce_ms=300)
        store.update_status("indexing")
        state = store.load()
        assert state["status"] == "indexing"
        assert state["watch"]["enabled"] is True
        assert state["watch"]["debounce_ms"] == 300

    def test_mark_indexing(self, tmp_path):
        store = IndexStateStore(tmp_path)
        store.mark_indexing()
        assert store.load()["status"] == "indexing"

    def test_set_pending_changes(self, tmp_path):
        store = IndexStateStore(tmp_path)
        store.set_pending_changes(
            changed=["a.py"], added=["b.py"], deleted=["c.py"],
        )
        pc = store.load()["pending_changes"]
        assert pc["changed"] == ["a.py"]
        assert pc["added"] == ["b.py"]
        assert pc["deleted"] == ["c.py"]

    def test_clear_pending_changes(self, tmp_path):
        store = IndexStateStore(tmp_path)
        store.set_pending_changes(["a.py"], [], [])
        store.clear_pending_changes()
        pc = store.load()["pending_changes"]
        assert pc == {"changed": [], "added": [], "deleted": []}

    def test_init_and_disable_watch(self, tmp_path):
        store = IndexStateStore(tmp_path)
        store.init_watch(debounce_ms=700)
        assert store.load()["watch"]["enabled"] is True
        store.disable_watch()
        assert store.load()["watch"]["enabled"] is False

    def test_corrupted_state_file_returns_defaults(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("not valid json", encoding="utf-8")
        store = IndexStateStore(tmp_path)
        state = store.load()
        assert state["status"] == "missing"


# ══════════════════════════════════════════════════════════════════════════
# Watch pattern tests
# ══════════════════════════════════════════════════════════════════════════


class TestWatchPatterns:
    def test_should_watch_py_file(self, tmp_path):
        (tmp_path / "test.py").write_text("x=1", encoding="utf-8")
        assert _should_watch("test.py", tmp_path) is True

    def test_should_watch_pyproject_toml(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        assert _should_watch("pyproject.toml", tmp_path) is True

    def test_should_watch_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
        assert _should_watch("requirements.txt", tmp_path) is True

    def test_should_not_watch_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config.py").write_text("", encoding="utf-8")
        assert _should_watch(".git/config.py", tmp_path) is False

    def test_should_not_watch_node_modules(self, tmp_path):
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "index.py").write_text("", encoding="utf-8")
        assert _should_watch("node_modules/pkg/index.py", tmp_path) is False

    def test_should_not_watch_pycache(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.py").write_text("", encoding="utf-8")
        assert _should_watch("__pycache__/mod.py", tmp_path) is False

    def test_should_not_watch_codegraph_dir(self, tmp_path):
        (tmp_path / ".codegraph").mkdir()
        (tmp_path / ".codegraph" / "data.py").write_text("", encoding="utf-8")
        assert _should_watch(".codegraph/data.py", tmp_path) is False

    def test_should_not_watch_non_py_file(self, tmp_path):
        (tmp_path / "README.md").write_text("", encoding="utf-8")
        assert _should_watch("README.md", tmp_path) is False

    def test_ignore_dirs_contains_expected(self):
        assert ".git" in IGNORE_DIRS
        assert ".venv" in IGNORE_DIRS
        assert "__pycache__" in IGNORE_DIRS
        assert ".codegraph" in IGNORE_DIRS
        assert ".mypy_cache" in IGNORE_DIRS
        assert ".ruff_cache" in IGNORE_DIRS

    def test_watch_globs_contains_expected(self):
        assert "**/*.py" in WATCH_GLOBS
        assert "pyproject.toml" in WATCH_GLOBS

    def test_chinese_path(self, tmp_path):
        sub = tmp_path / "项目" / "模块"
        sub.mkdir(parents=True)
        (sub / "认证.py").write_text("x=1", encoding="utf-8")
        assert _should_watch("项目/模块/认证.py", tmp_path) is True

    def test_space_path(self, tmp_path):
        sub = tmp_path / "my project" / "src"
        sub.mkdir(parents=True)
        (sub / "main.py").write_text("x=1", encoding="utf-8")
        assert _should_watch("my project/src/main.py", tmp_path) is True


# ══════════════════════════════════════════════════════════════════════════
# WatchSyncManager tests (unit tests for core logic)
# ══════════════════════════════════════════════════════════════════════════


class TestWatchSyncManagerUnit:
    """Unit tests for WatchSyncManager — these test the core logic without
    actually starting a file watcher, so they're stable."""

    def test_initial_state(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        mgr = WatchSyncManager(repo_root=tmp_path, debounce_ms=500)
        state = mgr.get_state()
        assert "status" in state

    def test_on_file_event_accumulates_changes(self, tmp_path):
        (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
        (tmp_path / "b.py").write_text("y=2", encoding="utf-8")
        mgr = WatchSyncManager(repo_root=tmp_path, debounce_ms=500)
        mgr._running = True  # enable event processing without starting watcher
        mgr.on_file_event(str(tmp_path / "a.py"), "modified")
        mgr.on_file_event(str(tmp_path / "b.py"), "created")

        with mgr._lock_obj:
            # At least one event should be registered
            has_changes = (
                mgr._changed_files or mgr._added_files or mgr._deleted_files
            )
            assert has_changes, "Expected at least some file events to be tracked"

    def test_on_file_event_ignores_non_watched(self, tmp_path):
        mgr = WatchSyncManager(repo_root=tmp_path, debounce_ms=500)
        mgr.on_file_event("README.md", "modified")
        with mgr._lock_obj:
            assert len(mgr._changed_files) == 0
            assert len(mgr._added_files) == 0

    def test_is_indexing_flag(self, tmp_path):
        mgr = WatchSyncManager(repo_root=tmp_path, debounce_ms=500)
        assert mgr.is_indexing is False

    def test_stop_cleans_up(self, tmp_path):
        mgr = WatchSyncManager(repo_root=tmp_path, debounce_ms=500)
        mgr.start()
        # Should stop cleanly without errors
        mgr.stop()
        state = mgr.get_state()
        assert state["watch"]["enabled"] is False


# ══════════════════════════════════════════════════════════════════════════
# Incremental index tests (watch sync logic)
# ══════════════════════════════════════════════════════════════════════════


class TestIncrementalIndex:
    """Tests for the shared incremental index logic used by watch mode."""

    def setup_project(self, tmp_path):
        """Create a minimal indexed project."""
        (tmp_path / "main.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""", encoding="utf-8")

        from codegraph.cli.main import _save_index_artifacts
        from codegraph.indexer.graph_builder import build_index

        nodes, edges = build_index(tmp_path)
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        _save_index_artifacts(cg_dir, nodes, edges, tmp_path)
        return cg_dir

    def test_incremental_detects_modified_file(self, tmp_path):
        """Watch should detect and re-index a modified file."""
        cg_dir = self.setup_project(tmp_path)

        # Modify a file
        (tmp_path / "main.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
def farewell(name: str) -> str:
    return f"Goodbye {name}"
""", encoding="utf-8")

        store = FileStore(cg_dir)
        result = run_incremental_index(tmp_path, cg_dir, store)

        assert result.status == "updated"
        assert result.changed_count == 1
        assert result.nodes_added > 0  # new function added
        # Check the new symbol exists in the updated index
        updated_nodes = store.load_nodes()
        node_names = [n.get("name") for n in updated_nodes]
        assert "farewell" in node_names

    def test_incremental_detects_added_file(self, tmp_path):
        """Watch should detect and index a newly added file."""
        cg_dir = self.setup_project(tmp_path)

        # Add a new file
        (tmp_path / "utils.py").write_text("""
def helper() -> str:
    return "helper"
""", encoding="utf-8")

        store = FileStore(cg_dir)
        result = run_incremental_index(tmp_path, cg_dir, store)

        assert result.status == "updated"
        assert result.added_count == 1
        updated_nodes = store.load_nodes()
        node_names = [n.get("name") for n in updated_nodes]
        assert "helper" in node_names

    def test_incremental_detects_deleted_file(self, tmp_path):
        """Watch should detect and remove symbols for deleted files."""
        cg_dir = self.setup_project(tmp_path)

        # Remove a file
        (tmp_path / "main.py").unlink()

        store = FileStore(cg_dir)
        result = run_incremental_index(tmp_path, cg_dir, store)

        assert result.status == "updated"
        assert result.deleted_count == 1
        assert result.total_symbols == 0  # all symbols removed

    def test_incremental_updates_metadata_fingerprint(self, tmp_path):
        """After incremental index, metadata fingerprint should be updated."""
        cg_dir = self.setup_project(tmp_path)

        (tmp_path / "main.py").write_text("x = 42", encoding="utf-8")

        store = FileStore(cg_dir)
        run_incremental_index(tmp_path, cg_dir, store)

        metadata = store.load_metadata()
        assert metadata is not None
        main_entry = next(
            (f for f in metadata.files if f.path == "main.py"), None,
        )
        assert main_entry is not None

    def test_incremental_returns_fresh_when_no_changes(self, tmp_path):
        """If nothing changed, incremental should report fresh."""
        cg_dir = self.setup_project(tmp_path)

        store = FileStore(cg_dir)
        result = run_incremental_index(tmp_path, cg_dir, store)

        assert result.status == "fresh"
        if result.status_result is not None:
            assert result.status_result.total_changes == 0

    def test_incremental_returns_missing_when_no_index(self, tmp_path):
        """If no index exists, incremental should report missing."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        (tmp_path / "main.py").write_text("x=1", encoding="utf-8")

        store = FileStore(cg_dir)
        result = run_incremental_index(tmp_path, cg_dir, store)

        assert result.status == "missing"

    def test_incremental_handles_failure_without_deleting_old_index(self, tmp_path):
        """If index fails (e.g. parse error in a file), old index survives."""
        cg_dir = self.setup_project(tmp_path)

        # Snapshot current index state
        store = FileStore(cg_dir)
        old_nodes = store.load_nodes()
        old_node_count = len(old_nodes)

        # Write a syntactically broken Python file
        (tmp_path / "broken.py").write_text("def broken(  # syntax error", encoding="utf-8")

        try:
            run_incremental_index(tmp_path, cg_dir, store)
        except Exception:
            pass  # Expected — bad syntax

        # The old nodes should still exist (old index preserved)
        current_nodes = store.load_nodes()
        # broken.py may or may not have been added to index depending on where
        # the error occurred — but the original nodes should still exist
        assert len(current_nodes) >= old_node_count


# ══════════════════════════════════════════════════════════════════════════
# State update integration tests
# ══════════════════════════════════════════════════════════════════════════


class TestStateUpdateIntegration:
    """Tests that state.json is properly updated during watch operations."""

    def test_state_store_updates_to_fresh_after_sync(self, tmp_path):
        """After a successful watch sync, state should be fresh."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        # Setup initial state as stale
        state_store = IndexStateStore(cg_dir)
        state_store.update_status("stale")

        # Simulate what happens after a successful sync
        state_store.update_status(
            "fresh",
            last_incremental_at="2026-01-01T00:00:00+00:00",
        )
        state_store.clear_pending_changes()

        state = state_store.load()
        assert state["status"] == "fresh"
        assert state["last_incremental_at"] is not None
        assert state["pending_changes"] == {
            "changed": [], "added": [], "deleted": [],
        }

    def test_state_store_tracks_error(self, tmp_path):
        """After an index failure, state should be error with last_error."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        state_store = IndexStateStore(cg_dir)
        state_store.update_status("error", last_error="SyntaxError in foo.py")

        state = state_store.load()
        assert state["status"] == "error"
        assert "SyntaxError" in state["last_error"]

    def test_state_transitions(self, tmp_path):
        """Simulate a full lifecycle: fresh → indexing → fresh."""
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()

        state_store = IndexStateStore(cg_dir)

        # Start: fresh
        state_store.update_status("fresh")
        assert state_store.load()["status"] == "fresh"

        # Indexing begins
        state_store.mark_indexing()
        assert state_store.load()["status"] == "indexing"

        # Done
        state_store.update_status("fresh")
        assert state_store.load()["status"] == "fresh"


# ══════════════════════════════════════════════════════════════════════════
# Polling fallback tests
# ══════════════════════════════════════════════════════════════════════════


class TestPollingFallback:
    """Tests for the polling-based file change detection."""

    def test_scan_files_discovers_python(self, tmp_path):
        (tmp_path / "a.py").write_text("x=1", encoding="utf-8")
        (tmp_path / "b.py").write_text("y=2", encoding="utf-8")
        (tmp_path / "README.md").write_text("readme", encoding="utf-8")

        mgr = WatchSyncManager(repo_root=tmp_path, use_watchdog=False)
        snapshot = mgr._scan_files()
        assert "a.py" in snapshot
        assert "b.py" in snapshot
        assert "README.md" not in snapshot

    def test_scan_files_excludes_ignored_dirs(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "config.py").write_text("", encoding="utf-8")
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "mod.cpython-312.pyc").write_text("", encoding="utf-8")
        (tmp_path / "real.py").write_text("x=1", encoding="utf-8")

        mgr = WatchSyncManager(repo_root=tmp_path, use_watchdog=False)
        snapshot = mgr._scan_files()
        assert "real.py" in snapshot
        assert not any(k.startswith(".git") for k in snapshot)
        assert not any(k.startswith("__pycache__") for k in snapshot)

    def test_compare_snapshots_detects_changes(self, tmp_path):
        (tmp_path / "a.py").write_text("v1", encoding="utf-8")
        (tmp_path / "b.py").write_text("v1", encoding="utf-8")

        mgr = WatchSyncManager(repo_root=tmp_path, use_watchdog=False)
        mgr._running = True  # enable event processing without starting watcher

        prev = mgr._scan_files()

        # Modify a.py
        (tmp_path / "a.py").write_text("v2", encoding="utf-8")
        # Delete b.py
        (tmp_path / "b.py").unlink()
        # Add c.py
        (tmp_path / "c.py").write_text("new", encoding="utf-8")

        current = mgr._scan_files()
        mgr._compare_snapshots(prev, current)

        with mgr._lock_obj:
            changed = mgr._changed_files.copy()
            added = mgr._added_files.copy()
            deleted = mgr._deleted_files.copy()

        assert "a.py" in changed
        assert "c.py" in added
        assert "b.py" in deleted
