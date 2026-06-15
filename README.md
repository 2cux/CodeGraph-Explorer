# CodeGraph Explorer

Local-first code graph and MCP workflow layer for coding agents.

CodeGraph Explorer 帮助 Claude Code、Codex、Cursor 等编码 Agent 在读文件和改代码前，先通过本地代码图理解符号、调用关系、影响范围和测试覆盖信号。

它是一个纯后端、MCP-native、local-first 的代码图系统：

- 不带 web dashboard
- 不依赖 SaaS 后端
- 不默认上传仓库源码
- 核心索引、本地 SQLite、MCP server、CLI 都在本地运行

## 为什么需要 CodeGraph Explorer？

很多 Agent 在进入任务时会直接 `Glob` / `Grep` / `Read`。这对小改动可以工作，但在这些场景里很容易失焦：

- 跨文件重构
- 共用类型或公共 API 修改
- route / service 影响分析
- 测试覆盖审计
- 模块职责解释和上下文建立

CodeGraph Explorer 先给 Agent 一个结构化入口，让它先问：

- 这个符号在哪里？
- 谁调用它？
- 改它会影响哪些文件和测试？
- 哪些 production symbols 缺少测试信号？
- 这个模块大概负责什么？
- 当前索引是否可信、是否过期？

准确的说法不是“完全替代 Read/Grep”，而是：

> CodeGraph helps agents start with structure and impact before falling back to targeted source reads.

## Quick Start

只保留源码安装路径，不使用 `npm` / `npx` / `curl` / `irm`。

### 1. 安装 CodeGraph Explorer

```bash
git clone https://github.com/2cux/CodeGraph-Explorer.git
cd CodeGraph-Explorer
pip install -e "backend[mcp,watch]"
```

### 2. 在目标项目初始化索引

```bash
cd /path/to/your-project
codegraph init
codegraph doctor
```

### 3. 配置 MCP

```bash
codegraph configure all
```

如果你明确需要覆盖已有配置，可使用：

```bash
codegraph configure all --force
```

这不是必需项，只在你确认需要重写已有配置时再使用。

### 4. 更新

```bash
cd CodeGraph-Explorer
git pull
pip install -e "backend[mcp,watch]"
codegraph configure all --force
codegraph doctor
```

## Workflow-first：让 Agent 先用 CodeGraph

MCP 工具本身是被动的，Agent 不一定会自动优先使用它们。CodeGraph Explorer 提供可选 workflow commands，让用户显式进入 CodeGraph-first 流程。

安装 Claude Code workflow commands：

```bash
codegraph configure workflows --agent claude
```

会生成这些 Markdown workflow 文件：

```text
.claude/commands/codegraph-impact.md
.claude/commands/codegraph-test-audit.md
.claude/commands/codegraph-explain.md
.claude/commands/codegraph-find.md
```

使用方式：

```text
/codegraph-impact
/codegraph-test-audit
/codegraph-explain
/codegraph-find
```

| Command | 用途 |
|---|---|
| `/codegraph-impact` | 修改共用类型、route、service、公共 API 前先看影响范围 |
| `/codegraph-test-audit` | 查找缺少测试信号的 production symbols / files |
| `/codegraph-explain` | 在读完整源码前理解 symbol 或 file |
| `/codegraph-find` | 查找函数、类、方法、route、service，并决定下一步 |

这些 command 文件的边界很明确：

- 是纯 Markdown workflow 文件
- 不修改源码
- 不安装 hook
- 不创建 dashboard
- 不调用外部服务

## Deterministic Workflow CLI

当 MCP 不可用，或你想在 hook / CI / 脚本里稳定复用同一套逻辑时，可以直接使用 workflow CLI。

### 已实现

```bash
codegraph workflow impact --files backend/codegraph/workflow.py --change-type refactor
codegraph workflow test-audit --paths src/** --types function,method
codegraph workflow explain --symbol MemoryService
codegraph workflow find login
```

这些命令是确定性的 CLI 入口，适合作为 MCP fallback，也适合作为本地自动化的稳定执行目标。

## Optional pre-commit impact hook

如果你希望在提交前做一次 warning-only 的本地影响检查，可以安装可选 pre-commit hook：

```bash
codegraph configure git-hook --pre-commit-impact
```

它会读取 staged files，并调用：

```bash
codegraph workflow impact --files <staged files> --change-type unknown --format markdown
```

默认行为：

- warning only，不阻塞 commit
- 不运行测试
- 不修改文件
- 不覆盖已有 hook，除非显式使用 `--force`

如需覆盖已有 hook：

```bash
codegraph configure git-hook --pre-commit-impact --force
```

详情见 [docs/git-hooks.md](docs/git-hooks.md)。

## MCP Tools

`coverage_gaps` 这里指的是基于代码图推断的 test signal，不是 runtime line coverage。

