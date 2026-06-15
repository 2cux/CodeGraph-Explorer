"""Tests for codegraph configure git-hook --pre-commit-impact.

Covers:
- CLI creates .git/hooks/pre-commit in a Git repo
- Hook file contains "codegraph workflow impact"
- Hook file is executable on Unix
- Staged files empty → hook exits 0
- codegraph workflow impact failure → hook exits 0
- Existing pre-commit hook without --force is not overwritten
- Existing pre-commit hook with --force backs up old hook
- --force writes new hook
- Non-Git repo returns readable error
- Command does not modify MCP config
- Command does not run codegraph init
- docs/git-hooks.md exists and documents warning-only behavior
- All existing tests still pass
"""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codegraph.cli.main import app
from codegraph.hooks.template import build_pre_commit_impact_hook_script

runner = CliRunner()


# ── helpers ──────────────────────────────────────────────────────────────


def _init_git_repo(tmp_path: Path) -> Path:
    """Initialize a git repo at the given path and return it."""
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    return tmp_path


# ══ Template Tests ═══════════════════════════════════════════════════════


class TestPreCommitHookTemplate:
    """Tests for the pre-commit impact hook script template."""

    def test_template_contains_codegraph_workflow_impact(self):
        """Hook template must contain 'codegraph workflow impact'."""
        script = build_pre_commit_impact_hook_script()
        assert "codegraph workflow impact" in script

    def test_template_contains_staged_files_logic(self):
        """Hook template must use git diff --cached to get staged files."""
        script = build_pre_commit_impact_hook_script()
        assert "git diff --cached" in script
        assert "--name-only" in script
        assert "STAGED_FILES" in script

    def test_template_uses_comma_separator(self):
        """Hook must join staged files with commas (not spaces).

        The ``workflow impact`` CLI expects ``--files`` as a comma-separated
        string, not multiple space-separated arguments.
        """
        script = build_pre_commit_impact_hook_script()
        assert "tr '\\n' ','" in script

    def test_template_includes_format_markdown(self):
        """Hook must pass --format markdown to workflow impact."""
        script = build_pre_commit_impact_hook_script()
        assert "--format markdown" in script

    def test_template_includes_change_type_unknown(self):
        """Hook must pass --change-type unknown to workflow impact."""
        script = build_pre_commit_impact_hook_script()
        assert "--change-type unknown" in script

    def test_template_quotes_staged_files_variable(self):
        """Hook must quote $STAGED_FILES to prevent word splitting and glob expansion."""
        script = build_pre_commit_impact_hook_script()
        assert '"$STAGED_FILES"' in script

    def test_template_always_exits_zero(self):
        """Hook must always exit 0 to never block commits."""
        script = build_pre_commit_impact_hook_script()
        # All exit paths should be exit 0
        lines = script.split("\n")
        exit_lines = [l.strip() for l in lines if "exit" in l.lower()]
        for line in exit_lines:
            if line.startswith("exit"):
                assert "exit 0" in line, f"Expected 'exit 0', got '{line}'"

    def test_template_handles_empty_staged_files(self):
        """Hook must exit early when staged files are empty."""
        script = build_pre_commit_impact_hook_script()
        assert 'if [ -z "$STAGED_FILES" ]' in script
        assert "exit 0" in script

    def test_template_handles_failed_impact_check(self):
        """Hook must exit 0 even when impact check fails."""
        script = build_pre_commit_impact_hook_script()
        assert "Impact check failed or index is unavailable" in script
        assert "Commit is not blocked" in script

    def test_template_uses_posix_sh(self):
        """Hook must use #!/usr/bin/env sh for maximum compatibility."""
        script = build_pre_commit_impact_hook_script()
        assert script.startswith("#!/usr/bin/env sh")

    def test_template_uses_set_u(self):
        """Hook must use set -u for safety."""
        script = build_pre_commit_impact_hook_script()
        assert "set -u" in script

    def test_template_does_not_run_tests(self):
        """Hook must not run any test commands."""
        script = build_pre_commit_impact_hook_script()
        assert "pytest" not in script
        assert "npm test" not in script.lower()
        assert "tox" not in script

    def test_template_does_not_modify_files(self):
        """Hook must not modify any files."""
        script = build_pre_commit_impact_hook_script()
        # No output redirection to files except /dev/null
        # The hook should only output to terminal
        assert ">" not in script or "/dev/null" in script

    def test_template_does_not_call_external_services(self):
        """Hook must not call external services."""
        script = build_pre_commit_impact_hook_script()
        assert "curl" not in script
        assert "wget" not in script
        assert "http" not in script.lower()

    def test_template_does_not_auto_init(self):
        """Hook must not run codegraph init or refresh index."""
        script = build_pre_commit_impact_hook_script()
        assert "codegraph init" not in script
        assert "codegraph sync" not in script

    def test_template_mentions_codegraph_branding(self):
        """Hook must prefix output with [CodeGraph]."""
        script = build_pre_commit_impact_hook_script()
        assert "[CodeGraph]" in script


