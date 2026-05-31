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


class TestCliDashboard:
    def test_dashboard_no_index_warning(self, runner, tmp_path):
        # Dashboard should warn but still start
        result = runner.invoke(app, ["dashboard", "--root", str(tmp_path),
                                     "--port", "18765", "--no-open"])
        # It may start a server process — check that the warning appears
        assert "No .codegraph directory found" in result.output or result.exit_code == 0


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
