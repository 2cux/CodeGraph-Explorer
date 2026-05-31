#!/usr/bin/env python3
"""CodeGraph Explorer — Plugin Command Simulation Runner.

Simulates all ``/codegraph`` plugin commands that an AI Agent would invoke.

Usage:
    python scripts/run_simulation.py [--project PATH] [--force-index]

This will:
  1. Index the demo Python project
  2. Run ``search`` on various queries
  3. Run ``explain`` on discovered symbols
  4. Run ``impact`` on a key symbol
  5. Run ``context`` for a natural language task
  6. Print repo summary
  7. Start and stop dashboard (quick test)
"""

import argparse
import sys
import time
from pathlib import Path

# Ensure backend is on the path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from codegraph.plugin_sim import CodeGraphPlugin


def separator(title: str) -> None:
    width = 72
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="CodeGraph Explorer — Plugin Command Simulation"
    )
    parser.add_argument(
        "--project",
        default=str(PROJECT_ROOT / "examples" / "demo_python_project"),
        help="Path to the project to index (default: demo project)",
    )
    parser.add_argument(
        "--force-index", "-f",
        action="store_true",
        help="Force re-index even if index exists",
    )
    args = parser.parse_args()

    project_path = Path(args.project).resolve()
    if not project_path.is_dir():
        print(f"Error: Project path does not exist: {project_path}")
        sys.exit(1)

    plugin = CodeGraphPlugin()

    # ── Simulate /codegraph index ─────────────────────────────────────
    separator("1. /codegraph index — Index the codebase")
    print(f"Project: {project_path}\n")

    result = plugin.index(str(project_path), force=args.force_index)
    print(f"  Status:      {result['status']}")
    print(f"  Files:       {result.get('file_count', '?')}")
    print(f"  Symbols:     {result.get('symbol_count', '?')}")
    print(f"  Edges:       {result.get('edge_count', '?')}")
    print(f"  Languages:   {result.get('languages', ['?'])}")
    print()

    # ── Simulate /codegraph search (multiple queries) ─────────────────
    separator("2. /codegraph search — Search symbols")

    queries = ["login", "user", "auth", "token", "main"]
    for query in queries:
        search_result = plugin.search(query, limit=5)
        total = search_result["total"]
        if total > 0:
            top = search_result["results"][0]
            print(f"  '{query}': {total} result(s)  |  top: {top['symbol_id']} ({top['score']})")
        else:
            print(f"  '{query}': 0 results")

    # ── Simulate /codegraph explain ───────────────────────────────────
    separator("3. /codegraph explain — Explain symbols")

    # First, find some good symbols to explain
    search_result = plugin.search("login", limit=3)
    symbols_to_explain = [
        r["symbol_id"] for r in search_result["results"]
    ]

    # If search found nothing, try common symbol names from the demo project
    if not symbols_to_explain:
        data = plugin._load_graph()
        store = data["store"]
        for n in store.all_nodes()[:10]:
            symbols_to_explain.append(n.id)

    for sym_id in symbols_to_explain[:3]:
        print(f"\n  Explaining: {sym_id}")
        explain_result = plugin.explain(sym_id)
        if "error" in explain_result:
            print(f"    Error: {explain_result['error']}")
            continue
        print(f"    Type:     {explain_result['type']}")
        print(f"    File:     {explain_result['file_path']}")
        if explain_result.get("signature"):
            print(f"    Sig:      {explain_result['signature']}")
        print(f"    Callers:  {explain_result['caller_count']}")
        print(f"    Callees:  {explain_result['callee_count']}")
        if explain_result.get("callers"):
            for c in explain_result["callers"][:3]:
                print(f"      <- {c['node_id']}")

    # ── Simulate /codegraph impact ────────────────────────────────────
    separator("4. /codegraph impact — Impact analysis")

    if symbols_to_explain:
        target = symbols_to_explain[0]
        print(f"  Analyzing: {target}\n")
        impact_result = plugin.impact(target)
        if "error" in impact_result:
            print(f"  Error: {impact_result['error']}")
        else:
            risk = impact_result.get("risk", {})
            print(f"  Risk Level: {risk.get('level', '?')}")
            for reason in risk.get("reasons", []):
                print(f"    - {reason}")
            print()
            affected = impact_result.get("affected_files", [])
            print(f"  Affected Files ({len(affected)}):")
            for f in affected[:5]:
                print(f"    [{f['priority']}] {f['file_path']}")
            print()
            recs = impact_result.get("recommendations", [])
            print(f"  Recommendations:")
            for i, r in enumerate(recs, 1):
                print(f"    {i}. {r}")

    # ── Simulate /codegraph context (the core command!) ───────────────
    separator("5. /codegraph context — Context Pack (core feature)")

    tasks = [
        "add MFA to login flow",
        "fix bug in user authentication",
        "understand how token validation works",
    ]

    for task in tasks:
        print(f"\n  Task: \"{task}\"\n")
        ctx_result = plugin.context(task, max_tokens=4000)
        pack_id = ctx_result.get("pack_id", "?")
        entry_count = len(ctx_result.get("entry_points", []))
        related_count = len(ctx_result.get("related_symbols", []))
        selected_count = len(ctx_result.get("selected_context", []))
        risk_level = ctx_result.get("impact", {}).get("risk", {}).get("level", "?")
        warnings = ctx_result.get("warnings", [])

        print(f"    Pack ID:         {pack_id}")
        print(f"    Entry Points:    {entry_count}")
        print(f"    Related:         {related_count}")
        print(f"    Selected Context:{selected_count} items")
        print(f"    Risk Level:      {risk_level}")
        if warnings:
            for w in warnings:
                print(f"    Warning:         {w}")

        if ctx_result.get("entry_points"):
            print()
            for ep in ctx_result["entry_points"][:3]:
                print(f"      [{ep['score']:.2f}] {ep['symbol_id']}")
                print(f"             {ep['reason']}")

        if ctx_result.get("selected_context"):
            print()
            for sc in ctx_result["selected_context"][:4]:
                print(f"      [{sc.get('priority', '?')}] {sc.get('symbol_id', sc.get('context_id', '?'))} ({sc.get('relation', '?')})")

        # Print export paths
        exports = ctx_result.get("exports", {})
        if exports.get("markdown_path"):
            print(f"\n    Markdown: {exports['markdown_path']}")
        if exports.get("json_path"):
            print(f"    JSON:     {exports['json_path']}")
        print()

    # ── Repo Summary ─────────────────────────────────────────────────
    separator("6. Repo Summary (for AI Agent context)")
    summary = plugin.repo_summary()
    for key, val in summary.items():
        print(f"  {key}: {val}")

    # ── Quick dashboard test (start + stop) ─────────────────────────
    separator("7. /codegraph dashboard — Quick start/stop test")
    dashboard_result = plugin.dashboard(port=8766)
    print(f"  Dashboard URL: {dashboard_result['url']}")
    print(f"  PID:           {dashboard_result['pid']}")
    time.sleep(1)
    CodeGraphPlugin.dashboard_stop(dashboard_result["pid"])
    print("  Server stopped. OK!")
    print()

    separator("SIMULATION COMPLETE")
    print("All plugin commands simulated successfully.\n")


if __name__ == "__main__":
    main()