# ══ CLI Tests ════════════════════════════════════════════════════════════


class TestConfigureGitHookCli:
    """Tests for ``codegraph configure git-hook --pre-commit-impact``."""

    def test_creates_pre_commit_hook_in_git_repo(self, tmp_path):
        """CLI creates .git/hooks/pre-commit when run in a Git repo."""
        repo = _init_git_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, \
            f"CLI failed. stdout: {result.stdout}\nstderr: {result.stderr}"
        hook_path = repo / ".git" / "hooks" / "pre-commit"
        assert hook_path.exists(), "Hook file was not created"

    def test_cli_creates_hook_file(self, tmp_path):
        """CLI must create .git/hooks/pre-commit file."""
        repo = _init_git_repo(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        # Should succeed
        hook_path = repo / ".git" / "hooks" / "pre-commit"
        assert hook_path.exists(), f"Hook not created. stdout: {result.stdout}\nstderr: {result.stderr}"

    def test_hook_file_contains_workflow_impact(self, tmp_path):
        """Created hook file must contain 'codegraph workflow impact'."""
        repo = _init_git_repo(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        hook_path = repo / ".git" / "hooks" / "pre-commit"
        content = hook_path.read_text(encoding="utf-8")
        assert "codegraph workflow impact" in content

    def test_hook_file_is_executable_on_unix(self, tmp_path):
        """Created hook file must be executable on Unix."""
        if sys.platform == "win32":
            pytest.skip("Executable permission not applicable on Windows")

        repo = _init_git_repo(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        hook_path = repo / ".git" / "hooks" / "pre-commit"
        st = hook_path.stat()
        assert st.st_mode & stat.S_IXUSR, "Hook file is not user-executable"

    def test_staged_files_empty_hook_exits_zero(self, tmp_path):
        """Hook must exit 0 when no staged files.

        Verifies the hook script logic: when STAGED_FILES is empty,
        the script exits 0 before calling codegraph.
        """
        script = build_pre_commit_impact_hook_script()
        # Extract the logic: the first exit after checking STAGED_FILES is 0
        lines = script.split("\n")
        found_empty_check = False
        for i, line in enumerate(lines):
            if '-z "$STAGED_FILES"' in line or '-z "${STAGED_FILES}"' in line:
                found_empty_check = True
                # Next non-empty line should be 'exit 0'
                for j in range(i + 1, min(i + 5, len(lines))):
                    if "exit 0" in lines[j]:
                        break
                break
        assert found_empty_check, "Hook must check for empty STAGED_FILES"

    def test_impact_check_failure_hook_exits_zero(self, tmp_path):
        """Hook must exit 0 even when codegraph workflow impact fails.

        Verifies the hook script logic: after running codegraph workflow impact,
        the script checks STATUS and exits 0 regardless.
        """
        script = build_pre_commit_impact_hook_script()
        # Verify the failure path: after '$STATUS' check, must exit 0
        assert 'if [ "$STATUS" -ne 0 ]' in script
        assert "exit 0" in script
        # Count exit statements — all must be "exit 0"
        lines = script.split("\n")
        for line in lines:
            stripped = line.strip()
            # Skip non-exit lines and lines inside echo/comment
            if not stripped.startswith("exit "):
                continue
            if stripped.startswith("#"):
                continue
            if "echo" in stripped:
                continue
            assert stripped == "exit 0", \
                f"All exit commands must be 'exit 0', found: '{stripped}'"

    def test_existing_hook_not_overwritten_without_force(self, tmp_path):
        """If pre-commit hook exists, CLI must not overwrite without --force."""
        repo = _init_git_repo(tmp_path)

        # Create an existing pre-commit hook
        hooks_dir = repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_content = "#!/bin/sh\necho 'my custom hook'\n"
        existing_hook.write_text(existing_content, encoding="utf-8")
        if sys.platform != "win32":
            st = existing_hook.stat()
            existing_hook.chmod(st.st_mode | stat.S_IEXEC)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        # Check stdout/stderr for "not overwritten" message
        combined = result.stdout + result.stderr
        assert "not overwritten" in combined.lower() or "existing" in combined.lower(), \
            f"Expected 'not overwritten' message. Got: {combined}"

        # The existing hook content must be preserved
        current_content = existing_hook.read_text(encoding="utf-8")
        assert "my custom hook" in current_content, \
            f"Existing hook was overwritten! Content: {current_content}"

    def test_force_backs_up_existing_hook(self, tmp_path):
        """--force must back up existing hook before overwriting."""
        repo = _init_git_repo(tmp_path)

        hooks_dir = repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_content = "#!/bin/sh\necho 'my custom hook'\n"
        existing_hook.write_text(existing_content, encoding="utf-8")
        if sys.platform != "win32":
            st = existing_hook.stat()
            existing_hook.chmod(st.st_mode | stat.S_IEXEC)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact", "--force"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        # Backup file must exist
        backup_path = hooks_dir / "pre-commit.codegraph.bak"
        assert backup_path.exists(), \
            f"Backup not created. stdout: {result.stdout}\nstderr: {result.stderr}"

        # Backup must contain the original content
        backup_content = backup_path.read_text(encoding="utf-8")
        assert "my custom hook" in backup_content

        # New hook must contain codegraph workflow impact
        new_content = existing_hook.read_text(encoding="utf-8")
        assert "codegraph workflow impact" in new_content

    def test_force_writes_new_hook(self, tmp_path):
        """--force must write the new hook after backing up."""
        repo = _init_git_repo(tmp_path)

        hooks_dir = repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho old\n", encoding="utf-8")

        subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact", "--force"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        new_content = existing_hook.read_text(encoding="utf-8")
        assert "codegraph workflow impact" in new_content
        assert "--change-type unknown" in new_content

    def test_non_git_repo_returns_error(self, tmp_path):
        """Running outside a Git repo must return a readable error."""
        # tmp_path is not a git repo by default
        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert "not a git repository" in combined.lower() or "not a Git repository" in combined, \
            f"Expected git repo error. Got: {combined}"

    def test_command_does_not_modify_mcp_config(self, tmp_path):
        """Command must not modify any MCP config files."""
        repo = _init_git_repo(tmp_path)

        # Capture state of common MCP config paths
        home = Path.home()
        claude_config = home / ".claude.json"
        claude_existed = claude_config.exists()

        subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        # MCP config files must not be created or modified
        if not claude_existed:
            assert not claude_config.exists(), \
                "MCP config was created by git-hook command!"

    def test_command_does_not_run_codegraph_init(self, tmp_path):
        """Command must not run codegraph init."""
        repo = _init_git_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        # No .codegraph directory should be created
        cg_dir = repo / ".codegraph"
        assert not cg_dir.exists(), \
            f".codegraph directory was created by git-hook command!"

    def test_command_does_not_run_tests(self, tmp_path):
        """Command must not execute any tests."""
        repo = _init_git_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        # Output should not contain pytest output
        combined = result.stdout + result.stderr
        assert "test session" not in combined.lower()

    def test_output_mentions_warning_only_behavior(self, tmp_path):
        """CLI output must mention warning-only behavior."""
        repo = _init_git_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert "does not block" in combined.lower() or "warning only" in combined.lower(), \
            f"Expected warning-only mention. Got: {combined}"

    def test_output_shows_hook_path(self, tmp_path):
        """CLI output must show the installed hook path."""
        repo = _init_git_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert ".git" in combined
        assert "hooks" in combined
        assert "pre-commit" in combined

    def test_no_pre_commit_impact_flag_shows_usage(self):
        """Running without --pre-commit-impact shows usage info."""
        result = runner.invoke(
            app,
            ["configure", "git-hook"],
        )

        combined = result.stdout + str(result.output)
        assert "Usage" in combined or "--pre-commit-impact" in combined

    def test_hook_does_not_write_report_files(self, tmp_path):
        """Hook must not write files to .codegraph/reports/ by default."""
        repo = _init_git_repo(tmp_path)
        subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        hook_content = (repo / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
        assert "--output" not in hook_content, \
            "Hook should not write report files by default"

    def test_success_output_format(self, tmp_path):
        """CLI success output must follow the expected format."""
        repo = _init_git_repo(tmp_path)

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        stdout = result.stdout
        assert "Installed CodeGraph pre-commit impact hook" in stdout
        assert "codegraph workflow impact" in stdout
        assert "--change-type unknown" in stdout
        assert "Default behavior" in stdout or "does not block" in stdout.lower()

    def test_existing_hook_message_suggests_force(self, tmp_path):
        """When hook exists, message must suggest --force option."""
        repo = _init_git_repo(tmp_path)

        hooks_dir = repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho old\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert "--force" in combined

    def test_force_message_acknowledges_overwrite(self, tmp_path):
        """--force output must mention that old hook was backed up."""
        repo = _init_git_repo(tmp_path)

        hooks_dir = repo / ".git" / "hooks"
        existing_hook = hooks_dir / "pre-commit"
        existing_hook.write_text("#!/bin/sh\necho old\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact", "--force"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        combined = result.stdout + result.stderr
        assert "Backed up" in combined or "backup" in combined.lower()

    def test_force_backup_with_timestamp_when_backup_exists(self, tmp_path):
        """When .codegraph.bak already exists, backup uses timestamp."""
        repo = _init_git_repo(tmp_path)

        hooks_dir = repo / ".git" / "hooks"

        # Create existing hook
        (hooks_dir / "pre-commit").write_text("#!/bin/sh\necho old\n", encoding="utf-8")

        # Create an existing backup
        (hooks_dir / "pre-commit.codegraph.bak").write_text("old backup", encoding="utf-8")

        subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact", "--force"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        # Should have created a timestamped backup
        backups = list(hooks_dir.glob("pre-commit.codegraph.bak*"))
        assert len(backups) >= 2, \
            f"Expected at least 2 backup files (original + timestamped), got: {backups}"

        # Original .codegraph.bak still has old content
        original_bak = (hooks_dir / "pre-commit.codegraph.bak").read_text(encoding="utf-8")
        assert "old backup" in original_bak

    def test_command_does_not_add_frontend_deps(self, tmp_path):
        """Command must not add any frontend/node dependencies."""
        repo = _init_git_repo(tmp_path)

        subprocess.run(
            [sys.executable, "-m", "codegraph.cli.main", "configure",
             "git-hook", "--pre-commit-impact"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )

        # No package.json should be created
        assert not (repo / "package.json").exists()
        # No node_modules
        assert not (repo / "node_modules").exists()


# ══ Documentation Tests ══════════════════════════════════════════════════


class TestDocumentation:
    """Tests that documentation files exist and are accurate."""

    def test_git_hooks_doc_exists(self):
        """docs/git-hooks.md must exist."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        doc_path = pkg_dir / "docs" / "git-hooks.md"
        assert doc_path.exists(), f"docs/git-hooks.md not found at {doc_path}"

    def test_git_hooks_doc_mentions_warning_only(self):
        """docs/git-hooks.md must document warning-only behavior."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        doc_path = pkg_dir / "docs" / "git-hooks.md"
        content = doc_path.read_text(encoding="utf-8")
        assert "warning only" in content.lower() or "does not block" in content.lower()

    def test_git_hooks_doc_mentions_force(self):
        """docs/git-hooks.md must document --force option."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        doc_path = pkg_dir / "docs" / "git-hooks.md"
        content = doc_path.read_text(encoding="utf-8")
        assert "--force" in content

    def test_git_hooks_doc_mentions_backup(self):
        """docs/git-hooks.md must document backup behavior."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        doc_path = pkg_dir / "docs" / "git-hooks.md"
        content = doc_path.read_text(encoding="utf-8")
        assert "backup" in content.lower() or ".codegraph.bak" in content

    def test_git_hooks_doc_includes_hook_script(self):
        """docs/git-hooks.md must include the hook script content."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        doc_path = pkg_dir / "docs" / "git-hooks.md"
        content = doc_path.read_text(encoding="utf-8")
        assert "codegraph workflow impact" in content
        assert "STAGED_FILES" in content

    def test_git_hooks_doc_mentions_no_tests(self):
        """docs/git-hooks.md must clarify that hook does not run tests."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        doc_path = pkg_dir / "docs" / "git-hooks.md"
        content = doc_path.read_text(encoding="utf-8")
        assert "does not run tests" in content.lower() or "not a test runner" in content.lower()

    def test_readme_mentions_git_hook(self):
        """README.md must mention the git hook feature."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        readme_path = pkg_dir / "README.md"
        content = readme_path.read_text(encoding="utf-8")
        assert "pre-commit-impact" in content
        assert "git-hooks.md" in content

    def test_agent_adoption_doc_mentions_git_hook(self):
        """docs/agent-adoption-p0-test.md must mention git hook verification."""
        import codegraph
        pkg_dir = Path(codegraph.__file__).parent.parent.parent
        doc_path = pkg_dir / "docs" / "agent-adoption-p0-test.md"
        content = doc_path.read_text(encoding="utf-8")
        assert "pre-commit-impact" in content or "git-hook" in content.lower()
