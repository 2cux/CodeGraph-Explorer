# MCP Tool Surface Recommendation

**Date:** 2026-06-16
**Based on:** MCP Profile implementation (Round 1) + Performance benchmark (Round 2) + A/B analysis (Round 3)
**Status:** Recommendation only — no tools or code deleted.

---

## Current State

17 MCP tools are implemented and active. They are organized into 3 profiles via `CODEGRAPH_MCP_PROFILE`:

| Profile | Tool Count | Env Var | Default |
|---|---|---|---|
| agent | 6 | `CODEGRAPH_MCP_PROFILE=agent` | ✅ (when unset) |
| full | 13 | `CODEGRAPH_MCP_PROFILE=full` | — |
| debug | 17 | `CODEGRAPH_MCP_PROFILE=debug` | — |

---

## Agent Profile — Recommended Default Exposure (6 tools)

These are the high-level task entry tools suitable for all coding agents.

| Tool | Category | Role | Rationale |
|---|---|---|---|
| `codegraph_repo_status` | repo | high_level | Entry point — agent checks index freshness before using other tools |
| `codegraph_find` | find | high_level | Primary task: "find X in codebase" — most-used tool in A/B |
| `codegraph_explain` | explain | high_level | Symbol/file understanding before reading source |
| `codegraph_pre_edit_check` | impact | high_level | Impact analysis before editing files |
| `codegraph_coverage_gaps` | coverage | high_level | Test coverage audit |
| `codegraph_build_context_pack` | context | high_level | Complex task entry — returns structured context for multi-step work |

**Why these 6:** They cover the 6 core agent workflows identified in `agent_ab_tasks.json`: bug locate → find; refactor → pre_edit_check; coverage → coverage_gaps; explain → explain; large refactor → build_context_pack; new feature → build_context_pack/find.

---

## Full Profile — Advanced Users (13 tools)

Agent profile + stable primitive search & graph tools.

### Additional tools beyond agent (7 tools)

| Tool | Category | Role | Rationale |
|---|---|---|---|
| `codegraph_repo_summary` | repo | summary | Repo overview — useful for new project entry |
| `codegraph_search_symbols` | symbol | primitive | Fuzzy symbol search with type filtering |
| `codegraph_get_symbol` | symbol | primitive | Exact symbol detail lookup |
| `codegraph_get_callers` | graph | primitive | Upstream call chain traversal |
| `codegraph_get_callees` | graph | primitive | Downstream dependency traversal |
| `codegraph_get_neighbors` | graph | primitive | Local sub-graph exploration |
| `codegraph_get_impact` | impact | primitive | Symbol-level impact analysis |

**Why these are not in agent profile:** For most high-level tasks, `codegraph_find` + `codegraph_explain` + `codegraph_pre_edit_check` give enough context. Primitives like `get_callers`/`get_callees` are useful for deep exploration but add tool-surface noise for simple agent workflows. The A/B data confirms agents complete tasks without reaching for these primitives.

---

## Debug Profile — Developers & Debugging (17 tools)

Full profile + harness introspection & debug tools.

### Additional tools beyond full (4 tools)

| Tool | Category | Role | Rationale |
|---|---|---|---|
| `codegraph_harness_list` | harness | debug | List available harness modules |
| `codegraph_harness_run` | harness | debug | Execute harness workflow modules |
| `codegraph_harness_status` | harness | debug | Check harness run state |
| `codegraph_harness_artifacts` | harness | debug | Read harness run artifacts |

**Important:** All 4 harness tools are **stable** and **in active use** — they are the MCP entry point for workflow execution. They are restricted to `debug` profile because:
1. They expose workflow execution (not a normal agent operation)
2. They can create persistent run state (disk I/O side effects)
3. The `codegraph_harness_artifacts` tool can read file content up to 32KB

---

## Tools Not Recommended for Default Exposure

| Tool | Current Profile | Status | Reason |
|---|---|---|---|
| `codegraph_harness_list` | debug only | **Correctly hidden** | Exposes internal module registry |
| `codegraph_harness_run` | debug only | **Correctly hidden** | Side-effect: creates run dirs + artifacts |
| `codegraph_harness_status` | debug only | **Correctly hidden** | Debug/introspection only |
| `codegraph_harness_artifacts` | debug only | **Correctly hidden** | File I/O — on-demand only |

