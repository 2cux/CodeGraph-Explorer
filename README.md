# CodeGraph Explorer

面向 AI Coding Agent 的本地代码图谱 MCP 后端。

*Local-first MCP code graph backend for AI coding agents.*

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-Beta-3178c6)
![JavaScript](https://img.shields.io/badge/JavaScript-Beta-f7df1e)
![Java](https://img.shields.io/badge/Java-Beta-ed8b00)
![Go](https://img.shields.io/badge/Go-Beta-00add8)
![C#](https://img.shields.io/badge/C%23-Beta-512bd4)
![MCP](https://img.shields.io/badge/MCP-Agent%20Tools-purple)
![CodeGraph](https://img.shields.io/badge/CodeGraph-Local%20Index-orange)
![Benchmark](https://img.shields.io/badge/Benchmark--74.6%25%20tokens-success)

CodeGraph Explorer 会预先索引代码库，生成本地代码图谱，并通过 MCP 暴露符号、调用关系、影响面和框架入口查询能力。Agent 不需要每次任务都重新 `grep` / `read` 整个仓库。

---

- **MCP-first**：为 Claude Code、Cursor、Codex 等 Agent 提供细粒度代码查询
- **Local-first**：索引和查询都在本地运行，零遥测
- **Token-efficient**：减少重复 `grep` / `read` 和大段文件读取
- **Auto-updated**：`codegraph init` 默认安装 post-commit hook，提交后自动更新索引
- **Multi-language**：Python Production，TypeScript / JavaScript / Java / Go / C# Beta

---

## 快速开始

### 1. 安装

最简单的安装方式，直接告诉你的编码Agent，帮我安装并配置这个mcp
```
https://github.com/2cux/CodeGraph-Explorer
```
在命令行中安装
```bash
git clone https://github.com/2cux/CodeGraph-Explorer.git
cd CodeGraph-Explorer
pip install -e "backend[mcp,watch]"
```

**pipx 安装：**

```bash
pipx install "git+https://github.com/2cux/CodeGraph-Explorer.git"
```


### 2. 配置 Agent
如果你是手动安装则要给你的编码Agent配置一下
```bash
codegraph configure all
```

自动配置 Claude Code 和 Cursor，使其在启动时加载 CodeGraph MCP 工具。

### 3. 初始化项目

```bash
cd your-project
codegraph init
```

构建本地 `.codegraph/` 索引，并默认安装 post-commit 自动更新 hook。

### 4. 检查状态

```bash
codegraph doctor
```

验证索引完整性、MCP 配置、auto-update hook 和本地环境。

完成后，打开 Claude Code 或 Cursor，即可让 Agent 使用 CodeGraph 进行代码库导航。

> 💡 **提示**：如果 Agent 已经配置了 CodeGraph MCP，但仍然习惯使用 grep/read，可以把下方「Agent 使用建议」中的提示块复制到目标项目的 CLAUDE.md、Cursor Rules 或 AGENTS.md。

---

## 维护命令

### 更新

**从源码安装：**

```bash
cd CodeGraph-Explorer
git pull
pip install -e "backend[mcp,watch]"
codegraph configure all --force
codegraph doctor
```

**pipx 安装：**

```bash
pipx upgrade codegraph
```

### 关闭自动更新

```bash
codegraph config set auto_update_on_commit false
```

或移除 post-commit hook：

```bash
codegraph hooks uninstall
```

### 卸载

**从源码安装：**

```bash
pip uninstall codegraph
```

**pipx 安装：**

```bash
pipx uninstall codegraph
```

MCP 配置文件（`~/.claude.json`、`~/.cursor/mcp.json`）不会自动删除。如需清理 MCP 配置：

```bash
codegraph configure remove all
```

---

## 语言支持

| 语言 | 状态 | 符号提取 | 导入解析 | 调用关系 | 框架支持 | 影响面 | 备注 |
|----------|--------|---------|---------|-------|------------|--------|-------|
| Python | 🟢 Production | Full AST | Full | Intra-file + imported | FastAPI, Flask, Django | Confirmed/possible | 解析失败时回退 LLM 辅助提取 |
| TypeScript | 🟡 Beta | Full tree-sitter | Named/default/namespace/barrel | Intra-file + imported | Express, Next.js, NestJS, React | Confirmed/possible | 动态属性访问、回调启发式有限 |
| JavaScript | 🟡 Beta | Full tree-sitter | require/module.exports | Intra-file + imported | Express, Next.js | Confirmed/possible | 与 TypeScript 相同限制 |
| Java | 🟡 Beta | Full tree-sitter | Single/static/wildcard | Intra-file + package-local | Spring Boot (REST, DI) | Confirmed/possible | 重载/接口方法不强制 confirmed |
| Go | 🟡 Beta | Regex-based | Package import | Intra-package + cross-package | Gin, Hertz | Confirmed/possible | 接口实现、嵌入方法有限 |
| C# | 🟡 Beta | Regex-based | using/using alias | Intra-namespace + cross-namespace | ASP.NET Core (Controllers, Minimal API, DI) | Confirmed/possible | 扩展方法、动态/反射有限 |

> **Production** = Agent 可直接信赖；**Beta** = 已知限制下可用，调用边分为 confirmed / possible / unresolved。

---

## 框架支持

| 框架 | 语言 | 状态 | 支持信号 |
|-----------|----------|--------|-------------------|
| FastAPI | Python | 🟢 Production | Route 装饰器、依赖注入、路径参数 |
| Flask | Python | 🟢 Production | Route 装饰器、视图函数 |
| Django | Python | 🟡 Beta | View 启发式、URL 模式 |
| Express | TypeScript/JS | 🟡 Beta | Route handler（`app.get/post/use`）、中间件链 |
| Next.js | TypeScript/JS | 🟡 Beta | 文件路由（`page.tsx`、`route.ts`）、API routes |
| NestJS | TypeScript/JS | 🟡 Beta | Controller 装饰器、`@Injectable` DI 解析 |
| Spring Boot | Java | 🟡 Beta | `@RestController`、`@Service`、`@Repository`、`@Autowired` DI |
| Gin | Go | 🟡 Beta | Router 分组、路由 handler、中间件链 |
| Hertz | Go | 🟡 Beta | Router 分组、路由 handler、中间件链 |
| ASP.NET Core | C# | 🟡 Beta | `[ApiController]`、`[Route]`、`MapGet`/`MapPost`、构造函数 DI、`MapGroup` |

> Route-to-handler 的 confirmed 边与 possible/unresolved 严格区分。不确定的关系不会进入 confirmed。

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

## 自动更新

在 Git 仓库中只需运行一次：

```bash
codegraph init
```

默认情况下，`codegraph init` 会：

- 在 `.codegraph/` 中构建初始本地索引
- 安装 Git `post-commit` hook
- 每次 commit 后自动增量更新索引

之后，正常的 Git 工作流即可：

```bash
git add .
git commit -m "your change"
codegraph status
codegraph doctor
```

post-commit hook 是非阻塞的。即使更新失败，Git commit 仍会正常完成，CodeGraph 会将警告写入 `.codegraph/logs/hooks.log`。使用 `codegraph doctor` 诊断问题并获取修复命令，通常是 `codegraph hooks install --force` 或 `codegraph init --force`。

关闭 commit 时自动更新：

```bash
codegraph init --no-hook
codegraph config set auto_update_on_commit false
codegraph hooks uninstall
```

检查或修复 hook 状态：

```bash
codegraph hooks status
codegraph doctor
codegraph hooks install --force
```

`post-commit` 自动更新在 commit 后触发。如果需要在保存文件时（commit 前）更新索引，可使用 watch 模式：

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
	pip uninstall -y codegraph

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

**全局 auto-detect（推荐，适合多项目）：**

用户级配置 `~/.claude.json`：
```json
{
  "mcpServers": {
    "codegraph": {
      "command": "C:\\path\\to\\venv\\Scripts\\python.exe",
      "args": ["-m", "codegraph.mcp_server"]
    }
  }
}
```

不加 `env.CODEGRAPH_PROJECT_ROOT`，MCP Server 会自动根据当前工作目录查找 `.codegraph/`。

**项目绑定（适合固定项目）：**

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
      "args": ["-m", "codegraph.mcp_server"]
    }
  }
}
```

项目级配置 `<project>/.mcp.json` 使用相同格式。

### Cursor

用户级配置 `~/.cursor/mcp.json`，项目级配置 `<project>/.cursor/mcp.json`，格式同上。

MCP Server 会自动从当前工作目录检测 `.codegraph/` 索引。如需指定固定路径，在 `env` 中设置 `CODEGRAPH_PROJECT_ROOT`。

CodeGraph Explorer 本身不需要修改 `CLAUDE.md`、Cursor rules 或其他 Agent 指令文件。它只提供 MCP 工具，不向 Agent 注入实现建议。如需让 Agent 在**目标项目**中优先使用 CodeGraph，参考下方「Agent 使用建议」中的提示块。

---

## Agent 使用建议

CodeGraph MCP 安装完成后，Agent 不一定会自动优先使用它。Agent 仍然可能默认使用 Read / Grep / Glob。

如果希望 Agent 在某个项目里优先调用 CodeGraph MCP，需要把下面的提示块复制到**该项目的** Agent 规则文件中。

### 多项目使用

如果你在多个项目中使用 CodeGraph：

- **推荐使用全局 auto-detect 配置**：`codegraph configure all`（不加 `--root`），MCP Server 会自动跟随当前工作目录查找 `.codegraph/`
- **每个项目只需运行一次** `codegraph init`
- **不推荐**在全局配置中写死 `CODEGRAPH_PROJECT_ROOT`，否则在其他项目中 MCP 会查错索引
- 使用 `codegraph doctor` 或 MCP 工具 `codegraph_repo_status` 检查当前 MCP 查询的是哪个项目
- 详见 [docs/multi-project-setup.md](docs/multi-project-setup.md)

### 目标位置

| Agent | 目标文件 |
|-------|---------|
| Claude Code | 目标项目根目录的 `CLAUDE.md` |
| Cursor | 目标项目的 `.cursor/rules/codegraph.mdc` |
| 其他 Agent | 目标项目的 `AGENTS.md` 或对应规则文件 |

> 注意：这里说的是**你要分析/修改的项目**，不是 CodeGraph Explorer 仓库本身。

### 提示块

复制下面这段到目标项目的 Agent 规则文件：

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

### 目标项目使用流程

在复制提示块之前，先在目标项目中完成索引：

```bash
cd your-project
codegraph init
codegraph doctor
```

`doctor` 显示索引正常（symbols > 0，index_health 为 ok），再把 CodeGraph Usage 提示块复制到该项目的 `CLAUDE.md` 或 Cursor Rules。

### 验证 Agent 是否使用了 CodeGraph

参考 [docs/agent-adoption-test.md](docs/agent-adoption-test.md) 的验证流程。

### 重要说明

- CodeGraph 提供 MCP 工具和使用建议，帮助 Agent 优先使用结构化代码导航，减少重复 grep/read。
- 提示块不会自动写入任何文件，需要手动复制。
- 提示块是**建议性**的，不强制 Agent 调用 MCP。

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

**全局配置（推荐）：**

```bash
codegraph configure all --force
```

不加 `--root` 时，MCP Server 会自动跟随当前项目（auto-detect 模式），适合多项目使用。

**项目绑定配置：**

```bash
codegraph configure all --root /path/to/project --force
```

如果只想让某个项目固定使用 CodeGraph，可以使用项目级配置：

```bash
codegraph configure all --project
```

> 不推荐在全局配置中写死 `CODEGRAPH_PROJECT_ROOT`。如果配置了固定的项目路径，MCP 在其他项目中会查错索引。用 `codegraph doctor` 检查是否有跨项目绑定风险。

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

## 工作原理

CodeGraph Explorer 当前采用 Python-first 的静态分析流程：

1. 扫描项目文件
2. 解析 Python AST
3. 提取函数、类、方法、导入和调用关系
4. 构建本地代码图谱
5. 计算 confidence / resolution / evidence
6. 通过 CLI 和 MCP Server 暴露查询能力

核心目标不是生成自然语言解释，而是提供稳定、可查询、可验证的代码图谱证据。

---

## 运行 Benchmark

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

## 路线图

* TypeScript / JavaScript → production quality（从 beta 升级）
* Java → production quality（从 beta 升级）
* Go → production quality（从 beta 升级）
* C# → production quality（从 beta 升级）
* 更多框架 route mapping（Ruby on Rails, Laravel, Fiber, Echo）
* 跨语言调用图
* 更大的多语言 benchmark suite
* workspace 级索引（monorepo 支持）
* 更强的增量同步

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

## 本地优先 · 零遥测

CodeGraph Explorer 是一个**完全本地运行**的工具：

- **不上传任何代码**：所有源码文件只在本地解析，不会发送到任何远程服务
- **不上传文件路径**：项目路径、文件结构仅存储在本地 `.codegraph/` 索引中
- **不上传索引数据**：代码图谱（节点、边、元数据）完全存储在本地
- **不上传错误信息**：所有错误和诊断信息仅输出到本地 stderr
- **不上传使用数据**：不收集任何遥测、分析或使用统计

如果你在防火墙后或离线环境中使用，CodeGraph Explorer 完全不需要网络访问（除了通过 pip 安装依赖）。

---

## 许可证

MIT

---

## 文档

| 文档 | 说明 |
|----------|-------------|
| [docs/mcp-tools.md](docs/mcp-tools.md) | MCP 工具参考，含参数与示例 |
| [docs/language-support.md](docs/language-support.md) | 语言与框架支持矩阵及限制 |
| [docs/benchmark.md](docs/benchmark.md) | Benchmark 套件与 regression gate 指南 |
| [docs/troubleshooting.md](docs/troubleshooting.md) | 常见问题及修复 |
| [docs/multi-project-setup.md](docs/multi-project-setup.md) | 多项目配置指南：全局 vs 项目绑定 |
| [docs/evidence-pack.md](docs/evidence-pack.md) | Evidence Pack 格式、用法与限制 |
| [docs/agent-adoption-test.md](docs/agent-adoption-test.md) | Agent 是否使用 CodeGraph 的验证流程 |
| [docs/development.md](docs/development.md) | 开发环境、规范与工作流 |
| [docs/storage.md](docs/storage.md) | 存储层详情 |
| [CHANGELOG.md](CHANGELOG.md) | 版本历史与变更记录 |
| [docs/PRD/INDEX.md](docs/PRD/INDEX.md) | 完整 PRD 索引（设计参考） |

---

## 项目状态

CodeGraph Explorer 当前重点是验证和打磨：

* Python-first 代码图谱索引
* MCP 细粒度图查询
* compact payload
* impact confirmed / possible 区分
* index freshness
* Agent benchmark

项目不追求替 Agent 做决策，而是提供更可靠、更紧凑、更可解释的代码图谱证据。
