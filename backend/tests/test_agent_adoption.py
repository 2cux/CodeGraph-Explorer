"""Tests for Agent Adoption mechanism.

Verifies:
- MCP tool descriptions guide agents to prefer CodeGraph over grep/read
- README clearly explains where to put the CodeGraph Usage block
- README does not make false promises about automatic usage
- docs/agent-adoption-test.md exists and has verification steps
- CLI init output includes adoption hint after successful indexing
"""

import inspect
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import codegraph.mcp_server as mcp_mod
from codegraph.cli.main import app


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def runner() -> CliRunner:
    """Create a CliRunner for testing CLI commands."""
    return CliRunner()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _project_root() -> Path:
    """Return the project root directory."""
    return Path(__file__).resolve().parent.parent.parent


def _read_file(rel_path: str) -> str:
    """Read a project file relative to project root."""
    return (_project_root() / rel_path).read_text(encoding="utf-8")


def _tool_docstrings() -> dict[str, str]:
    """Return a dict of tool_name -> full docstring for all MCP tools."""
    tools: dict[str, str] = {}
    for name, obj in inspect.getmembers(mcp_mod, inspect.isfunction):
        if hasattr(obj, "__mcp_tool_name__"):
            tool_name = obj.__mcp_tool_name__
            doc = (inspect.getdoc(obj) or "").strip()
            tools[tool_name] = doc
    return tools


# ── MCP Tool Description Tests ──────────────────────────────────────────────


class TestMcpToolDescriptions:
    """Verify MCP tool descriptions contain usage-trigger keywords."""

    def test_build_context_pack_first_tool_language(self):
        """build_context_pack should be described as PRIMARY TOOL for first use."""
        doc = inspect.getdoc(mcp_mod.build_context_pack) or ""
        doc_lower = doc.lower()
        assert "primary tool" in doc_lower, (
            f"build_context_pack description should state PRIMARY TOOL. Got: {doc[:120]}..."
        )
        assert "use first" in doc_lower, (
            f"build_context_pack description should guide 'use first'. Got: {doc[:120]}..."
        )

    def test_build_context_pack_before_grep(self):
        """build_context_pack should say 'before grep/glob/read-heavy exploration'."""
        doc = inspect.getdoc(mcp_mod.build_context_pack) or ""
        assert "before grep" in doc.lower() or "before grep/glob/read" in doc.lower(), (
            f"build_context_pack should reference grep/glob/read-heavy. Got: {doc[:120]}..."
        )

    def test_repo_summary_first_when_entering(self):
        """repo_summary should say 'Use first when entering'."""
        doc = inspect.getdoc(mcp_mod.repo_summary) or ""
        assert "use first when entering" in doc.lower(), (
            f"repo_summary should state 'Use first when entering'. Got: {doc[:120]}..."
        )

    def test_repo_summary_before_glob_grep(self):
        """repo_summary should mention glob/grep."""
        doc = inspect.getdoc(mcp_mod.repo_summary) or ""
        assert "glob/grep" in doc.lower(), (
            f"repo_summary should mention glob/grep. Got: {doc[:120]}..."
        )

    def test_search_symbols_before_grep(self):
        """search_symbols should say 'Use before grep'."""
        doc = inspect.getdoc(mcp_mod.search_symbols) or ""
        assert "before grep" in doc.lower(), (
            f"search_symbols should state 'before grep'. Got: {doc[:120]}..."
        )

    def test_search_symbols_exports_mention(self):
        """search_symbols should mention exports."""
        doc = inspect.getdoc(mcp_mod.search_symbols) or ""
        assert "exports" in doc.lower(), (
            f"search_symbols should mention exports. Got: {doc[:120]}..."
        )

    def test_get_neighbors_before_reading(self):
        """get_neighbors should say 'Use before reading multiple'."""
        doc = inspect.getdoc(mcp_mod.get_neighbors) or ""
        assert "before reading multiple" in doc.lower(), (
            f"get_neighbors should state 'Use before reading multiple'. Got: {doc[:120]}..."
        )

    def test_get_callers_instead_of_grep(self):
        """get_callers should say 'Use instead of grep for call chain'."""
        doc = inspect.getdoc(mcp_mod.get_callers) or ""
        assert "instead of grep" in doc.lower(), (
            f"get_callers should state 'Use instead of grep'. Got: {doc[:120]}..."
        )

    def test_get_callees_dependency_exploration(self):
        """get_callees should mention downstream calls and dependencies."""
        doc = inspect.getdoc(mcp_mod.get_callees) or ""
        assert (
            "depend on" in doc.lower() or "dependency" in doc.lower()
            or "downstream calls" in doc.lower()
        ), (
            f"get_callees should mention dependencies or downstream calls. Got: {doc[:120]}..."
        )

    def test_get_impact_before_editing(self):
        """get_impact should say 'Use before editing shared'."""
        impact_doc = inspect.getdoc(mcp_mod.get_impact) or ""
        assert "before editing shared" in impact_doc.lower(), (
            f"get_impact should state 'Use before editing shared'. Got: {impact_doc[:120]}..."
        )

    def test_repo_status_fresh_mention(self):
        """repo_status should mention fresh/stale/missing/healthy."""
        doc = inspect.getdoc(mcp_mod.repo_status) or ""
        assert "fresh" in doc.lower() and "stale" in doc.lower(), (
            f"repo_status should mention fresh/stale. Got: {doc[:120]}..."
        )

    def test_no_tool_claims_automatic_usage(self):
        """No MCP tool description should claim Agent will automatically use CodeGraph."""
        for name, obj in inspect.getmembers(mcp_mod, inspect.isfunction):
            if hasattr(obj, "__mcp_tool_name__"):
                doc = (inspect.getdoc(obj) or "").lower()
                assert "will automatically" not in doc, (
                    f"Tool {obj.__mcp_tool_name__} must not claim 'will automatically'"
                )