---

## Tools Recommended to Hide (Not Delete)

| Tool | Hide From | Rationale |
|---|---|---|
| `codegraph_search_symbols` | agent profile | Redundant with `codegraph_find` for most agent tasks. Keep in full/debug. |
| `codegraph_get_symbol` | agent profile | Agent can get symbol details through `codegraph_find` (include_details=true). Keep in full/debug. |
| `codegraph_get_callers` | agent profile | Deep traversal — agent workflows don't need this as first-class tool. Keep in full/debug. |
| `codegraph_get_callees` | agent profile | Same as callers. Keep in full/debug. |
| `codegraph_get_neighbors` | agent profile | Sub-graph exploration. Keep in full/debug. |
| `codegraph_get_impact` | agent profile | `codegraph_pre_edit_check` covers file-level impact for agent tasks. Keep in full/debug for symbol-level analysis. |
| `codegraph_repo_summary` | agent profile | Useful for first-time project entry but not per-task. Keep in full/debug. |
| `codegraph_harness_*` (4 tools) | agent + full | Debug/introspection. Keep in debug only. ✅ Already implemented |

---

## Deletion Candidates (Audit Only — Do Not Delete)

**No deletion candidates identified.**

All 17 MCP tools are:
- ✅ Actively wired through `@mcp.tool()` decorators in `mcp_server.py`
- ✅ Backed by live graph/indexer/harness implementations
- ✅ Covered by tests (regression + unit + profile tests)
- ✅ Referenced by CLI, MCP, or workflow modules

The dead code audit (see `docs/dead-code-audit.md`) confirmed zero matching candidates in the seed file.

### Tools That Could Be Considered in Future (Not Now)

| Candidate | Reason to Consider | Blocking Factor |
|---|---|---|
| `codegraph_search_symbols` vs `codegraph_find` merge | Partial functional overlap | `find` is a composite tool (search + get_symbol); `search_symbols` is the primitive. Both serve different use cases. |
| `codegraph_get_impact` vs `codegraph_pre_edit_check` merge | `pre_edit_check` wraps `get_impact` for file-level queries | `get_impact` works at symbol level; `pre_edit_check` at file level. Different granularity. |

---

## Confirmed Decisions (2026-06-16)

### 1. ✅ Agent Profile Default

**Decision:** 默认 profile = `agent`

```
CODEGRAPH_MCP_PROFILE 未设置时，使用 agent。
```

原因：核心目标是让普通编码 Agent 少误选工具。默认暴露 6 个高层工具合理。不默认 `full`（工具太多），不默认 `debug`（harness 工具进入普通 Agent 视野会增加误选）。

---

### 2. ✅ Profile Migration Strategy

**Decision:** 短期保持兼容，新安装默认 agent

| 场景 | 行为 |
|---|---|
| 新用户 / 新配置 | 默认 `agent` profile |
| 老用户已配置过 MCP | 不强制覆盖已有配置 |
| `codegraph configure all --force` | 写入 `agent` profile |
| 用户需要完整工具 | 显式设置 `CODEGRAPH_MCP_PROFILE=full` |
| 开发调试 | 显式设置 `CODEGRAPH_MCP_PROFILE=debug` |

Profile 语义说明（写入文档）：

```
agent = recommended default for coding agents
full  = advanced users
debug = CodeGraph development / harness debugging
```

不做无提示 profile 迁移——老用户从全量工具改成 6 个工具会破坏已有用法。

---

### 3. ✅ Profile A/B Testing (Gate Before Launch)

**Decision:** 必须补测，上线前完成。

测试矩阵：

| 组 | Profile | 说明 |
|---|---|---|
| A | `agent` | 6 个高层工具 |
| B | `full` | 13 个稳定工具 |
| C | `debug` | 17 个全部工具 |
| D | without CodeGraph | 对照组 |

每组跑同一批任务：find bug, explain module, trace flow, pre-edit refactor, coverage audit, route/service impact。

