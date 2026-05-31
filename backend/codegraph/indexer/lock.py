"""Index lock to prevent concurrent writes to .codegraph.

Uses a lock file (.codegraph/index.lock) with PID tracking.
Detects stale locks from dead processes.
"""

import ctypes
import json
import os
import sys
import time
from pathlib import Path

STALE_LOCK_TIMEOUT_SECONDS = 300  # 5 minutes


def _pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is still running."""
    if sys.platform == "win32":
        try:
            handle = ctypes.windll.kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


class IndexLock:
    """File-based lock to prevent concurrent index writes.

    Usage as context manager::

        lock = IndexLock(cg_dir)
        if not lock.acquire():
            raise RuntimeError("Another index operation is in progress")
        try:
            # ... do work ...
        finally:
            lock.release()
    """

    def __init__(self, cg_dir: Path) -> None:
        cg_dir.mkdir(parents=True, exist_ok=True)
        self._path = cg_dir / "index.lock"
        self._held = False

    def acquire(self, timeout: float = 0.0) -> bool:
        """Try to acquire the lock.

        Returns True if the lock was acquired, False if another process holds it.
        If *timeout* > 0, blocks for up to *timeout* seconds.
        """
        deadline = time.monotonic() + timeout
        while True:
            if self._try_acquire():
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.1)

    def _try_acquire(self) -> bool:
        """Attempt to acquire the lock. Cleans up stale locks."""
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                pid = data.get("pid")
                created_at = data.get("created_at", 0)
                if pid and not _pid_alive(pid):
                    # Stale lock from dead process
                    self._path.unlink(missing_ok=True)
                elif time.time() - created_at > STALE_LOCK_TIMEOUT_SECONDS:
                    # Stale lock by timeout
                    self._path.unlink(missing_ok=True)
                else:
                    return False
            except (json.JSONDecodeError, OSError):
                self._path.unlink(missing_ok=True)

        # Create the lock file
        lock_data = {
            "pid": os.getpid(),
            "created_at": time.time(),
            "hostname": os.uname().nodename if hasattr(os, "uname") else "",
        }
        try:
            tmp = self._path.with_suffix(".lock_tmp")
            tmp.write_text(json.dumps(lock_data), encoding="utf-8")
            os.replace(tmp, self._path)
            self._held = True
            return True
        except OSError:
            return False

    def release(self) -> None:
        """Release the lock."""
        if self._held:
            self._path.unlink(missing_ok=True)
            self._held = False

    def is_locked(self) -> bool:
        """Check if the lock is held (by any process, including this one)."""
        if not self._path.exists():
            return False
        if self._held:
            return True
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            pid = data.get("pid")
            if pid and _pid_alive(pid):
                return True
        except (json.JSONDecodeError, OSError):
            pass
        return False

    def __enter__(self) -> "IndexLock":
        if not self.acquire():
            raise RuntimeError(
                "Failed to acquire index lock. Another index operation may be in progress."
            )
        return self

    def __exit__(self, *args: object) -> None:
        self.release()
