"""Git post-commit hook manager.

Provides ``HookManager``, a static class for installing, uninstalling,
and checking the status of CodeGraph's managed post-commit hook.
"""

import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

from codegraph.hooks.template import (
    SENTINEL_START,
    SENTINEL_END,
    build_unix_hook_script,
    build_windows_hook_script,
    _is_windows_without_sh,
)
from codegraph.storage.state_store import IndexStateStore

HOOK_NAME = "post-commit"


class HookManager:
    """Manage git post-commit hook for automatic incremental index updates.

    All methods are static.  Managed blocks are identified by sentinel comments
    (``# >>> codegraph hook >>>`` / ``# <<< codegraph hook <<<``) and are
    inserted/removed without disturbing user-written hook content.

    Usage::

        result = HookManager.install(project_root)
        result = HookManager.uninstall(project_root)
        status = HookManager.status(project_root)
    """

    # ── public API ───────────────────────────────────────────────────────

    @staticmethod
    def install(project_root: Path, force: bool = False) -> dict:
        """Install the managed post-commit hook.

        Creates ``.git/hooks/post-commit`` if it does not exist.
        Inserts or updates the CodeGraph managed block if the file exists.
        Sets executable permission on Unix.

        Args:
            project_root: Root of the git repository.
            force: If True, re-install even if already installed.

        Returns:
            Dict with keys: ``installed`` (bool), ``action`` (str),
            ``hook_path`` (str), ``message`` (str).
        """
        git_dir = HookManager._find_git_dir(project_root)
        if git_dir is None:
            return {
                "installed": False,
                "action": "skip",
                "hook_path": None,
                "message": f"No .git directory found in {project_root}",
            }

        hooks_dir = git_dir / "hooks"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        hook_path = hooks_dir / HOOK_NAME

        # Build the managed block
        managed_block = HookManager._build_managed_block(project_root)

        if hook_path.exists():
            existing = hook_path.read_text(encoding="utf-8")

            if SENTINEL_START in existing:
                if not force:
                    return {
                        "installed": True,
                        "action": "skip",
                        "hook_path": str(hook_path),
                        "message": "Hook already installed (managed block found)",
                    }
                else:
                    # Replace the existing managed block
                    new_content = HookManager._replace_managed_block(
                        existing, managed_block,
                    )
                    hook_path.write_text(new_content, encoding="utf-8")
                    action = "updated"
            else:
                # Append managed block to existing user hook
                if not existing.endswith("\n"):
                    existing += "\n"
                new_content = existing + "\n" + managed_block + "\n"
                hook_path.write_text(new_content, encoding="utf-8")
                action = "appended"
        else:
            # Create new hook file
            new_content = managed_block + "\n"
            hook_path.write_text(new_content, encoding="utf-8")
            action = "created"

        # Make executable on Unix
        if sys.platform != "win32":
            st = hook_path.stat()
            hook_path.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        # Update state
        now = datetime.now(timezone.utc).isoformat()
        state_store = IndexStateStore(project_root / ".codegraph")
        state_store.update_hook_config(
            installed=True,
            installed_at=now,
            hook_path=str(hook_path),
        )

        return {
            "installed": True,
            "action": action,
            "hook_path": str(hook_path),
            "message": f"Hook {action} at {hook_path}",
        }

    @staticmethod
    def uninstall(project_root: Path) -> dict:
        """Remove the managed post-commit hook.

        Deletes only the CodeGraph managed block.  If the remaining file
        is empty (or only contains a shebang), the entire hook file is
        deleted.  User-written hook content is preserved.

        Args:
            project_root: Root of the git repository.

        Returns:
            Dict with keys: ``uninstalled`` (bool), ``action`` (str),
            ``hook_path`` (str), ``message`` (str).
        """
        git_dir = HookManager._find_git_dir(project_root)
        if git_dir is None:
            return {
                "uninstalled": False,
                "action": "skip",
                "hook_path": None,
                "message": f"No .git directory found in {project_root}",
            }

        hook_path = git_dir / "hooks" / HOOK_NAME

        if not hook_path.exists():
            state_store = IndexStateStore(project_root / ".codegraph")
            state_store.update_hook_config(
                installed=False,
                hook_path=None,
            )
            return {
                "uninstalled": True,
                "action": "skip",
                "hook_path": None,
                "message": "Hook file does not exist — nothing to remove",
            }

        existing = hook_path.read_text(encoding="utf-8")

        if SENTINEL_START not in existing:
            state_store = IndexStateStore(project_root / ".codegraph")
            state_store.update_hook_config(
                installed=False,
                hook_path=None,
            )
            return {
                "uninstalled": True,
                "action": "skip",
                "hook_path": str(hook_path),
                "message": "No managed block found in hook — nothing to remove",
            }

        # Remove the managed block
        cleaned = HookManager._remove_managed_block(existing)

        # If only a shebang and whitespace remain, delete the file
        stripped = cleaned.strip()
        if not stripped or stripped.startswith("#!") and len(stripped.split("\n")) <= 1:
            hook_path.unlink()
            action = "deleted"
        else:
            hook_path.write_text(cleaned, encoding="utf-8")
            action = "cleaned"

        # Update state
        state_store = IndexStateStore(project_root / ".codegraph")
        state_store.update_hook_config(
            installed=False,
            hook_path=None,
        )

        return {
            "uninstalled": True,
            "action": action,
            "hook_path": str(hook_path) if action == "cleaned" else None,
            "message": f"Hook {action} at {hook_path}",
        }

    @staticmethod
    def status(project_root: Path) -> dict:
        """Check the current state of the post-commit hook.

        Args:
            project_root: Root of the git repository.

        Returns:
            Dict with keys: ``installed``, ``hook_path``, ``has_managed_block``,
            ``auto_update_on_commit``, ``last_run_at``, ``total_runs``,
            ``total_failures``, ``valid``, ``issues``.
        """
        state_store = IndexStateStore(project_root / ".codegraph")
        hook_config = state_store.get_hook_config()

        git_dir = HookManager._find_git_dir(project_root)
        hook_path = git_dir / "hooks" / HOOK_NAME if git_dir else None

        hook_exists = bool(hook_path and hook_path.exists())
        has_managed_block = False
        python_valid = False
        root_valid = False
        issues: list[str] = []

        if hook_exists:
            content = hook_path.read_text(encoding="utf-8")
            has_managed_block = SENTINEL_START in content

            if has_managed_block:
                # Check python path validity
                python_path = HookManager._extract_field(
                    content, "CODEGRAPH_PYTHON",
                )
                if python_path and Path(python_path).exists():
                    python_valid = True
                elif python_path:
                    issues.append(
                        f"Python path in hook does not exist: {python_path}",
                    )
                else:
                    issues.append("CODEGRAPH_PYTHON is missing from hook")

                # Check project root validity
                hook_root = HookManager._extract_field(
                    content, "CODEGRAPH_PROJECT_ROOT",
                )
                if hook_root and Path(hook_root).exists():
                    root_valid = True
                elif hook_root:
                    issues.append(
                        f"CODEGRAPH_PROJECT_ROOT in hook does not exist: {hook_root}",
                    )
                else:
                    issues.append("CODEGRAPH_PROJECT_ROOT is missing from hook")

        if not git_dir:
            issues.append("Not a git repository")

        if not has_managed_block and hook_config.get("auto_update_on_commit", True):
            issues.append(
                "auto_update_on_commit is enabled but hook is not installed. "
                "Run: codegraph hooks install",
            )

        valid = len(issues) == 0
        auto_update = hook_config.get("auto_update_on_commit", True)
        if not auto_update:
            state = "disabled"
        elif not has_managed_block:
            state = "missing"
        elif valid:
            state = "enabled"
        else:
            state = "invalid"

        return {
            "state": state,
            "installed": has_managed_block,
            "hook_path": str(hook_path) if hook_path else None,
            "hook_exists": hook_exists,
            "has_managed_block": has_managed_block,
            "auto_update_on_commit": hook_config.get(
                "auto_update_on_commit", True,
            ),
            "last_run_at": hook_config.get("last_run_at"),
            "total_runs": hook_config.get("total_runs", 0),
            "total_failures": hook_config.get("total_failures", 0),
            "valid": valid,
            "issues": issues,
        }

    # ── internal helpers ─────────────────────────────────────────────────

    @staticmethod
    def _find_git_dir(project_root: Path) -> Path | None:
        """Locate the ``.git`` directory, handling worktrees.

        In git worktrees ``.git`` is a file (not a directory) containing
        a ``gitdir: /path/to/real/.git`` line.

        Returns:
            Path to the real ``.git`` directory, or None.
        """
        git_path = project_root / ".git"
        if git_path.is_dir():
            return git_path
        if git_path.is_file():
            try:
                content = git_path.read_text(encoding="utf-8").strip()
                if content.startswith("gitdir: "):
                    real = content[len("gitdir: "):]
                    real_path = Path(real)
                    if not real_path.is_absolute():
                        real_path = (project_root / real_path).resolve()
                    return real_path if real_path.is_dir() else None
            except (OSError, UnicodeDecodeError):
                pass
        return None

    @staticmethod
    def _build_managed_block(project_root: Path) -> str:
        """Generate the hook script content for the managed block."""
        python_path = sys.executable

        if _is_windows_without_sh():
            return build_windows_hook_script(
                python_path, str(project_root.resolve()),
            )
        else:
            return build_unix_hook_script(
                python_path, str(project_root.resolve()),
            )

    @staticmethod
    def _replace_managed_block(existing: str, managed_block: str) -> str:
        """Replace the managed block portion within existing content."""
        before = existing[: existing.index(SENTINEL_START)]
        sentinel_end_pos = existing.index(SENTINEL_END)
        after = existing[sentinel_end_pos + len(SENTINEL_END):]

        # Find the end of the line containing SENTINEL_END
        newline_pos = after.find("\n")
        if newline_pos != -1:
            after = after[newline_pos + 1:]

        result = before.rstrip("\n") + "\n\n" + managed_block + "\n"
        if after.strip():
            result += "\n" + after.lstrip("\n")
        return result

    @staticmethod
    def _remove_managed_block(existing: str) -> str:
        """Remove the managed block from existing content."""
        start_pos = existing.index(SENTINEL_START)
        end_pos = existing.index(SENTINEL_END) + len(SENTINEL_END)

        # Extend to include the trailing newline
        if end_pos < len(existing) and existing[end_pos] == "\n":
            end_pos += 1

        before = existing[:start_pos]
        after = existing[end_pos:]

        # Clean up: remove trailing whitespace-only lines before the block
        before_lines = before.split("\n")
        while before_lines and before_lines[-1].strip() == "":
            before_lines.pop()
        before = "\n".join(before_lines)

        # Clean up: remove leading whitespace-only lines after the block
        after = after.lstrip("\n")

        if before and after:
            return before + "\n\n" + after
        return before + after

    @staticmethod
    def _extract_field(content: str, var_name: str) -> str | None:
        """Extract a shell variable value from hook content.

        Handles both bash syntax (``VAR="val"``) and batch syntax
        (``set "VAR=val"``).
        """
        import re

        # Bash: VAR="value"
        match = re.search(
            rf'{var_name}=["\']([^"\']*)["\']', content,
        )
        if match:
            return match.group(1)

        # Batch: set "VAR=value"
        match = re.search(
            rf'set\s+["\']{var_name}=([^"\']*)["\']', content,
        )
        if match:
            return match.group(1)

        return None