重点观测指标：

```
first_tool
wrong_entry_tool_rate
workflow_start_rate
broad_search_before_mcp_rate
avg_mcp_calls
fallback_rate
task_success
latency
```

上线门槛：

```
agent profile 的 wrong_entry_tool_rate < full/debug 的 wrong_entry_tool_rate
agent profile 的 broad_search_before_mcp_rate ≈ 0
agent profile 不显著降低任务成功率
```

---

### 4. ✅ Tool Description Optimization

**Decision:** 必须做，优先级高于删工具。

当前问题不是 Agent 不用 CodeGraph，而是入口选错——Agent 偏向 `workflow.find`。

工具描述策略：

| 工具 | 适用场景 | 不适用场景 |
|---|---|---|
| `codegraph_find` | 定位 symbol / route / class / function | 解释模块、改代码前 impact、trace flow |
| `codegraph_explain` | 读源码前解释 symbol/file；understand | — |
| `codegraph_pre_edit_check` | 准备修改文件或符号前；refactor/edit/change | — |
| `codegraph_coverage_gaps` | test audit / missing tests / coverage signal | — |
| `codegraph_build_context_pack` | broad context / scan / deepen / impact mode | — |

Workflow command 入口选择：所有任务不从 `workflow.find` 起步——根据任务类型选择正确的 workflow command。

---

### 5. ✅ workflow.find Performance

**Decision:** `workflow.find` 不能作为普通 find 的默认替代。

| 场景 | 推荐工具 | 典型延迟 |
|---|---|---|
| 普通符号查找 | `codegraph_find` | p95 < 185ms |
| 需要报告/artifacts/审计 | `workflow.find` 或 `harness workflow.find` | p95 ~6000ms |

处理原则：

```
agent profile 保留 codegraph_find
不要把 codegraph_harness_run workflow.find 暴露给普通 Agent
workflow.find 保留在 CLI / workflow command / debug 场景
```

后续可优化 `workflow.find`（批量 get_symbol 调用等），但上线前不把它设为普通 Agent 默认入口。

---

### 6. ✅ Harness Independent Profile

**Decision:** 短期 debug 包含 harness；正式上线前新增 `harness` profile。

最终 profile 矩阵：

| Profile | 工具数 | 内容 |
|---|---|---|
| `agent` | 6 | 普通编码 Agent 默认工具 |
| `full` | 13 | 高级 CodeGraph 工具，不含 harness internals |
| `harness` | 4 | 只暴露 harness list/run/status/artifacts，用于测试和自动化 |
| `debug` | 17 | full + harness + 诊断工具（当前已实现） |

短期不改——debug 已覆盖开发者需求。正式上线前加 `harness` profile，避免用户为了使用 harness status/artifacts 被迫打开所有 debug 工具。

---

## Decision Summary Table

| # | 问题 | 决策 |
|---|---|---|
| 1 | agent profile 默认值 | 默认 `agent` |
| 2 | profile 迁移策略 | 新配置默认 agent，老配置不强制覆盖 |
| 3 | profile A/B 测试 | 上线前必须补测 agent/full/debug |
| 4 | 工具描述优化 | 必须做，优先修入口误选 |
| 5 | workflow.find 性能 | 不作为普通 Agent 默认入口；普通查找用 `codegraph_find` |
| 6 | harness 独立 profile | 短期 debug 包含 harness；正式前新增 `harness` profile |

---

## Immediate Action Items (Priority Order)

1. **优化工具描述和 workflow command** — 让 Agent 不再所有任务都先用 find。最高优先级。
2. **补 agent/full/debug 真实 A/B 测试** — 上线前必须完成，验证 profile 降低 wrong_entry_tool_rate。
3. **新增 `harness` profile** — 正式上线前从 `debug` 中拆分出独立 `harness` profile。

> **当前不删任何工具。** 数据不支持删除，只支持：默认隐藏、描述优化、profile 分层、继续实测。

---

## Non-Deletion Guarantee

**This report recommends zero deletions.** All 17 MCP tools remain fully implemented, registered, tested, and functional. Profile restrictions only control MCP surface exposure — tool implementations are never unregistered or removed.