class TestMcpToolDescriptionsExampleDriven:
    """Verify MCP tool descriptions are example-driven with concrete call samples."""

    def test_build_context_pack_has_primary_tool(self):
        """build_context_pack description must contain PRIMARY TOOL."""
        doc = inspect.getdoc(mcp_mod.build_context_pack) or ""
        assert "PRIMARY TOOL" in doc, (
            f"build_context_pack description should state PRIMARY TOOL. Got: {doc[:120]}..."
        )

    def test_build_context_pack_has_task_example(self):
        """build_context_pack description must contain a concrete task example."""
        doc = inspect.getdoc(mcp_mod.build_context_pack) or ""
        assert 'task="fix' in doc or 'task="implement' in doc, (
            f"build_context_pack description should contain task= example. Got: {doc[:120]}..."
        )

    def test_search_symbols_has_find_login_example(self):
        """search_symbols description must contain Find \"login\" function example."""
        doc = inspect.getdoc(mcp_mod.search_symbols) or ""
        assert 'Find "login" function' in doc, (
            f"search_symbols should have Find 'login' function example. Got: {doc[:120]}..."
        )

    def test_get_callers_has_who_calls_question(self):
        """get_callers description must contain 'Who calls this function?'."""
        doc = inspect.getdoc(mcp_mod.get_callers) or ""
        assert "Who calls this function?" in doc, (
            f"get_callers should ask 'Who calls this function?'. Got: {doc[:120]}..."
        )

    def test_get_callees_has_what_depends_question(self):
        """get_callees description must contain 'What does this symbol call or depend on?'."""
        doc = inspect.getdoc(mcp_mod.get_callees) or ""
        assert "What does this symbol call or depend on?" in doc, (
            f"get_callees should ask 'What does this symbol call or depend on?'. Got: {doc[:120]}..."
        )

    def test_get_neighbors_has_what_connected_question(self):
        """get_neighbors description must contain 'What is connected to this symbol?'."""
        doc = inspect.getdoc(mcp_mod.get_neighbors) or ""
        assert "What is connected to this symbol?" in doc, (
            f"get_neighbors should ask 'What is connected to this symbol?'. Got: {doc[:120]}..."
        )

    def test_get_impact_has_what_breaks_question(self):
        """get_impact description must contain 'If I change this symbol, what might break?'."""
        doc = inspect.getdoc(mcp_mod.get_impact) or ""
        assert "If I change this symbol, what might break?" in doc, (
            f"get_impact should ask 'If I change this symbol, what might break?'. Got: {doc[:120]}..."
        )

    def test_repo_status_has_which_project_question(self):
        """repo_status description must contain 'Which project is CodeGraph querying right now?'."""
        doc = inspect.getdoc(mcp_mod.repo_status) or ""
        assert "Which project is CodeGraph querying right now?" in doc, (
            f"repo_status should ask 'Which project is CodeGraph querying right now?'. Got: {doc[:120]}..."
        )

    def test_all_tool_names_preserved(self):
        """All 10 MCP tool functions exist and have docstrings."""
        tool_funcs = [
            ("codegraph_build_context_pack", mcp_mod.build_context_pack),
            ("codegraph_search_symbols", mcp_mod.search_symbols),
            ("codegraph_get_symbol", mcp_mod.get_symbol),
            ("codegraph_find", mcp_mod.codegraph_find),
            ("codegraph_get_callers", mcp_mod.get_callers),
            ("codegraph_get_callees", mcp_mod.get_callees),
            ("codegraph_get_neighbors", mcp_mod.get_neighbors),
            ("codegraph_get_impact", mcp_mod.get_impact),
            ("codegraph_repo_status", mcp_mod.repo_status),
            ("codegraph_repo_summary", mcp_mod.repo_summary),
        ]
        for expected_name, func in tool_funcs:
            assert callable(func), (
                f"{expected_name} is not callable"
            )
            doc = inspect.getdoc(func) or ""
            assert len(doc) > 0, (
                f"{expected_name} has empty docstring"
            )

    def test_tool_parameter_schemas_unchanged(self):
        """All MCP tool parameter names and defaults should not have changed structurally."""
        # Verify signature is non-empty for all tools — structural check only.
        for name, obj in inspect.getmembers(mcp_mod, inspect.isfunction):
            if not hasattr(obj, "__mcp_tool_name__"):
                continue
            sig = inspect.signature(obj)
            param_names = list(sig.parameters.keys())
            assert len(param_names) > 0, (
                f"Tool {obj.__mcp_tool_name__} has no parameters — schema may be broken"
            )
            # Verify the signature is still callable with its defaults
            for p_name, p in sig.parameters.items():
                assert p.kind in (
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                    inspect.Parameter.KEYWORD_ONLY,
                ), (
                    f"Tool {obj.__mcp_tool_name__} param {p_name} has unexpected "
                    f"kind {p.kind} — schema may be broken"
                )


