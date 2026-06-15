"""Report writer for .codegraph/reports/ directory.

Generates agent-referenceable markdown reports for:
- Impact analysis (``impact-{date}.md``)
- Coverage gaps (``coverage-gaps.md``)
- Enrichment status (``enrichment-status.md``)

Reports are idempotent: same-day impact reports overwrite; coverage
and enrichment reports always replace the previous version.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReportWriter:
    """Write timestamped markdown reports to ``.codegraph/reports/``."""

    def __init__(self, cg_dir: Path) -> None:
        self._reports_dir = cg_dir / "reports"
        self._reports_dir.mkdir(parents=True, exist_ok=True)

    @property
    def reports_dir(self) -> Path:
        """Path to the reports directory."""
        return self._reports_dir

    def _timestamp(self) -> str:
        """Return YYYYMMDD date string (UTC)."""
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    def _iso_now(self) -> str:
        """Return ISO-8601 timestamp (UTC)."""
        return datetime.now(timezone.utc).isoformat()

    # ── Impact Report ───────────────────────────────────────────────────

    def write_impact_report(
        self,
        symbol: str,
        data: dict[str, Any],
    ) -> Path:
        """Write ``impact-{date}.md``. Same-day writes overwrite.

        Args:
            symbol: The symbol that was analyzed (e.g. "MemoryService").
            data: Impact analysis result with keys:
                - affected_callers (list of {symbol, file, confidence})
                - affected_files (list of {file, reason})
                - affected_tests (list of {symbol, file})
                - risk_level (str)
                - summary (str)

        Returns:
            Path to the written report file.
        """
        path = self._reports_dir / f"impact-{self._timestamp()}.md"

        sections: list[str] = [
            f"# Impact Analysis: `{symbol}`",
            f"",
            f"**Generated**: {self._iso_now()}",
            f"**Risk Level**: {data.get('risk_level', 'unknown')}",
            f"",
            f"## Summary",
            f"",
            data.get("summary", "No summary available."),
            f"",
        ]

        # Affected callers
        callers = data.get("affected_callers", [])
        if callers:
            sections += [
                f"## Affected Callers ({len(callers)})",
                f"",
            ]
            for c in callers:
                sym = c.get("symbol", c.get("name", "?"))
                fpath = c.get("file", c.get("file_path", "?"))
                conf = c.get("confidence", "N/A")
                sections.append(
                    f"- `{sym}` in `{fpath}` (confidence: {conf})"
                )
            sections.append("")

        # Affected files
        files = data.get("affected_files", [])
        if files:
            sections += [
                f"## Affected Files ({len(files)})",
                f"",
            ]
            for af in files:
                fpath = af.get("file", af.get("file_path", "?"))
                reason = af.get("reason", "")
                line = f"- `{fpath}`"
                if reason:
                    line += f" — {reason}"
                sections.append(line)
            sections.append("")

        # Affected tests
        tests = data.get("affected_tests", [])
        if tests:
            sections += [
                f"## Affected Tests ({len(tests)})",
                f"",
            ]
            for t in tests:
                sym = t.get("symbol", t.get("name", "?"))
                fpath = t.get("file", t.get("file_path", "?"))
                sections.append(f"- `{sym}` in `{fpath}`")
            sections.append("")

        sections += [
            "## Stats",
            "",
            f"- Total affected callers: {len(callers)}",
            f"- Total affected files: {len(files)}",
            f"- Total affected tests: {len(tests)}",
            f"- Risk level: {data.get('risk_level', 'unknown')}",
            "",
        ]

        path.write_text("\n".join(sections), encoding="utf-8")
        return path

    # ── Coverage Gaps Report ────────────────────────────────────────────

    def write_coverage_gaps_report(self, data: dict[str, Any]) -> Path:
        """Write ``coverage-gaps.md``. Replaces on each write.

        Args:
            data: Coverage gaps result with keys:
                - symbols_without_tests (list of {name, file, type})
                - low_confidence_links (int)
                - message (str)

        Returns:
            Path to the written report file.
        """
        path = self._reports_dir / "coverage-gaps.md"

        sections: list[str] = [
            "# Coverage Gaps Report",
            "",
            f"**Generated**: {self._iso_now()}",
            "",
            data.get("message", ""),
            "",
        ]

        untested = data.get("symbols_without_tests", [])
        if untested:
            sections += [
                f"## Symbols Without Tests ({len(untested)})",
                "",
            ]
            for sym in untested[:200]:  # Cap at 200 to avoid huge files
                name = sym.get("name", sym.get("symbol", "?"))
                fpath = sym.get("file", sym.get("file_path", "?"))
                stype = sym.get("type", "?")
                sections.append(f"- `{name}` (`{stype}`) in `{fpath}`")

            if len(untested) > 200:
                sections.append(
                    f"  ... and {len(untested) - 200} more (truncated)."
                )
            sections.append("")

        sections += [
            "## Stats",
            "",
            f"- Symbols without tests: {len(untested)}",
            f"- Low-confidence test links: {data.get('low_confidence_links', 0)}",
            "",
        ]

        path.write_text("\n".join(sections), encoding="utf-8")
        return path

    # ── Enrichment Status Report ────────────────────────────────────────

    def write_enrichment_status_report(self, data: dict[str, Any]) -> Path:
        """Write ``enrichment-status.md``. Replaces on each write.

        Args:
            data: Enrichment status with keys:
                - total_nodes, enriched_nodes, pending_nodes, skipped_nodes,
                  error_nodes
                - enriched_files, total_files
                - confidence_breakdown (dict[str, int])
                - last_enriched_at (str)

        Returns:
            Path to the written report file.
        """
        path = self._reports_dir / "enrichment-status.md"

        total = data.get("total_nodes", 0)
        enriched = data.get("enriched_nodes", 0)
        pct = (enriched / total * 100) if total > 0 else 0

        sections: list[str] = [
            "# Enrichment Status Report",
            "",
            f"**Generated**: {self._iso_now()}",
            "",
            "## Coverage",
            "",
            f"- Total nodes: {total}",
            f"- Enriched: {enriched} ({pct:.1f}%)",
            f"- Pending: {data.get('pending_nodes', 0)}",
            f"- Skipped: {data.get('skipped_nodes', 0)}",
            f"- Errors: {data.get('error_nodes', 0)}",
            "",
            "## Files",
            "",
            f"- Enriched files: {data.get('enriched_files', 0)} / {data.get('total_files', 0)}",
            "",
        ]

        confidence = data.get("confidence_breakdown", {})
        if confidence:
            sections += [
                "## Confidence Breakdown",
                "",
            ]
            for level in ("high", "medium", "low"):
                count = confidence.get(level, 0)
                sections.append(f"- **{level}**: {count}")
            sections.append("")

        last = data.get("last_enriched_at", "")
        if last:
            sections.append(f"**Last enriched**: {last}")
            sections.append("")

        path.write_text("\n".join(sections), encoding="utf-8")
        return path

    # ── Helpers ─────────────────────────────────────────────────────────

    def latest_report_path(self, prefix: str) -> Path | None:
        """Return the most recently modified report matching a prefix.

        Args:
            prefix: Filename prefix to match (e.g. ``"impact-"``,
                    ``"coverage-gaps"``, ``"enrichment-status"``).

        Returns:
            Path to the latest matching report, or None if none found.
        """
        candidates = sorted(
            self._reports_dir.glob(f"{prefix}*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def list_reports(self) -> list[Path]:
        """Return all report files sorted by modification time (newest first)."""
        return sorted(
            self._reports_dir.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
