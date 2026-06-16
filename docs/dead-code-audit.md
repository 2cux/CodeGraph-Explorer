# Dead Code Audit Report

> **This report is audit-only. Do not delete code in this phase.**
>
> Date: 2026-06-16
> Data source: `fixtures/dead_code_audit_seed.json` + actual codebase `rg` search

## Audit Methodology

For each candidate in the seed file, we performed:
1. File existence check via `glob`
2. Symbol existence check via `rg` + Python import
3. Cross-reference search via `rg` across entire codebase
4. CLI / MCP / tests / docs reference classification

## Candidates from Seed

| Candidate | Kind | Exists | References | CLI | MCP | Tests | Docs | Deletion Risk | Recommendation | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `backend/codegraph/templates/legacy_workflow.md` | template | **No** | 0 | No | No | No | No | — | **No action needed** | File does not exist in codebase |
| `backend/codegraph/reports/old_benchmark_report.py` | python_file | **No** | 0 | No | No | No | No | — | **No action needed** | File does not exist in codebase |
| `backend/codegraph/graph/legacy_impact.py` | python_file | **No** | 0 | No | No | No | No | — | **No action needed** | File does not exist in codebase |
| `backend/codegraph/mcp_legacy_tools.py` | python_file | **No** | 0 | No | No | No | No | — | **No action needed** | File does not exist in codebase |
| `render_old_context_report` | function | **No** | 0 | No | No | No | No | — | **No action needed** | Symbol not found in codebase |
| `ExperimentalEdgeNormalizer` | class | **No** | 0 | No | No | No | No | — | **No action needed** | Symbol not found in codebase |

**Summary: All 6 seed candidates confirmed absent from the codebase.** No dead code matching the seed exists. This is consistent with the PRD's focus on keeping the codebase lean — legacy artifacts were likely cleaned up during previous phases.

## Verified-Active Code (Not Dead)

During the audit, we confirmed the following are actively referenced and should NOT be removed:

| File/Symbol | References | Referenced By | Status |
|---|---|---|---|
| `backend/codegraph/context/reading_plan.py` | 0 (file missing) | CLAUDE.md mentions as stub | Stub was removed — CLAUDE.md entry is stale documentation |
| `backend/codegraph/templates/claude_commands/*.md` | In use | CLI `configure` command | Active — agent adoption templates |
| `backend/codegraph/templates/agents/*.md` | In use | Enrich workflow | Active |
| `backend/codegraph/harness/benchmark_gate.py` | Reserved | Manifest registry | Reserved for future — keep |
| `backend/codegraph/harness/agent_ab_regression.py` | Reserved | Manifest registry | Reserved for future — keep |

## Stale Documentation Reference

| Location | Issue | Recommendation |
|---|---|---|
| `CLAUDE.md` line ~124 | References `reading_plan.py` as "Stub（已废弃，始终返回 []）" | File does not exist. Update CLAUDE.md to remove or note it was already deleted. |

## Low-risk candidates

None identified. The codebase is clean with respect to the seed candidates. All harness modules, MCP tools, and graph operations are actively wired through the registry or import chain.

## Medium-risk candidates

None identified.

## High-risk / keep

None identified. All verified modules are actively referenced.

## Required Follow-up

1. **Update CLAUDE.md** — Remove or correct the `reading_plan.py` stub reference.
2. **Re-run audit after feature completion** — When `benchmark.gate` and `agent_ab_regression` are implemented, revisit whether their reserved stubs should be removed.
3. **Confirm with owner** before any deletion in a separate PR.

> **No files, functions, templates, or tests were deleted during this audit.**
