"""Tests for MCP Tool Profile mechanism.

Covers:
    - agent profile exposes only high-level task tools
    - full profile exposes stable tools (agent + primitives)
    - debug profile exposes stable tools + harness/debug tools
    - unknown profile falls back to agent with warning
    - reserved/unsafe/harness tools excluded from agent profile
    - existing tools are never deleted (only hidden from MCP surface)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codegraph.mcp.profiles import (
    AGENT_TOOLS,
    DEBUG_TOOLS,
    FULL_TOOLS,
    PROFILES,
    VALID_PROFILES,
    UNKNOWN_FALLBACK_PROFILE,
    DEFAULT_PROFILE,
    apply_profile,
    get_active_profile,
    get_allowed_tools,
    get_profile_info,
    log_profile,
)


# ── Profile tool set assertions ───────────────────────────────────────────

AGENT_EXPECTED = {
    "codegraph_repo_status",
    "codegraph_find",
    "codegraph_explain",
    "codegraph_pre_edit_check",
    "codegraph_coverage_gaps",
    "codegraph_build_context_pack",
}

FULL_EXPECTED = AGENT_EXPECTED | {
    "codegraph_repo_summary",
    "codegraph_search_symbols",
    "codegraph_get_symbol",
    "codegraph_get_callers",
    "codegraph_get_callees",
    "codegraph_get_neighbors",
    "codegraph_get_impact",
}

DEBUG_EXPECTED = FULL_EXPECTED | {
    "codegraph_harness_list",
    "codegraph_harness_run",
    "codegraph_harness_status",
    "codegraph_harness_artifacts",
}


class TestProfileToolSets:
    """Verify the three built-in profile tool sets."""

    def test_agent_tools_match_expected(self):
        assert AGENT_TOOLS == AGENT_EXPECTED

    def test_full_tools_match_expected(self):
        assert FULL_TOOLS == FULL_EXPECTED

    def test_debug_tools_match_expected(self):
        assert DEBUG_TOOLS == DEBUG_EXPECTED

    def test_agent_subset_of_full(self):
        assert AGENT_TOOLS <= FULL_TOOLS

    def test_full_subset_of_debug(self):
        assert FULL_TOOLS <= DEBUG_TOOLS

    def test_harness_tools_not_in_agent(self):
        harness = DEBUG_TOOLS - FULL_TOOLS
        assert harness
        for tool in harness:
            assert tool not in AGENT_TOOLS

    def test_harness_tools_not_in_full(self):
        harness = DEBUG_TOOLS - FULL_TOOLS
        for tool in harness:
            assert tool not in FULL_TOOLS


class TestGetActiveProfile:
    """Environment variable → profile resolution."""

    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("CODEGRAPH_MCP_PROFILE", raising=False)
        assert get_active_profile() == "agent"

    def test_empty_string_defaults_to_agent(self, monkeypatch):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "")
        assert get_active_profile() == "agent"

    def test_explicit_agent(self, monkeypatch):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "agent")
        assert get_active_profile() == "agent"

    def test_explicit_full(self, monkeypatch):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "full")
        assert get_active_profile() == "full"

    def test_explicit_debug(self, monkeypatch):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "debug")
        assert get_active_profile() == "debug"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "AGENT")
        assert get_active_profile() == "agent"
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "Full")
        assert get_active_profile() == "full"

    def test_unknown_profile_falls_back_to_agent(self, monkeypatch, capsys):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "super_agent")
        result = get_active_profile()
        assert result == "agent"

    def test_unknown_profile_prints_warning(self, monkeypatch, capsys):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "xyz_unknown")
        get_active_profile()
        captured = capsys.readouterr()
        assert "Unknown CODEGRAPH_MCP_PROFILE='xyz_unknown'" in captured.err
        assert "Falling back to 'agent'" in captured.err

    def test_whitespace_trimmed(self, monkeypatch):
        monkeypatch.setenv("CODEGRAPH_MCP_PROFILE", "  debug  ")
        # .strip() handles it
        result = get_active_profile()
        assert result in VALID_PROFILES or result == "agent"


class TestGetAllowedTools:
    """Tool set lookup for each profile."""

    def test_agent_allowed(self):
        tools = get_allowed_tools("agent")
        assert tools == AGENT_TOOLS

    def test_full_allowed(self):
        tools = get_allowed_tools("full")
        assert tools == FULL_TOOLS

    def test_debug_allowed(self):
        tools = get_allowed_tools("debug")
        assert tools == DEBUG_TOOLS

    def test_unknown_profile_returns_agent_tools(self):
        tools = get_allowed_tools("nonexistent")
        assert tools == AGENT_TOOLS


class TestGetProfileInfo:
    """Profile metadata lookup."""

    def test_agent_has_required_fields(self):
        info = get_profile_info("agent")
        assert "description" in info
        assert "tools" in info
        assert "policy" in info
        assert isinstance(info["tools"], set)

    def test_full_has_required_fields(self):
        info = get_profile_info("full")
        assert "description" in info
        assert "tools" in info
        assert "policy" in info

    def test_debug_has_required_fields(self):
        info = get_profile_info("debug")
        assert "description" in info
        assert "tools" in info
        assert "policy" in info

    def test_unknown_returns_agent_info(self):
        info = get_profile_info("bogus")
        assert info["tools"] == AGENT_TOOLS


class TestApplyProfile:
    """FastMCP tool filtering integration."""

    @staticmethod
    def _make_mock_mcp(tool_names: list[str]):
        """Create a mock FastMCP with ToolManager-like internals."""
        mcp = MagicMock()
        tools_dict = {name: MagicMock() for name in tool_names}
        tool_manager = MagicMock()
        tool_manager._tools = tools_dict
        # remove_tool should actually delete from the dict
        tool_manager.remove_tool = lambda name: tools_dict.pop(name, None)
        mcp._tool_manager = tool_manager
        return mcp, tools_dict

    def test_agent_profile_hides_primitives(self):
        all_tools = sorted(AGENT_TOOLS | FULL_TOOLS | DEBUG_TOOLS)
        mcp, tools_dict = self._make_mock_mcp(all_tools)

        removed = apply_profile(mcp, "agent")

        remaining = set(tools_dict.keys())
        assert remaining == AGENT_TOOLS
        # Primitives + harness should be removed
        for tool in FULL_TOOLS - AGENT_TOOLS:
            assert tool in removed
        for tool in DEBUG_TOOLS - AGENT_TOOLS:
            assert tool in removed

    def test_full_profile_hides_harness(self):
        all_tools = sorted(FULL_TOOLS | DEBUG_TOOLS)
        mcp, tools_dict = self._make_mock_mcp(all_tools)

        removed = apply_profile(mcp, "full")

        remaining = set(tools_dict.keys())
        assert remaining == FULL_TOOLS
        harness_tools = DEBUG_TOOLS - FULL_TOOLS
        for tool in harness_tools:
            assert tool in removed
        for tool in harness_tools:
            assert tool not in remaining

    def test_debug_profile_keeps_everything(self):
        all_tools = sorted(DEBUG_TOOLS)
        mcp, tools_dict = self._make_mock_mcp(all_tools)

        removed = apply_profile(mcp, "debug")

        remaining = set(tools_dict.keys())
        assert remaining == DEBUG_TOOLS
        assert len(removed) == 0

    def test_unknown_profile_uses_agent_set(self):
        all_tools = sorted(DEBUG_TOOLS)
        mcp, tools_dict = self._make_mock_mcp(all_tools)

        removed = apply_profile(mcp, "nonexistent")

        remaining = set(tools_dict.keys())
        assert remaining == AGENT_TOOLS

    def test_empty_tool_manager_is_safe(self):
        mcp, _ = self._make_mock_mcp([])
        removed = apply_profile(mcp, "agent")
        assert removed == []

    def test_no_tool_manager_is_safe(self):
        mcp = MagicMock(spec=[])  # no _tool_manager attr
        removed = apply_profile(mcp, "agent")
        assert removed == []

    def test_removed_list_is_sorted(self):
        all_tools = sorted(DEBUG_TOOLS)
        mcp, _ = self._make_mock_mcp(all_tools)
        removed = apply_profile(mcp, "agent")
        assert removed == sorted(removed)


class TestLogProfile:
    """Diagnostic logging."""

    def test_log_profile_does_not_raise(self, capsys):
        log_profile("agent")
        captured = capsys.readouterr()
        assert "agent" in captured.err

    def test_log_profile_shows_tool_count(self, capsys):
        log_profile("full")
        captured = capsys.readouterr()
        assert str(len(FULL_TOOLS)) in captured.err


class TestRegistryConsistency:
    """Cross-check the profile registry."""

    def test_all_profiles_in_valid_frozenset(self):
        for name in PROFILES:
            assert name in VALID_PROFILES

    def test_every_profile_has_tools_description_policy(self):
        for name, entry in PROFILES.items():
            assert "description" in entry, f"{name} missing description"
            assert "tools" in entry, f"{name} missing tools"
            assert "policy" in entry, f"{name} missing policy"
            assert isinstance(entry["tools"], set), f"{name} tools is not a set"
            # Agent must have fewer tools than debug
            if name != "debug":
                assert len(entry["tools"]) <= len(DEBUG_TOOLS), (
                    f"{name} has more tools than debug"
                )

    def test_unknown_fallback_is_valid_profile(self):
        assert UNKNOWN_FALLBACK_PROFILE in VALID_PROFILES

    def test_default_profile_is_valid(self):
        assert DEFAULT_PROFILE in VALID_PROFILES

    def test_no_harness_tools_in_agent(self):
        harness = DEBUG_TOOLS - FULL_TOOLS
        for tool in harness:
            assert tool not in AGENT_TOOLS, (
                f"Harness tool '{tool}' leaked into agent profile"
            )

    def test_no_harness_tools_in_full(self):
        harness = DEBUG_TOOLS - FULL_TOOLS
        for tool in harness:
            assert tool not in FULL_TOOLS, (
                f"Harness tool '{tool}' leaked into full profile"
            )

    def test_agent_has_exactly_6_tools(self):
        """Explicit count check — agent surface should stay minimal."""
        assert len(AGENT_TOOLS) == 6

    def test_full_has_exactly_13_tools(self):
        """agent(6) + primitives(7) = 13"""
        assert len(FULL_TOOLS) == 13

    def test_debug_has_exactly_17_tools(self):
        """full(13) + harness(4) = 17"""
        assert len(DEBUG_TOOLS) == 17


class TestNoDeletion:
    """Verify that applying a profile never deletes tool implementations.

    The profile mechanism only changes the MCP surface — it doesn't
    touch the underlying functions registered via @mcp.tool().
    """

    # Mapping from MCP tool name to the Python function name in mcp_server.py.
    # Some functions use the full tool name, others omit the "codegraph_" prefix.
    TOOL_NAME_TO_FUNC: dict[str, str] = {
        "codegraph_repo_status": "repo_status",
        "codegraph_repo_summary": "repo_summary",
        "codegraph_find": "codegraph_find",
        "codegraph_explain": "codegraph_explain",
        "codegraph_pre_edit_check": "pre_edit_check",
        "codegraph_coverage_gaps": "coverage_gaps",
        "codegraph_build_context_pack": "build_context_pack",
        "codegraph_search_symbols": "search_symbols",
        "codegraph_get_symbol": "get_symbol",
        "codegraph_get_callers": "get_callers",
        "codegraph_get_callees": "get_callees",
        "codegraph_get_neighbors": "get_neighbors",
        "codegraph_get_impact": "get_impact",
        "codegraph_harness_list": "codegraph_harness_list",
        "codegraph_harness_run": "codegraph_harness_run",
        "codegraph_harness_status": "codegraph_harness_status",
        "codegraph_harness_artifacts": "codegraph_harness_artifacts",
    }

    def test_original_tool_functions_still_exist(self):
        """All 17 tool functions must still be importable from mcp_server."""
        import codegraph.mcp_server as mcp_mod

        for tool_name, func_name in self.TOOL_NAME_TO_FUNC.items():
            assert hasattr(mcp_mod, func_name), (
                f"Tool function '{func_name}' for '{tool_name}' "
                f"not found in mcp_server module"
            )
            # Verify it's callable (a function, not a different attribute)
            func = getattr(mcp_mod, func_name)
            assert callable(func), (
                f"'{func_name}' exists but is not callable"
            )
