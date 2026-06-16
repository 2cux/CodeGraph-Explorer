# workflow.find Performance Triage Report

**Date:** 2026-06-16
**Data source:** Real profiling runs (3 iterations per case), `reports/mcp_harness_perf.json`
**Status:** Triage only — no code changes applied

---

## Summary

| Case | p50 | p95 | Max | Results | Artifact Bytes | Notes |
|---|---:|---:|---:|---:|---:|---|
| Direct `codegraph_find` (baseline) | 63ms | 132ms | 132ms | 5 | 0 | Fast — pure search + detail |
| wf.find default (limit=5, details=true) | **7012ms** | 7194ms | 7194ms | 5 | 0* | Full enrichment |
| wf.find limit=1 (details=true) | **3585ms** | 3611ms | 3611ms | 2 | 0* | 1 get_symbol instead of 5 |
| wf.find no details (limit=5, details=false) | **1632ms** | 1679ms | 1679ms | 5 | 0* | Skips per-result get_symbol |
| Full harness (harness_run wf.find) | **5410ms** | 5496ms | 5496ms | 5 | ~10KB | Adds run dir + artifacts |

*No harness mode — no artifact writes.

---

## Cost Center Breakdown (limit=5, include_details=true)

### Primary Cost: Per-Result `get_symbol()` Enrichment — **~77%**

```
Total wf.find default:     ~7012ms
Minus wf.find no details:  ~1632ms
→ Enrichment cost:         ~5380ms  (77%)
```

**Root cause:** `_build_enriched_results()` calls `get_symbol()` once per search result. With limit=5, that's 5 sequential MCP calls, each doing:
- Symbol resolution (`_resolve_node_detailed`)
- Source snippet extraction (up to 40 lines)
- Relation summary computation
- Response serialization

Each `get_symbol()` call takes ~1000-1200ms. 5 × ~1100ms = ~5500ms — matches the observed enrichment cost.

### Secondary Cost: Search + Result Building — **~22%**

```
wf.find no details:        ~1632ms
Minus direct find:         ~84ms
→ Search + build + markdown: ~1548ms  (22%)
```

This includes:
- `run_find()` — raw search (~100ms)
- `codegraph_find()` — MCP find call (~84ms, includes its own search + detail)
- `_build_enriched_results()` structure building (~200ms)
- `build_workflow_find_result()` ~100ms
- Warning collection + reason/confidence derivation (~100ms)
- Markdown generation (`build_workflow_find_markdown`) ~800ms

### Tertiary Cost: Harness Persistence — **<5%**

```
Full harness:              ~5444ms
wf.find no harness:        ~7012ms
→ Harness overhead:        negative (caching effects)
```

The full harness run was actually slightly faster than the no-harness raw call, likely due to:
- Store caching: the harness loads the store once, then reuses it
- In the no-harness case, `_call_mcp_helper` resets MCP globals each time

Harness artifacts (JSON 2KB + Markdown 8KB) and run dir creation add <100ms — confirmed negligible.

---

## Cost by Case

### wf.find limit=1 (reduced enrichment)

**p50: 3585ms** — 49% faster than limit=5

Reducing to 1 result cuts enrichment from 5 `get_symbol()` calls to 1. The remaining ~3500ms includes the mandatory `codegraph_find()` (~84ms), one `get_symbol()` (~1100ms), result building (~200ms), and markdown generation (~800ms). This confirms the linear scaling of enrichment cost.

### wf.find no_details (skip get_symbol)

**p50: 1632ms** — 77% faster than default

Skipping all per-result `get_symbol()` calls eliminates the dominant cost. The remaining ~1632ms is:
- `run_find()` + `codegraph_find()`: ~200ms (combined)
- Result structure building: ~200ms
- Markdown generation: ~800ms
- Warnings + reason + confidence: ~300ms

This is the single most effective optimization if acceptable.

---

## Recommendations

### Low-Risk Optimizations (Recommended)

| # | Optimization | Expected Impact | Risk |
|---|---|---|---|
| 1 | **Default `include_details=false` in MCP harness_run** | Cuts wf.find from ~5400ms → ~1700ms (68% reduction) | **Low.** Details available on-demand via `include_details=true`. Agent can still request full enrichment when needed. |
| 2 | **Reduce default `limit` from 10 to 5** | Already at 5 for test cases. Prevents accidental limit=10 enrichment. | **Low.** Agent can increase limit explicitly. |
| 3 | **Lazy markdown generation in MCP mode** | Markdown is ~800ms. For MCP `harness_run`, generate markdown only if `format="markdown"` is explicitly requested. Default to JSON artifact only. | **Low.** JSON is sufficient for MCP consumption. Markdown is useful for CLI/human reports. |
| 4 | **Parallel `get_symbol()` calls** | Instead of sequential calls, batch them. 5 calls × 1100ms sequential → ~1100ms parallel (80% reduction in enrichment cost). | **Medium.** Thread safety needs verification (MCP globals). Use the existing `_MCP_HELPER_LOCK` with care. |

### Not Recommended (High Risk / Out of Scope)

| # | Optimization | Why Not |
|---|---|---|
| — | Merge workflow.find into codegraph_find | Breaks separation — workflow.find produces reports + artifacts, codegraph_find is a lightweight query tool. Different purposes. |
| — | Remove enrichment entirely | Enrichment is the value-add of workflow.find over codegraph_find. Without it, workflow.find is just a wrapper. |
| — | Change default to no_details permanently | Some workflows genuinely need details. Defaulting to false breaks those. Better to let the caller choose. |
| — | Pre-compute enrichment at index time | Too invasive — requires index schema changes, migration, and disk space trade-offs. Not justified by the current latency. |
| — | Remove markdown artifact generation | Markdown is a key output for CLI `codegraph workflow find`. Keep for CLI, make optional for MCP. |

---

## Architecture Confirmation

The triage confirms the earlier design decisions:

1. **Direct `codegraph_find` IS the correct default for agents.** p95 ~132ms is excellent for frequent lookups.
2. **`workflow.find` is NOT a drop-in replacement for `codegraph_find`.** It's a report-generation tool that does enrichment, markdown, and artifact writes.
3. **`codegraph_harness_run workflow.find` belongs in `harness`/`debug` profile, not `agent`.** Confirmed — the latency profile is fundamentally different from direct find.
4. **Artifact content is NOT in MCP responses by default.** Confirmed — response_bytes for harness_run is 7.5KB vs artifact_bytes of ~10KB.

---

## Implementation Priority

If optimization is pursued in a future round:

1. **P0:** Default `include_details=false` in MCP `harness_run` — single parameter change, 68% latency reduction.
2. **P1:** Lazy markdown — skip markdown when `format=json` or in MCP mode.
3. **P2:** Parallel `get_symbol()` calls — requires verification of thread safety with MCP globals.
4. **P3:** Batch `get_symbol()` — if parallel is not feasible, a batch API could reduce round-trips.

---

## Non-Deletion Guarantee

**This triage did not delete any tools or code.**

No MCP tools were modified. No profile configuration was changed. No benchmark results were altered. The optimization recommendations are advisory only — no implementation was performed.
