"""Tests for ``serve --mcp``, ``serve --mcp --check``, and ``doctor`` commands."""

import json
import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.configure import (
    MCP_SERVER_NAME,
    build_server_config,
    configure_target,
    read_config,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── Helpers ──────────────────────────────────────────────────────────────


def _write_minimal_index(cg_dir: Path, root_path: Path) -> None:
    """Write a minimal but complete .codegraph index for testing."""
    cg_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    # metadata.json
    (cg_dir / "metadata.json").write_text(json.dumps({
        "schema_version": "1.0.0",
        "indexer_version": "1.0.0",
        "root_path": str(root_path),
        "indexed_at": now,
        "file_count": 1,
        "symbol_count": 1,
        "edge_count": 0,
        "files": [],
    }), encoding="utf-8")

    # graph.json
    (cg_dir / "graph.json").write_text(json.dumps({
        "schema_version": "1.0.0",
        "repo": {
            "repo_id": "local:test",
            "name": "test",
            "root_path": str(root_path),
            "languages": ["python"],
            "indexed_at": now,
            "file_count": 1,
            "symbol_count": 1,
        },
        "nodes": [],
        "edges": [],
    }), encoding="utf-8")

    # nodes.json
    (cg_dir / "nodes.json").write_text("[]", encoding="utf-8")
    # edges.json
    (cg_dir / "edges.json").write_text("[]", encoding="utf-8")


# ── serve --mcp --check ──────────────────────────────────────────────────


class TestServeMcpCheck:
    """Tests for ``codegraph serve --mcp --check``."""

    def test_check_passes_with_valid_index(self, runner, tmp_path, monkeypatch):
        """With a complete index, --check should pass and print success."""
        project = tmp_path / "myproject"
        project.mkdir()
        cg_dir = project / ".codegraph"
        _write_minimal_index(cg_dir, project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["serve", "--mcp", "--check"])
        assert result.exit_code == 0
        assert "CodeGraph MCP check passed" in result.stdout
        assert str(project) in result.stdout

    def test_check_fails_without_index(self, runner, tmp_path, monkeypatch):
        """Without a .codegraph index, --check should exit with clear error."""
        project = tmp_path / "noproject"
        project.mkdir()
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["serve", "--mcp", "--check"])
        assert result.exit_code != 0
        assert "No CodeGraph index found" in result.stderr or "No CodeGraph index found" in result.stdout
        assert "codegraph init" in result.stderr or "codegraph init" in result.stdout

    def test_check_fails_with_incomplete_index(self, runner, tmp_path, monkeypatch):
        """If index files are missing, --check should report incomplete."""
        project = tmp_path / "partial"
        project.mkdir()
        cg_dir = project / ".codegraph"
        cg_dir.mkdir()
        # Only write graph.json, missing others
        (cg_dir / "graph.json").write_text(json.dumps({
            "schema_version": "1.0.0", "repo": {}, "nodes": [], "edges": [],
        }))
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["serve", "--mcp", "--check"])
        assert result.exit_code != 0
        assert "incomplete" in result.stderr.lower() or "incomplete" in result.stdout.lower()

    def test_check_fails_with_nonexistent_root(self, runner, monkeypatch):
        """If CODEGRAPH_PROJECT_ROOT doesn't exist, report path error."""
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", "/nonexistent/path/xyz")

        result = runner.invoke(app, ["serve", "--mcp", "--check"])
        assert result.exit_code != 0
        assert "does not exist" in result.stderr or "does not exist" in result.stdout

    def test_serve_without_mcp_flag_shows_usage(self, runner):
        """Without --mcp, serve command shows usage."""
        result = runner.invoke(app, ["serve"])
        assert result.exit_code != 0
        assert "serve --mcp" in result.stderr or "serve --mcp" in result.stdout


# ── serve --mcp startup validation ───────────────────────────────────────


class TestServeMcpValidation:
    """Tests for startup validation in ``codegraph serve --mcp``."""

    def test_validation_rejects_nonexistent_root(self, runner, monkeypatch):
        """Startup should reject a path that does not exist."""
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", "/ghost/path/nowhere")
        result = runner.invoke(app, ["serve", "--mcp", "--check"])
        assert result.exit_code != 0

    def test_autodetect_from_cwd_when_no_env(self, runner, tmp_path, monkeypatch):
        """Without CODEGRAPH_PROJECT_ROOT, auto-detect from CWD."""
        project = tmp_path / "autodetect"
        project.mkdir()
        cg_dir = project / ".codegraph"
        _write_minimal_index(cg_dir, project)
        monkeypatch.chdir(project)

        result = runner.invoke(app, ["serve", "--mcp", "--check"])
        assert result.exit_code == 0
        assert "CodeGraph MCP check passed" in result.stdout


# ── doctor command ───────────────────────────────────────────────────────


