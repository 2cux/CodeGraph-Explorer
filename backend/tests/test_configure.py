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
    def test_without_root_defaults_to_cwd(self):
        """When root is not provided, CODEGRAPH_PROJECT_ROOT defaults to CWD absolute path."""
        cfg = build_server_config()
        assert cfg["command"] == sys.executable
        assert cfg["args"] == ["-m", "codegraph.mcp_server"]
        assert "env" in cfg
        assert "CODEGRAPH_PROJECT_ROOT" in cfg["env"]
        assert Path(cfg["env"]["CODEGRAPH_PROJECT_ROOT"]).is_absolute()
        assert cfg["env"]["CODEGRAPH_PROJECT_ROOT"] == str(Path.cwd().resolve())

    def test_with_root(self):
        cfg = build_server_config(root="/tmp/myproject")
        assert cfg["env"] == {"CODEGRAPH_PROJECT_ROOT": "/tmp/myproject"}

    def test_custom_python_command(self):
        cfg = build_server_config(python_command="/usr/bin/python3.12")
        assert cfg["command"] == "/usr/bin/python3.12"

    def test_default_python_is_sys_executable(self):
        cfg = build_server_config()
        assert cfg["command"] == sys.executable


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
        configure_target(ConfigTarget.CLAUDE, python_command="/old/python")
        result = configure_target(ConfigTarget.CLAUDE, python_command="/new/python", force=True)
        assert result["status"] == "overwritten"
        assert result["config"]["command"] == "/new/python"

    def test_configure_with_root(self, home_tmp):
        result = configure_target(ConfigTarget.CURSOR, root="/abs/project")
        assert result["config"]["env"] == {"CODEGRAPH_PROJECT_ROOT": "/abs/project"}

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
        assert "[ok] claude: configured" in result.stdout.lower()
        assert "[ok] cursor: configured" in result.stdout.lower()

        # Both config files should exist
        assert home_tmp.joinpath(".claude.json").exists()
        assert home_tmp.joinpath(".cursor", "mcp.json").exists()

        # Both should contain codegraph entry
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cursor_data = json.loads(home_tmp.joinpath(".cursor", "mcp.json").read_text(encoding="utf-8"))
        assert "codegraph" in claude_data["mcpServers"]
        assert "codegraph" in cursor_data["mcpServers"]

    def test_configure_all_idempotent(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        assert "Skipped to avoid overwriting" in result.stdout

    def test_configure_all_with_force(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "all", "--force"])
        assert result.exit_code == 0
        assert "[ok]" in result.stdout.lower()
        assert "overwritten" in result.stdout.lower()

    def test_configure_all_with_root(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "all", "--root", "/tmp/testproj"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert cfg["env"]["CODEGRAPH_PROJECT_ROOT"] == "/tmp/testproj"

    def test_configure_all_force_updates_project_root(self, runner, home_tmp):
        """--force should update CODEGRAPH_PROJECT_ROOT even if already configured."""
        runner.invoke(app, ["configure", "all", "--root", "/old/path"])
        result = runner.invoke(app, ["configure", "all", "--root", "/new/path", "--force"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert cfg["env"]["CODEGRAPH_PROJECT_ROOT"] == "/new/path"

    def test_configure_all_defaults_cwd_in_env(self, runner, home_tmp):
        """configure all without --root writes CWD as absolute path."""
        result = runner.invoke(app, ["configure", "all"])
        assert result.exit_code == 0
        claude_data = json.loads(home_tmp.joinpath(".claude.json").read_text(encoding="utf-8"))
        cfg = claude_data["mcpServers"]["codegraph"]
        assert "CODEGRAPH_PROJECT_ROOT" in cfg["env"]
        assert Path(cfg["env"]["CODEGRAPH_PROJECT_ROOT"]).is_absolute()


class TestCliConfigureClaude:
    def test_configure_claude(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "claude"])
        assert result.exit_code == 0
        assert "[ok] claude: configured" in result.stdout.lower()
        assert home_tmp.joinpath(".claude.json").exists()

    def test_configure_claude_already_configured(self, runner, home_tmp):
        runner.invoke(app, ["configure", "claude"])
        result = runner.invoke(app, ["configure", "claude"])
        assert "Skipped to avoid overwriting" in result.stdout


class TestCliConfigureCursor:
    def test_configure_cursor(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "cursor"])
        assert result.exit_code == 0
        assert "[ok] cursor: configured" in result.stdout.lower()
        assert home_tmp.joinpath(".cursor", "mcp.json").exists()

    def test_configure_cursor_already_configured(self, runner, home_tmp):
        runner.invoke(app, ["configure", "cursor"])
        result = runner.invoke(app, ["configure", "cursor"])
        assert "Skipped to avoid overwriting" in result.stdout


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
        assert "removed" in result.stdout.lower()

        # Verify removal
        status = show_status()
        assert status["claude"]["configured"] is False
        assert status["cursor"]["configured"] is False

    def test_remove_specific(self, runner, home_tmp):
        runner.invoke(app, ["configure", "all"])
        result = runner.invoke(app, ["configure", "remove", "claude"])
        assert result.exit_code == 0
        assert "claude: removed" in result.stdout.lower()

        status = show_status()
        assert status["claude"]["configured"] is False
        assert status["cursor"]["configured"] is True

    def test_remove_not_configured(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "remove", "claude"])
        assert result.exit_code == 0
        assert "not configured" in result.stdout.lower()

    def test_remove_invalid_target(self, runner, home_tmp):
        result = runner.invoke(app, ["configure", "remove", "invalid"])
        assert result.exit_code != 0
        assert "error" in result.stderr.lower() or "error" in result.stdout.lower()
