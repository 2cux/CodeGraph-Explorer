"""Real agent adoption A/B recorder and report generator.

This module complements the synthetic benchmark runner with a structured
"real agent" evaluation flow. It does not execute an external agent.
Instead, it validates recorded observations from with-CodeGraph vs
without-CodeGraph runs and produces a stable markdown report.

Usage:
    python -m tests.agent_benchmark.adoption --write-template
    python -m tests.agent_benchmark.adoption --input tests/agent_benchmark/results/agent_adoption_observations.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_BENCHMARK_DIR = Path(__file__).resolve().parent
_CASES_PATH = _BENCHMARK_DIR / "adoption_cases.json"
_RESULTS_DIR = _BENCHMARK_DIR / "results"
_REPORTS_DIR = _PROJECT_ROOT / "reports"

REQUIRED_TASK_TYPES = (
    "bug_locate",
    "shared_type_refactor",
    "coverage_audit",
    "explain_module",
    "trace_flow",
    "route_service_impact",
)
REQUIRED_MODES = ("with_codegraph", "without_codegraph")


@dataclass(frozen=True)
class AdoptionCase:
    task_id: str
    task_type: str
    title: str
    prompt: str
    goal: str


def load_adoption_cases(path: Path | None = None) -> list[AdoptionCase]:
    """Load the fixed real-A/B task catalog."""
    case_path = path or _CASES_PATH
    data = json.loads(case_path.read_text(encoding="utf-8"))
    return [AdoptionCase(**item) for item in data]


def build_observation_template(
    run_id: str = "replace-me",
    project: str = "target-project",
    agent: str = "target-agent",
    round_id: str = "round-1",
) -> list[dict[str, Any]]:
    """Create an empty two-arm A/B template for one round."""
    rows: list[dict[str, Any]] = []
    for mode in REQUIRED_MODES:
        for case in load_adoption_cases():
            rows.append(
                {
                    "run_id": run_id,
                    "round_id": round_id,
                    "project": project,
                    "agent": agent,
                    "mode": mode,
                    "task_id": case.task_id,
                    "task_type": case.task_type,
                    "title": case.title,
                    "goal": case.goal,
                    "prompt": case.prompt,
                    "first_tool": "",
                    "codegraph_call_count": 0,
                    "consecutive_codegraph_calls": 0,
                    "read_grep_glob_before_codegraph": 0,
                    "read_grep_glob_after_codegraph": 0,
                    "workflow_used": False,
                    "followed_next_recommended_tools": False,
                    "fallback_used": False,
                    "fallback_reason": "",
                    "immediate_fallback_after_codegraph": False,
                    "read_after_codegraph_targeted": False,
                    "task_completed_seconds": 0.0,
                    "error_count": 0,
                    "test_failure_count": 0,
                    "control_repo_regressed": False,
                    "notes": "",
                }
            )
    return rows


def load_observations(path: Path) -> list[dict[str, Any]]:
    """Load raw observation rows."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Observation file must contain a JSON array.")
    return data


def _case_maps() -> tuple[dict[str, AdoptionCase], dict[str, AdoptionCase]]:
    cases = load_adoption_cases()
    by_id = {case.task_id: case for case in cases}
    by_type = {case.task_type: case for case in cases}
    return by_id, by_type