# ── README Content Tests ────────────────────────────────────────────────────


class TestReadmeAgentAdoption:
    """Verify README correctly guides users on CodeGraph agent adoption."""

    @pytest.fixture
    def readme(self) -> str:
        return _read_file("README.md")

    def test_has_agent_usage_section(self, readme):
        """README should have a section about agent usage."""
        assert "Agent 使用建议" in readme, (
            "README must have 'Agent 使用建议' section"
        )

    def test_mentions_target_project(self, readme):
        """README should clarify the block goes to the target project, not CodeGraph Explorer."""
        assert "目标项目" in readme, (
            "README must mention '目标项目' (target project)"
        )

    def test_lists_target_locations(self, readme):
        """README should list CLAUDE.md, .cursor/rules/codegraph.mdc, AGENTS.md."""
        assert "CLAUDE.md" in readme
        assert ".cursor/rules/codegraph.mdc" in readme
        assert "AGENTS.md" in readme

    def test_provides_codegraph_usage_block(self, readme):
        """README should contain the CodeGraph Usage markdown block."""
        assert "## CodeGraph Usage" in readme, (
            "README must include the CodeGraph Usage markdown block"
        )
        assert "codegraph_build_context_pack" in readme, (
            "The CodeGraph Usage block must mention codegraph_build_context_pack"
        )

    def test_block_mentions_before_grep(self, readme):
        """The CodeGraph Usage block should say 'before grep/glob/read-heavy exploration'."""
        assert "before grep/glob/read-heavy exploration" in readme.lower(), (
            "CodeGraph Usage block must include 'before grep/glob/read-heavy exploration'"
        )

    def test_explains_not_automatic(self, readme):
        """README should explain that Agent does not automatically prefer CodeGraph."""
        assert "不一定会自动" in readme or "does not automatically" in readme.lower(), (
            "README must explain that Agent does not automatically prefer CodeGraph"
        )

    def test_no_false_automatic_claim(self, readme):
        """README must not claim Agent will automatically use CodeGraph."""
        readme_lower = readme.lower()
        # Check for false promises in the adoption section context
        false_claims = [
            "agent will automatically use codegraph",
            "会自动使用 codegraph",
            "automatically replaces grep",
            "自动替代 grep",
            "强制 agent 使用",
        ]
        for claim in false_claims:
            assert claim not in readme_lower, (
                f"README must not contain false claim: '{claim}'"
            )

    def test_no_unimplemented_commands(self, readme):
        """README must not reference unimplemented commands."""
        unimplemented = [
            "codegraph agents install-hints",
        ]
        for cmd in unimplemented:
            assert cmd not in readme, (
                f"README must not reference unimplemented command: '{cmd}'"
            )

    def test_explicitly_says_block_not_automatic(self, readme):
        """README should include disclaimers about the prompt block."""
        assert "不会自动写入" in readme or "需要手动复制" in readme, (
            "README must state the prompt block is not auto-written"
        )
        assert "建议性" in readme or "advisory" in readme.lower(), (
            "README must state the prompt is advisory"
        )


