"""Integration tests for the full enrichment pipeline."""

import json
from pathlib import Path
import pytest
from typer.testing import CliRunner
from codegraph.cli.main import app
from codegraph.enrich.models import AgentOutput, EnrichedFile, EnrichedSymbol, EnrichedEvidence
from codegraph.storage.sqlite_store import SqliteStore


runner = CliRunner()


def _make_indexed_project(tmp_path: Path) -> Path:
    """Create a minimal indexed project with multiple files."""
    project = tmp_path / "test_project"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    (src / "main.py").write_text(
        '"""Application entry point."""\ndef main():\n    """Start the app."""\n    pass\n',
        encoding="utf-8",
    )
    (src / "auth.py").write_text(
        '"""Authentication module."""\ndef login(user: str, pwd: str) -> str:\n    """Authenticate user."""\n    return "token"\n',
        encoding="utf-8",
    )

    result = runner.invoke(app, ["init", str(project)])
    assert result.exit_code == 0, f"init failed: {result.stdout}"
    return project


class TestFullPipeline:
    def test_prepare_validate_import_clear(self, tmp_path):
        """End-to-end: prepare -> validate -> import -> status -> clear."""
        project = _make_indexed_project(tmp_path)

        # 1. Prepare
        result = runner.invoke(app, ["enrich", "prepare", "--root", str(project), "--force"])
        assert result.exit_code == 0
        input_path = project / ".codegraph" / "intermediate" / "enrich_input.json"
        assert input_path.exists()

        # 2. Create simulated agent output
        output_path = project / ".codegraph" / "intermediate" / "enrich_output.json"
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="src/main.py",
                    summary="Application entry point that bootstraps and starts the server",
                    tags=["entry", "bootstrap"],
                    role="controller",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="src/main.py", line_start=1, line_end=5)],
                ),
                EnrichedFile(
                    path="src/auth.py",
                    summary="Handles user authentication with token-based sessions",
                    tags=["auth", "security"],
                    role="service",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="src/auth.py", line_start=1, line_end=10)],
                ),
            ],
            symbols=[
                EnrichedSymbol(
                    symbol="main",
                    file="src/main.py",
                    summary="Starts the application server",
                    responsibilities=["Initialize config", "Start HTTP server"],
                    edge_cases=["Missing config file", "Port already in use"],
                    test_relevance="Test with missing config and port conflicts",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="src/main.py", line_start=2, line_end=4)],
                ),
                EnrichedSymbol(
                    symbol="login",
                    file="src/auth.py",
                    summary="Validates user credentials and returns an auth token",
                    responsibilities=["Validate credentials", "Generate token"],
                    edge_cases=["Empty credentials", "Invalid password"],
                    test_relevance="Test with empty/invalid credentials",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="src/auth.py", line_start=3, line_end=5)],
                ),
            ],
        )
        output_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")

        # 3. Validate
        result = runner.invoke(app, ["enrich", "validate", str(output_path), "--root", str(project)])
        assert result.exit_code == 0
        assert "PASSED" in result.stdout

        # 4. Import
        result = runner.invoke(app, ["enrich", "import", str(output_path), "--root", str(project)])
        assert result.exit_code == 0
        assert "Import complete" in result.stdout

        # 5. Status
        result = runner.invoke(app, ["enrich", "status", "--root", str(project)])
        assert result.exit_code == 0
        assert "Enriched" in result.stdout

        # 6. Verify enrichment is readable from SQLite
        sqlite_path = project / ".codegraph" / "index.sqlite"
        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        status = sqlite.get_enrichment_status()
        assert status["enriched_nodes"] > 0
        assert status["enriched_files"] > 0
        sqlite.close()

        # 7. Clear
        result = runner.invoke(app, ["enrich", "clear", "--root", str(project), "--force"])
        assert result.exit_code == 0

        # 8. Verify cleared
        sqlite = SqliteStore(sqlite_path)
        sqlite.initialize()
        status = sqlite.get_enrichment_status()
        assert status["enriched_nodes"] == 0
        sqlite.close()

    def test_status_json_output(self, tmp_path):
        """Status --json returns valid JSON."""
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, ["enrich", "status", "--root", str(project), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "total_nodes" in data
        assert isinstance(data["total_nodes"], int)
        assert "enriched_nodes" in data
        assert "confidence_breakdown" in data