def validate_observations(observations: list[dict[str, Any]]) -> list[str]:
    """Validate observation schema and round completeness."""
    errors: list[str] = []
    by_id, _ = _case_maps()
    required_fields = {
        "run_id",
        "round_id",
        "project",
        "agent",
        "mode",
        "task_id",
        "task_type",
        "first_tool",
        "codegraph_call_count",
        "consecutive_codegraph_calls",
        "read_grep_glob_before_codegraph",
        "read_grep_glob_after_codegraph",
        "workflow_used",
        "followed_next_recommended_tools",
        "fallback_used",
        "fallback_reason",
        "immediate_fallback_after_codegraph",
        "read_after_codegraph_targeted",
        "task_completed_seconds",
        "error_count",
        "test_failure_count",
        "control_repo_regressed",
    }
    numeric_fields = {
        "codegraph_call_count",
        "consecutive_codegraph_calls",
        "read_grep_glob_before_codegraph",
        "read_grep_glob_after_codegraph",
        "task_completed_seconds",
        "error_count",
        "test_failure_count",
    }

    seen_keys: set[tuple[str, str, str]] = set()
    for idx, obs in enumerate(observations):
        label = f"row[{idx}]"
        missing = sorted(required_fields - set(obs))
        if missing:
            errors.append(f"{label}: missing fields: {', '.join(missing)}")
            continue

        mode = obs["mode"]
        if mode not in REQUIRED_MODES:
            errors.append(f"{label}: invalid mode '{mode}'")

        task_id = obs["task_id"]
        case = by_id.get(task_id)
        if case is None:
            errors.append(f"{label}: unknown task_id '{task_id}'")
        elif obs["task_type"] != case.task_type:
            errors.append(
                f"{label}: task_type '{obs['task_type']}' does not match catalog "
                f"'{case.task_type}'"
            )

        key = (obs["round_id"], mode, task_id)
        if key in seen_keys:
            errors.append(
                f"{label}: duplicate observation for round={obs['round_id']} "
                f"mode={mode} task_id={task_id}"
            )
        seen_keys.add(key)

        for field in numeric_fields:
            value = obs[field]
            if not isinstance(value, (int, float)):
                errors.append(f"{label}: field '{field}' must be numeric")
                continue
            if value < 0:
                errors.append(f"{label}: field '{field}' must be >= 0")

        if obs["fallback_used"] and not str(obs["fallback_reason"]).strip():
            errors.append(f"{label}: fallback_used=true requires fallback_reason")

        if not obs["fallback_used"] and str(obs["fallback_reason"]).strip():
            errors.append(f"{label}: fallback_reason should be empty when fallback_used=false")

        if mode == "with_codegraph" and obs["codegraph_call_count"] <= 0:
            errors.append(f"{label}: with_codegraph row requires codegraph_call_count > 0")

        if mode == "without_codegraph" and obs["codegraph_call_count"] != 0:
            errors.append(
                f"{label}: without_codegraph row must keep codegraph_call_count == 0 "
                f"for a clean control arm"
            )

        if obs["consecutive_codegraph_calls"] > obs["codegraph_call_count"]:
            errors.append(
                f"{label}: consecutive_codegraph_calls cannot exceed codegraph_call_count"
            )

    rounds: dict[tuple[str, str], set[str]] = defaultdict(set)
    for obs in observations:
        rounds[(obs["round_id"], obs["mode"])].add(obs["task_type"])
    for round_mode, task_types in sorted(rounds.items()):
        missing_types = [task for task in REQUIRED_TASK_TYPES if task not in task_types]
        if missing_types:
            errors.append(
                f"round={round_mode[0]} mode={round_mode[1]} missing required task types: "
                f"{', '.join(missing_types)}"
            )
    return errors


