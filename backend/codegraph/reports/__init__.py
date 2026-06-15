"""Workflow report generation for .codegraph/reports/.

Provides ``ReportWriter`` for generating agent-referenceable markdown
reports: impact analysis, coverage gaps, and enrichment status.
"""

from codegraph.reports.writer import ReportWriter

__all__ = ["ReportWriter"]
