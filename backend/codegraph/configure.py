"""MCP configuration management for Claude Code and Cursor editors.

Provides idempotent read/write of MCP server config entries so that
``codegraph configure`` can register the MCP server in the user's
editor config files without manual JSON editing.
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Any

MCP_SERVER_NAME = "codegraph"

CLAUDE_USER_CONFIG = Path.home() / ".claude.json"
CLAUDE_PROJECT_CONFIG_REL = Path(".mcp.json")
CURSOR_USER_CONFIG = Path.home() / ".cursor" / "mcp.json"
CURSOR_PROJECT_CONFIG_REL = Path(".cursor") / "mcp.json"


class ConfigTarget(Enum):
    CLAUDE = "claude"
    CURSOR = "cursor"


def build_server_config(
    root: str | None = None,
    python_command: str | None = None,
) -> dict[str, Any]:
    """Build a single MCP server config entry for codegraph.

    Args:
        root: If set, adds ``env.CODEGRAPH_PROJECT_ROOT`` to the config.
        python_command: Override the Python interpreter path.

    Returns:
        A dict with ``command``, ``args``, and optionally ``env``.
    """
    entry: dict[str, Any] = {
        "command": python_command or sys.executable,
        "args": ["-m", "codegraph.mcp_server"],
    }
    if root:
        entry["env"] = {"CODEGRAPH_PROJECT_ROOT": root}
    return entry


def read_config(filepath: Path) -> dict[str, Any]:
    """Read an MCP config JSON file.

    Always returns a dict that contains at least the ``"mcpServers"`` key.
    Missing files, empty files, and invalid JSON are all treated as an
    empty configuration.
    """
    if not filepath.exists():
        return {"mcpServers": {}}
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return {"mcpServers": {}}
    if not isinstance(data, dict):
        return {"mcpServers": {}}
    if "mcpServers" not in data:
        data["mcpServers"] = {}
    return data


def write_config(filepath: Path, data: dict[str, Any]) -> None:
    """Write an MCP config JSON file, creating parent directories as needed."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _resolve_filepath(target: ConfigTarget, *, project: bool) -> Path:
    """Return the config file path for a given target and scope."""
    if target == ConfigTarget.CLAUDE:
        return Path.cwd() / CLAUDE_PROJECT_CONFIG_REL if project else CLAUDE_USER_CONFIG
    else:
        return Path.cwd() / CURSOR_PROJECT_CONFIG_REL if project else CURSOR_USER_CONFIG


def configure_target(
    target: ConfigTarget,
    *,
    root: str | None = None,
    python_command: str | None = None,
    project: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Write the codegraph MCP server entry for a target editor.

    Idempotent by default — if a ``"codegraph"`` entry already exists the
    function returns ``"already_configured"`` without writing.  Pass
    ``force=True`` to overwrite.

    Returns:
        A result dict with keys ``status``, ``target``, ``filepath``,
        ``project``, and ``config``.
    """
    filepath = _resolve_filepath(target, project=project)
    data = read_config(filepath)
    existing = data["mcpServers"].get(MCP_SERVER_NAME)

    if existing and not force:
        return {
            "status": "already_configured",
            "target": target.value,
            "filepath": str(filepath),
            "project": project,
            "config": existing,
        }

    server_config = build_server_config(root=root, python_command=python_command)
    data["mcpServers"][MCP_SERVER_NAME] = server_config
    write_config(filepath, data)

    return {
        "status": "overwritten" if existing else "configured",
        "target": target.value,
        "filepath": str(filepath),
        "project": project,
        "config": server_config,
    }


def remove_target(
    target: ConfigTarget,
    *,
    project: bool = False,
) -> dict[str, Any]:
    """Remove the codegraph MCP server entry for a target editor.

    Returns:
        A result dict with keys ``status``, ``target``, ``filepath``, and
        ``project``.
    """
    filepath = _resolve_filepath(target, project=project)
    data = read_config(filepath)

    if MCP_SERVER_NAME not in data["mcpServers"]:
        return {
            "status": "not_configured",
            "target": target.value,
            "filepath": str(filepath),
            "project": project,
        }

    del data["mcpServers"][MCP_SERVER_NAME]
    write_config(filepath, data)

    return {
        "status": "removed",
        "target": target.value,
        "filepath": str(filepath),
        "project": project,
    }


def show_status(*, project: bool = False) -> dict[str, Any]:
    """Return the current MCP configuration status for all targets.

    Returns:
        A dict keyed by target name (``"claude"``, ``"cursor"``), each
        value containing ``configured``, ``filepath``, and ``config``.
    """
    result: dict[str, Any] = {}
    for target in ConfigTarget:
        fp = _resolve_filepath(target, project=project)
        data = read_config(fp)
        entry = data["mcpServers"].get(MCP_SERVER_NAME)
        result[target.value] = {
            "configured": entry is not None,
            "filepath": str(fp),
            "config": entry,
        }
    return result
