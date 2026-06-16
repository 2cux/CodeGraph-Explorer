# MCP Harness Validation Report

**Date:** 2026-06-16
**Commit:** feat/search-ranking-quality
**Harness phase:** Round 2 — MCP Profile + Performance Benchmark
**Decision:** needs_work (profile + benchmark functional; tool confusion and harness overhead need attention)

## Tool Surface

| Profile | Tool Count | Notes |
|---|---:|---|
| agent | 6 | High-level entry tools only |
| full | 13 | Agent + stable primitives |
| debug | 17 | Full + harness introspection |

Profile implementation verified — environment variable `CODEGRAPH_MCP_PROFILE` controls tool exposure. Unknown profile falls back to `agent` with stderr warning.

## Agent A/B Metrics (Round 1 — Synthetic Fixture)

Data source: `fixtures/sample_agent_ab_round1.json`

| Metric | with CodeGraph | without CodeGraph | Notes |
|---|---:|---:|---|
| workflow_start_rate | 100.0% | 0.0% | Agent uses CodeGraph workflows reliably |
| broad_search_before_mcp_rate | 0.0% | 100.0% | Without CG, agent starts with broad `rg` |
| immediate_fallback_after_mcp_rate | 0.0% | 0.0% | No immediate fallback observed |
| targeted_fallback_rate | 16.7% | 0.0% | Only trace_flow task needed fallback |
| avg_mcp_calls_per_task | 2.0 | 0.0 | ~2 CodeGraph calls per task when available |
| next_recommended_follow_rate | 0.0% | n/a | Agent ignores `next_recommended_tools` hints |
| tool_confusion_rate | 50.0% | 100.0% | Agent defaults to `workflow find` for non-find tasks |
| harness_usage_rate | 0.0% | 0.0% | All workflow calls were direct, not via harness MCP |

### Mode-specific metrics

| Mode | Tasks | Status |
|---|---|---|
| with_codegraph | 6 | measured ✅ |
| without_codegraph | 6 | measured ✅ |
| agent_profile | 0 | not measured yet |
| full_profile | 0 | not measured yet |
| debug_profile | 0 | not measured yet |
| workflow-first | 0 | not measured yet |

### Tool Confusion Detail

| Task | Expected Entry | Actual First Tool | Confused |
|---|---|---|---|
| bug_locate_code_paths | codegraph_find / workflow.find | codegraph workflow find | No ✅ |
| shared_type_refactor | pre_edit_check / workflow.impact | codegraph workflow find | **Yes** ❌ |
| coverage_audit | coverage_gaps / workflow.test_audit | codegraph workflow test-audit | No ✅ |
| explain_module | codegraph_explain / workflow.explain | codegraph workflow find | **Yes** ❌ |
| trace_flow | explain / get_neighbors / get_impact | codegraph workflow find | **Yes** ❌ |
| route_service_impact | pre_edit_check / get_impact / workflow.impact | codegraph workflow impact | No ✅ |

**Finding:** The agent defaults to `workflow.find` (or its CLI alias `codegraph workflow find`) even for explain, trace-flow, and refactor tasks. This is a **tool discovery** issue — `codegraph_find` is the most prominently described tool, overshadowing `codegraph_explain`, `codegraph_get_impact`, and `codegraph_pre_edit_check`.

## Performance (Round 2 Benchmark)

Data source: `reports/mcp_harness_perf.json` (3 iterations × 10 cases)

| Metric | Value |
|---|---:|
| Direct MCP p50 | 45.2 ms |
| Direct MCP p95 | 185.5 ms |
| Harness MCP p50 | 860.1 ms |
| Harness MCP p95 | 5787.4 ms |
| Estimated harness overhead p50 | 1946.2 ms |
| Total errors | 0 |

### Threshold Results

| Case | Mode | p95 ms | Threshold | Pass |
|---|---|---:|---|---|
| direct_find_basic | direct_mcp | 73 | <1000 | ✅ |
| direct_explain_symbol | direct_mcp | 21 | <1000 | ✅ |
| direct_pre_edit_file | direct_mcp | 42 | <1000 | ✅ |
| direct_coverage_gaps | direct_mcp | 194 | <3000 | ✅ |
| direct_impact_symbol | direct_mcp | 15 | <3000 | ✅ |
| direct_context_scan | direct_mcp | 95 | n/a | ✅ |
| harness_workflow_explain | harness_mcp | 815 | <1000 | ✅ |
| harness_workflow_impact | harness_mcp | 1072 | <3000 | ✅ |
| harness_workflow_test_audit | harness_mcp | 1044 | <3000 | ✅ |
| harness_workflow_find | harness_mcp | **5980** | **<1000** | **❌ FAILED** |

### Performance Concerns

| # | Finding | Detail |
|---|---|---|
| 1 | **workflow.find latency** | p95=5980ms, 6× above the 1000ms threshold |
| 2 | **Harness overhead overestimated** | The "overhead" includes enrichment work (get_symbol enrichment, markdown generation), not just persistence I/O. True persistence overhead is <100ms for explain/impact/test_audit cases |
| 3 | **workflow.find does the most work** | Unlike other workflows, workflow.find enriches every result with `get_symbol` calls, which multiplies latency |
| 4 | **Response bytes scale with enrichment** | test_audit avg response 65KB — acceptable for compact mode but worth monitoring |

### Suspected Causes

1. **workflow.find** calls `get_symbol` for each search result to enrich with details, signatures, and snippets. A 5-result query triggers 5 extra `get_symbol` calls + markdown artifact generation.
2. The `codegraph_find` tool is fast (p95=73ms) — the extra latency is from enrichment and artifact serialization inside the workflow module.
3. Not a harness persistence issue — `harness_workflow_explain` (815ms p95) and `harness_workflow_impact` (1072ms p95) show acceptable persistence overhead.

## Recommendations

### Immediate (this phase)

- **Keep profile config as-is.** agent (6 tools), full (13 tools), debug (17 tools) are correctly scoped.
- **Do not optimize workflow.find yet.** The latency is from legitimate enrichment work, not a bug. Defer optimization to a dedicated performance phase.
- **Add a "tool discovery" hint** in the `codegraph_find` tool description to steer agents toward `codegraph_explain` and `codegraph_pre_edit_check` for non-find tasks.

### Next phase

- **Run A/B with profile modes** (agent_profile, full_profile, debug_profile). Current data only has with/without_codegraph.
- **Profile workflow.find enrichment path** to identify whether batching get_symbol calls would help.
- **Measure harness usage rate** with the profile mechanism active — debug profile should show >0% harness_usage_rate.

## Non-goals

This validation phase did not delete tools or code.
Profile thresholds and benchmark cases are advisory — no tools were removed based on performance results.
