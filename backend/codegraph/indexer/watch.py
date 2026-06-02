"""Watch mode — file system monitoring and automatic incremental index sync.

Provides WatchSyncManager that detects Python file changes and triggers
incremental index updates. Supports watchdog (preferred) and polling fallback.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from codegraph.indexer.incremental import run_incremental_index, IncrementalResult
from codegraph.indexer.lock import IndexLock
from codegraph.storage.file_store import FileStore
from codegraph.storage.state_store import IndexStateStore

# ── Watch / ignore patterns ───────────────────────────────────────────────

WATCH_GLOBS: list[str] = [
    "**/*.py",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
]

IGNORE_DIRS: set[str] = {
    ".git", ".venv", "venv", "env", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "dist", "build", ".codegraph",
}

# ── Helpers ───────────────────────────────────────────────────────────────


def _should_watch(path: str, root: Path) -> bool:
    """Check if a file path should be watched based on globs and ignore dirs.

    Handles both absolute paths (from watchdog) and paths already relative
    to *root* (from internal callers).
    """
    p = Path(path)
    try:
        rel = p.relative_to(root)
    except ValueError:
        # Path may already be relative to root
        if not p.is_absolute():
            rel = p
        else:
            return False

    parts = rel.parts
    if any(part in IGNORE_DIRS for part in parts):
        return False

    name = parts[-1] if parts else ""
    if name in {"pyproject.toml", "requirements.txt", "setup.py"}:
        return True

    return name.endswith(".py")


def _should_watch_path(path: Path, root: Path) -> bool:
    """Check if a Path should be watched."""
    try:
        rel_str = str(path.relative_to(root))
    except ValueError:
        return False
    return _should_watch(rel_str, root)


def _is_py_or_config(path: str) -> bool:
    """Quick check if a path matches watch patterns without root comparison."""
    name = os.path.basename(path)
    if name in {"pyproject.toml", "requirements.txt", "setup.py"}:
        return True
    return name.endswith(".py")


# ── WatchSyncManager ──────────────────────────────────────────────────────


class WatchSyncManager:
    """Watches a repo for file changes and triggers incremental index sync.

    Parameters:
        repo_root: Root path of the project to watch.
        debounce_ms: Delay in ms to batch changes before syncing.
        use_watchdog: If True, prefer watchdog; if False, use polling.
        poll_interval: Seconds between poll scans when using polling fallback.
        on_sync: Optional callback invoked after each sync completes.
            Called with the IncrementalResult.
    """

    def __init__(
        self,
        repo_root: str | Path,
        debounce_ms: int = 500,
        use_watchdog: bool = True,
        poll_interval: float = 2.0,
        on_sync: Callable[[IncrementalResult], None] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.debounce_ms = debounce_ms
        self.use_watchdog = use_watchdog
        self.poll_interval = poll_interval
        self.on_sync = on_sync

        cg_dir = self.repo_root / ".codegraph"
        cg_dir.mkdir(parents=True, exist_ok=True)
        self._cg_dir = cg_dir

        self._lock = IndexLock(cg_dir)
        self._state_store = IndexStateStore(cg_dir)
        self._file_store = FileStore(cg_dir)

        # Threading state
        self._running = False
        self._debounce_timer: threading.Timer | None = None
        self._indexing = False
        self._pending = False
        self._observer = None  # watchdog Observer
        self._poll_thread: threading.Thread | None = None
        self._lock_obj = threading.Lock()  # protects _indexing, _pending
        self._stop_event = threading.Event()

        # Accumulated changes during debounce window
        self._changed_files: set[str] = set()
        self._added_files: set[str] = set()
        self._deleted_files: set[str] = set()

    # ── Public API ─────────────────────────────────────────────────

    def start(self) -> None:
        """Start watching the repo. Returns immediately (watcher runs in background)."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()

        # Initialize state
        self._state_store.init_watch(debounce_ms=self.debounce_ms)
        # Set initial status based on current index
        self._refresh_state_status()

        if self.use_watchdog and self._try_start_watchdog():
            pass  # watchdog started successfully
        else:
            if self.use_watchdog:
                print("Watchdog not available, falling back to polling.")
            self._start_polling()

    def stop(self) -> None:
        """Stop watching the repo. Blocks until any in-progress sync completes."""
        self._running = False
        self._stop_event.set()

        # Cancel pending debounce timer
        with self._lock_obj:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None

        # Stop watchdog observer
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception:
                pass
            self._observer = None

        # Wait for polling thread
        if self._poll_thread is not None and self._poll_thread.is_alive():
            self._poll_thread.join(timeout=self.poll_interval + 2.0)

        # Wait for any in-progress sync
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            with self._lock_obj:
                if not self._indexing:
                    break
            time.sleep(0.1)

        self._state_store.disable_watch()
        print("Watch stopped.")

    @property
    def is_indexing(self) -> bool:
        """Whether an incremental index sync is currently running."""
        with self._lock_obj:
            return self._indexing

    def get_state(self) -> dict:
        """Return current state from state.json."""
        return self._state_store.load()

    # ── Event handling ─────────────────────────────────────────────

    def on_file_event(self, path: str, event_type: str) -> None:
        """Handle a file change event. Called from watchdog or polling."""
        if not self._running:
            return

        if not _should_watch(path, self.repo_root):
            return

        with self._lock_obj:
            if event_type == "modified":
                self._changed_files.add(path)
            elif event_type == "created":
                self._added_files.add(path)
            elif event_type == "deleted":
                # If a file is both changed and deleted, treat as changed
                if path in self._changed_files:
                    self._changed_files.discard(path)
                if path in self._added_files:
                    self._added_files.discard(path)
                self._deleted_files.add(path)

            # Reset debounce timer
            self._reset_debounce_timer_locked()

    def _reset_debounce_timer_locked(self) -> None:
        """Cancel and restart the debounce timer. Must hold _lock_obj."""
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()

        delay = self.debounce_ms / 1000.0
        self._debounce_timer = threading.Timer(delay, self._debounce_callback)
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _debounce_callback(self) -> None:
        """Called when the debounce timer fires — trigger sync."""
        if not self._running:
            return

        with self._lock_obj:
            if self._indexing:
                self._pending = True
                return

            changed = list(self._changed_files)
            added = list(self._added_files)
            deleted = list(self._deleted_files)

            if not changed and not added and not deleted:
                return

            self._indexing = True
            self._changed_files.clear()
            self._added_files.clear()
            self._deleted_files.clear()

        # Run sync in a background thread so we don't block the watcher
        t = threading.Thread(
            target=self._run_sync,
            args=(changed, added, deleted),
            daemon=True,
        )
        t.start()

    # ── Sync logic ─────────────────────────────────────────────────

    def _run_sync(
        self, changed: list[str], added: list[str], deleted: list[str],
    ) -> None:
        """Execute an incremental index sync (runs in background thread)."""
        self._state_store.mark_indexing()

        try:
            if not self._lock.acquire(timeout=10.0):
                print("Warning: Could not acquire index lock — sync skipped.")
                return

            try:
                result = run_incremental_index(
                    root_path=self.repo_root,
                    output_dir=self._cg_dir,
                    store=self._file_store,
                )
            finally:
                self._lock.release()

            # Update state
            now_iso = datetime.now(timezone.utc).isoformat()
            if result.status == "updated":
                self._state_store.update_status(
                    status="fresh",
                    last_incremental_at=now_iso,
                )
                cs = result.change_summary or {}
                cosmetic_skipped = cs.get("cosmetic", 0)
                if cosmetic_skipped > 0 or result.cosmetic_count > 0:
                    print(
                        f"Index updated: {result.structural_count} structural, "
                        f"{result.added_count} added, {result.deleted_count} deleted "
                        f"({cosmetic_skipped or result.cosmetic_count} cosmetic changes skipped)"
                    )
                else:
                    print(
                        f"Index updated: {result.changed_count} changed, "
                        f"{result.added_count} added, {result.deleted_count} deleted"
                    )
                if result.reparsed_files > 0:
                    print(
                        f"  ({result.reparsed_files} files re-parsed, "
                        f"{result.inserted_nodes_count} nodes, "
                        f"{result.inserted_edges_count} edges, "
                        f"{result.duration_ms:.0f}ms)"
                    )
                if result.recommend_full_rebuild:
                    print(
                        f"Note: {result.structural_count} structural files changed. "
                        f"Consider running 'codegraph init --force' for a full rebuild."
                    )
            elif result.status == "fresh":
                self._state_store.update_status(status="fresh")
            elif result.status == "missing":
                print("Warning: No index found. Run 'codegraph init' first.")

            self._state_store.clear_pending_changes()

            if self.on_sync:
                try:
                    self.on_sync(result)
                except Exception:
                    pass

        except Exception as exc:
            print(f"Error during incremental index: {exc}")
            self._state_store.update_status(
                status="error",
                last_error=str(exc),
            )
        finally:
            with self._lock_obj:
                self._indexing = False
                pending = self._pending
                self._pending = False

            # If more changes arrived during sync, run again
            if pending and self._running:
                with self._lock_obj:
                    if not self._indexing:
                        if self._changed_files or self._added_files or self._deleted_files:
                            self._indexing = True
                            changed2 = list(self._changed_files)
                            added2 = list(self._added_files)
                            deleted2 = list(self._deleted_files)
                            self._changed_files.clear()
                            self._added_files.clear()
                            self._deleted_files.clear()
                            t2 = threading.Thread(
                                target=self._run_sync,
                                args=(changed2, added2, deleted2),
                                daemon=True,
                            )
                            t2.start()

    # ── Watchdog observer ──────────────────────────────────────────

    def _try_start_watchdog(self) -> bool:
        """Try to start a watchdog observer. Returns True if successful."""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            return False

        root = str(self.repo_root)

        class _Handler(FileSystemEventHandler):
            def __init__(self, manager: WatchSyncManager) -> None:
                super().__init__()
                self._manager = manager

            def on_modified(self, event):
                if not event.is_directory:
                    self._manager.on_file_event(event.src_path, "modified")

            def on_created(self, event):
                if not event.is_directory:
                    self._manager.on_file_event(event.src_path, "created")

            def on_deleted(self, event):
                if not event.is_directory:
                    self._manager.on_file_event(event.src_path, "deleted")

            def on_moved(self, event):
                if not event.is_directory:
                    self._manager.on_file_event(event.src_path, "deleted")
                    self._manager.on_file_event(event.dest_path, "created")

        observer = Observer()
        observer.schedule(_Handler(self), root, recursive=True)
        observer.start()
        self._observer = observer
        return True

    # ── Polling fallback ───────────────────────────────────────────

    def _start_polling(self) -> None:
        """Start a polling thread that periodically checks file mtimes."""
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True,
        )
        self._poll_thread.start()

    def _poll_loop(self) -> None:
        """Polling loop — scan for changes at regular intervals."""
        # Build initial snapshot of mtimes
        prev_snapshot = self._scan_files()

        while self._running and not self._stop_event.is_set():
            self._stop_event.wait(self.poll_interval)
            if not self._running:
                break

            current = self._scan_files()
            self._compare_snapshots(prev_snapshot, current)
            prev_snapshot = current

    def _scan_files(self) -> dict[str, float]:
        """Scan watched files and return {rel_path: mtime}."""
        result: dict[str, float] = {}
        root = self.repo_root

        for glob_pattern in WATCH_GLOBS:
            for path in root.glob(glob_pattern):
                if not _should_watch_path(path, root):
                    continue
                try:
                    rel = str(path.relative_to(root))
                    result[rel] = path.stat().st_mtime
                except OSError:
                    pass

        return result

    def _compare_snapshots(
        self, prev: dict[str, float], current: dict[str, float],
    ) -> None:
        """Compare two file snapshots and emit events for differences."""
        prev_set = set(prev.keys())
        curr_set = set(current.keys())

        for path in sorted(curr_set - prev_set):
            self.on_file_event(path, "created")

        for path in sorted(prev_set - curr_set):
            self.on_file_event(path, "deleted")

        for path in sorted(curr_set & prev_set):
            if prev[path] != current[path]:
                self.on_file_event(path, "modified")

    # ── Internal helpers ───────────────────────────────────────────

    def _refresh_state_status(self) -> None:
        """Set initial state.json status based on current index freshness."""
        from codegraph.indexer.status import detect_status

        metadata = self._file_store.load_metadata()
        if metadata is None:
            self._state_store.update_status(status="missing")
            return

        result = detect_status(self.repo_root, metadata)
        self._state_store.update_status(
            status=result.status,
            last_indexed_at=result.indexed_at,
        )


# ── Standalone entry helpers ─────────────────────────────────────────────


def run_watch_loop(
    repo_root: str | Path,
    debounce_ms: int = 500,
    poll_interval: float = 2.0,
) -> None:
    """Run watch mode in the foreground (blocking). Prints status to stdout."""
    repo_path = Path(repo_root).resolve()
    print(f"Watching {repo_path}")

    cg_dir = repo_path / ".codegraph"
    state_store = IndexStateStore(cg_dir)
    current_state = state_store.load()
    print(f"Index status: {current_state['status']}")

    def _on_sync(result: IncrementalResult) -> None:
        if result.status == "updated":
            print(
                f"Index updated: {result.changed_count} changed, "
                f"{result.added_count} added, {result.deleted_count} deleted"
            )
        print(f"Status: fresh")

    manager = WatchSyncManager(
        repo_root=repo_path,
        debounce_ms=debounce_ms,
        poll_interval=poll_interval,
        on_sync=_on_sync,
    )

    manager.start()
    print("Watch started. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping watch...")
    finally:
        manager.stop()
