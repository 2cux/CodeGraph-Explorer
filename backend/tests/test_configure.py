"""Tests for codegraph configure command."""

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.configure import (
    MCP_SERVER_NAME,
    ConfigTarget,
    build_server_config,
    configure_target,
    read_config,
    remove_target,
    show_status,
    write_config,
)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def home_tmp(monkeypatch, tmp_path):
    """Redirect Path.home() to tmp_path for isolated user-level config tests."""
    import codegraph.configure as cfg

    monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / ".claude.json")
    monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / ".cursor" / "mcp.json")
    return tmp_path


# ── build_server_config ──────────────────────────────────────────────────


class TestBuildServerConfig:
    def test_default_uses_sys_executable_with_m_module(self):
        """Default uses current Python interpreter absolute path with -m.
        Global config (root=None) does NOT write CODEGRAPH_PROJECT_ROOT."""
        cfg = build_server_config()
        assert cfg["command"] == sys.executable
        assert cfg["args"] == ["-m", "codegraph.mcp_server"]
        # Global auto-detect mode: no env
        assert "env" not in cfg

    def test_with_root_adds_env(self):
        """When root is provided, writes CODEGRAPH_PROJECT_ROOT in env."""
        cfg = build_server_config(root="/tmp/myproject")
        assert cfg["command"] == sys.executable
        assert cfg["args"] == ["-m", "codegraph.mcp_server"]
        assert cfg["env"] == {"CODEGRAPH_PROJECT_ROOT": str(Path("/tmp/myproject").resolve())}

    def test_without_root_no_env(self):
        """Without root (global auto-detect), no env is written."""
        cfg = build_server_config()
        assert "env" not in cfg

    def test_command_override_codegraph_uses_legacy_serve_mcp(self):
        """command_override='codegraph' writes legacy CLI entry point.
        Global config does NOT write env."""
        cfg = build_server_config(command_override="codegraph")
        assert cfg["command"] == "codegraph"
        assert cfg["args"] == ["serve", "--mcp"]
        # Global auto-detect: no env
        assert "env" not in cfg

    def test_command_override_codegraph_with_root_writes_env(self):
        """command_override='codegraph' with root writes env."""
        cfg = build_server_config(command_override="codegraph", root="/tmp/myproject")
        assert cfg["command"] == "codegraph"
        assert cfg["args"] == ["serve", "--mcp"]
        assert cfg["env"] == {"CODEGRAPH_PROJECT_ROOT": str(Path("/tmp/myproject").resolve())}

    def test_command_override_custom_python_uses_m_module(self):
        """Custom python path uses -m codegraph.mcp_server args.
        Global config does NOT write env."""
        cfg = build_server_config(command_override="/usr/bin/python3.12")
        assert cfg["command"] == "/usr/bin/python3.12"
        assert cfg["args"] == ["-m", "codegraph.mcp_server"]
        # Global auto-detect: no env
        assert "env" not in cfg


# ── read_config ───────────────────────────────────────────────────────────


class TestReadConfig:
    def test_file_not_exists(self, tmp_path):
        result = read_config(tmp_path / "nonexistent.json")
        assert result == {"mcpServers": {}}

    def test_empty_file(self, tmp_path):
        fp = tmp_path / "empty.json"
        fp.write_text("", encoding="utf-8")
        result = read_config(fp)
        assert result == {"mcpServers": {}}

    def test_valid_file(self, tmp_path):
        fp = tmp_path / "valid.json"
        fp.write_text('{"mcpServers": {"gh": {"command": "gh"}}}', encoding="utf-8")
        result = read_config(fp)
        assert result["mcpServers"]["gh"]["command"] == "gh"

    def test_file_without_mcp_servers_key(self, tmp_path):
        fp = tmp_path / "no_key.json"
        fp.write_text('{"numStartups": 5}', encoding="utf-8")
        result = read_config(fp)
        assert result["mcpServers"] == {}
        assert result["numStartups"] == 5

    def test_invalid_json(self, tmp_path):
        fp = tmp_path / "bad.json"
        fp.write_text("{invalid", encoding="utf-8")
        result = read_config(fp)
        assert result == {"mcpServers": {}}

    def test_non_dict_json(self, tmp_path):
        fp = tmp_path / "list.json"
        fp.write_text("[1, 2, 3]", encoding="utf-8")
        result = read_config(fp)
        assert result == {"mcpServers": {}}