def _group_by_round_and_mode(
    observations: list[dict[str, Any]]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for obs in observations:
        grouped[(obs["round_id"], obs["mode"])].append(obs)
    return grouped


def summarize_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate adoption results and acceptance criteria."""
    grouped = _group_by_round_and_mode(observations)
    pair_groups: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for obs in observations:
        pair_groups[(obs["round_id"], obs["task_id"])][obs["mode"]] = obs

    per_mode: dict[str, dict[str, Any]] = {}
    for mode in REQUIRED_MODES:
        mode_rows = [obs for obs in observations if obs["mode"] == mode]
        row_count = len(mode_rows)
        totals = {
            "rows": row_count,
            "rounds": len({obs["round_id"] for obs in mode_rows}),
            "codegraph_call_count": sum(obs["codegraph_call_count"] for obs in mode_rows),
            "consecutive_codegraph_2plus": sum(
                1 for obs in mode_rows if obs["consecutive_codegraph_calls"] >= 2
            ),
            "read_grep_glob_before_codegraph": sum(
                obs["read_grep_glob_before_codegraph"] for obs in mode_rows
            ),
            "read_grep_glob_after_codegraph": sum(
                obs["read_grep_glob_after_codegraph"] for obs in mode_rows
            ),
            "workflow_used": sum(1 for obs in mode_rows if obs["workflow_used"]),
            "followed_next_recommended_tools": sum(
                1 for obs in mode_rows if obs["followed_next_recommended_tools"]
            ),
            "fallback_used": sum(1 for obs in mode_rows if obs["fallback_used"]),
            "immediate_fallback_after_codegraph": sum(
                1 for obs in mode_rows if obs["immediate_fallback_after_codegraph"]
            ),
            "read_after_codegraph_targeted": sum(
                1 for obs in mode_rows if obs["read_after_codegraph_targeted"]
            ),
            "task_completed_seconds": round(
                sum(obs["task_completed_seconds"] for obs in mode_rows), 3
            ),
            "error_count": sum(obs["error_count"] for obs in mode_rows),
            "test_failure_count": sum(obs["test_failure_count"] for obs in mode_rows),
            "control_repo_regressed": sum(
                1 for obs in mode_rows if obs["control_repo_regressed"]
            ),
        }
        totals["avg_task_completed_seconds"] = round(
            totals["task_completed_seconds"] / row_count, 3
        ) if row_count else 0.0
        totals["avg_manual_scan_calls"] = round(
            (
                totals["read_grep_glob_before_codegraph"]
                + totals["read_grep_glob_after_codegraph"]
            ) / row_count,
            3,
        ) if row_count else 0.0
        per_mode[mode] = totals

    round_acceptance: list[dict[str, Any]] = []
    for (round_id, mode), rows in sorted(grouped.items()):
        if mode != "with_codegraph":
            continue
        category_hits = sorted(
            {
                obs["task_type"]
                for obs in rows
                if obs["consecutive_codegraph_calls"] >= 2
            }
        )
        accepted = {
            "round_id": round_id,
            "category_hits": category_hits,
            "category_hit_count": len(category_hits),
            "consecutive_codegraph_ok": len(category_hits) >= 3,
            "no_immediate_broad_fallback": all(
                not obs["immediate_fallback_after_codegraph"] for obs in rows
            ),
            "reads_targeted_after_codegraph": all(
                obs["read_grep_glob_after_codegraph"] == 0 or obs["read_after_codegraph_targeted"]
                for obs in rows
            ),
            "followed_next_recommended_tools": all(
                obs["followed_next_recommended_tools"] for obs in rows
            ),
            "control_repo_not_degraded": all(
                not obs["control_repo_regressed"] for obs in rows
            ),
        }
        accepted["passed"] = all(
            (
                accepted["consecutive_codegraph_ok"],
                accepted["no_immediate_broad_fallback"],
                accepted["reads_targeted_after_codegraph"],
                accepted["control_repo_not_degraded"],
            )
        )
        round_acceptance.append(accepted)

    pairwise: list[dict[str, Any]] = []
    for (round_id, task_id), pair in sorted(pair_groups.items()):
        with_obs = pair.get("with_codegraph")
        without_obs = pair.get("without_codegraph")
        if not with_obs or not without_obs:
            continue
        with_manual = (
            with_obs["read_grep_glob_before_codegraph"]
            + with_obs["read_grep_glob_after_codegraph"]
        )
        without_manual = (
            without_obs["read_grep_glob_before_codegraph"]
            + without_obs["read_grep_glob_after_codegraph"]
        )
        pairwise.append(
            {
                "round_id": round_id,
                "task_id": task_id,
                "task_type": with_obs["task_type"],
                "with_first_tool": with_obs["first_tool"],
                "without_first_tool": without_obs["first_tool"],
                "with_codegraph_call_count": with_obs["codegraph_call_count"],
                "without_codegraph_call_count": without_obs["codegraph_call_count"],
                "with_manual_scan_calls": with_manual,
                "without_manual_scan_calls": without_manual,
                "manual_scan_delta": with_manual - without_manual,
                "with_task_completed_seconds": with_obs["task_completed_seconds"],
                "without_task_completed_seconds": without_obs["task_completed_seconds"],
                "task_time_delta": round(
                    with_obs["task_completed_seconds"] - without_obs["task_completed_seconds"],
                    3,
                ),
                "with_errors": with_obs["error_count"],
                "without_errors": without_obs["error_count"],
                "with_test_failures": with_obs["test_failure_count"],
                "without_test_failures": without_obs["test_failure_count"],
                "with_followed_next": with_obs["followed_next_recommended_tools"],
                "with_fallback_used": with_obs["fallback_used"],
                "with_fallback_reason": with_obs["fallback_reason"],
            }
        )

    comparison = {
        "paired_tasks": len(pairwise),
        "with_codegraph_fewer_manual_scans": sum(
            1 for row in pairwise if row["manual_scan_delta"] < 0
        ),
        "with_codegraph_not_worse_manual_scans": sum(
            1 for row in pairwise if row["manual_scan_delta"] <= 0
        ),
        "with_codegraph_fewer_errors": sum(
            1 for row in pairwise if row["with_errors"] < row["without_errors"]
        ),
        "with_codegraph_fewer_test_failures": sum(
            1 for row in pairwise if row["with_test_failures"] < row["without_test_failures"]
        ),
    }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "required_task_types": list(REQUIRED_TASK_TYPES),
        "required_modes": list(REQUIRED_MODES),
        "per_mode": per_mode,
        "round_acceptance": round_acceptance,
        "pairwise": pairwise,
        "comparison": comparison,
    }


def generate_report(summary: dict[str, Any]) -> str:
    """Render the adoption A/B summary as markdown."""
    lines: list[str] = []
    lines.append("# Real Agent Adoption A/B Report")
    lines.append("")
    lines.append(f"**Generated:** {summary['generated_at']}")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append("This report compares real-agent runs in two arms:")
    lines.append("")
    lines.append("- `with_codegraph`: the agent is instructed to use CodeGraph-first workflows.")
    lines.append("- `without_codegraph`: the control arm does not use CodeGraph.")
    lines.append("")
    lines.append("Each round must include these six task types:")
    for task_type in summary["required_task_types"]:
        lines.append(f"- `{task_type}`")
    lines.append("")

    lines.append("## Per-Mode Totals")
    lines.append("")
    lines.append(
        "| Mode | Rows | Rounds | CodeGraph Calls | Manual Scan Calls | "
        "Workflow Used | Followed Next Tools | Fallbacks | Avg Time (s) | Errors | Test Failures |"
    )
    lines.append(
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
    )
    for mode in REQUIRED_MODES:
        data = summary["per_mode"][mode]
        manual_total = (
            data["read_grep_glob_before_codegraph"] + data["read_grep_glob_after_codegraph"]
        )
        lines.append(
            f"| {mode} | {data['rows']} | {data['rounds']} | {data['codegraph_call_count']} | "
            f"{manual_total} | {data['workflow_used']} | "
            f"{data['followed_next_recommended_tools']} | {data['fallback_used']} | "
            f"{data['avg_task_completed_seconds']:.3f} | {data['error_count']} | "
            f"{data['test_failure_count']} |"
        )
    lines.append("")

    lines.append("## Acceptance")
    lines.append("")
    lines.append(
        "| Round | 3+ Categories With 2+ Consecutive CodeGraph Calls | "
        "No Immediate Broad Fallback | Reads Targeted After CodeGraph | "
        "Control Repo Not Degraded | Passed | Categories |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for row in summary["round_acceptance"]:
        lines.append(
            f"| {row['round_id']} | {'yes' if row['consecutive_codegraph_ok'] else 'no'} | "
            f"{'yes' if row['no_immediate_broad_fallback'] else 'no'} | "
            f"{'yes' if row['reads_targeted_after_codegraph'] else 'no'} | "
            f"{'yes' if row['control_repo_not_degraded'] else 'no'} | "
            f"{'yes' if row['passed'] else 'no'} | {', '.join(row['category_hits'])} |"
        )
    lines.append("")

    comparison = summary["comparison"]
    lines.append("## A/B Comparison")
    lines.append("")
    lines.append(
        f"- Paired tasks: `{comparison['paired_tasks']}`"
    )
    lines.append(
        f"- With-CodeGraph fewer manual scans: `{comparison['with_codegraph_fewer_manual_scans']}`"
    )
    lines.append(
        f"- With-CodeGraph not worse on manual scans: "
        f"`{comparison['with_codegraph_not_worse_manual_scans']}`"
    )
    lines.append(
        f"- With-CodeGraph fewer errors: `{comparison['with_codegraph_fewer_errors']}`"
    )
    lines.append(
        f"- With-CodeGraph fewer test failures: "
        f"`{comparison['with_codegraph_fewer_test_failures']}`"
    )
    lines.append("")

    lines.append("## Pairwise Task Detail")
    lines.append("")
    lines.append(
        "| Round | Task | With First Tool | Without First Tool | "
        "With CG Calls | With Manual Scans | Without Manual Scans | "
        "Manual Delta | With Time (s) | Without Time (s) | Fallback |"
    )
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---|")
    for row in summary["pairwise"]:
        fallback = (
            row["with_fallback_reason"]
            if row["with_fallback_used"] and row["with_fallback_reason"]
            else "no"
        )
        lines.append(
            f"| {row['round_id']} | {row['task_id']} | {row['with_first_tool']} | "
            f"{row['without_first_tool']} | {row['with_codegraph_call_count']} | "
            f"{row['with_manual_scan_calls']} | {row['without_manual_scan_calls']} | "
            f"{row['manual_scan_delta']} | {row['with_task_completed_seconds']:.3f} | "
            f"{row['without_task_completed_seconds']:.3f} | {fallback} |"
        )
    lines.append("")

    return "\n".join(lines)


def _default_input_path() -> Path:
    return _RESULTS_DIR / "agent_adoption_observations.json"


def _default_report_path() -> Path:
    return _REPORTS_DIR / "agent_adoption_ab.md"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a real-agent adoption A/B report."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=_default_input_path(),
        help="Observation JSON file path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_default_report_path(),
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--write-template",
        action="store_true",
        help="Write an empty observation template to --input and exit.",
    )
    parser.add_argument("--run-id", default="replace-me")
    parser.add_argument("--project", default="target-project")
    parser.add_argument("--agent", default="target-agent")
    parser.add_argument("--round-id", default="round-1")
    args = parser.parse_args()

    if args.write_template:
        args.input.parent.mkdir(parents=True, exist_ok=True)
        template = build_observation_template(
            run_id=args.run_id,
            project=args.project,
            agent=args.agent,
            round_id=args.round_id,
        )
        args.input.write_text(
            json.dumps(template, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"Template written to {args.input}")
        return 0

    if not args.input.exists():
        print(
            f"Observation file not found: {args.input}\n"
            f"Run with --write-template first.",
            file=sys.stderr,
        )
        return 2

    observations = load_observations(args.input)
    errors = validate_observations(observations)
    if errors:
        print("Observation validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    summary = summarize_observations(observations)
    report = generate_report(summary)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