| Tool | 用途 |
|---|---|
| `codegraph_repo_status` | 检查项目根、索引 freshness、健康状态与建议动作 |
| `codegraph_repo_summary` | 获取仓库概览、语言分布、测试覆盖信号摘要 |
| `codegraph_find` | 一步完成 symbol search + 基础详情 |
| `codegraph_explain` | 基于代码图和 evidence 解释 symbol / file |
| `codegraph_pre_edit_check` | 改代码前检查 planned files / symbols 的影响 |
| `codegraph_get_impact` | 查询某个 symbol 的影响范围 |
| `codegraph_get_neighbors` | 查看某个 symbol 周边关系 |
| `codegraph_coverage_gaps` | 查找缺少测试信号的 production symbols / files |
| `codegraph_build_context_pack` | 构建 scan / deepen / impact 模式上下文包 |

## Validation

Recent real-agent A/B regression showed:

- With CodeGraph workflow: 6/6 tasks started with CodeGraph.
- With CodeGraph workflow: 0 broad Read/Grep/Glob before CodeGraph.
- Without CodeGraph: 6/6 tasks started with broad `rg`.
- Average CodeGraph calls in workflow mode: about 2 per task.
- One trace/flow case still required targeted `rg`, which is tracked as a sufficiency improvement.

Known follow-ups:

- Improve PowerShell wildcard handling for workflow paths.
- Improve trace / flow sufficiency.
- Improve `next_recommended_tools` follow-through.
- Improve dropped-edge diagnostics and index health reporting.

这些结果说明 CodeGraph 更擅长把 broad grep 变成 targeted fallback，而不是宣称所有场景都不再需要读源码。

## Backend-only and local-first

CodeGraph Explorer does not ship a web dashboard.
It does not require a SaaS backend.
It does not upload your repository by default.
The core index is local.
The MCP server and CLI run locally.

关于后续 LLM enrichment，当前不写成已内置 provider。规划方向是：

> Planned: Agent-side zero-config enrichment
>
> Future enrichment is designed to run through the user's coding agent workflow, not through a mandatory CodeGraph-hosted LLM API. CodeGraph will prepare bounded inputs, validate agent-generated JSON, and import local metadata.

## Agent 使用建议

CodeGraph MCP 安装完成后，Agent 不一定会自动优先使用它。Agent 仍然可能默认使用 Read / Grep / Glob。

如果希望 Agent 在某个目标项目里优先调用 CodeGraph MCP，需要把下面的提示块复制到目标项目的规则文件中。这里说的是目标项目，不是 CodeGraph Explorer 仓库本身。

### 目标位置

| Agent | 文件 |
|---|---|
| Claude Code | `CLAUDE.md` |
| Cursor | `.cursor/rules/codegraph.mdc` |
| 其他 Agent | `AGENTS.md` |

### CodeGraph Usage

```markdown
## CodeGraph Usage

This repository is indexed by CodeGraph.

Before code exploration, bug fixing, refactoring, feature implementation, or impact analysis, use CodeGraph MCP before grep/glob/read-heavy exploration.

Start with `codegraph_build_context_pack` for larger tasks.

Use:
- `codegraph_repo_summary` to understand repository structure.
- `codegraph_search_symbols` to find functions, classes, methods, routes, and entry points.
- `codegraph_get_neighbors` to inspect relationships around a symbol.
- `codegraph_get_callers` and `codegraph_get_callees` instead of grep for call chains.
- `codegraph_get_impact` before modifying shared code.

Use `Read` only when exact source text is needed.
```

几点边界需要明确：

- 这个提示块不会自动写入任何文件，需要手动复制
- 它是建议性的，不是要求 Agent 必须使用 CodeGraph 的机制
- 它帮助 Agent 更早进入结构化导航，但 does not automatically replace Read/Grep

## Roadmap

### 近期

- Better index health diagnostics: dropped-edge categories, top examples, auto-correction report.
- Better search ranking: production entry boost, test-file penalty, named seed injection.
- Better sufficiency: evidence, confidence, file-level staleness, targeted snippets.
- Better workflow follow-through: required next steps after find / impact / test-audit.
- Better shell compatibility for workflow paths on PowerShell.

### 后续

- Agent-side zero-config enrichment.
- Dynamic dispatch heuristics for callbacks, events, React, middleware.
- Non-code architecture files: Dockerfile, CI, package config, SQL, GraphQL, Terraform.
- More A/B evaluation gates.

## Known Issues

- Some Java / TypeScript tree-sitter dependency failures may still appear in the full backend test suite depending on local parser setup.
- High dropped-edge ratio should be inspected with `codegraph doctor`; fine-grained diagnostics are being improved.
- PowerShell wildcard expansion for workflow paths needs better handling.
- Flow tracing may still fall back to targeted grep when the current graph lacks enough caller/import evidence.

## 文档

| 文档 | 说明 |
|---|---|
| [docs/mcp-tools.md](docs/mcp-tools.md) | MCP 工具说明、推荐工作流与 CLI workflow 示例 |
| [docs/git-hooks.md](docs/git-hooks.md) | `pre-commit-impact` hook 的安装、覆盖和备份行为 |
| [docs/agent-adoption-test.md](docs/agent-adoption-test.md) | 如何验证 Agent 是否先用 CodeGraph |
| [docs/agent-adoption-p0-test.md](docs/agent-adoption-p0-test.md) | `coverage_gaps`、`pre_edit_check`、workflow commands、git hook 验证 |
| [docs/benchmark.md](docs/benchmark.md) | benchmark 与 regression gate |
| [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md) | 当前语言/框架限制 |

## License

MIT
