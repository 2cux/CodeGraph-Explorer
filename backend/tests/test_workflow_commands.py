"""Tests for CodeGraph workflow commands (codegraph configure workflows).

Verifies:
- CLI creates .claude/commands/ directory and 4 workflow command files
- Each file contains the expected MCP tool name
- --force overwrites existing files, default skips them
- Templates do not hardcode project paths or CODEGRAPH_PROJECT_ROOT
- Command does not modify MCP config or install git hooks
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── Template content tests ──────────────────────────────────────────────────


class TestTemplateContent:
    """Verify the template files contain the correct MCP tool references."""

    @pytest.fixture
    def templates_dir(self) -> Path:
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent
        return pkg_dir / "templates" / "claude_commands"

    def test_all_four_templates_exist(self, templates_dir):
        """All 4 template files must exist in the package."""
        expected = [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]
        for name in expected:
            path = templates_dir / name
            assert path.exists(), f"Template missing: {name}"

    def test_impact_contains_pre_edit_check(self, templates_dir):
        """codegraph-impact.md must mention codegraph_pre_edit_check."""
        text = (templates_dir / "codegraph-impact.md").read_text(encoding="utf-8")
        assert "codegraph_pre_edit_check" in text
        assert "codegraph_get_impact" in text
        assert "codegraph_repo_status" in text

    def test_test_audit_contains_coverage_gaps(self, templates_dir):
        """codegraph-test-audit.md must mention codegraph_coverage_gaps."""
        text = (templates_dir / "codegraph-test-audit.md").read_text(encoding="utf-8")
        assert "codegraph_coverage_gaps" in text
        assert "codegraph_repo_status" in text

    def test_explain_contains_explain(self, templates_dir):
        """codegraph-explain.md must mention codegraph_explain."""
        text = (templates_dir / "codegraph-explain.md").read_text(encoding="utf-8")
        assert "codegraph_explain" in text
        assert "codegraph_get_neighbors" in text

    def test_find_contains_find(self, templates_dir):
        """codegraph-find.md must mention codegraph_find."""
        text = (templates_dir / "codegraph-find.md").read_text(encoding="utf-8")
        assert "codegraph_find" in text
        assert "codegraph_get_neighbors" in text

    def test_no_hardcoded_project_root(self, templates_dir):
        """No template should hardcode CODEGRAPH_PROJECT_ROOT."""
        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            text = (templates_dir / name).read_text(encoding="utf-8")
            assert "CODEGRAPH_PROJECT_ROOT" not in text, (
                f"{name} must not hardcode CODEGRAPH_PROJECT_ROOT"
            )

    def test_no_hardcoded_absolute_path(self, templates_dir):
        """No template should contain an absolute path to the current project."""
        import codegraph
        pkg_dir = str(Path(codegraph.__file__).parent.parent.parent.resolve())
        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            text = (templates_dir / name).read_text(encoding="utf-8")
            assert pkg_dir not in text, (
                f"{name} must not hardcode the CodeGraph-Explorer project path"
            )

    def test_no_frontend_or_dashboard_content(self, templates_dir):
        """Templates must not reference dashboards, browsers, or frontend UI."""
        banned = ["dashboard", "browser ui", "frontend", "visualization", "web ui"]
        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            text = (templates_dir / name).read_text(encoding="utf-8").lower()
            for term in banned:
                assert term not in text, (
                    f"{name} must not contain '{term}'"
                )

    def test_no_git_hook_references(self, templates_dir):
        """Templates must not reference git hooks."""
        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            text = (templates_dir / name).read_text(encoding="utf-8")
            assert "git hook" not in text.lower(), (
                f"{name} must not reference git hooks"
            )
            assert "post-commit" not in text.lower(), (
                f"{name} must not reference post-commit hook"
            )

    def test_all_templates_mention_repo_status(self, templates_dir):
        """Every workflow template should suggest checking repo_status first."""
        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            text = (templates_dir / name).read_text(encoding="utf-8")
            assert "codegraph_repo_status" in text, (
                f"{name} must mention codegraph_repo_status"
            )

    def test_all_templates_anti_pattern_do_not_grep_first(self, templates_dir):
        """Every template should advise against starting with Grep/Glob/Read."""
        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            text = (templates_dir / name).read_text(encoding="utf-8")
            has_anti_grep = (
                "Do not start" in text
                and ("Grep" in text or "Glob" in text or "Read" in text or "grep" in text.lower())
            )
            assert has_anti_grep, (
                f"{name} must advise against starting with Grep/Glob/Read"
            )


# ── CLI integration tests ───────────────────────────────────────────────────


class TestCliConfigureWorkflows:
    """Verify the ``codegraph configure workflows`` CLI command."""

    def test_creates_directory_and_files(self, runner, tmp_path, monkeypatch):
        """Running configure workflows creates .claude/commands/ and 4 files."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        assert result.exit_code == 0

        cmd_dir = tmp_path / ".claude" / "commands"
        assert cmd_dir.is_dir(), ".claude/commands/ should be created"

        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            fpath = cmd_dir / name
            assert fpath.exists(), f"{name} should be created"
            content = fpath.read_text(encoding="utf-8")
            assert len(content) > 100, f"{name} should have meaningful content"

    def test_output_lists_installed_files(self, runner, tmp_path, monkeypatch):
        """Output should list all installed files and usage commands."""
        monkeypatch.chdir(tmp_path)

        result = runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        assert result.exit_code == 0

        assert ".claude/commands/codegraph-impact.md" in result.stdout
        assert ".claude/commands/codegraph-test-audit.md" in result.stdout
        assert ".claude/commands/codegraph-explain.md" in result.stdout
        assert ".claude/commands/codegraph-find.md" in result.stdout

        assert "/codegraph-impact" in result.stdout
        assert "/codegraph-test-audit" in result.stdout
        assert "/codegraph-explain" in result.stdout
        assert "/codegraph-find" in result.stdout

    def test_skips_existing_files_without_force(self, runner, tmp_path, monkeypatch):
        """Second run without --force should skip all existing files."""
        monkeypatch.chdir(tmp_path)

        # First install
        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])

        # Second install (should skip)
        result = runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        assert result.exit_code == 0
        assert "SKIP" in result.stdout
        assert "already exists" in result.stdout
        assert "All workflow commands already exist" in result.stdout

    def test_overwrites_with_force(self, runner, tmp_path, monkeypatch):
        """--force should overwrite existing files."""
        monkeypatch.chdir(tmp_path)

        # First install
        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])

        # Modify one file to detect overwrite
        cmd_dir = tmp_path / ".claude" / "commands"
        impact_file = cmd_dir / "codegraph-impact.md"
        impact_file.write_text("modified content", encoding="utf-8")

        # Force install
        result = runner.invoke(app, ["configure", "workflows", "--agent", "claude", "--force"])
        assert result.exit_code == 0
        assert "Overwritten" in result.stdout

        # Verify content was overwritten (restored from template)
        content = impact_file.read_text(encoding="utf-8")
        assert "codegraph_pre_edit_check" in content
        assert content != "modified content"

    def test_written_files_contain_correct_mcp_tools(self, runner, tmp_path, monkeypatch):
        """Installed files must contain the expected MCP tool names."""
        monkeypatch.chdir(tmp_path)

        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        cmd_dir = tmp_path / ".claude" / "commands"

        impact = (cmd_dir / "codegraph-impact.md").read_text(encoding="utf-8")
        assert "codegraph_pre_edit_check" in impact
        assert "codegraph_get_impact" in impact

        audit = (cmd_dir / "codegraph-test-audit.md").read_text(encoding="utf-8")
        assert "codegraph_coverage_gaps" in audit

        explain = (cmd_dir / "codegraph-explain.md").read_text(encoding="utf-8")
        assert "codegraph_explain" in explain

        find = (cmd_dir / "codegraph-find.md").read_text(encoding="utf-8")
        assert "codegraph_find" in find

    def test_unsupported_agent_exits_with_error(self, runner):
        """Unsupported --agent should exit with code 1 and error message."""
        result = runner.invoke(app, ["configure", "workflows", "--agent", "cursor"])
        assert result.exit_code == 1
        assert "error" in result.stdout.lower() or "error" in result.stderr.lower()

    def test_written_files_dont_hardcode_project_root(self, runner, tmp_path, monkeypatch):
        """Installed files must not contain CODEGRAPH_PROJECT_ROOT."""
        monkeypatch.chdir(tmp_path)

        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        cmd_dir = tmp_path / ".claude" / "commands"

        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            content = (cmd_dir / name).read_text(encoding="utf-8")
            assert "CODEGRAPH_PROJECT_ROOT" not in content, (
                f"Installed {name} must not contain CODEGRAPH_PROJECT_ROOT"
            )

    def test_written_files_dont_hardcode_absolute_paths(self, runner, tmp_path, monkeypatch):
        """Installed files must not contain the CodeGraph-Explorer project path."""
        monkeypatch.chdir(tmp_path)

        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        cmd_dir = tmp_path / ".claude" / "commands"

        import codegraph
        repo_root = str(Path(codegraph.__file__).parent.parent.parent.resolve())

        for name in [
            "codegraph-impact.md",
            "codegraph-test-audit.md",
            "codegraph-explain.md",
            "codegraph-find.md",
        ]:
            content = (cmd_dir / name).read_text(encoding="utf-8")
            assert repo_root not in content, (
                f"Installed {name} must not contain the CodeGraph-Explorer repo path"
            )

    def test_does_not_modify_mcp_config(self, runner, tmp_path, monkeypatch):
        """configure workflows must not touch MCP config files."""
        monkeypatch.chdir(tmp_path)

        # Pre-create a .claude.json (MCP config) with some content
        claude_json = tmp_path / ".claude.json"
        claude_json.write_text(
            json.dumps({"mcpServers": {"other": {"command": "npx"}}}),
            encoding="utf-8",
        )

        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])

        # MCP config should be untouched
        assert claude_json.exists()
        data = json.loads(claude_json.read_text(encoding="utf-8"))
        assert "codegraph" not in data.get("mcpServers", {}), (
            "configure workflows must not add codegraph to MCP config"
        )
        assert data["mcpServers"]["other"]["command"] == "npx"

    def test_does_not_create_mcp_json(self, runner, tmp_path, monkeypatch):
        """configure workflows must not create .mcp.json file."""
        monkeypatch.chdir(tmp_path)

        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])

        mcp_json = tmp_path / ".mcp.json"
        assert not mcp_json.exists(), (
            "configure workflows must not create .mcp.json"
        )

    def test_does_not_install_git_hook(self, runner, tmp_path, monkeypatch):
        """configure workflows must not install git hooks."""
        monkeypatch.chdir(tmp_path)

        # Initialize a git repo
        import subprocess
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)

        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])

        # Check hooks directory
        hooks_dir = tmp_path / ".git" / "hooks"
        post_commit = hooks_dir / "post-commit"
        if post_commit.exists():
            content = post_commit.read_text(encoding="utf-8")
            # Should NOT contain CodeGraph hook content
            assert "codegraph" not in content.lower(), (
                "configure workflows must not install git hooks"
            )

    def test_cwd_without_dot_claude_creates_it(self, runner, tmp_path, monkeypatch):
        """Even if .claude/ doesn't exist, configure workflows should create it."""
        monkeypatch.chdir(tmp_path)

        # No .claude directory exists yet
        assert not (tmp_path / ".claude").exists()

        result = runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        assert result.exit_code == 0

        assert (tmp_path / ".claude" / "commands").is_dir()

    def test_partial_existing_files(self, runner, tmp_path, monkeypatch):
        """When some files exist and some don't, install only missing ones."""
        monkeypatch.chdir(tmp_path)

        # First install
        runner.invoke(app, ["configure", "workflows", "--agent", "claude"])

        # Delete one file
        cmd_dir = tmp_path / ".claude" / "commands"
        (cmd_dir / "codegraph-find.md").unlink()

        # Second install (no --force)
        result = runner.invoke(app, ["configure", "workflows", "--agent", "claude"])
        assert result.exit_code == 0

        # The deleted file should be reinstalled
        assert "Installed" in result.stdout
        assert "codegraph-find.md" in result.stdout

        # Existing files should be skipped
        assert "SKIP" in result.stdout

    def test_agent_is_required(self, runner):
        """--agent is a required option."""
        result = runner.invoke(app, ["configure", "workflows"])
        assert result.exit_code != 0


# ── CLI help text tests ─────────────────────────────────────────────────────


class TestCliHelp:
    """Verify the workflows subcommand appears in CLI help."""

    def test_configure_help_shows_workflows(self, runner):
        """codegraph configure --help should list workflows subcommand."""
        result = runner.invoke(app, ["configure", "--help"])
        assert result.exit_code == 0
        assert "workflows" in result.stdout

    def test_workflows_help_shows_agent_option(self, runner):
        """codegraph configure workflows --help should document --agent."""
        result = runner.invoke(app, ["configure", "workflows", "--help"])
        assert result.exit_code == 0
        assert "--agent" in result.stdout
        assert "--force" in result.stdout
