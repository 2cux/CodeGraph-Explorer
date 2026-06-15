"""Tests for enrichment CLI commands via CliRunner."""

import json
from pathlib import Path
import pytest
from typer.testing import CliRunner
from codegraph.cli.main import app
from codegraph.enrich.models import AgentOutput, EnrichedFile, EnrichedSymbol, EnrichedEvidence


runner = CliRunner()


def _make_indexed_project(tmp_path: Path) -> Path:
    """Create a minimal indexed project and return the project root."""
    project = tmp_path / "test_project"
    project.mkdir()
    src = project / "src"
    src.mkdir()
    (src / "main.py").write_text("def main(): pass\n", encoding="utf-8")
    (src / "utils.py").write_text("def helper(): pass\n", encoding="utf-8")

    result = runner.invoke(app, ["init", str(project)])
    return project


class TestEnrichPrepareCLI:
    def test_prepare_requires_index(self, tmp_path):
        result = runner.invoke(app, ["enrich", "prepare", "--root", str(tmp_path)])
        assert result.exit_code != 0

    def test_prepare_creates_output(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, ["enrich", "prepare", "--root", str(project), "--force"])
        assert result.exit_code == 0
        output_path = project / ".codegraph" / "intermediate" / "enrich_input.json"
        assert output_path.exists()
        data = json.loads(output_path.read_text(encoding="utf-8"))
        assert "project" in data
        assert "files" in data
        assert "constraints" in data


class TestEnrichValidateCLI:
    def test_validate_missing_file(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, [
            "enrich", "validate",
            str(tmp_path / "nonexistent.json"),
            "--root", str(project),
        ])
        assert result.exit_code != 0

    def test_validate_invalid_json(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        output_path = project / ".codegraph" / "intermediate" / "enrich_output.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("not json", encoding="utf-8")

        result = runner.invoke(app, [
            "enrich", "validate",
            str(output_path),
            "--root", str(project),
        ])
        assert result.exit_code == 1

    def test_validate_valid_output(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        output_path = project / ".codegraph" / "intermediate" / "enrich_output.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="src/main.py",
                    summary="Entry point",
                    role="controller",
                    confidence="high",
                )
            ],
        )
        output_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")

        result = runner.invoke(app, [
            "enrich", "validate",
            str(output_path),
            "--root", str(project),
        ])
        assert result.exit_code == 0


class TestEnrichStatusCLI:
    def test_status_no_index(self, tmp_path):
        result = runner.invoke(app, ["enrich", "status", "--root", str(tmp_path)])
        assert result.exit_code != 0

    def test_status_with_fresh_index(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, ["enrich", "status", "--root", str(project)])
        assert result.exit_code == 0
        assert "Total nodes" in result.stdout

    def test_status_json_output(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, ["enrich", "status", "--root", str(project), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert "total_nodes" in data
        assert "enriched_nodes" in data


class TestEnrichClearCLI:
    def test_clear_requires_confirmation(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, [
            "enrich", "clear", "--root", str(project),
        ], input="n\n")
        assert "Aborted" in result.stdout or result.exit_code != 0

    def test_clear_with_force(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, [
            "enrich", "clear", "--root", str(project), "--force",
        ])
        assert result.exit_code == 0


class TestEnrichImportCLI:
    def test_import_missing_file(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        result = runner.invoke(app, [
            "enrich", "import",
            str(tmp_path / "nonexistent.json"),
            "--root", str(project),
        ])
        assert result.exit_code != 0

    def test_import_with_validation(self, tmp_path):
        project = _make_indexed_project(tmp_path)
        output_path = project / ".codegraph" / "intermediate" / "enrich_output.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="src/main.py",
                    summary="Main entry point",
                    tags=["entry"],
                    role="controller",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="src/main.py", line_start=1, line_end=5)],
                )
            ],
        )
        output_path.write_text(output.model_dump_json(indent=2), encoding="utf-8")

        result = runner.invoke(app, [
            "enrich", "import",
            str(output_path),
            "--root", str(project),
        ])
        assert result.exit_code == 0
        assert "Import complete" in result.stdout