# ── write_config ──────────────────────────────────────────────────────────


class TestWriteConfig:
    def test_creates_parent_dirs(self, tmp_path):
        fp = tmp_path / "deep" / "nested" / "config.json"
        write_config(fp, {"mcpServers": {}})
        assert fp.exists()
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data == {"mcpServers": {}}

    def test_writes_valid_json(self, tmp_path):
        fp = tmp_path / "cfg.json"
        write_config(fp, {"mcpServers": {"codegraph": {"command": "python"}}})
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert data["mcpServers"]["codegraph"]["command"] == "python"

    def test_preserves_extra_keys(self, tmp_path):
        fp = tmp_path / "cfg.json"
        data = {"numStartups": 42, "mcpServers": {"other": {"command": "npx"}}}
        write_config(fp, data)
        # Read back and verify
        result = read_config(fp)
        assert result["numStartups"] == 42
        assert result["mcpServers"]["other"]["command"] == "npx"


# ── configure_target ─────────────────────────────────────────────────────


class TestConfigureTarget:
    def test_configure_new(self, home_tmp):
        result = configure_target(ConfigTarget.CLAUDE)
        assert result["status"] == "configured"
        assert result["target"] == "claude"
        assert home_tmp.joinpath(".claude.json").exists()

    def test_configure_idempotent(self, home_tmp):
        configure_target(ConfigTarget.CLAUDE)
        result = configure_target(ConfigTarget.CLAUDE)
        assert result["status"] == "already_configured"

    def test_configure_force_overwrite(self, home_tmp):
        configure_target(ConfigTarget.CLAUDE, command_override="/old/python")
        result = configure_target(ConfigTarget.CLAUDE, command_override="/new/python", force=True)
        assert result["status"] == "overwritten"
        assert result["config"]["command"] == "/new/python"
        assert result["config"]["args"] == ["-m", "codegraph.mcp_server"]

    def test_configure_with_root(self, home_tmp):
        result = configure_target(ConfigTarget.CURSOR, root="/abs/project")
        assert result["config"]["env"] == {"CODEGRAPH_PROJECT_ROOT": str(Path("/abs/project").resolve())}

    def test_configure_project_level(self, tmp_path, monkeypatch):
        """Project-level config writes to ./mcp.json and ./.cursor/mcp.json."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "home" / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "home" / ".cursor" / "mcp.json")
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        result = configure_target(ConfigTarget.CLAUDE, project=True)
        assert result["status"] == "configured"
        project_cfg = tmp_path / ".mcp.json"
        assert project_cfg.exists()

    def test_configure_preserves_other_servers(self, home_tmp):
        # Pre-populate Claude config with another server
        fp = home_tmp / ".claude.json"
        fp.write_text(json.dumps({
            "mcpServers": {
                "figma": {"command": "npx", "args": ["-y", "figma-mcp"]}
            }
        }), encoding="utf-8")

        configure_target(ConfigTarget.CLAUDE)
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert "codegraph" in data["mcpServers"]
        assert "figma" in data["mcpServers"]


# ── remove_target ─────────────────────────────────────────────────────────


class TestRemoveTarget:
    def test_remove_existing(self, home_tmp):
        configure_target(ConfigTarget.CLAUDE)
        result = remove_target(ConfigTarget.CLAUDE)
        assert result["status"] == "removed"

        data = read_config(home_tmp / ".claude.json")
        assert MCP_SERVER_NAME not in data["mcpServers"]

    def test_remove_not_configured(self, home_tmp):
        result = remove_target(ConfigTarget.CURSOR)
        assert result["status"] == "not_configured"

    def test_remove_preserves_other_servers(self, home_tmp):
        fp = home_tmp / ".claude.json"
        fp.write_text(json.dumps({
            "mcpServers": {
                "figma": {"command": "npx"},
                "codegraph": {"command": "python"},
            }
        }), encoding="utf-8")

        remove_target(ConfigTarget.CLAUDE)
        data = json.loads(fp.read_text(encoding="utf-8"))
        assert "codegraph" not in data["mcpServers"]
        assert "figma" in data["mcpServers"]


# ── show_status ───────────────────────────────────────────────────────────


class TestShowStatus:
    def test_none_configured(self, home_tmp):
        status = show_status()
        assert status["claude"]["configured"] is False
        assert status["cursor"]["configured"] is False

    def test_one_configured(self, home_tmp):
        configure_target(ConfigTarget.CLAUDE)
        status = show_status()
        assert status["claude"]["configured"] is True
        assert status["cursor"]["configured"] is False

    def test_both_configured(self, home_tmp):
        configure_target(ConfigTarget.CLAUDE)
        configure_target(ConfigTarget.CURSOR)
        status = show_status()
        assert status["claude"]["configured"] is True
        assert status["cursor"]["configured"] is True

    def test_project_level_status(self, tmp_path, monkeypatch):
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "home" / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "home" / ".cursor" / "mcp.json")
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        configure_target(ConfigTarget.CLAUDE, project=True)
        status = show_status(project=True)
        assert status["claude"]["configured"] is True


# ── CLI integration tests ─────────────────────────────────────────────────


class TestCliConfigureAll:
    def test_configure_all_writes_both(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        assert "CONFIGURED" in result.stdout
        assert "codegraph" in result.stdout.lower()

        # Both config files should exist
        assert home_tmp.joinpath(".claude.json").exists()
        assert home_tmp.joinpath(".cursor", "mcp.json").exists()

        # Both should contain codegraph entry with sys.executable + -m
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cursor_data = json.loads(home_tmp.joinpath(".cursor", "mcp.json").read_text(encoding="utf-8"))
        assert "codegraph" in claude_data["mcpServers"]
        assert "codegraph" in cursor_data["mcpServers"]
        # Verify the default command format
        assert claude_data["mcpServers"]["codegraph"]["command"] == sys.executable
        assert claude_data["mcpServers"]["codegraph"]["args"] == ["-m", "codegraph.mcp_server"]

    def test_configure_all_idempotent(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        assert "already configured" in result.stdout.lower()

    def test_configure_all_with_force(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "all", "--force"])
        assert result.exit_code == 0
        assert "UPDATED" in result.stdout

    def test_configure_all_with_root(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "all", "--root", "/tmp/testproj"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert cfg["command"] == sys.executable
        assert cfg["args"] == ["-m", "codegraph.mcp_server"]
        assert cfg["env"]["CODEGRAPH_PROJECT_ROOT"] == str(Path("/tmp/testproj").resolve())

    def test_configure_all_force_updates_project_root(self, runner, home_tmp):
        """--force should update CODEGRAPH_PROJECT_ROOT even if already configured."""
        runner.invoke(app, ["configure", "all", "--root", "/old/path"])
        result = runner.invoke(app, ["configure", "all", "--root", "/new/path", "--force"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert cfg["args"] == ["-m", "codegraph.mcp_server"]
        assert cfg["env"]["CODEGRAPH_PROJECT_ROOT"] == str(Path("/new/path").resolve())

    def test_configure_all_defaults_global_auto_detect(self, runner, home_tmp):
        """configure all without --root writes global auto-detect config (no env)."""
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert cfg["command"] == sys.executable
        assert cfg["args"] == ["-m", "codegraph.mcp_server"]
        # Global config: no fixed CODEGRAPH_PROJECT_ROOT
        assert "env" not in cfg

    def test_configure_all_with_command_codegraph_legacy(self, runner, home_tmp):
        """--command codegraph writes legacy CLI entry point."""
        result = runner.invoke(app, ["configure", "all", "--command", "codegraph"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert cfg["command"] == "codegraph"
        assert cfg["args"] == ["serve", "--mcp"]

    def test_configure_all_shows_command_in_output(self, runner, home_tmp):
        """After configure, output shows the actual command being written."""
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        assert "Command:" in result.stdout
        assert "codegraph.mcp_server" in result.stdout

    def test_configure_all_shows_mode_in_output(self, runner, home_tmp):
        """After configure, output shows auto-detect mode."""
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        assert "Mode: global auto-detect" in result.stdout

    def test_configure_all_shows_current_directory_in_output(self, runner, home_tmp):
        """After configure, output shows current directory info."""
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        # The output should mention the current directory (auto-detect mode)
        assert "Current directory" in result.stdout

    def test_configure_all_global_no_env(self, runner, home_tmp):
        """Global config (no --root) does NOT write CODEGRAPH_PROJECT_ROOT."""
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        # Global auto-detect: no env block
        assert "env" not in cfg

    def test_configure_all_with_root_writes_env(self, runner, home_tmp):
        """configure all --root writes CODEGRAPH_PROJECT_ROOT in env."""
        result = runner.invoke(app, ["configure", "all", "--root", "/tmp/testproj"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert "env" in cfg
        assert cfg["env"]["CODEGRAPH_PROJECT_ROOT"] == str(Path("/tmp/testproj").resolve())

    def test_configure_project_writes_env(self, runner, tmp_path, monkeypatch):
        """--project writes project-level config with CODEGRAPH_PROJECT_ROOT."""
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "home" / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "home" / ".cursor" / "mcp.json")
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        result = runner.invoke(app, ["configure", "all", "--project"])
        assert result.exit_code == 0
        project_cfg = tmp_path / ".mcp.json"
        assert project_cfg.exists()
        data = json.loads(project_cfg.read_text(encoding="utf-8"))
        cg_cfg = data["mcpServers"]["codegraph"]
        assert "env" in cg_cfg
        assert cg_cfg["env"]["CODEGRAPH_PROJECT_ROOT"] == str(tmp_path.resolve())


class TestCliConfigureClaude:
    def test_configure_claude(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "claude"])
        assert result.exit_code == 0
        assert "CONFIGURED" in result.stdout
        assert home_tmp.joinpath(".claude.json").exists()

    def test_configure_claude_already_configured(self, runner, home_tmp):
        runner.invoke(app, ["configure", "claude"])
        result = runner.invoke(app, ["configure", "claude"])
        assert "already configured" in result.stdout.lower()


class TestCliConfigureCursor:
    def test_configure_cursor(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "cursor"])
        assert result.exit_code == 0
        assert "CONFIGURED" in result.stdout
        assert home_tmp.joinpath(".cursor", "mcp.json").exists()

    def test_configure_cursor_already_configured(self, runner, home_tmp):
        runner.invoke(app, ["configure", "cursor"])
        result = runner.invoke(app, ["configure", "cursor"])
        assert "already configured" in result.stdout.lower()


class TestCliConfigureShow:
    def test_show_not_configured(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "show"])
        assert result.exit_code == 0
        assert "NOT CONFIGURED" in result.stdout

    def test_show_after_configure(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "show"])
        assert result.exit_code == 0
        assert "CONFIGURED" in result.stdout

    def test_show_project_level(self, runner, tmp_path, monkeypatch):
        import codegraph.configure as cfg
        monkeypatch.setattr(cfg, "CLAUDE_USER_CONFIG", tmp_path / "home" / ".claude.json")
        monkeypatch.setattr(cfg, "CURSOR_USER_CONFIG", tmp_path / "home" / ".cursor" / "mcp.json")
        monkeypatch.setattr(Path, "cwd", lambda: tmp_path)

        runner.invoke(app, ["configure", "claude", "--project"])
        result = runner.invoke(app, ["configure", "show", "--project"])
        assert result.exit_code == 0
        assert "CONFIGURED" in result.stdout


class TestCliConfigureRemove:
    def test_remove_all(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "remove", "all"])
        assert result.exit_code == 0
        assert "REMOVED" in result.stdout

        # Verify removal
        status = show_status()
        assert status["claude"]["configured"] is False
        assert status["cursor"]["configured"] is False

    def test_remove_specific(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "remove", "claude"])
        assert result.exit_code == 0
        assert "REMOVED" in result.stdout

        status = show_status()
        assert status["claude"]["configured"] is False
        assert status["cursor"]["configured"] is True

    def test_remove_not_configured(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "remove", "claude"])
        assert result.exit_code == 0
        assert "SKIP" in result.stdout

    def test_remove_invalid_target(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "remove", "invalid"])
        assert result.exit_code != 0
        assert "error" in result.stderr.lower() or "error" in result.stdout.lower()
