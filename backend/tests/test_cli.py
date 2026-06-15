"""Tests for CLI helpers — _find_codegraph_dir, _find_node, _type_label, etc."""

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app, _type_label, _format_location, _find_codegraph_dir
from codegraph.graph.models import GraphNode, GraphEdge, CodeGraph, RepoInfo, NodeType, Location


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTypeLabel:
    def test_function(self):
        assert _type_label(NodeType.function) == "function"

    def test_class(self):
        assert _type_label(NodeType.class_) == "class"

    def test_method(self):
        assert _type_label(NodeType.method) == "method"

    def test_file(self):
        assert _type_label(NodeType.file) == "file"

    def test_module(self):
        assert _type_label(NodeType.module) == "module"

    def test_test(self):
        assert _type_label(NodeType.test) == "test"

    def test_import(self):
        assert _type_label(NodeType.import_) == "import"

    def test_external(self):
        assert _type_label(NodeType.external_symbol) == "external"

    def test_unknown_falls_back(self):
        assert _type_label(NodeType.repository) == "repository"


class TestFormatLocation:
    def test_with_location(self):
        node = GraphNode(id="test.py::f", type=NodeType.function, name="f",
                         location=Location(line_start=10, line_end=20))
        assert _format_location(node) == ":10"

    def test_without_location(self):
        node = GraphNode(id="test.py::f", type=NodeType.function, name="f")
        assert _format_location(node) == ""


class TestFindCodegraphDir:
    def test_not_found(self, tmp_path):
        result = _find_codegraph_dir(str(tmp_path))
        assert result is None

    def test_found_in_root(self, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}", encoding="utf-8")
        result = _find_codegraph_dir(str(tmp_path))
        assert result == cg_dir

    def test_found_in_parent(self, tmp_path):
        # Create .codegraph in tmp_path, search from a subdirectory
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        (cg_dir / "graph.json").write_text("{}", encoding="utf-8")
        sub = tmp_path / "sub" / "dir"
        sub.mkdir(parents=True)
        result = _find_codegraph_dir(str(sub))
        assert result == cg_dir


class TestCliIndex:
    def test_index_non_existent_dir(self, runner):
        result = runner.invoke(app, ["index", "/nonexistent/path"])
        assert result.exit_code != 0
        assert "valid directory" in result.output.lower()

    def test_index_defaults_to_cwd(self, runner, tmp_path, monkeypatch):
        """codegraph index without path should initialize current directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "greeter.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""", encoding="utf-8")

        result = runner.invoke(app, ["index"])
        assert result.exit_code == 0
        assert "Scanning" in result.output
        assert "Found" in result.output
        assert (tmp_path / ".codegraph" / "graph.json").exists()

    def test_index_with_explicit_path(self, runner, tmp_path):
        """codegraph index <path> should still work with explicit path."""
        (tmp_path / "greeter.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""", encoding="utf-8")

        result = runner.invoke(app, ["index", str(tmp_path)])
        assert result.exit_code == 0
        assert "Scanning" in result.output
        assert "Found" in result.output
        assert (tmp_path / ".codegraph" / "graph.json").exists()


class TestCliSearch:
    def test_search_no_index(self, runner, tmp_path):
        result = runner.invoke(app, ["search", "test", "--root", str(tmp_path)])
        assert result.exit_code != 0
        assert "No .codegraph directory found" in result.output


class TestCliExplain:
    def test_explain_no_index(self, runner, tmp_path):
        result = runner.invoke(app, ["explain", "foo", "--root", str(tmp_path)])
        assert result.exit_code != 0
        assert "No .codegraph directory found" in result.output


class TestCliImpact:
    def test_impact_no_index(self, runner, tmp_path):
        result = runner.invoke(app, ["impact", "foo", "--root", str(tmp_path)])
        assert result.exit_code != 0
        assert "No .codegraph directory found" in result.output


class TestCliContext:
    def test_context_no_index(self, runner, tmp_path):
        result = runner.invoke(app, ["context", "test", "--root", str(tmp_path)])
        assert result.exit_code != 0
        assert "No .codegraph directory found" in result.output




# ── Index → Search integration ───────────────────────────────────────────


class TestIndexSearchIntegration:
    def test_index_and_search_demo(self, runner):
        """Full integration: index a temp project and search it."""
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "greeter.py").write_text("""
def greet(name: str) -> str:
    '''Greet someone.'''
    return f"Hello {name}"

def farewell(name: str) -> str:
    '''Say goodbye.'''
    return f"Goodbye {name}"
""", encoding="utf-8")

        # Index
        result = runner.invoke(app, ["index", str(tmp)])
        assert result.exit_code == 0
        assert "Scanning" in result.output

        # Search
        result = runner.invoke(app, ["search", "greet", "--root", str(tmp)])
        assert result.exit_code == 0
        assert "greet" in result.output

        # Explain
        result = runner.invoke(app, ["explain", "greeter.py::greet", "--root", str(tmp)])
        assert result.exit_code == 0
        assert "greet" in result.output

        # Cleanup
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


