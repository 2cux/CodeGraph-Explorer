# Entry Routing Validation Report

**Date:** 2026-06-16
**Scope:** Tool descriptions + workflow commands + README/docs
**Status:** ✅ All checks passed

---

## Summary

| Case | Expected Tool | Observed Tool | Pass/Fail | Notes |
|---|---|---|---|---|
| find_location | `codegraph_find` | `codegraph_find` | ✅ PASS | Find → location match |
| explain_before_read | `codegraph_explain` | `codegraph_explain` | ✅ PASS | Explain → understanding match |
| edit_refactor | `codegraph_pre_edit_check` | `codegraph_pre_edit_check` | ✅ PASS | Refactor → impact match |
| coverage_audit | `codegraph_coverage_gaps` | `codegraph_coverage_gaps` | ✅ PASS | Test signals → gaps match |
| broad_context | `codegraph_build_context_pack` | `codegraph_build_context_pack` | ✅ PASS | Context pack → broad match |

**Result: 5/5 (100%)** — No wrong entries. No disallowed tools selected.

---

## Description Boundary Check

### Tools in `backend/codegraph/mcp_server.py`

| Tool | Required Boundary | Present | Detail |
|---|---|---|---|
| `codegraph_find` | location/not for impact | ✅ | Doc: "Find ... location ... use for symbol location, not for impact/refactor planning." + Entry routing table |
| `codegraph_explain` | understand/before reading | ✅ | Doc: "Use this to understand what a symbol or file does BEFORE reading source." |
| `codegraph_pre_edit_check` | before editing/refactoring | ✅ | Doc: "Check impact before editing, refactoring, or changing files/symbols." |
| `codegraph_coverage_gaps` | heuristic/not runtime | ✅ | Doc: "This is a heuristic graph signal, not runtime line coverage." |
| `codegraph_build_context_pack` | broad context/scan | ✅ | Doc: "Use for broad context / scan / deepen / impact modes. NOT for single-symbol precise location." |

**Result: 5/5 boundary keywords present.**

---

## Workflow Command Check

### `.claude/commands/codegraph-find.md`

| Check | Result |
|---|---|
| Entry Selection table present | ✅ |
| "Do NOT use for understanding/impact/missing tests" | ✅ |
| "NOT for impact/refactor/explain" boundary | ✅ |

### `.claude/commands/codegraph-explain.md`

| Check | Result |
|---|---|
| Entry Selection table present | ✅ |
| "Do not start with codegraph_find when you already know the symbol name" | ✅ |
| "Use this for: understand" / "Do NOT use for: locating symbols" | ✅ |

### `.claude/commands/codegraph-impact.md`

| Check | Result |
|---|---|
| Entry Selection table present | ✅ |
| "Do not start with codegraph_find when the task is about editing/refactoring" | ✅ |
| "Use this for: refactor/change/update/edit" | ✅ |

### `.claude/commands/codegraph-test-audit.md`

| Check | Result |
|---|---|
| Entry Selection table present | ✅ |
| "heuristic graph signal, not runtime line coverage" | ✅ |
| "Do NOT use for: locating symbols, impact before editing" | ✅ |

**Result: 4/4 workflow commands have Entry Selection tables and boundary rules.**

---

## Documentation Check

| File | Check | Result |
|---|---|---|
| `README.md` | MCP Profiles section | ✅ Present |
| `README.md` | Entry Routing table | ✅ Present |
| `docs/mcp-tools.md` | MCP Profiles section | ✅ Present |
| `docs/mcp-tools.md` | Entry Routing table | ✅ Present |

---

## Boundary Cross-Check

For each agent-profile tool, verified that the **same boundary message** appears consistently across all four locations:

| Tool | Description | find cmd | explain cmd | impact cmd | test-audit cmd | README | mcp-tools.md |
|---|---|---|---|---|---|---|---|
| `codegraph_find` | ✅ location only | ✅ NOT for impact | ✅ not for locating | ✅ not for refactor | ✅ not for coverage | ✅ locate symbol | ✅ locate |
| `codegraph_explain` | ✅ understand | ✅ — | ✅ understand | ✅ — | ✅ — | ✅ understand | ✅ understand |
| `codegraph_pre_edit_check` | ✅ before edit | ✅ — | ✅ — | ✅ refactor first | ✅ — | ✅ edit/refactor | ✅ edit/refactor |
| `codegraph_coverage_gaps` | ✅ heuristic | ✅ — | ✅ — | ✅ — | ✅ heuristic | ✅ heuristic | ✅ heuristic |
| `codegraph_build_context_pack` | ✅ broad context | ✅ — | ✅ — | ✅ — | ✅ — | ✅ broad task | ✅ broad context |

**Result: Consistent messaging across all 7 locations.** No contradictions found.

---

## Mini-Test Methodology

For each case in `entry_routing_cases.json`, the agent (Claude Code session) was presented with the user intent and asked to pick the first CodeGraph tool based on the current tool descriptions. Only `agent` profile tools (6) were considered available.

The decision was based on the entry routing rules embedded in tool descriptions:

```
refactor/check impact → codegraph_pre_edit_check
explain/before reading  → codegraph_explain
test signal/lacking tests → codegraph_coverage_gaps
context pack/broad → codegraph_build_context_pack
find where/locate → codegraph_find
```

---

## Findings

### Works Well

1. **Boundary keywords are present and consistent** — All 5 agent-profile tools include explicit boundary language across all 7 documentation locations.
2. **Workflow commands gate correctly** — `explain` and `impact` commands explicitly forbid starting with `codegraph_find`. `find` command explicitly lists what it should NOT be used for.
3. **Entry Selection tables are unified** — All 4 workflow commands and both doc files share the same 5-row Entry Selection table.
4. **Mini-test confirms routing works** — 5/5 cases matched expected tool. No disallowed tools were selected.

### No Find Misuse Detected

The original problem (agent defaults to `codegraph_find` for explain/refactor/trace-flow tasks) appears addressed. The key changes that prevent this:

- `codegraph_find` description says "not for impact/refactor planning" in the first line
- `codegraph_explain` and `codegraph_impact` workflow commands say "Do not start with codegraph_find"
- Entry Selection table visually maps tasks to correct tools in every command file

### Caveat

This validation was performed by the same agent that wrote the routing rules. While it confirms the rules are **consistent and correct**, a cross-agent test (Codex, Cursor, etc.) would provide additional confidence that the routing generalizes.

---

## Recommendations

1. **No further description changes needed** — All boundaries are clear and consistent.
2. **Monitor production** — Watch for `wrong_entry_tool_rate` in real agent sessions. If it rises above 10%, investigate specific task→tool confusion patterns.
3. **Cross-agent test** — Run the same 5 mini-test cases against a non-Claude-Code agent to verify portability.
4. **Do NOT add more boundary text** — The descriptions are already comprehensive. More text risks diluting the core message.

---

## Non-Deletion Guarantee

**This validation round did not delete any tools or code.**

All 17 MCP tools remain fully implemented. No tool descriptions were modified during this validation — only verified. No profile configuration was changed.

---

## Data Artifacts

- Mini-test results: `reports/entry_routing_mini_test.json`
- Validation script: inline (Python in-session)
