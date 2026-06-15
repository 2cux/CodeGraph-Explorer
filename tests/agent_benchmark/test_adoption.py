"""Tests for the real-agent adoption A/B helper."""

from __future__ import annotations

from pathlib import Path

from tests.agent_benchmark.adoption import (
    REQUIRED_TASK_TYPES,
    build_observation_template,
    generate_report,
    load_adoption_cases,
    summarize_observations,
    validate_observations,
)


def _completed_rows():
    rows = build_observation_template(
        run_id="run-1",
        project="demo",
        agent="codex",
        round_id="r1",
    )
    for row in rows:
        if row["mode"] == "with_codegraph":
            row["first_tool"] = "codegraph_find"
            row["codegraph_call_count"] = 3
            row["consecutive_codegraph_calls"] = 2
            row["followed_next_recommended_tools"] = True
            row["workflow_used"] = True
            row["read_after_codegraph_targeted"] = True
            row["task_completed_seconds"] = 20
        else:
            row["first_tool"] = "grep"
            row["task_completed_seconds"] = 35
            row["read_grep_glob_before_codegraph"] = 4
            row["read_grep_glob_after_codegraph"] = 2
    return rows


def test_adoption_cases_cover_required_task_types() -> None:
    cases = load_adoption_cases()
    assert len(cases) == 6
    assert {case.task_type for case in cases} == set(REQUIRED_TASK_TYPES)


def test_template_is_complete_for_one_round() -> None:
    template = build_observation_template(
        run_id="run-1",
        project="demo",
        agent="codex",
        round_id="r1",
    )
    assert len(template) == 12
    with_rows = [row for row in template if row["mode"] == "with_codegraph"]
    without_rows = [row for row in template if row["mode"] == "without_codegraph"]
    assert len(with_rows) == 6
    assert len(without_rows) == 6
    assert all("task_id" in row for row in template)


def test_validate_rejects_incomplete_control_arm() -> None:
    rows = _completed_rows()
    control_row = next(row for row in rows if row["mode"] == "without_codegraph")
    control_row["codegraph_call_count"] = 1
    errors = validate_observations(rows)
    assert any("without_codegraph row must keep codegraph_call_count == 0" in err for err in errors)


def test_summary_and_report_capture_acceptance() -> None:
    rows = _completed_rows()
    assert validate_observations(rows) == []

    summary = summarize_observations(rows)
    assert summary["comparison"]["paired_tasks"] == 6
    assert summary["comparison"]["with_codegraph_fewer_manual_scans"] == 6
    assert summary["round_acceptance"][0]["passed"] is True

    report = generate_report(summary)
    assert "Real Agent Adoption A/B Report" in report
    assert "3+ Categories With 2+ Consecutive CodeGraph Calls" in report
    assert "With-CodeGraph fewer manual scans" in report
