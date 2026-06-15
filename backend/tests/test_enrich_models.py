"""Tests for enrichment Pydantic models."""

import json
import pytest
from codegraph.enrich.models import (
    PrepareProject,
    PrepareSymbol,
    PrepareFile,
    PrepareConstraints,
    PrepareOutput,
    EnrichedEvidence,
    EnrichedFile,
    EnrichedSymbol,
    AgentOutput,
    ValidationError_,
    ValidationResult,
    EnrichmentStatus,
)


class TestPrepareModels:
    def test_prepare_output_minimal(self):
        output = PrepareOutput(
            project=PrepareProject(name="test", root="/tmp/test"),
        )
        assert output.project.name == "test"
        assert output.files == []
        assert output.constraints.max_summary_chars == 500

    def test_prepare_output_with_files(self):
        output = PrepareOutput(
            project=PrepareProject(name="test", root="/tmp/test"),
            files=[
                PrepareFile(
                    path="src/main.py",
                    language="python",
                    symbols=[PrepareSymbol(name="main", type="function")],
                )
            ],
        )
        assert len(output.files) == 1
        assert output.files[0].symbols[0].name == "main"

    def test_prepare_constraints_defaults(self):
        c = PrepareConstraints()
        assert c.schema_version == "codegraph_enrichment_v1"
        assert c.max_summary_chars == 500
        assert c.max_tags == 10
        assert c.relative_paths_only is True
        assert c.evidence_required is True
        assert "high" in c.confidence_values


class TestAgentOutputModels:
    def test_enriched_file_valid(self):
        f = EnrichedFile(
            path="src/main.py",
            summary="Entry point",
            tags=["entry", "cli"],
            role="controller",
            confidence="high",
            evidence=[EnrichedEvidence(file="src/main.py", line_start=1, line_end=10)],
        )
        assert f.confidence == "high"
        assert len(f.tags) == 2

    def test_enriched_file_invalid_confidence(self):
        with pytest.raises(Exception):
            EnrichedFile(
                path="src/main.py",
                confidence="unknown",
            )

    def test_enriched_symbol_valid(self):
        s = EnrichedSymbol(
            symbol="login",
            file="src/auth.py",
            summary="Login handler",
            responsibilities=["Validate credentials"],
            edge_cases=["Empty password"],
            test_relevance="Test auth flow",
            confidence="medium",
        )
        assert s.symbol == "login"
        assert len(s.responsibilities) == 1

    def test_enriched_symbol_invalid_confidence(self):
        with pytest.raises(Exception):
            EnrichedSymbol(
                symbol="login",
                file="src/auth.py",
                confidence="invalid_value",
            )

    def test_agent_output_full(self):
        output = AgentOutput(
            schema_version="codegraph_enrichment_v1",
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="src/main.py",
                    summary="App entry",
                    role="controller",
                    confidence="high",
                )
            ],
            symbols=[
                EnrichedSymbol(
                    symbol="login",
                    file="src/auth.py",
                    summary="Login",
                    confidence="medium",
                )
            ],
        )
        assert output.schema_version == "codegraph_enrichment_v1"
        assert len(output.files) == 1
        assert len(output.symbols) == 1

    def test_agent_output_empty(self):
        output = AgentOutput()
        assert output.schema_version == "codegraph_enrichment_v1"
        assert output.files == []
        assert output.symbols == []

    def test_agent_output_json_roundtrip(self):
        output = AgentOutput(
            enriched_at="2026-06-15T10:00:00Z",
            files=[
                EnrichedFile(
                    path="src/main.py",
                    summary="Entry",
                    role="controller",
                    confidence="high",
                    evidence=[EnrichedEvidence(file="src/main.py", line_start=1, line_end=5)],
                )
            ],
        )
        json_str = output.model_dump_json(indent=2)
        parsed = AgentOutput.model_validate(json.loads(json_str))
        assert parsed.files[0].path == "src/main.py"
        assert parsed.files[0].confidence == "high"


class TestValidationModels:
    def test_validation_result_valid(self):
        r = ValidationResult(valid=True, stats={"files_checked": 5})
        assert r.valid is True
        assert r.errors == []

    def test_validation_result_with_errors(self):
        r = ValidationResult(
            valid=False,
            errors=[ValidationError_(path="files[0].path", message="Invalid path")],
            warnings=[ValidationError_(path="symbols[0]", message="Missing timestamp", severity="warning")],
            stats={"files_checked": 1},
        )
        assert r.valid is False
        assert len(r.errors) == 1
        assert len(r.warnings) == 1


class TestEnrichmentStatus:
    def test_status_defaults(self):
        s = EnrichmentStatus()
        assert s.total_nodes == 0
        assert s.enriched_nodes == 0
        assert s.confidence_breakdown == {}

    def test_status_with_data(self):
        s = EnrichmentStatus(
            total_nodes=100,
            enriched_nodes=45,
            pending_nodes=50,
            skipped_nodes=3,
            error_nodes=2,
            confidence_breakdown={"high": 20, "medium": 15, "low": 10},
            last_enriched_at="2026-06-15T10:00:00Z",
        )
        assert s.total_nodes == 100
        assert s.enriched_nodes == 45
        assert s.confidence_breakdown["high"] == 20
