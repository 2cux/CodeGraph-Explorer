"""Tests for ReportWriter — workflow report generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from codegraph.reports.writer import ReportWriter


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def writer(tmp_path: Path) -> ReportWriter:
    """Create a ReportWriter pointing at a temp directory."""
    return ReportWriter(tmp_path / ".codegraph")


# ── Impact Report ─────────────────────────────────────────────────────


class TestImpactReport:
    """Tests for write_impact_report()."""

    def test_writes_file(self, writer: ReportWriter):
        data = {
            "risk_level": "medium",
            "summary": "Test summary.",
            "affected_callers": [
                {"symbol": "login", "file": "auth.py", "confidence": 0.9},
            ],
            "affected_files": [
                {"file": "auth.py", "reason": "direct caller"},
            ],
            "affected_tests": [
                {"symbol": "test_login", "file": "test_auth.py"},
            ],
        }
        path = writer.write_impact_report("TestService", data)
        assert path.exists()
        assert "impact-" in path.name
        assert path.suffix == ".md"

    def test_content_includes_symbol(self, writer: ReportWriter):
        path = writer.write_impact_report("MyService", {
            "risk_level": "low",
            "summary": "Nothing to see.",
            "affected_callers": [],
            "affected_files": [],
            "affected_tests": [],
        })
        content = path.read_text(encoding="utf-8")
        assert "MyService" in content
        assert "low" in content
        assert "Nothing to see" in content

    def test_empty_callers(self, writer: ReportWriter):
        path = writer.write_impact_report("Svc", {
            "risk_level": "unknown",
            "summary": "No impact.",
            "affected_callers": [],
            "affected_files": [],
            "affected_tests": [],
        })
        assert path.exists()

    def test_same_day_overwrites(self, writer: ReportWriter):
        p1 = writer.write_impact_report("A", {
            "risk_level": "low",
            "summary": "First write.",
            "affected_callers": [],
            "affected_files": [],
            "affected_tests": [],
        })
        mtime1 = p1.stat().st_mtime
        p2 = writer.write_impact_report("B", {
            "risk_level": "high",
            "summary": "Second write.",
            "affected_callers": [],
            "affected_files": [],
            "affected_tests": [],
        })
        # Same-day should be same file
        assert p1 == p2
        content = p2.read_text(encoding="utf-8")
        assert "B" in content


# ── Coverage Gaps Report ──────────────────────────────────────────────


class TestCoverageGapsReport:
    """Tests for write_coverage_gaps_report()."""

    def test_writes_file(self, writer: ReportWriter):
        path = writer.write_coverage_gaps_report({
            "symbols_without_tests": [
                {"name": "helper", "file": "util.py", "type": "function"},
            ],
            "low_confidence_links": 5,
            "message": "Found 1 untested symbol.",
        })
        assert path.exists()
        assert path.name == "coverage-gaps.md"

    def test_content_includes_symbols(self, writer: ReportWriter):
        path = writer.write_coverage_gaps_report({
            "symbols_without_tests": [
                {"name": "foo", "file": "a.py", "type": "function"},
                {"name": "bar", "file": "b.py", "type": "class"},
            ],
            "low_confidence_links": 0,
            "message": "Found 2 untested symbols.",
        })
        content = path.read_text(encoding="utf-8")
        assert "foo" in content
        assert "bar" in content

    def test_empty_symbols(self, writer: ReportWriter):
        path = writer.write_coverage_gaps_report({
            "symbols_without_tests": [],
            "low_confidence_links": 0,
            "message": "All symbols tested.",
        })
        assert path.exists()


# ── Enrichment Status Report ──────────────────────────────────────────


class TestEnrichmentStatusReport:
    """Tests for write_enrichment_status_report()."""

    def test_writes_file(self, writer: ReportWriter):
        path = writer.write_enrichment_status_report({
            "total_nodes": 100,
            "enriched_nodes": 50,
            "pending_nodes": 40,
            "skipped_nodes": 5,
            "error_nodes": 5,
            "enriched_files": 10,
            "total_files": 20,
            "confidence_breakdown": {"high": 30, "medium": 15, "low": 5},
            "last_enriched_at": "2026-06-15T00:00:00",
        })
        assert path.exists()
        assert path.name == "enrichment-status.md"
        content = path.read_text(encoding="utf-8")
        assert "50.0%" in content  # enriched percentage
        assert "high" in content

    def test_zero_nodes(self, writer: ReportWriter):
        path = writer.write_enrichment_status_report({
            "total_nodes": 0,
            "enriched_nodes": 0,
            "pending_nodes": 0,
            "skipped_nodes": 0,
            "error_nodes": 0,
            "enriched_files": 0,
            "total_files": 0,
            "confidence_breakdown": {},
            "last_enriched_at": "",
        })
        assert path.exists()


# ── Report listing ────────────────────────────────────────────────────


class TestReportListing:
    """Tests for latest_report_path and list_reports."""

    def test_latest_report_none_when_empty(self, writer: ReportWriter):
        assert writer.latest_report_path("impact-") is None
        assert writer.latest_report_path("coverage-gaps") is None

    def test_latest_report_returns_path(self, writer: ReportWriter):
        writer.write_impact_report("X", {
            "risk_level": "low",
            "summary": "Test.",
            "affected_callers": [],
            "affected_files": [],
            "affected_tests": [],
        })
        latest = writer.latest_report_path("impact-")
        assert latest is not None
        assert "impact-" in latest.name

    def test_list_reports(self, writer: ReportWriter):
        writer.write_coverage_gaps_report({
            "symbols_without_tests": [],
            "low_confidence_links": 0,
            "message": "",
        })
        writer.write_enrichment_status_report({
            "total_nodes": 1,
            "enriched_nodes": 0,
            "pending_nodes": 1,
            "skipped_nodes": 0,
            "error_nodes": 0,
            "enriched_files": 0,
            "total_files": 1,
            "confidence_breakdown": {},
            "last_enriched_at": "",
        })
        reports = writer.list_reports()
        assert len(reports) >= 2
        assert all(r.suffix == ".md" for r in reports)
