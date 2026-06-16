"""MCP Tool Profiles — control which tools are exposed based on user profile.

Profiles:
    agent — High-level task entry tools for coding agents.
    full  — All stable tools (agent + primitive search/graph tools).
    debug — All stable tools + harness/debug introspection tools.

Usage:
    Set ``CODEGRAPH_MCP_PROFILE`` to one of ``agent``, ``full``, or ``debug``.
    Unknown values fall back to ``agent`` with a clear log warning.

Design:
    Profiles are defined declaratively as sets of tool names.  The module
    provides a single entry point ``apply_profile(mcp, profile_name)`` that
    removes tools from the FastMCP instance which are not in the profile.

    No tools or underlying implementations are deleted — only the MCP surface
    exposed to the client changes.
"""

from __future__ import annotations

import os
import sys
from typing import Set

# ── Profile tool sets ─────────────────────────────────────────────────────

# Agent profile: high-level task entry tools only.
# Reserved / unsafe / harness / debug tools are excluded.
AGENT_TOOLS: Set[str] = {
    "codegraph_repo_status",
    "codegraph_find",
    "codegraph_explain",
    "codegraph_pre_edit_check",
    "codegraph_coverage_gaps",
    "codegraph_build_context_pack",
}

# Full profile: agent tools + stable primitive search & graph tools.
# Excludes harness/debug tools.
FULL_TOOLS: Set[str] = (
    AGENT_TOOLS
    | {
        "codegraph_repo_summary",
        "codegraph_search_symbols",
        "codegraph_get_symbol",
        "codegraph_get_callers",
        "codegraph_get_callees",
        "codegraph_get_neighbors",
        "codegraph_get_impact",
    }
)

# Debug profile: full tools + harness/debug introspection tools.
DEBUG_TOOLS: Set[str] = (
    FULL_TOOLS
    | {
        "codegraph_harness_list",
        "codegraph_harness_run",
        "codegraph_harness_status",
        "codegraph_harness_artifacts",
    }
)

# ── Profile registry ──────────────────────────────────────────────────────

PROFILES: dict[str, dict[str, object]] = {
    "agent": {
        "description": (
            "Default minimal MCP surface for coding agents."
        ),
        "tools": AGENT_TOOLS,
        "policy": "High-level task tools only. No harness/debug primitives.",
    },
    "full": {
        "description": (
            "Advanced user profile with stable high-level and primitive tools."
        ),
        "tools": FULL_TOOLS,
        "policy": "Stable tools only; excludes harness debug tools by default.",
    },
    "debug": {
        "description": (
            "Developer/debug profile with stable tools and harness introspection."
        ),
        "tools": DEBUG_TOOLS,
        "policy": (
            "Includes harness tools; still excludes unsafe/reserved modules."
        ),
    },
}

VALID_PROFILES = frozenset(PROFILES.keys())
DEFAULT_PROFILE = "agent"
UNKNOWN_FALLBACK_PROFILE = "agent"


# ── Public API ────────────────────────────────────────────────────────────


def get_active_profile() -> str:
    """Read ``CODEGRAPH_MCP_PROFILE`` and return the canonical profile name.

    Returns:
        One of ``"agent"``, ``"full"``, ``"debug"``.

    Unknown profile values trigger a warning on stderr and fall back to
    ``"agent"`` so the server stays usable.
    """
    raw = os.environ.get("CODEGRAPH_MCP_PROFILE", "").strip().lower()

    if not raw:
        return DEFAULT_PROFILE

    if raw in VALID_PROFILES:
        return raw

    # Unknown profile → warn and fall back to agent.
    print(
        f"[codegraph] Unknown CODEGRAPH_MCP_PROFILE='{raw}'. "
        f"Valid values: {', '.join(sorted(VALID_PROFILES))}. "
        f"Falling back to '{UNKNOWN_FALLBACK_PROFILE}' profile.",
        file=sys.stderr,
    )
    return UNKNOWN_FALLBACK_PROFILE


def get_allowed_tools(profile: str) -> Set[str]:
    """Return the set of tool names allowed for *profile*.

    Unknown *profile* values return the agent set (same fallback as
    ``get_active_profile``).
    """
    entry = PROFILES.get(profile)
    if entry is None:
        entry = PROFILES[UNKNOWN_FALLBACK_PROFILE]
    tools = entry["tools"]
    assert isinstance(tools, set)
    return tools


def get_profile_info(profile: str) -> dict[str, object]:
    """Return the profile metadata dict for *profile*.

    Unknown *profile* values return the agent profile info.
    """
    return PROFILES.get(profile, PROFILES[UNKNOWN_FALLBACK_PROFILE])


def apply_profile(mcp_instance: object, profile: str) -> list[str]:
    """Remove tools from *mcp_instance* that are not in *profile*.

    Uses FastMCP's ``remove_tool`` method so no tool implementations are
    deleted — only the MCP surface changes.

    Args:
        mcp_instance: A ``FastMCP`` instance (e.g. the module-level ``mcp``).
        profile: One of ``"agent"``, ``"full"``, ``"debug"``.

    Returns:
        List of tool names that were *removed* (for logging / test assertions).
    """
    allowed = get_allowed_tools(profile)
    removed: list[str] = []

    # FastMCP stores tools in _tool_manager._tools (dict name → Tool).
    tool_manager = getattr(mcp_instance, "_tool_manager", None)
    if tool_manager is None:
        return removed

    all_tools: dict[str, object] = getattr(tool_manager, "_tools", {})
    # Snapshot keys so we can mutate during iteration.
    for tool_name in list(all_tools.keys()):
        if tool_name not in allowed:
            try:
                tool_manager.remove_tool(tool_name)
                removed.append(tool_name)
            except Exception:
                # If removal fails, keep the tool exposed (safe default).
                pass

    return removed


def log_profile(profile: str) -> None:
    """Print the active profile to stderr for diagnostics."""
    info = get_profile_info(profile)
    tools = info["tools"]
    assert isinstance(tools, set)
    print(
        f"[codegraph] MCP profile: {profile} "
        f"({len(tools)} tools) — {info['description']}",
        file=sys.stderr,
    )