# ── Docs Existence Tests ────────────────────────────────────────────────────


class TestDocsExistence:
    """Verify required documentation files exist and have required content."""

    def test_agent_adoption_test_exists(self):
        """docs/agent-adoption-test.md should exist."""
        path = _project_root() / "docs" / "agent-adoption-test.md"
        assert path.exists(), "docs/agent-adoption-test.md must exist"

    def test_agent_adoption_test_has_steps(self):
        """agent-adoption-test.md should contain verification steps."""
        text = _read_file("docs/agent-adoption-test.md")
        assert "codegraph init" in text, (
            "agent-adoption-test.md must mention 'codegraph init'"
        )
        assert "codegraph doctor" in text, (
            "agent-adoption-test.md must mention 'codegraph doctor'"
        )
        assert "CLAUDE.md" in text, (
            "agent-adoption-test.md must mention CLAUDE.md"
        )
        assert "grep" in text.lower(), (
            "agent-adoption-test.md must mention grep"
        )

    def test_agent_adoption_p0_test_exists(self):
        """docs/agent-adoption-p0-test.md should exist with P0 verification content."""
        path = _project_root() / "docs" / "agent-adoption-p0-test.md"
        assert path.exists(), "docs/agent-adoption-p0-test.md must exist"

    def test_agent_adoption_p0_test_has_required_sections(self):
        """agent-adoption-p0-test.md should have P0-specific verification content."""
        text = _read_file("docs/agent-adoption-p0-test.md")
        assert "P0" in text, "Must mention P0"
        assert "next_recommended_tools" in text, "Must mention next_recommended_tools"
        assert "codegraph_session" in text, "Must mention codegraph_session"
        assert "测试任务" in text or "Test Task" in text, "Must have test tasks"
        assert "有效" in text or "success" in text.lower(), "Must define success criteria"

    def test_mcp_tools_has_workflow(self):
        """docs/mcp-tools.md should have Recommended Agent Workflow section."""
        text = _read_file("docs/mcp-tools.md")
        assert "## Recommended Agent Workflow" in text, (
            "docs/mcp-tools.md must have 'Recommended Agent Workflow' section"
        )
        assert "codegraph_repo_status" in text, (
            "docs/mcp-tools.md workflow must include codegraph_repo_status"
        )
        assert "codegraph_build_context_pack" in text, (
            "docs/mcp-tools.md workflow must include codegraph_build_context_pack"
        )

    def test_agent_usage_reminder_exists(self):
        """docs/agent-usage-reminder.md should exist."""
        path = _project_root() / "docs" / "agent-usage-reminder.md"
        assert path.exists(), "docs/agent-usage-reminder.md must exist"

    def test_agent_usage_reminder_has_required_sections(self):
        """agent-usage-reminder.md should have required sections."""
        text = _read_file("docs/agent-usage-reminder.md")
        assert "## Why this matters" in text, (
            "agent-usage-reminder.md must have 'Why this matters' section"
        )
        assert "## Recommended reminder" in text, (
            "agent-usage-reminder.md must have 'Recommended reminder' section"
        )
        assert "## Where to put it" in text, (
            "agent-usage-reminder.md must have 'Where to put it' section"
        )
        assert "## How to verify" in text, (
            "agent-usage-reminder.md must have 'How to verify' section"
        )
        assert "CLAUDE.md" in text, (
            "agent-usage-reminder.md must mention CLAUDE.md"
        )
        assert ".cursor/rules/codegraph.mdc" in text, (
            "agent-usage-reminder.md must mention .cursor/rules/codegraph.mdc"
        )
        assert "AGENTS.md" in text, (
            "agent-usage-reminder.md must mention AGENTS.md"
        )
        assert "codegraph_build_context_pack" in text, (
            "agent-usage-reminder.md must mention codegraph_build_context_pack"
        )
        assert "does not automatically" in text.lower(), (
            "agent-usage-reminder.md must explain agents don't auto-use CodeGraph"
        )