# ── Init without path (CWD default) ──────────────────────────────────────


class TestCliInit:
    def test_init_defaults_to_cwd(self, runner, tmp_path, monkeypatch):
        """codegraph init without path should initialize current directory."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "greeter.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""", encoding="utf-8")

        result = runner.invoke(app, ["init"])
        assert result.exit_code == 0
        assert "Scanning" in result.output
        assert "Found" in result.output
        assert (tmp_path / ".codegraph" / "graph.json").exists()

    def test_init_with_explicit_path(self, runner, tmp_path):
        """codegraph init <path> should still work with explicit path."""
        (tmp_path / "greeter.py").write_text("""
def greet(name: str) -> str:
    return f"Hello {name}"
""", encoding="utf-8")

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0
        assert "Scanning" in result.output
        assert "Found" in result.output
        assert (tmp_path / ".codegraph" / "graph.json").exists()

    def test_init_nonexistent_dir(self, runner):
        """codegraph init with non-existent path should error."""
        result = runner.invoke(app, ["init", "/nonexistent/path"])
        assert result.exit_code != 0
        assert "valid directory" in result.output.lower()


class TestCliStatus:
    def test_status_missing_shows_codegraph_init(self, runner, tmp_path):
        """codegraph status on missing index should suggest 'codegraph init'."""
        result = runner.invoke(app, ["status", "--root", str(tmp_path)])
        assert result.exit_code == 0
        assert "codegraph init" in result.output
        # The old long-path form should no longer appear
        assert "codegraph init " + str(tmp_path) not in result.output


# ── Update command ──────────────────────────────────────────────────────


class TestCliUpdate:
    def test_update_success(self, runner, monkeypatch, tmp_path):
        """codegraph update runs pip install -e and reports success."""
        import subprocess

        # Simulate editable install: __file__ -> backend/codegraph/__init__.py
        # parent.parent -> backend/  (where pyproject.toml lives)
        backend_dir = tmp_path / "backend"
        codegraph_dir = backend_dir / "codegraph"
        codegraph_dir.mkdir(parents=True)
        (codegraph_dir / "__init__.py").write_text("")
        (backend_dir / "pyproject.toml").write_text("[project]\nname='codegraph'\n", encoding="utf-8")

        monkeypatch.setattr(
            "codegraph.__file__",
            str(codegraph_dir / "__init__.py"),
        )

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        result = runner.invoke(app, ["update"])
        assert result.exit_code == 0
        assert "updated successfully" in result.output.lower()

    def test_update_not_editable_install(self, runner, monkeypatch, tmp_path):
        """codegraph update fails gracefully when not in editable install."""
        # Point to a dir without pyproject.toml at parent.parent
        codegraph_dir = tmp_path / "codegraph"
        codegraph_dir.mkdir(parents=True)
        (codegraph_dir / "__init__.py").write_text("")

        monkeypatch.setattr(
            "codegraph.__file__",
            str(codegraph_dir / "__init__.py"),
        )

        result = runner.invoke(app, ["update"])
        assert result.exit_code != 0
        assert "editable" in result.output.lower()

    def test_update_preserves_mcp_config(self, runner, monkeypatch, tmp_path):
        """codegraph update should not modify MCP configuration files."""
        import subprocess
        import json
        import codegraph.configure as cfg

        # Redirect MCP config paths to tmp_path
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / ".cursor" / "mcp.json")

        # Pre-configure MCP
        from codegraph.configure import configure_target, ConfigTarget
        configure_result = configure_target(ConfigTarget.CLAUDE)
        assert configure_result["status"] == "configured"

        # Set up simulated editable install: backend/codegraph/__init__.py
        backend_dir = tmp_path / "backend"
        codegraph_dir = backend_dir / "codegraph"
        codegraph_dir.mkdir(parents=True)
        (codegraph_dir / "__init__.py").write_text("")
        (backend_dir / "pyproject.toml").write_text("[project]\nname='codegraph'\n", encoding="utf-8")

        monkeypatch.setattr(
            "codegraph.__file__",
            str(codegraph_dir / "__init__.py"),
        )

        mock_result = subprocess.CompletedProcess(args=[], returncode=0, stdout="ok")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: mock_result)

        result = runner.invoke(app, ["update"])
        assert result.exit_code == 0

        # Verify MCP config is intact
        claude_config_after = json.loads(
            (tmp_path / ".claude.json").read_text(encoding="utf-8")
        )
        assert "codegraph" in claude_config_after["mcpServers"]


