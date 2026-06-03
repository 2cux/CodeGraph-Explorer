"""Hook script templates for git post-commit.

Generates hook script content with absolute Python path
and managed-block sentinels.
"""

import sys
from pathlib import Path

SENTINEL_START = "# >>> codegraph hook >>>"
SENTINEL_END = "# <<< codegraph hook <<<"
MANAGED_BLOCK_NOTE = " (managed block — do not edit manually)"


def _escape_path(path: str) -> str:
    """Shell-escape a path for use in a script.

    On Windows we use forward slashes which work in both bash and cmd.
    """
    return str(Path(path).as_posix())


def build_unix_hook_script(
    python_path: str,
    project_root: str,
) -> str:
    """Build a Unix (bash/sh) post-commit hook script.

    Works on Linux, macOS, and Windows Git Bash (MSYS2).

    Args:
        python_path: Absolute path to the Python executable.
        project_root: Absolute path to the project root directory.

    Returns:
        Complete hook script content.
    """
    py = _escape_path(python_path)
    root = _escape_path(project_root)

    return f"""#!/usr/bin/env bash
{SENTINEL_START}{MANAGED_BLOCK_NOTE}
CODEGRAPH_PYTHON="{py}"
CODEGRAPH_PROJECT_ROOT="{root}"
"$CODEGRAPH_PYTHON" -m codegraph.cli.main sync --incremental --quiet --trigger post-commit || true
{SENTINEL_END}
"""


def build_windows_hook_script(
    python_path: str,
    project_root: str,
) -> str:
    """Build a Windows batch (.cmd) post-commit hook script.

    Used as fallback when ``sh`` is not available on the system.

    Args:
        python_path: Absolute path to the Python executable.
        project_root: Absolute path to the project root directory.

    Returns:
        Complete hook script content.
    """
    py = _escape_path(python_path)
    root = _escape_path(project_root)

    return f"""@echo off
REM {SENTINEL_START}{MANAGED_BLOCK_NOTE}
set "CODEGRAPH_PYTHON={py}"
set "CODEGRAPH_PROJECT_ROOT={root}"
"%CODEGRAPH_PYTHON%" -m codegraph.cli.main sync --incremental --quiet --trigger post-commit 2>NUL
exit /b 0
REM {SENTINEL_END}
"""


def _is_windows_without_sh() -> bool:
    """Return True on Windows when sh.exe is not available."""
    import shutil

    if sys.platform != "win32":
        return False
    return shutil.which("sh") is None and shutil.which("bash") is None