class TestDoctor:
    """Tests for ``codegraph doctor``."""

    def test_doctor_reports_project_root(self, runner, tmp_path, monkeypatch):
        """doctor should report the project root."""
        project = tmp_path / "drproj"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert str(project) in result.stdout

    def test_doctor_reports_index_status(self, runner, tmp_path, monkeypatch):
        """doctor should report index presence and freshness."""
        project = tmp_path / "drproj2"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "Index status" in result.stdout
        assert ".codegraph" in result.stdout
        assert "Index is fresh" in result.stdout

    def test_doctor_reports_missing_index(self, runner, tmp_path, monkeypatch):
        """doctor should report when .codegraph is missing."""
        project = tmp_path / "drproj3"
        project.mkdir()
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "No .codegraph" in result.stdout
        assert "codegraph init" in result.stdout

    def test_doctor_reports_mcp_config(self, runner, tmp_path, monkeypatch):
        """doctor should report MCP configuration status."""
        import codegraph.configure as cfg

        project = tmp_path / "drproj4"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        # Point user config to temp
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")

        # Pre-configure Claude
        configure_target(cfg.ConfigTarget.CLAUDE, root=str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP configuration" in result.stdout
        assert "configured" in result.stdout.lower()

    def test_doctor_reports_package_and_python(self, runner):
        """doctor should report Python version and package path."""
        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "Python version" in result.stdout
        assert "Package path" in result.stdout
        assert "CLI availability" in result.stdout

    def test_doctor_reports_serve_readiness_pass(self, runner, tmp_path, monkeypatch):
        """doctor should report serve --mcp readiness when index is valid."""
        project = tmp_path / "readyproj"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "serve --mcp readiness" in result.stdout
        assert "serve --mcp can start" in result.stdout

    def test_doctor_reports_serve_readiness_fail(self, runner, tmp_path, monkeypatch):
        """doctor should report serve --mcp failure when index is missing."""
        project = tmp_path / "failproj"
        project.mkdir()
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "serve --mcp would fail" in result.stdout

    def test_doctor_checks_mcp_command_exists(self, runner, tmp_path, monkeypatch):
        """doctor should report MCP command existence (check 8)."""
        import codegraph.configure as cfg

        project = tmp_path / "drproj_cmd"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")

        # Configure with sys.executable (should exist)
        configure_target(cfg.ConfigTarget.CLAUDE)

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP command existence" in result.stdout

    def test_doctor_detects_missing_mcp_command(self, runner, tmp_path, monkeypatch):
        """doctor should FAIL when configured command does not exist."""
        import codegraph.configure as cfg

        project = tmp_path / "drproj_badcmd"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")

        # Write a config with a nonexistent command
        bad_cfg = {
            "mcpServers": {
                "codegraph": {
                    "command": "/nonexistent/path/to/python",
                    "args": ["-m", "codegraph.mcp_server"],
                }
            }
        }
        cfg.write_config(tmp_path / "claude_cfg.json", bad_cfg)

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP command existence" in result.stdout
        # Should report failure for the nonexistent command
        assert "not found" in result.stdout.lower() or "FAIL" in result.stdout

    def test_doctor_validates_mcp_server_launch(self, runner, tmp_path, monkeypatch):
        """doctor should check MCP server launch (check 9)."""
        import codegraph.configure as cfg

        project = tmp_path / "drproj_launch"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")

        # Configure with sys.executable
        configure_target(cfg.ConfigTarget.CLAUDE)

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP server launch check" in result.stdout

    def test_doctor_detects_mcp_root_without_index(self, runner, tmp_path, monkeypatch):
        """doctor FAILs when CODEGRAPH_PROJECT_ROOT points to dir without .codegraph."""
        import codegraph.configure as cfg

        # Create a directory without .codegraph
        empty_dir = tmp_path / "empty_project"
        empty_dir.mkdir()
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(empty_dir))
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")

        # Configure with the empty directory as root
        configure_target(cfg.ConfigTarget.CLAUDE, root=str(empty_dir))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP project root validation" in result.stdout
        # Should report that .codegraph is missing
        assert "no .codegraph" in result.stdout.lower() or "FAIL" in result.stdout

    def test_doctor_validates_mcp_root_path_exists(self, runner, tmp_path, monkeypatch):
        """doctor FAILs when CODEGRAPH_PROJECT_ROOT path does not exist."""
        import codegraph.configure as cfg

        nonexistent = tmp_path / "ghost_dir"
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")

        # Configure with nonexistent path
        configure_target(cfg.ConfigTarget.CLAUDE, root=str(nonexistent))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP project root validation" in result.stdout
        # Should report path does not exist
        output_lower = result.stdout.lower()
        assert "does not exist" in output_lower or "fail" in output_lower

    def test_doctor_validates_mcp_root_has_index(self, runner, tmp_path, monkeypatch):
        """doctor OK when CODEGRAPH_PROJECT_ROOT has valid .codegraph."""
        import codegraph.configure as cfg

        project = tmp_path / "valid_proj"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")

        configure_target(cfg.ConfigTarget.CLAUDE, root=str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP project root validation" in result.stdout
        assert ".codegraph found" in result.stdout

    def test_doctor_reports_mcp_protocol_compliance(self, runner, tmp_path, monkeypatch):
        """doctor should report MCP protocol compliance (check 11)."""
        import codegraph.configure as cfg

        project = tmp_path / "proto_proj"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "claude_cfg.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "cursor_cfg.json")
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        result = runner.invoke(app, ["doctor"])
        assert result.exit_code == 0
        assert "MCP protocol compliance" in result.stdout
        assert "structured dicts" in result.stdout
        assert "Zero telemetry" in result.stdout


# ── configure writes serve --mcp ─────────────────────────────────────────


class TestConfigureWritesServeMcp:
    """Verify configure writes Python interpreter with -m codegraph.mcp_server."""

    def test_configure_writes_sys_executable(self, tmp_path, monkeypatch):
        """configure should write sys.executable with -m codegraph.mcp_server and env."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / ".cursor" / "mcp.json")

        result = configure_target(cfg.ConfigTarget.CLAUDE)
        assert result["status"] == "configured"
        assert result["config"]["command"] == sys.executable
        assert result["config"]["args"] == ["-m", "codegraph.mcp_server"]
        # Always writes CODEGRAPH_PROJECT_ROOT
        assert "env" in result["config"]
        assert "CODEGRAPH_PROJECT_ROOT" in result["config"]["env"]

    def test_configure_with_root_writes_env(self, tmp_path, monkeypatch):
        """configure --root should set CODEGRAPH_PROJECT_ROOT to that path."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")

        result = configure_target(cfg.ConfigTarget.CLAUDE, root="/abs/path")
        assert result["config"]["command"] == sys.executable
        assert result["config"]["env"] == {"CODEGRAPH_PROJECT_ROOT": str(Path("/abs/path").resolve())}

    def test_configure_without_root_writes_cwd_env(self, tmp_path, monkeypatch):
        """configure without --root writes CODEGRAPH_PROJECT_ROOT from CWD."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")

        result = configure_target(cfg.ConfigTarget.CLAUDE)
        assert "env" in result["config"]
        assert result["config"]["env"]["CODEGRAPH_PROJECT_ROOT"] == str(Path.cwd().resolve())

    def test_configure_force_updates_old_config(self, tmp_path, monkeypatch):
        """--force should update old codegraph CLI config to sys.executable format."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")

        # Write old-style config (codegraph serve --mcp)
        old_cfg = {
            "mcpServers": {
                "codegraph": {
                    "command": "codegraph",
                    "args": ["serve", "--mcp"],
                    "env": {"CODEGRAPH_PROJECT_ROOT": "/old"},
                }
            }
        }
        cfg.write_config(tmp_path / ".claude.json", old_cfg)

        result = configure_target(cfg.ConfigTarget.CLAUDE, force=True)
        assert result["status"] == "overwritten"
        assert result["config"]["command"] == sys.executable
        assert result["config"]["args"] == ["-m", "codegraph.mcp_server"]

    def test_configure_all_cli_writes_sys_executable(self, runner, tmp_path, monkeypatch):
        """CLI ``configure all`` writes sys.executable by default."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / ".cursor" / "mcp.json")

        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0

        claude_data = read_config(tmp_path / ".claude.json")
        entry = claude_data["mcpServers"]["codegraph"]
        assert entry["command"] == sys.executable
        assert entry["args"] == ["-m", "codegraph.mcp_server"]


# ── configure output messages ────────────────────────────────────────────


class TestConfigureOutputMessages:
    """Verify improved configure output with next steps."""

    def test_configure_all_shows_next_steps(self, runner, tmp_path, monkeypatch):
        """After successful configure, show Next steps."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / ".cursor" / "mcp.json")

        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        assert "Configured CodeGraph MCP" in result.stdout
        assert "Project root:" in result.stdout
        assert "Next:" in result.stdout
        assert "codegraph doctor" in result.stdout

    def test_configure_all_already_configured_shows_hint(self, runner, tmp_path, monkeypatch):
        """When already configured without --force, show --force hint."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / ".cursor" / "mcp.json")

        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        assert "already configured" in result.stdout.lower()
        assert "--force" in result.stdout


# ── serve --check without entering stdio loop ────────────────────────────


class TestServeCheckNoStdio:
    """Verify --check mode does not enter the stdio MCP loop."""

    def test_check_returns_quickly(self, runner, tmp_path, monkeypatch):
        """--check should return immediately, not hang in stdio loop."""
        project = tmp_path / "quickproj"
        project.mkdir()
        _write_minimal_index(project / ".codegraph", project)
        monkeypatch.setenv("CODEGRAPH_PROJECT_ROOT", str(project))

        import time
        start = time.time()
        result = runner.invoke(app, ["serve", "--mcp", "--check"])
        elapsed = time.time() - start

        assert result.exit_code == 0
        assert elapsed < 5.0, "--check should return quickly, not enter stdio loop"
