"""Tests for enrichment prepare module."""

import json
from pathlib import Path
import pytest
from codegraph.enrich.models import PrepareOutput
from codegraph.enrich.prepare import generate_prepare_output, write_prepare_output


class TestGeneratePrepareOutput:
    def test_generates_with_populated_store(self, populated_store, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        output = generate_prepare_output(
            populated_store, cg_dir, max_files=10
        )
        assert isinstance(output, PrepareOutput)
        assert output.project.name
        assert len(output.files) > 0
        assert output.constraints.schema_version == "codegraph_enrichment_v1"

    def test_generates_with_empty_store(self, empty_store, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        output = generate_prepare_output(
            empty_store, cg_dir, max_files=10
        )
        assert isinstance(output, PrepareOutput)
        assert output.files == []

    def test_respects_max_files(self, populated_store, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        output = generate_prepare_output(
            populated_store, cg_dir, max_files=1
        )
        assert len(output.files) <= 1

    def test_file_has_required_fields(self, populated_store, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        output = generate_prepare_output(
            populated_store, cg_dir, max_files=10
        )
        if output.files:
            f = output.files[0]
            assert f.path
            assert f.language
            assert isinstance(f.symbols, list)
            assert isinstance(f.imports, list)

    def test_json_serializable(self, populated_store, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        output = generate_prepare_output(
            populated_store, cg_dir, max_files=10
        )
        json_str = output.model_dump_json(indent=2)
        parsed = json.loads(json_str)
        assert "project" in parsed
        assert "files" in parsed
        assert "constraints" in parsed


class TestWritePrepareOutput:
    def test_writes_to_correct_path(self, populated_store, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        output = generate_prepare_output(populated_store, cg_dir, max_files=5)
        written = write_prepare_output(output, cg_dir)
        assert written.exists()
        assert written.name == "enrich_input.json"
        assert "intermediate" in str(written)

    def test_output_is_valid_json(self, populated_store, tmp_path):
        cg_dir = tmp_path / ".codegraph"
        cg_dir.mkdir()
        output = generate_prepare_output(populated_store, cg_dir, max_files=5)
        written = write_prepare_output(output, cg_dir)
        data = json.loads(written.read_text(encoding="utf-8"))
        assert data["constraints"]["schema_version"] == "codegraph_enrichment_v1"
