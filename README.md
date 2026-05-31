# CodeGraph Explorer

面向 AI 编码 Agent 的本地代码图谱索引与 MCP 查询工具。

**Python-first local code graph index and MCP toolkit for AI coding agents.**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![MCP](https://img.shields.io/badge/MCP-Agent%20Tools-purple)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-green)
![CodeGraph](https://img.shields.io/badge/CodeGraph-Local%20Index-orange)
![Benchmark](https://img.shields.io/badge/Benchmark--31.3%25%20tokens-success)

CodeGraph Explorer 会提前将代码库解析为结构化代码图谱，让 Claude Code、Cursor、Codex 等 AI 编码 Agent 可以通过 MCP 查询符号、调用者、被调用者、局部子图、影响面、测试信号和索引状态，而不是反复 `grep` / `glob` / `read` 扫描代码文件。

它提供的是 **代码图谱证据层**，不是实现计划生成器。

---

## 为什么需要 CodeGraph Explorer？

你让 Agent 修改一个大型项目里的登录逻辑。

Agent 通常会先做这些事：

* 搜索 `login`
* 读取多个 `auth` 文件
* 手动追踪调用链
* 查找 token 存储逻辑
* 查找相关测试
* 估算修改影响面

这些探索过程会消耗大量工具调用和 token。

CodeGraph Explorer 的做法是：

```text
先索引代码库
      ↓
生成本地代码图谱
      ↓
通过 MCP 暴露细粒度查询工具
      ↓
Agent 按需查询 callers / callees / neighbors / impact
```

让 Agent 不再每次任务都重新扫描整个代码库。

---

## 核心亮点

### MCP-first，而不是一次性大上下文

CodeGraph Explorer 的主路径是 MCP 细粒度查询。

Agent 可以按需调用：

* `codegraph_search_symbols`
* `codegraph_get_symbol`
* `codegraph_get_callers`
* `codegraph_get_callees`
* `codegraph_get_neighbors`
* `codegraph_get_impact`

而不是一次性接收一个巨大的上下文包。

---

### Compact 输出，减少 MCP payload

MCP 工具默认返回紧凑 JSON，只保留关键字段：

* `symbol_id`
* `file_path`
* `confidence`
* `resolution`
* `reason_codes`
* `relation`

需要完整解释时，再显式请求标准输出。

---

### 影响面分析区分 confirmed / possible

`codegraph_get_impact` 会区分：

* confirmed impact
* possible impact
* related tests
* external / unresolved calls

避免把低置信度关系、同模块 sibling、external 调用混进确定影响面。

---

### 可解释的代码关系

关键边和关系可以包含：

* `confidence`
* `confidence_level`
* `resolution`
* `reason_codes`
* `evidence`

这让 Agent 和开发者都能判断：这条关系是确定事实，还是弱推断。

---

### 索引新鲜度检测

CodeGraph Explorer 会检测索引是否过期：

* `fresh`
* `stale`
* `missing`
* `indexing`
* `error`

避免 Agent 基于旧图谱继续推理。

---

### Dashboard：证据验证界面

Dashboard 不是花哨大屏，也不是 Agent 计划器。

它用于验证 CodeGraph 返回的 evidence：

* 节点
* 边
* confidence
* resolution
* evidence
* confirmed / possible impact
* index status
* warnings

---

## Benchmark 结果

我们用内置 Python benchmark fixtures 对比了两种流程：

* **Baseline**：Agent 使用 grep / glob / read 进行代码探索
* **CodeGraph**：Agent 使用 compact MCP 图查询

| 指标                       |        优化前 |         优化后 |     目标 |
| ------------------------ | ---------: | ----------: | -----: |
| Recall 不低于 baseline      | 6/12 (50%) | 11/12 (92%) | ≥ 8/12 |
| grep/read 调用减少           |      -100% |      -90.3% |  ≥ 30% |
| 文件读取减少                   |      -100% |      -77.5% |  ≥ 25% |
| token 估算减少               |   +54%（更差） |      -29.1% |  ≥ 20% |
| MCP discovery payload 减少 |        N/A |      -60.5% |      — |
| 完整任务 token 估算            |        N/A |      -31.3% |      — |

> 以上结果来自项目内置 Python benchmark fixtures，只代表当前测试集上的方向性结果，不代表所有真实代码库。

---

## Quick Start

### 1. 安装（首次安装）

```bash
git clone <repo-url>
cd CodeGraph-Explorer
pip install -e "backend[mcp,watch]"
```

然后配置 MCP Server：

```bash
codegraph configure all        # 同时配置 Claude Code 和 Cursor
codegraph configure claude     # 仅配置 Claude Code
codegraph configure cursor     # 仅配置 Cursor
```

在项目目录中初始化本地索引：

```bash
cd your-project
codegraph init
```

查看索引状态：

```bash
codegraph status
```

可选：启动 Watch Mode 自动同步文件变更。

```bash
codegraph watch ./examples/demo_python_project
```

### 2. 更新（获取最新版本）

GitHub 安装方式：

```bash
cd CodeGraph-Explorer
git pull
pip install -e "backend[mcp,watch]"
```

或使用 CLI 命令：

```bash
codegraph update
```

更新不会影响已有的 MCP 配置和索引文件。

### 3. 删除/卸载（完全移除 CLI 和依赖）

```bash
pip uninstall codegraph-explorer
```

如果是 GitHub clone 安装，额外删除项目目录：

```bash
rm -rf CodeGraph-Explorer
```

MCP 配置文件（`~/.claude.json`、`~/.cursor/mcp.json`）不会被自动删除。如需移除 MCP 配置：

```bash
codegraph configure remove all
```

---

## 一键运行 Demo

```bash
make demo
```

如果项目还没有 `Makefile`，可以添加：

```makefile
install:
	pip install -e "backend[mcp,watch]"

update:
	git pull
	pip install -e "backend[mcp,watch]"

uninstall:
	pip uninstall -y codegraph-explorer

configure:
	codegraph configure all

init-demo:
	cd examples/demo_python_project && codegraph init

status:
	codegraph status

dashboard:
	cd frontend && npm install && npm run dev

benchmark:
	python -m tests.agent_benchmark.runner --mode baseline
	python -m tests.agent_benchmark.runner --mode codegraph
	python -m tests.agent_benchmark.report

demo: install configure init-demo status
	codegraph context "add MFA to login flow"
```

如果要同时体验 Dashboard：

```bash
make dashboard
```

---

## 在 Claude Code / Cursor 中使用

运行 `codegraph configure all` 即可自动注册 MCP Server。或手动添加到配置文件：

### Claude Code

用户级配置 `~/.claude.json`：
```json
{
  "mcpServers": {
    "codegraph": {
      "command": "python",
      "args": ["-m", "codegraph.mcp_server"]
    }
  }
}
```

项目级配置 `<project>/.mcp.json` 使用相同格式。

### Cursor

用户级配置 `~/.cursor/mcp.json`，项目级配置 `<project>/.cursor/mcp.json`，格式同上。

MCP Server 会自动从当前工作目录检测 `.codegraph/` 索引。如需指定固定路径，在 `env` 中设置 `CODEGRAPH_PROJECT_ROOT`。

CodeGraph Explorer 不需要修改 `CLAUDE.md`、Cursor rules 或其他 Agent 指令文件。它只提供 MCP 工具，不向 Agent 注入实现建议。

---

## MCP 工具一览

| 工具                             | 用途                             |
| ------------------------------ | ------------------------------ |
| `codegraph_search_symbols`     | 按名称、类型、标签或路径搜索符号               |
| `codegraph_get_symbol`         | 获取符号位置、签名、元数据和可选源码片段           |
| `codegraph_get_callers`        | 查询某个符号的上游调用者                   |
| `codegraph_get_callees`        | 查询某个符号的下游被调用者                  |
| `codegraph_get_neighbors`      | 获取某个符号周围的局部子图                  |
| `codegraph_get_impact`         | 查询修改某个符号可能影响的文件和测试             |
| `codegraph_repo_status`        | 查看索引是否 fresh / stale / missing |
| `codegraph_repo_summary`       | 查看仓库图谱统计信息                     |
| `codegraph_build_context_pack` | 生成可选 Evidence Pack 快照          |

---

## 示例：Agent 查询调用关系

Agent 想知道：

```text
login 会调用哪些下游逻辑？
```

它可以调用：

```text
codegraph_get_callees("app/api/auth.py::login")
```

返回结构化结果：

```json
{
  "target": "app/api/auth.py::login",
  "callees": [
    {
      "symbol_id": "app/services/auth_service.py::AuthService.login_user",
      "file_path": "app/services/auth_service.py",
      "distance": 1,
      "confidence": 0.88,
      "resolution": "module_instance_resolved"
    }
  ]
}
```

---

## 示例：Agent 查询影响面

Agent 想知道：

```text
如果修改 login，会影响哪些文件？
```

它可以调用：

```text
codegraph_get_impact("app/api/auth.py::login")
```

返回结果区分：

* confirmed impact
* possible impact
* related tests
* unresolved / external calls

这样 Agent 不需要手动递归追踪调用链。

---

## Dashboard

Dashboard 的定位是 **Evidence Verification UI**。

它用于查看：

* 局部代码图谱
* 节点详情
* 边详情
* `confidence`
* `resolution`
* `evidence`
* confirmed / possible impact
* index status
* warnings / pack notes

如果已有截图：

```markdown
![Dashboard](docs/assets/dashboard.png)
```

如果暂时没有截图：

```markdown
截图待补充。
```

---

## Evidence Pack

Evidence Pack 是一个可选的任务级代码证据快照，适合：

* 人类查看任务相关代码证据
* 复制给不支持 MCP 的 Agent
* 导出 JSON / Markdown 作为上下文材料

Evidence Pack 不包含：

* Reading Plan
* Agent Instructions
* 实现建议
* 执行顺序

它只包含结构化 evidence，例如：

* entry point candidates
* selected_context
* related_symbols
* call_graph
* impact signals
* tests
* warnings
* pack_notes
* token_budget

---

## 它是什么 / 不是什么

### CodeGraph Explorer 是

* 本地代码图谱索引工具
* 面向 AI 编码 Agent 的 MCP 工具集
* 结构化代码证据检索层
* 调用关系 / 影响面 / 测试信号查询工具
* 人类验证 evidence 的 Dashboard

### CodeGraph Explorer 不是

* 不是实现计划生成器
* 不是 Reading Plan 生成器
* 不是 Agent Instructions 生成器
* 不是替代 Agent 推理的系统
* 不是完整运行时语义分析器
* 不是通用代码搜索 UI

---

## 架构概览

```text
Repository
   |
   v
Indexer
   |
   v
Code Graph Store
   |
   +--> CLI
   +--> MCP Server
   +--> Dashboard API
   +--> Evidence Pack Export
```

| 模块          | 作用                                            |
| ----------- | --------------------------------------------- |
| Indexer     | 解析 Python 文件，提取符号、调用、导入、测试和元数据                |
| Graph Store | 存储节点和边，并保留 confidence / resolution / evidence |
| Query Layer | 提供 symbol、callers、callees、neighbors、impact 查询 |
| MCP Server  | 将图查询能力暴露给 AI 编码 Agent                         |
| Dashboard   | 面向人类的 evidence 验证界面                           |
| Benchmark   | 评估 CodeGraph 相比 grep/read 的效率收益               |

---

## Under the Hood

CodeGraph Explorer 当前采用 Python-first 的静态分析流程：

1. 扫描项目文件
2. 解析 Python AST
3. 提取函数、类、方法、导入和调用关系
4. 构建本地代码图谱
5. 计算 confidence / resolution / evidence
6. 通过 CLI、MCP Server 和 Dashboard API 暴露查询能力

核心目标不是生成自然语言解释，而是提供稳定、可查询、可验证的代码图谱证据。

---

## Benchmark

运行 benchmark：

```bash
python -m tests.agent_benchmark.runner --mode baseline
python -m tests.agent_benchmark.runner --mode codegraph
python -m tests.agent_benchmark.report
```

报告会生成到：

```text
reports/agent_benchmark.md
```

Benchmark 记录：

* expected symbol recall
* expected file recall
* grep / glob / read 调用数
* MCP payload tokens
* discovery token estimate
* full task token estimate
* elapsed time
* failure cases

---

## 推荐 GitHub Topics

请在 GitHub 仓库设置中添加：

```text
codegraph
code-intelligence
ai-coding
ai-agent
mcp
model-context-protocol
static-analysis
ast
python
fastapi
graph
knowledge-graph
developer-tools
code-search
impact-analysis
claude-code
cursor
codex
rag
graph-rag
```

> Topics 需要在 GitHub 仓库页面手动设置，README 中写入不会自动生效。

---

## 当前局限

* 目前是 Python-first
* 静态分析无法覆盖所有动态派发和 monkey patch
* 多语言项目支持有限
* benchmark 结果来自内置 fixtures，不代表所有真实项目
* 复杂框架依赖注入仍可能需要 Agent 自行验证

---

## Roadmap

* TypeScript / JavaScript 支持
* Java 支持
* 更多框架 route mapping
* 更强的 test discovery
* 更大的 benchmark suite
* workspace-level indexing
* 更强的 incremental sync
* Dashboard 过滤和对比能力

---

## 设计原则

### MCP-first

主工作流是 MCP 细粒度查询，而不是一次性大上下文。

### Compact by default

默认返回紧凑 JSON，避免把 token 消耗转移到 MCP payload 上。

### Evidence, not plans

CodeGraph Explorer 提供结构化代码证据，不生成阅读计划、实现计划或 Agent 指令。

### Confidence-aware

关键关系带有置信度和解析来源，便于 Agent 和开发者判断可信度。

### Freshness-aware

索引状态会暴露给 CLI、MCP 和 Dashboard，避免使用过期图谱。

### Human-verifiable

Dashboard 用于让开发者验证图谱关系、confidence、resolution 和 impact signals。

---

## License

MIT

---

## Project Status

CodeGraph Explorer 当前重点是验证和打磨：

* Python-first 代码图谱索引
* MCP 细粒度图查询
* compact payload
* impact confirmed / possible 区分
* index freshness
* Dashboard evidence verification
* Agent benchmark

项目不追求替 Agent 做决策，而是提供更可靠、更紧凑、更可解释的代码图谱证据。