# ── Workflow Impact CLI tests ────────────────────────────────────────────


@pytest.fixture
def indexed_project(tmp_path) -> Path:
    """Create a small indexed Python project for workflow tests."""
    proj = tmp_path / "proj"
    proj.mkdir()

    # Create a Python file with a function that calls another function
    (proj / "greeter.py").write_text("""
def format_greeting(name: str) -> str:
    '''Format a greeting string.'''
    return f"Hello, {name}!"

def greet(name: str) -> str:
    '''Greet someone.'''
    return format_greeting(name)

class Greeter:
    '''A greeter class.'''
    def __init__(self, prefix: str = "Hello"):
        self.prefix = prefix

    def greet(self, name: str) -> str:
        return f"{self.prefix}, {name}!"
""", encoding="utf-8")

    # Index the project
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, ["init", str(proj), "--no-hook"])
    assert result.exit_code == 0, f"Index failed: {result.output}"

    return proj


class TestWorkflowImpact:
    """Tests for ``codegraph workflow impact`` CLI command."""

    def test_help(self, runner):
        """workflow impact --help should show usage."""
        result = runner.invoke(app, ["workflow", "impact", "--help"])
        assert result.exit_code == 0
        assert "--files" in result.output
        assert "--symbols" in result.output
        assert "--change-type" in result.output
        assert "--format" in result.output

    def test_missing_files_and_symbols(self, runner):
        """Missing both --files and --symbols should return non-zero."""
        result = runner.invoke(app, ["workflow", "impact"])
        assert result.exit_code != 0
        assert "files" in result.output.lower() or "symbols" in result.output.lower()

    def test_invalid_change_type(self, runner):
        """Invalid change_type should return non-zero."""
        result = runner.invoke(
            app, ["workflow", "impact", "--files", "test.py", "--change-type", "invalid"]
        )
        assert result.exit_code != 0

    def test_invalid_format(self, runner):
        """Invalid format should return non-zero."""
        result = runner.invoke(
            app, ["workflow", "impact", "--files", "test.py", "--format", "xml"]
        )
        assert result.exit_code != 0

    def test_no_index(self, runner, tmp_path):
        """Running without an index should return non-zero."""
        result = runner.invoke(
            app, ["workflow", "impact", "--files", "greeter.py", "--root", str(tmp_path)]
        )
        assert result.exit_code != 0
        assert "No .codegraph directory found" in result.output

    def test_with_files_markdown(self, runner, indexed_project):
        """Basic invocation with --files should produce Markdown."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--change-type", "refactor",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "# CodeGraph Impact Workflow Report" in result.output

    def test_with_symbols_markdown(self, runner, indexed_project):
        """Invocation with --symbols should produce Markdown."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--symbols", "greet",
                "--change-type", "bugfix",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "# CodeGraph Impact Workflow Report" in result.output

    def test_markdown_contains_impact_summary(self, runner, indexed_project):
        """Markdown output should contain Impact Summary section."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--change-type", "refactor",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "## Impact Summary" in result.output
        assert "Risk level:" in result.output

    def test_markdown_contains_index_status(self, runner, indexed_project):
        """Markdown output should contain Index Status section."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "## Index Status" in result.output
        assert "Freshness:" in result.output

    def test_markdown_contains_recommended_checks(self, runner, indexed_project):
        """Markdown output should contain Recommended Checks section."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "## Recommended Checks" in result.output

    def test_json_output_valid(self, runner, indexed_project):
        """--format json should output valid JSON."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--change-type", "feature",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_json_contains_workflow_field(self, runner, indexed_project):
        """JSON output should contain workflow=impact."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data.get("workflow") == "impact"
        assert data.get("ok") is True

    def test_json_contains_planned_symbols(self, runner, indexed_project):
        """JSON output should contain planned_symbols."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "planned_symbols" in data
        assert isinstance(data["planned_symbols"], list)

    def test_json_contains_impact_summary(self, runner, indexed_project):
        """JSON output should contain impact_summary."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "impact_summary" in data
        assert "risk_level" in data["impact_summary"]

    def test_json_contains_warnings(self, runner, indexed_project):
        """JSON output should contain warnings list."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "warnings" in data
        assert isinstance(data["warnings"], list)

    def test_json_error_on_missing_args(self, runner):
        """JSON mode should output JSON error when args are missing."""
        result = runner.invoke(
            app,
            ["workflow", "impact", "--format", "json"],
        )
        assert result.exit_code != 0
        # Error may be on stdout or stderr
        output = result.output.strip() or result.stderr.strip()
        data = json.loads(output)
        assert data.get("ok") is False

    def test_output_writes_file(self, runner, indexed_project):
        """--output should write report to file."""
        out_path = indexed_project / "report.md"
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--output", str(out_path),
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "Report written to:" in result.output
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "# CodeGraph Impact Workflow Report" in content

    def test_no_output_flag_does_not_write_file(self, runner, indexed_project):
        """Without --output, no report file should be created in .codegraph/reports/."""
        reports_dir = indexed_project / ".codegraph" / "reports"
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        # Reports dir should not be created by default
        assert not reports_dir.exists() or not list(reports_dir.glob("impact*.md"))

    def test_existing_output_not_overwritten(self, runner, indexed_project):
        """Existing output file should not be overwritten without --force-output."""
        out_path = indexed_project / "report.md"
        out_path.write_text("existing content", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--output", str(out_path),
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code != 0
        assert "already exists" in result.output
        # Content should be unchanged
        assert out_path.read_text(encoding="utf-8") == "existing content"

    def test_force_output_overwrites(self, runner, indexed_project):
        """--force-output should overwrite existing output file."""
        out_path = indexed_project / "report.md"
        out_path.write_text("existing content", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--output", str(out_path),
                "--force-output",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "Report written to:" in result.output
        content = out_path.read_text(encoding="utf-8")
        assert "# CodeGraph Impact Workflow Report" in content

    def test_output_creates_parent_dirs(self, runner, indexed_project):
        """--output should create parent directories if needed."""
        out_path = indexed_project / "sub" / "deep" / "report.md"
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--output", str(out_path),
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert out_path.exists()

    def test_with_both_files_and_symbols(self, runner, indexed_project):
        """Using both --files and --symbols should work."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--symbols", "Greeter",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "# CodeGraph Impact Workflow Report" in result.output

    def test_symbol_not_found_warning(self, runner, indexed_project):
        """Non-existent symbol should produce warning but not error out."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--symbols", "nonexistent_func",
                "--root", str(indexed_project),
            ],
        )
        # Should still exit 0 (workflow completed, just no symbols found)
        assert result.exit_code == 0
        assert "## Impact Summary" in result.output

    def test_file_not_indexed_warning(self, runner, indexed_project):
        """Non-indexed file should produce warning but not error out."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "nonexistent.py",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "## Impact Summary" in result.output

    def test_json_contains_input_field(self, runner, indexed_project):
        """JSON should contain input section with files/symbols/change_type."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--symbols", "greet",
                "--change-type", "refactor",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["input"]["files"] == ["greeter.py"]
        assert data["input"]["symbols"] == ["greet"]
        assert data["input"]["change_type"] == "refactor"

    def test_json_contains_index_status(self, runner, indexed_project):
        """JSON should contain index_status section."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "index_status" in data
        assert "freshness" in data["index_status"]

    def test_workflow_help_shows_in_main_help(self, runner):
        """Main help should show workflow subcommand."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "workflow" in result.output

    def test_workflow_group_help(self, runner):
        """workflow --help should show impact subcommand."""
        result = runner.invoke(app, ["workflow", "--help"])
        assert result.exit_code == 0
        assert "impact" in result.output

    def test_no_include_tests_flag(self, runner, indexed_project):
        """--no-include-tests should still produce valid output."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--no-include-tests",
                "--format", "json",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["affected_tests"] == []

    def test_with_description(self, runner, indexed_project):
        """--description should appear in report."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--description", "Refactor greeting module",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        assert "Refactor greeting module" in result.output

    def test_workflow_does_not_create_frontend_deps(self, runner, indexed_project):
        """Workflow should not create any frontend files."""
        result = runner.invoke(
            app,
            [
                "workflow", "impact",
                "--files", "greeter.py",
                "--root", str(indexed_project),
            ],
        )
        assert result.exit_code == 0
        # No HTML, JS, CSS files should be created
        frontend_files = list(indexed_project.glob("*.html")) + \
            list(indexed_project.glob("*.js")) + \
            list(indexed_project.glob("*.css"))
        assert len(frontend_files) == 0

    def test_mcp_pre_edit_check_unchanged(self):
        """MCP pre_edit_check should still be importable and callable."""
        from codegraph.mcp_server import pre_edit_check
        import inspect
        sig = inspect.signature(pre_edit_check)
        params = list(sig.parameters.keys())
        # Verify signature unchanged
        assert "files" in params
        assert "symbols" in params
        assert "change_type" in params
        assert "response_mode" in params
