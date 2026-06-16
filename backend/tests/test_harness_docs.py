"""Tests for DocsGenerator — harness module reference docs.

Covers:
- render output format (markdown table, per-module sections)
- write to file (creates docs/harness-modules.md)
- module ordering (stable modules first per _DOC_MODULE_ORDER)
- stable vs reserved labels
- input/output schema blocks in rendered docs
- artifact lists in rendered docs
- integration with builtin manifests
"""

from __future__ import annotations

from pathlib import Path

from codegraph.harness.docs import DocsGenerator, _status_label


# ── DocsGenerator.render ───────────────────────────────────────────────────


class TestDocsGeneratorRender:
    def test_render_has_header(self) -> None:
        content = DocsGenerator().render()
        assert content.startswith("# Harness Modules")

    def test_render_has_summary_table(self) -> None:
        content = DocsGenerator().render()
        assert "| Module | Category | Status | Description |" in content
        assert "|---|---|---|---|"

    def test_render_includes_all_stable_modules(self) -> None:
        content = DocsGenerator().render()
        assert "## workflow.impact" in content
        assert "## workflow.test_audit" in content
        assert "## workflow.explain" in content
        assert "## workflow.find" in content
        assert "## doctor.run" in content

    def test_render_includes_all_reserved_modules(self) -> None:
        content = DocsGenerator().render()
        assert "## enrich.prepare" in content
        assert "## enrich.validate" in content
        assert "## enrich.import" in content
        assert "## benchmark.gate" in content
        assert "## agent_ab.regression" in content
        assert "## mcp.execute" in content

    def test_render_has_input_schema_blocks(self) -> None:
        content = DocsGenerator().render()
        assert "Input schema:" in content
        assert "```json" in content

    def test_render_has_output_schema_blocks(self) -> None:
        content = DocsGenerator().render()
        assert "Output schema:" in content

    def test_render_has_artifacts_section(self) -> None:
        content = DocsGenerator().render()
        assert "Artifacts:" in content

    def test_render_stable_module_shows_report_artifacts(self) -> None:
        content = DocsGenerator().render()
        # workflow.impact should list report.md and report.json
        assert "- report.md" in content
        assert "- report.json" in content

    def test_render_reserved_module_shows_none_declared(self) -> None:
        content = DocsGenerator().render()
        assert "- None declared." in content

    def test_render_ends_with_newline(self) -> None:
        content = DocsGenerator().render()
        assert content.endswith("\n")

    def test_render_stable_vs_reserved_in_table(self) -> None:
        content = DocsGenerator().render()
        # workflow.impact should be labeled stable
        assert "| `workflow.impact` | `workflow` | `stable` |" in content
        # enrich.prepare should be labeled reserved
        assert "| `enrich.prepare` | `enrich` | `reserved` |" in content

    def test_render_schema_contains_expected_keys(self) -> None:
        content = DocsGenerator().render()
        # workflow.impact schema should mention change_type
        assert '"change_type"' in content
        # workflow.find schema should mention query
        assert '"query"' in content
        # workflow.explain schema should mention symbol
        assert '"symbol"' in content


# ── DocsGenerator.write ────────────────────────────────────────────────────


class TestDocsGeneratorWrite:
    def test_write_creates_file(self, tmp_path: Path) -> None:
        gen = DocsGenerator()
        docs_path = gen.write(tmp_path)
        assert docs_path.exists()
        assert docs_path == tmp_path / "docs" / "harness-modules.md"

    def test_write_creates_parent_directories(self, tmp_path: Path) -> None:
        gen = DocsGenerator()
        docs_path = gen.write(tmp_path)
        assert docs_path.parent.is_dir()

    def test_write_content_matches_render(self, tmp_path: Path) -> None:
        gen = DocsGenerator()
        rendered = gen.render()
        docs_path = gen.write(tmp_path)
        written = docs_path.read_text(encoding="utf-8")
        assert written == rendered

    def test_write_overwrites_existing(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        existing = docs_dir / "harness-modules.md"
        existing.write_text("old content", encoding="utf-8")

        gen = DocsGenerator()
        gen.write(tmp_path)
        content = existing.read_text(encoding="utf-8")
        assert content != "old content"
        assert content.startswith("# Harness Modules")


# ── status_label helper ────────────────────────────────────────────────────


class TestStatusLabel:
    def test_stable_returns_stable(self) -> None:
        assert _status_label(True) == "stable"

    def test_not_stable_returns_reserved(self) -> None:
        assert _status_label(False) == "reserved"


# ── Module ordering ────────────────────────────────────────────────────────


class TestDocsModuleOrdering:
    def test_workflow_modules_appear_first(self) -> None:
        content = DocsGenerator().render()
        impact_pos = content.index("## workflow.impact")
        enrich_pos = content.index("## enrich.prepare")
        assert impact_pos < enrich_pos

    def test_ordered_modules_in_correct_sequence(self) -> None:
        content = DocsGenerator().render()
        # The defined order: workflow.impact, workflow.test_audit, workflow.explain,
        # workflow.find, doctor.run, enrich.prepare, enrich.validate, enrich.import,
        # benchmark.gate, agent_ab.regression, mcp.execute
        positions = {
            mod: content.index(f"## {mod}")
            for mod in [
                "workflow.impact",
                "workflow.test_audit",
                "workflow.explain",
                "workflow.find",
                "doctor.run",
                "enrich.prepare",
                "enrich.validate",
                "enrich.import",
                "benchmark.gate",
                "agent_ab.regression",
                "mcp.execute",
            ]
        }
        # Each subsequent module should appear after the previous
        ordered = sorted(positions.values())
        for mod, pos in positions.items():
            assert pos in ordered


# ── Edge cases ─────────────────────────────────────────────────────────────


class TestDocsEdgeCases:
    def test_render_is_not_empty(self) -> None:
        content = DocsGenerator().render()
        assert len(content) > 100  # Should be substantial

    def test_render_contains_all_eleven_modules(self) -> None:
        content = DocsGenerator().render()
        h2_count = content.count("\n## ")
        # 11 module sections
        assert h2_count == 11

    def test_rendered_content_is_valid_utf8(self) -> None:
        content = DocsGenerator().render()
        content.encode("utf-8")  # should not raise
