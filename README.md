# CodeGraph Explorer

面向 AI 编码 Agent 的多语言本地代码图谱索引与 MCP 查询工具。

**Multi-language local code graph index and MCP toolkit for AI coding agents.**

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-Beta-3178c6)
![JavaScript](https://img.shields.io/badge/JavaScript-Beta-f7df1e)
![Java](https://img.shields.io/badge/Java-Beta-ed8b00)
![Go](https://img.shields.io/badge/Go-Beta-00add8)
![C#](https://img.shields.io/badge/C%23-Beta-512bd4)
![MCP](https://img.shields.io/badge/MCP-Agent%20Tools-purple)
![CodeGraph](https://img.shields.io/badge/CodeGraph-Local%20Index-orange)
![Benchmark](https://img.shields.io/badge/Benchmark--74.6%25%20tokens-success)

CodeGraph Explorer 会提前将代码库解析为结构化代码图谱，让 Claude Code、Cursor、Codex 等 AI 编码 Agent 可以通过 MCP 查询符号、调用者、被调用者、局部子图、影响面、测试信号和索引状态，而不是反复 `grep` / `glob` / `read` 扫描代码文件。

它提供的是 **代码图谱证据层**，不是实现计划生成器。

---

## 为什么需要 CodeGraph Explorer？

AI Coding Agent 在理解代码库时，通常会先用 `grep`、`glob` 和 `Read` 反复扫描文件，寻找符号、调用链、入口点、测试和影响面。

这个过程会消耗大量 token 和工具调用，而且每个新任务都可能重复发生。

CodeGraph Explorer 的做法是：

```text
预先索引代码库
        ↓
生成本地代码图谱
        ↓
通过 MCP 暴露结构化查询工具
        ↓
Agent 按需查询 callers / callees / neighbors / impact
```

Agent 不需要每次都重新扫描整个仓库，而是可以直接查询已经构建好的代码关系图。

这让代码理解过程更快、更稳定，也更节省 token。

---

## 核心亮点

### 让 Agent 更快理解代码库

CodeGraph Explorer 在本地预先建立代码图谱，Agent 可以直接查询符号、调用关系、
入口点、测试和影响面，而不需要每次都重新扫描文件。

### 减少 token 和工具调用

Agent 不再需要反复使用 `grep`、`glob`、`Read` 探索仓库。
它可以通过 MCP 查询已经索引好的结构化信息，从而减少重复的文件读取和上下文浪费。

### 更可靠的影响面分析

修改一个函数前，Agent 可以快速看到哪些上游调用者会受影响、哪些下游逻辑依赖它，
以及相关的测试文件。确定关系和可能关系会被明确区分，避免把低置信度推断混进
确定影响面。

### 自动保持索引新鲜

`codegraph init` 默认安装 post-commit hook。每次 commit 后自动增量更新索引，
减少手动维护成本。索引状态对 Agent 透明，过期时会有明确提示。

### 多语言和主流框架覆盖

Python 为 production 级别支持；TypeScript、JavaScript、Java、Go、C# 提供
Beta 级解析。同时覆盖 FastAPI、Express、Next.js、Spring Boot、Gin、ASP.NET Core
等常见 Web 框架的入口和路由信号。

### Local-first，零遥测

索引、查询和 MCP 服务全部在本地运行。不上传代码、文件路径、索引数据或错误信息。

---

## 语言支持

| Language | Status | Symbols | Imports | Calls | Frameworks | Impact | Notes |
|----------|--------|---------|---------|-------|------------|--------|-------|
| Python | 🟢 Production | Full AST | Full | Intra-file + imported | FastAPI, Flask, Django | Confirmed/possible | LLM-assisted extraction for unparseable files |
| TypeScript | 🟡 Beta | Full tree-sitter | Named/default/namespace/barrel | Intra-file + imported | Express, Next.js, NestJS, React | Confirmed/possible | Dynamic property access, callback heuristics limited |
| JavaScript | 🟡 Beta | Full tree-sitter | require/module.exports | Intra-file + imported | Express, Next.js | Confirmed/possible | Same limits as TypeScript |
| Java | 🟡 Beta | Full tree-sitter | Single/static/wildcard | Intra-file + package-local | Spring Boot (REST, DI) | Confirmed/possible | Overloaded/interface methods not forced confirmed |
| Go | 🟡 Beta | Regex-based | Package import | Intra-package + cross-package | Gin, Hertz | Confirmed/possible | Interface satisfaction, embedded methods limited |
| C# | 🟡 Beta | Regex-based | using/using alias | Intra-namespace + cross-namespace | ASP.NET Core (Controllers, Minimal API, DI) | Confirmed/possible | Extension methods, dynamic/reflection limited |

> **Production** = full confidence for agent use, **Beta** = functional with known limitations, call edges tiered as confirmed/possible/unresolved.

---

## 框架支持

| Framework | Language | Status | Supported Signals |
|-----------|----------|--------|-------------------|
| FastAPI | Python | 🟢 Production | Route decorators, dependency injection, path parameters |
| Flask | Python | 🟢 Production | Route decorators, view functions |
| Django | Python | 🟡 Beta | View heuristics, URL patterns |
| Express | TypeScript/JS | 🟡 Beta | Route handlers (`app.get/post/use`), middleware chains |
| Next.js | TypeScript/JS | 🟡 Beta | File-based routes (`page.tsx`, `route.ts`), API routes |
| NestJS | TypeScript/JS | 🟡 Beta | Controller decorators, `@Injectable` DI resolution |
| Spring Boot | Java | 🟡 Beta | `@RestController`, `@Service`, `@Repository`, `@Autowired` DI |
| Gin | Go | 🟡 Beta | Router groups, route handlers, middleware chains |
| Hertz | Go | 🟡 Beta | Router groups, route handlers, middleware chains |
| ASP.NET Core | C# | 🟡 Beta | `[ApiController]`, `[Route]`, `MapGet`/`MapPost`, constructor DI, `MapGroup` |

> **Route-to-handler** confirmed edges are separated from possible/unresolved. Uncertain relationships never enter confirmed.

---

## Benchmark 结果

我们用内置 Python benchmark fixtures 对比了两种流程：

* **Baseline**：Agent 使用 grep / glob / read 进行代码探索
* **CodeGraph**：Agent 使用 compact MCP 图查询

### 核心指标

| 指标 | 结果 | 阈值 | 状态 |
|------|------|------|------|
| Recall >= baseline | 10/12 (83.3%) | ≥ 7/12 (58%) | ✅ |
| grep/read 调用减少 | 90.3% | ≥ 40% | ✅ |
| 文件读取减少 | 77.5% | ≥ 30% | ✅ |
| Token 减少 | 74.6% | ≥ 10% | ✅ |
| Compact vs Standard payload 减少 | 68.1% | ≥ 30% | ✅ |
| Compact 平均 payload tokens | 685 | ≤ 2,000 | ✅ |
| 完整任务平均 token 估计 | 1,118 | ≤ 3,000 | ✅ |

### 质量指标

| 指标 | 结果 | 说明 |
|------|------|------|
| Symbol recall | 64.3% | 搜索平均召回率 |
| File recall | 92.1% | 文件平均召回率 |
| Top-1 准确率 | 91.7% | 首次搜索结果匹配预期符号 |
| 歧义率 | 0.0% | 返回歧义结果的比例 |
| 误报边 | 0 | 无仅凭名称匹配的虚假 confirmed 边 |
| Impact 已确认/可能分离 | ✅ | 已确认影响不含 unresolved/external |
| MCP stdout 清洁度 | ✅ | 工具响应均为合法 JSON，无日志混杂 |

### Benchmark Regression Gate

每次修改后运行 gate 检查是否回退：

```bash
python -m tests.agent_benchmark.gate
```

或通过 Makefile：

```bash
make benchmark-gate
```

当前 gate 状态：**✅ PASS**（36 checks passed, 0 failed）

> 以上结果来自项目内置 Python benchmark fixtures（12 个任务场景），只代表当前测试集上的方向性结果，不代表所有真实代码库。

---

## Auto-update By Default

Run this once in a Git repository:

```bash
codegraph init
```

By default, `codegraph init` will:

- Build the initial local index in `.codegraph/`
- Install a managed Git `post-commit` hook
- Incrementally update the index after every commit

After that, the normal Git workflow is enough:

```bash
git add .
git commit -m "your change"
codegraph status
codegraph doctor
```

The post-commit hook is non-blocking. If an update fails, Git commit still
finishes successfully and CodeGraph writes a warning to
`.codegraph/logs/hooks.log`. Use `codegraph doctor` to diagnose the issue and
get the repair command, usually `codegraph hooks install --force` or
`codegraph init --force`.

To turn off commit-time auto-update:

```bash
codegraph init --no-hook
codegraph config set auto_update_on_commit false
codegraph hooks uninstall
```

To inspect or repair hook state:

```bash
codegraph hooks status
codegraph doctor
codegraph hooks install --force
```

`post-commit` auto-update runs after commits. If you want the index to update
when files are saved before committing, use watch mode instead:

```bash
codegraph watch
```

## Makefile

```makefile
install:
	pip install -e "backend[mcp,watch]"

update:
	git pull
	pip install -e "backend[mcp,watch]"

uninstall:
	pip uninstall -y codegraph-explorer

init:
	codegraph init .

configure:
	codegraph configure all

doctor:
	codegraph doctor

mcp-check:
	codegraph serve --mcp --check

serve:
	codegraph serve --mcp

watch:
	codegraph watch .

status:
	codegraph status

test:
	pytest backend/tests/

benchmark:
	python -m tests.agent_benchmark.runner --mode baseline
	python -m tests.agent_benchmark.runner --mode codegraph --response-mode compact
	python -m tests.agent_benchmark.runner --mode codegraph --response-mode standard
	python -m tests.agent_benchmark.report

benchmark-gate:
	python -m tests.agent_benchmark.gate

demo: install configure init status
	codegraph context "add MFA to login flow"
```

---

## 在 Claude Code / Cursor 中使用

**推荐由 `codegraph configure` 自动生成配置。** 它会写入当前 Python 环境的绝对路径，避免 Windows PATH 找不到 `codegraph` 命令。

运行以下命令即可自动注册 MCP Server：

```bash
codegraph configure all
```

如需手动配置，参考以下示例（注意使用当前 Python 解释器的绝对路径）：

### Claude Code

用户级配置 `~/.claude.json`：
```json
{
  "mcpServers": {
    "codegraph": {
      "command": "C:\\path\\to\\venv\\Scripts\\python.exe",
      "args": ["-m", "codegraph.mcp_server"],
      "env": {
        "CODEGRAPH_PROJECT_ROOT": "C:\\path\\to\\project"
      }
    }
  }
}
```

macOS / Linux 示例：
```json
{
  "mcpServers": {
    "codegraph": {
      "command": "/path/to/venv/bin/python",
      "args": ["-m", "codegraph.mcp_server"],
      "env": {
        "CODEGRAPH_PROJECT_ROOT": "/path/to/project"
      }
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

## MCP 显示 Error 怎么办？

如果 Claude Code 或 Cursor 的 MCP 面板中 codegraph 显示 "Error"：

```bash
codegraph doctor
```

`doctor` 会检查所有环节并指出问题。常见原因和修复：

### 1. 没有初始化项目索引

```
No CodeGraph index found.
Run: codegraph init
```

在项目目录运行：

```bash
cd your-project
codegraph init
```

### 2. MCP 配置里的路径不对

如果项目路径变更或配置旧了：

```bash
codegraph configure all --force
```

这会用当前项目路径更新 MCP 配置。也可以用 `codegraph configure show` 查看当前配置的路径。

### 3. MCP 配置中的 command 不可用

从 v0.1.1 开始，`codegraph configure` 默认写入当前 Python 解释器的绝对路径（如 `C:\...\python.exe -m codegraph.mcp_server`），不再依赖 `codegraph` 命令在 PATH 中。

如果之前配置的是旧格式且 `codegraph` 不在 PATH 中：

```bash
# 重新生成配置（使用 Python 绝对路径）
codegraph configure all --force

# 或手动安装 codegraph 到 PATH
pip install -e "backend[mcp,watch]"
```

检查是否可用：

```bash
codegraph --help
python -m codegraph.mcp_server --check
codegraph serve --mcp --check
```

如果仍想使用 `codegraph` CLI 入口点作为 MCP 命令：

```bash
codegraph configure all --command codegraph
```

### 4. 修改配置后没有重启 Claude Code / Cursor

MCP 配置在编辑器启动时加载。修改 `~/.claude.json` 或 `~/.cursor/mcp.json` 后，需要重启编辑器。

### 5. 索引文件不完整

如果 `.codegraph/` 目录存在但缺少关键文件：

```bash
codegraph init --force
```

### 6. 看到 "No .codegraph directory found"

说明 MCP 配置中的 `CODEGRAPH_PROJECT_ROOT` 没有指向正确的项目路径（通常是配置时不在项目目录下运行 `codegraph configure`）。解决：

```bash
cd your-project
codegraph init
codegraph configure cursor --force   # 或 codegraph configure all --force
```

重启 Cursor / Claude Code 后生效。

### 快速自检命令

```bash
# 检查环境和配置
codegraph doctor

# 验证 serve --mcp 能启动（不进入 stdio loop）
codegraph serve --mcp --check

# 查看当前 MCP 配置状态
codegraph configure show

# 查看索引状态
codegraph status
```

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
   +--> Evidence Pack Export
```

| 模块          | 作用                                            |
| ----------- | --------------------------------------------- |
| Indexer     | 解析 Python 文件，提取符号、调用、导入、测试和元数据                |
| Graph Store | 存储节点和边，并保留 confidence / resolution / evidence |
| Query Layer | 提供 symbol、callers、callees、neighbors、impact 查询 |
| MCP Server  | 将图查询能力暴露给 AI 编码 Agent                         |
| Benchmark   | 评估 CodeGraph 相比 grep/read 的效率收益               |

---

## Under the Hood

CodeGraph Explorer 当前采用 Python-first 的静态分析流程：

1. 扫描项目文件
2. 解析 Python AST
3. 提取函数、类、方法、导入和调用关系
4. 构建本地代码图谱
5. 计算 confidence / resolution / evidence
6. 通过 CLI 和 MCP Server 暴露查询能力

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

* **Python 是 production 级别**；TypeScript、JavaScript、Java、Go、C# 均为 **Beta** 级别，调用边分为 confirmed / possible / unresolved
* 静态分析无法覆盖动态派发、反射、monkey patch、运行时代码生成
* Benchmark 结果来自内置 fixtures，不代表所有真实项目
* 复杂框架依赖注入链可能需要 Agent 自行验证

各语言的详细限制见 **[KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md)**。

---

## Roadmap

* TypeScript / JavaScript → production quality（from beta）
* Java → production quality（from beta）
* Go → production quality（from beta）
* C# → production quality（from beta）
* 更多框架 route mapping（Ruby on Rails, Laravel, Fiber, Echo）
* 跨语言调用图（cross-language call graph edges）
* 更大的多语言 benchmark suite
* workspace-level indexing（monorepo 支持）
* 更强的 incremental sync

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

索引状态会暴露给 CLI 和 MCP，避免使用过期图谱。

---

## 索引新鲜度与手动同步

CodeGraph 不会在 MCP tool 调用时自动修改索引。每次 MCP 调用都会返回：

- `index_status`：`fresh` / `stale` / `missing` / `error`
- `index_health`：`ok` / `warning` / `error`
- `warnings`：包含具体的修复建议

### 如果索引过期（stale）

Agent 会收到一个 `stale_index` warning，包含 `suggested_fix` 建议。你需要手动运行：

```bash
# 增量更新索引（推荐）
codegraph init --incremental

# 或启动 watch 模式自动保持索引更新
codegraph watch
```

### 如果索引不存在（missing）

MCP server 启动会失败，或 tool 返回错误信息：

```text
No CodeGraph index found. Run: codegraph init
```

### `repo_status` 返回的 suggested_fix 字段

`repo_status` 工具会返回 `suggested_fix` 字段，直接告诉你需要运行什么命令：

- `codegraph init` — 索引不存在，需要首次创建
- `codegraph init --incremental` — 索引存在但过期，需要增量更新
- `codegraph init --force` — 索引损坏，需要完全重建
- `codegraph doctor` — 索引健康检查发现问题

### 保持索引自动更新

如果你希望索引自动保持最新，可以启动 watch 模式：

```bash
codegraph watch
```

或在 MCP server 启动时附带 `--watch` 参数：

```json
{
  "mcpServers": {
    "codegraph": {
      "command": "codegraph",
      "args": ["serve", "--mcp", "--watch"],
      "env": {"CODEGRAPH_PROJECT_ROOT": "/path/to/project"}
    }
  }
}
```

> **重要：CodeGraph 不会在每次 MCP 查询时扫描文件或重新计算哈希。**
> `index_status` 基于 `state.json`、`metadata.json`、`fingerprints.json`、
> `validation_report.json` 的持久化状态判断，不会引入额外的 I/O 开销。

---

## 本地优先 / 零遥测

### Local-first / Zero Telemetry

CodeGraph Explorer 是一个**完全本地运行**的工具。它：

- **不上传任何代码**：所有源码文件只在本地解析，不会发送到任何远程服务
- **不上传文件路径**：项目路径、文件结构仅存储在本地 `.codegraph/` 索引中
- **不上传索引数据**：代码图谱（节点、边、元数据）完全存储在本地
- **不上传错误信息**：所有错误和诊断信息仅输出到本地 stderr
- **不上传使用数据**：不收集任何遥测、分析或使用统计

**CodeGraph Explorer is a fully local tool.** It never uploads code, file paths,
index data, error details, or usage information to any remote service.
All processing happens on the local machine.

如果你在防火墙后或离线环境中使用，CodeGraph Explorer 完全不需要网络访问（除了通过
pip 安装依赖）。

If you work behind a firewall or in an air-gapped environment, CodeGraph Explorer
requires no network access (beyond installing dependencies via pip).

---

## License

MIT

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/mcp-tools.md](docs/mcp-tools.md) | MCP tools reference with parameters and examples |
| [docs/language-support.md](docs/language-support.md) | Language and framework support matrix with limitations |
| [docs/benchmark.md](docs/benchmark.md) | Benchmark suite and regression gate guide |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Common issues and fixes |
| [docs/evidence-pack.md](docs/evidence-pack.md) | Evidence Pack format, usage, and limitations |
| [docs/development.md](docs/development.md) | Development setup, conventions, and workflow |
| [docs/storage.md](docs/storage.md) | Storage layer details |
| [CHANGELOG.md](CHANGELOG.md) | Release history and version changes |
| [docs/PRD/INDEX.md](docs/PRD/INDEX.md) | Full PRD index (design reference) |

---

## Project Status

CodeGraph Explorer 当前重点是验证和打磨：

* Python-first 代码图谱索引
* MCP 细粒度图查询
* compact payload
* impact confirmed / possible 区分
* index freshness
* Agent benchmark

项目不追求替 Agent 做决策，而是提供更可靠、更紧凑、更可解释的代码图谱证据。
