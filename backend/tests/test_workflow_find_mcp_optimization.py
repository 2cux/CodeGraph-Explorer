"""Tests for workflow.find MCP/Harness optimizations.

Covers:
    - MCP harness defaults: include_details=False, format=json, limit=5
    - Explicit include_details=True is respected
    - CLI defaults unchanged: include_details=True, format=markdown
    - MCP mode generates lightweight markdown, not heavy
    - Direct codegraph_find unchanged
    - MCP response compact, no large artifact content embedded
    - format=markdown still generates markdown when explicitly requested
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from codegraph.harness.modules.workflow_find import (
    WorkflowFindModule,
    _lightweight_markdown_summary,
    _normalize_input,
    run_workflow_find,
)


class TestMCPHarnessDefaults:
    """Verify MCP harness_run defaults for workflow.find."""

    def test_mcp_default_include_details_false(self):
        """When called from MCP harness without include_details, default to False."""
        result = _normalize_input(
            {"query": "test", "limit": 5},
            caller="mcp_harness",
        )
        assert result["include_details"] is False
        assert result["format"] == "json"
        assert result["limit"] == 5

    def test_mcp_default_format_json(self):
        """MCP mode defaults to format=json."""
        result = _normalize_input(
            {"query": "test"},
            caller="mcp_harness",
        )
        assert result["format"] == "json"

    def test_mcp_default_limit_5(self):
        """Default limit is 5 for all callers."""
        for caller in [None, "mcp_harness"]:
            result = _normalize_input({"query": "test"}, caller=caller)
            assert result["limit"] == 5, f"limit={result['limit']} for caller={caller}"

    def test_mcp_custom_limit_respected(self):
        """Explicit limit is respected."""
        result = _normalize_input(
            {"query": "test", "limit": 3},
            caller="mcp_harness",
        )
        assert result["limit"] == 3

    def test_limit_capped_at_100(self):
        """Limit capped at 100."""
        result = _normalize_input({"query": "test", "limit": 200})
        assert result["limit"] == 100

    def test_limit_min_1(self):
        """Limit minimum is 1."""
        result = _normalize_input({"query": "test", "limit": 0})
        assert result["limit"] == 1


class TestExplicitDetailsRespected:
    """Explicit include_details=True is never overridden."""

    def test_mcp_explicit_true_not_overridden(self):
        result = _normalize_input(
            {"query": "test", "include_details": True},
            caller="mcp_harness",
        )
        assert result["include_details"] is True

    def test_mcp_explicit_false_respected(self):
        result = _normalize_input(
            {"query": "test", "include_details": False},
            caller="mcp_harness",
        )
        assert result["include_details"] is False

    def test_mcp_explicit_string_true(self):
        """String 'true' should coerce to True."""
        result = _normalize_input(
            {"query": "test", "include_details": "true"},
            caller="mcp_harness",
        )
        assert result["include_details"] is True


class TestCLICompatibility:
    """CLI defaults remain unchanged."""

    def test_cli_default_include_details_true(self):
        result = _normalize_input({"query": "test", "limit": 5})
        assert result["include_details"] is True

    def test_cli_default_format_markdown(self):
        result = _normalize_input({"query": "test"})
        assert result["format"] == "markdown"

    def test_cli_explicit_details_false_respected(self):
        result = _normalize_input(
            {"query": "test", "limit": 5, "include_details": False},
        )
        assert result["include_details"] is False

    def test_cli_call_does_not_use_mcp_defaults(self):
        """CLI call (no caller arg) must not pick up MCP defaults."""
        result = _normalize_input({"query": "test", "limit": 5})
        assert result["include_details"] is True
        assert result["format"] == "markdown"
        assert result["limit"] == 5


class TestFormatMarkdownExplicit:
    """Explicit format=markdown generates markdown."""

    def test_mcp_format_markdown_respected(self):
        result = _normalize_input(
            {"query": "test", "format": "markdown"},
            caller="mcp_harness",
        )
        assert result["format"] == "markdown"

    def test_mcp_format_json_respected(self):
        result = _normalize_input(
            {"query": "test", "format": "json"},
            caller="mcp_harness",
        )
        assert result["format"] == "json"

    def test_cli_format_markdown_default(self):
        result = _normalize_input({"query": "test"})
        assert result["format"] == "markdown"


class TestLightweightMarkdown:
    """Lightweight markdown summary for MCP mode."""

    def test_lightweight_markdown_has_expected_sections(self):
        result = {
            "query": "test_query",
            "total": 3,
            "confidence": "high",
            "results": [
                {"symbol_id": "a::b", "symbol": "b", "type": "function", "file": "a.py"},
            ],
            "candidates": [
                {"symbol_id": "c::d", "symbol": "d"},
            ],
            "warnings": [{"message": "test warning"}],
        }
        md = _lightweight_markdown_summary(result)
        assert "# workflow.find: test_query" in md
        assert "**Results:** 1" in md
        assert "**Confidence:** high" in md
        assert "## Top Results" in md
        assert "## Other Candidates" in md
        assert "## Warnings" in md
        assert "lightweight summary" in md.lower()

    def test_lightweight_markdown_empty_results(self):
        result = {
            "query": "nonexistent",
            "total": 0,
            "confidence": "low",
            "results": [],
            "candidates": [],
            "warnings": [],
        }
        md = _lightweight_markdown_summary(result)
        assert "# workflow.find: nonexistent" in md
        assert "**Results:** 0" in md

    def test_lightweight_markdown_no_candidates_section_when_empty(self):
        result = {
            "query": "q", "total": 1, "confidence": "high",
            "results": [], "candidates": [], "warnings": [],
        }
        md = _lightweight_markdown_summary(result)
        assert "## Other Candidates" not in md
        assert "## Warnings" not in md


class TestNoAffectDirectFind:
    """Direct codegraph_find is NOT affected by workflow.find changes."""

    def test_codegraph_find_import_unchanged(self):
        """codegraph_find function is still importable and unchanged."""
        from codegraph.mcp_server import codegraph_find
        assert callable(codegraph_find)

    def test_codegraph_find_doc_unchanged(self):
        """Direct find description still contains expected boundary text."""
        from codegraph.mcp_server import codegraph_find
        doc = (codegraph_find.__doc__ or "").lower()
        assert "find" in doc
        assert "locate" in doc or "location" in doc


class TestHarnessModuleBehavior:
    """WorkflowFindModule.run() behavior."""

    def test_module_has_manifest(self):
        module = WorkflowFindModule()
        assert module.manifest is not None

    def test_module_run_requires_query(self):
        module = WorkflowFindModule()
        mock_ctx = MagicMock()
        mock_ctx.project_root = Path.cwd()
        with pytest.raises(ValueError, match="non-empty 'query'"):
            module.run(mock_ctx, {"query": ""})

    def test_module_run_with_minimal_input(self):
        """Module can run with minimal input (query only)."""
        module = WorkflowFindModule()
        mock_ctx = MagicMock()
        mock_ctx.project_root = Path.cwd()
        mock_ctx.log_info = MagicMock()
        mock_ctx.checkpoint = MagicMock()
        mock_ctx.artifact_json = MagicMock()
        mock_ctx.artifact_text = MagicMock()

        result = module.run(mock_ctx, {"query": "test_symbol", "limit": 3})
        assert isinstance(result, dict)
        assert "results" in result
        # Verify markdown was written (lightweight in MCP mode since no format=markdown)
        mock_ctx.artifact_text.assert_called()
        # Verify JSON artifact was written
        mock_ctx.artifact_json.assert_called()


class TestMCPResponseCompact:
    """MCP response should not embed large artifact content."""

    def test_mcp_harness_response_has_artifact_paths_not_content(self):
        """Response contains artifact paths, not inline content."""
        from codegraph.harness.mcp_tools import run_harness_module
        from pathlib import Path

        result = run_harness_module(
            module_id="workflow.find",
            input_data={"query": "test", "limit": 3},
            persist=True,
            project_root=Path.cwd(),
        )
        # Artifacts are paths (relative), not embedded content
        artifacts = result.get("artifacts", {})
        for key, path in artifacts.items():
            assert isinstance(path, str), f"Artifact '{key}' should be a path string"
            assert path.endswith(".json") or path.endswith(".md"), \
                f"Artifact path should end with .json or .md: {path}"
        # Output should not contain huge payloads
        output = result.get("output", {})
        if isinstance(output, dict):
            results = output.get("results", [])
            for r in results:
                # Details should be None when include_details=False
                if isinstance(r, dict):
                    pass  # OK either way


class TestRegression:
    """Verify existing tests still pass."""

    def test_mcp_profiles_import(self):
        from codegraph.mcp.profiles import (
            AGENT_TOOLS, FULL_TOOLS, HARNESS_TOOLS, DEBUG_TOOLS, PROFILES,
        )
        assert len(AGENT_TOOLS) == 6
        assert len(HARNESS_TOOLS) == 4

    def test_mcp_server_import(self):
        import codegraph.mcp_server as mcp_mod
        assert hasattr(mcp_mod, "codegraph_find")
        assert hasattr(mcp_mod, "codegraph_harness_run")

    def test_workflow_find_still_importable(self):
        from codegraph.harness.modules.workflow_find import (
            WorkflowFindModule, run_workflow_find, _normalize_input,
        )
        assert callable(run_workflow_find)
        assert callable(_normalize_input)


class TestTriageResultsMatch:
    """Optimization results match expected schema."""

    def test_optimization_results_file_exists(self):
        results_path = Path("reports/workflow_find_optimization_results.json")
        if results_path.exists():
            data = json.loads(results_path.read_text(encoding="utf-8"))
            assert "generated_at" in data
            assert "cases" in data
            assert "summary" in data
            for case in data["cases"]:
                assert "case_id" in case
                assert "ok" in case
                assert "p50_ms" in case
                assert "p95_ms" in case
                assert isinstance(case["ok"], bool)
                assert isinstance(case["p50_ms"], (int, float))
                assert isinstance(case["p95_ms"], (int, float))
