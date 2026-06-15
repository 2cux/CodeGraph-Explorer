"""Tests for enrichment validate module."""

import json
from pathlib import Path
import pytest
from codegraph.enrich.models import AgentOutput, EnrichedFile, EnrichedSymbol, EnrichedEvidence
from codegraph.enrich.validate import validate_agent_output


def _write_agent_output(tmp_path: Path, output: AgentOutput) -> Path:
    p = tmp_path / "enrich_output.json"
    p.write_text(output.model_dump_json(indent=2), encoding="utf-8")
    return p


class TestValidateAgentOutput:
    def test_valid_output_passes(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="app/api/auth.py",
                    summary="Auth module",
                    tags=["auth"],
                    role="service",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="app/api/auth.py", line_start=1, line_end=10)],
                )
            ],
            symbols=[
                EnrichedSymbol(
                    symbol="login",
                    file="app/api/auth.py",
                    summary="Login handler",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="app/api/auth.py", line_start=6, line_end=9)],
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert result.valid is True
        assert result.stats["files_checked"] == 1
        assert result.stats["symbols_checked"] == 1

    def test_invalid_json_fails(self, populated_store, tmp_path):
        p = tmp_path / "enrich_output.json"
        p.write_text("not json", encoding="utf-8")
        result = validate_agent_output(p, populated_store)
        assert result.valid is False

    def test_schema_mismatch_fails(self, populated_store, tmp_path):
        output = AgentOutput(schema_version="wrong_schema")
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert result.valid is False

    def test_absolute_path_fails(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[EnrichedFile(path="/absolute/path.py", summary="Test", confidence="medium")],
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert result.valid is False

    def test_summary_too_long_fails(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[EnrichedFile(path="app/api/auth.py", summary="x" * 600, confidence="medium")],
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert result.valid is False

    def test_too_many_tags_fails(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="app/api/auth.py",
                    summary="Test",
                    tags=[f"tag{i}" for i in range(15)],
                    confidence="medium",
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert result.valid is False

    def test_unknown_file_warns(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[EnrichedFile(path="nonexistent.py", summary="Test", confidence="medium")],
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert len(result.warnings) >= 1

    def test_unknown_symbol_warns(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            symbols=[
                EnrichedSymbol(
                    symbol="nonexistent_func",
                    file="app/api/auth.py",
                    summary="Test",
                    confidence="medium",
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert len(result.warnings) >= 1

    def test_negative_line_range_fails(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="app/api/auth.py",
                    summary="Test",
                    confidence="medium",
                    evidence=[EnrichedEvidence(file="app/api/auth.py", line_start=-1, line_end=5)],
                )
            ],
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert result.valid is False

    def test_empty_output_warns(self, populated_store, tmp_path):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
        )
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert len(result.warnings) >= 1

    def test_missing_enriched_at_warns(self, populated_store, tmp_path):
        output = AgentOutput(schema_version="codegraph_enrichment_v1")
        p = _write_agent_output(tmp_path, output)
        result = validate_agent_output(p, populated_store)
        assert len(result.warnings) >= 1