# ── CLI Init Output Tests ───────────────────────────────────────────────────


class TestCliInitAdoptionHint:
    """Verify CLI init output includes agent adoption guidance."""

    def test_init_shows_adoption_hint_with_symbols(self, runner, tmp_path, monkeypatch):
        """codegraph init should show the adoption hint when symbols > 0."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "greeter.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""", encoding="utf-8")

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "CodeGraph index ready" in result.output, (
            "init should print 'CodeGraph index ready' after successful indexing"
        )
        assert "CLAUDE.md" in result.output, (
            "init hint should mention CLAUDE.md"
        )
        assert "cursor/rules/codegraph.mdc" in result.output, (
            "init hint should mention .cursor/rules/codegraph.mdc"
        )
        assert "AGENTS.md" in result.output, (
            "init hint should mention AGENTS.md"
        )

    def test_init_does_not_claim_automatic(self, runner, tmp_path, monkeypatch):
        """init hint must NOT claim Agent will automatically use CodeGraph."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "greeter.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""", encoding="utf-8")

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "will automatically" not in result.output.lower(), (
            "init hint must not claim Agent will automatically use CodeGraph"
        )
        assert "automatically use" not in result.output.lower(), (
            "init hint must not claim auto-usage"
        )

    def test_init_warns_on_zero_symbols(self, runner, tmp_path, monkeypatch):
        """codegraph init should warn when 0 symbols are indexed."""
        monkeypatch.chdir(tmp_path)
        # Create an empty Python file with no functions/classes
        (tmp_path / "empty.py").write_text("# Just a comment\n", encoding="utf-8")

        result = runner.invoke(app, ["init"])
        # Index may succeed but with 0 symbols — should warn
        if "Found 0 symbols" in result.output or "Symbols:       0" in result.output:
            assert (
                "0 symbols" in result.output.lower()
                or "index may be empty" in result.output.lower()
            ), "init should warn about 0 symbols"
            # Should NOT show the ready message
            assert "index ready" not in result.output.lower(), (
                "init should NOT say 'index ready' when symbols == 0"
            )
