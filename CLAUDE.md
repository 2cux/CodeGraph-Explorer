# CLAUDE.md

## Project Overview

CodeGraph Explorer is a Python-first local code graph index and MCP toolkit for AI coding agents.
It helps agents query symbols, callers, callees, local subgraphs, impact, tests, and index freshness through structured tools instead of repeatedly grep/glob/read scanning the repository.

CodeGraph Explorer 是一个 Python-first 的本地代码图谱索引与 MCP 工具集，用于帮助 AI 编码 Agent 通过结构化工具查询符号、调用关系、局部子图、影响面、测试信号和索引新鲜度，减少重复 grep、glob 和文件读取。

核心定位：**MCP-first, Dashboard as evidence verifier**。MCP 细粒度图查询工具是 Agent 的主入口，Dashboard 是人类验证证据的界面，Evidence Pack 是可选的非 MCP 快照。

## Product Scope

当前处于 Phase 0（未开始编码），基于 PRD 定义的 MVP 范围：

### MVP 核心功能（按优先级排序）

1. **MCP 细粒度图查询工具** — Agent 通过 MCP 协议按需调用结构化查询工具，替代 grep/glob/read 扫描
   - `search_symbols` — 搜索代码符号
   - `get_symbol` — 获取符号详情（签名、docstring、源码位置）
   - `get_callers` — 查询调用者
   - `get_callees` — 查询被调用者
   - `get_neighbors` — 查询局部子图（center node + depth）
   - `get_impact` — 分析修改影响面
   - `repo_status` — 检查索引新鲜度、覆盖率、低置信度边比例
   - `build_evidence_pack` — 可选快照导出（summary-only，供人类或非 MCP Agent 使用）
2. **可靠索引与新鲜度检测** — `/codegraph index` 扫描代码库，解析 AST，构建代码图谱；`repo_status` 检测索引是否过期
3. **Impact / neighbors / callers / callees** — 图查询核心能力，MCP 工具和 CLI 共用同一查询引擎
4. **Dashboard 作为证据验证界面** — 人类验证索引质量、调用关系置信度、影响面的可视化入口
5. **Evidence Pack 作为可选快照** — 面向任务的范围快照，默认 summary-only，不带阅读计划和 Agent 指令

- 第一版只支持 **Python** 语言

### 暂不处理（非目标）
- SaaS 平台、多用户权限、企业工作区、PR Bot、IDE 插件深度集成
- 云端代码上传、全量大图展示、Neo4j、多语言支持、复杂 embedding RAG
- 不承诺 100% 精准静态调用图

## Tech Stack

| 层级 | 技术 | 状态 |
|------|------|------|
| 后端语言 | Python 3.10+ | 确认 |
| Web 框架 | FastAPI | 确认 |
| 数据模型 | Pydantic v2 | 确认 |
| 图分析 | NetworkX | 确认 |
| 存储 | SQLite + JSON 文件 | 确认 |
| AST 解析 | Python `ast` 标准库 | 确认 |
| CLI 框架 | Typer | 确认 |
| 前端语言 | TypeScript | 确认 |
| 前端框架 | React 18+ | 确认 |
| 构建工具 | Vite | 确认 |
| 图可视化 | React Flow | 确认 |
| CSS | Tailwind CSS | 确认 |
| 测试框架 | pytest（推测） | 待确认 |
| 包管理后端 | pip + pyproject.toml | 确认 |
| 包管理前端 | npm + package.json | 确认 |

## Directory Structure

以下目录结构基于 PRD 建议，开发时应按此组织。`backend/` 使用扁平包名 `codegraph`，非 `src/` 布局。

```
/
├── CLAUDE.md
├── docs/
│   └── PRD/                  # 产品需求文档（拆分后，INDEX.md 为入口）
│       ├── INDEX.md
│       ├── 01-overview.md
│       ├── ...
│       └── 10-development-plan.md
├── pyproject.toml            # Python 项目配置（待创建）
├── package.json              # 前端项目配置（待创建）
├── .gitignore
│
├── backend/
│   ├── codegraph/            # 后端主包
│   │   ├── cli/              # CLI 命令入口（codegraph xxx）
│   │   │   └── main.py
│   │   ├── indexer/          # 代码索引引擎
│   │   │   ├── scanner.py         # 文件扫描
│   │   │   ├── parser_python.py   # AST 解析
│   │   │   ├── symbol_extractor.py # 符号提取
│   │   │   ├── call_extractor.py  # 调用关系提取
│   │   │   └── graph_builder.py   # 图谱构建
│   │   ├── graph/            # 图谱层
│   │   │   ├── models.py     # Node/Edge Schema（Pydantic）
│   │   │   ├── store.py      # 图谱存储接口
│   │   │   ├── query.py      # 查询（search, callers, callees）
│   │   │   └── impact.py     # 影响面分析
│   │   ├── mcp/              # MCP 工具定义（Agent 主入口）
│   │   │   ├── tools.py      # MCP tool handlers
│   │   │   └── server.py     # MCP server 启动
│   │   ├── evidence/         # Evidence Pack 生成（可选快照）
│   │   │   ├── models.py     # Evidence Pack Schema
│   │   │   ├── pack_builder.py
│   │   │   └── markdown_exporter.py
│   │   ├── api/              # FastAPI HTTP API（供 Dashboard 使用）
│   │   │   ├── main.py
│   │   │   ├── routes_repo.py
│   │   │   ├── routes_symbols.py
│   │   │   ├── routes_graph.py
│   │   │   └── routes_evidence.py
│   │   └── storage/          # 存储层
│   │       ├── file_store.py
│   │       └── sqlite_store.py
│   └── tests/
│
├── frontend/                 # React Dashboard
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/            # 6 个页面
│   │   │   ├── ProjectOverview.tsx
│   │   │   ├── SymbolSearch.tsx
│   │   │   ├── SymbolDetail.tsx
│   │   │   ├── GraphExplorer.tsx
│   │   │   ├── ImpactView.tsx
│   │   │   └── EvidencePackViewer.tsx
│   │   ├── components/       # 通用组件
│   │   └── api/              # 后端 API 调用封装
│   └── package.json
│
└── examples/
    └── demo_python_project/  # 演示用 Python 项目
```

## Common Commands

> 注意：项目尚未创建 `pyproject.toml` 和 `package.json`，以下命令为 PRD 方案推断，**需人工确认**。

```bash
# 后端安装
pip install -e backend

# 前端安装
cd frontend && npm install

# 索引演示项目
codegraph index ./examples/demo_python_project

# 检查索引状态
codegraph status

# 搜索符号
codegraph search login

# 查看符号详情
codegraph explain src/app/api/auth.py::login

# 查询调用者
codegraph callers src/app/api/auth.py::login

# 查询被调用者
codegraph callees src/app/api/auth.py::login

# 查询局部子图
codegraph neighbors src/app/api/auth.py::login --depth 2

# 分析影响面
codegraph impact src/app/api/auth.py::login

# 生成 Evidence Pack（可选快照，summary-only）
codegraph evidence "add MFA to login flow"

# 启动 Dashboard（启动后端 + 前端）
codegraph dashboard

# 启动 MCP Server（供 MCP Agent 连接）
codegraph mcp

# 运行测试
pytest backend/tests/          # 需人工确认

# 前端开发服务器
cd frontend && npm run dev      # 需人工确认

# 前端构建
cd frontend && npm run build    # 需人工确认
```

## Development Workflow

0. **PRD 优先** — 对任何功能、Schema、命令有疑问时，先去 `docs/PRD/INDEX.md` 找到对应部分确认，不要凭假设编码。
1. **先读 PRD，再改代码** — 任何时候修改功能前，先对照 `docs/PRD/INDEX.md` 找到对应的部分确认需求，避免偏离产品定位。
2. **最小化改动** — 一次只做一个功能的增量开发。不要超前实现 PRD 中标记为"后续"或"非目标"的功能。
3. **按 Phase 顺序开发** — 严格按以下阶段顺序：Phase 1 Schema/Indexer → Phase 2 Query Engine → Phase 3 MCP Tools → Phase 4 CLI → Phase 5 Dashboard → Phase 6 Evidence Pack。不要跳过阶段。
4. **先写 Model/Schema，再写逻辑** — 任何模块先定义 Pydantic models，再实现业务逻辑。
5. **修改前查看 git status** — 确认工作区干净，避免混合多个任务的改动。

## Coding Rules

### 后端规则
- **分层职责**（严格遵守）:
  - `codegraph/indexer/` — 只负责从文件系统提取代码事实，不做业务决策
  - `codegraph/graph/` — 只负责图谱存储和查询，不涉及任务理解
  - `codegraph/mcp/` — 只负责 MCP 工具定义和协议处理，不包含图查询逻辑
  - `codegraph/evidence/` — 只负责 Evidence Pack 生成（可选快照），不操作文件系统
  - `codegraph/api/` — 只做 HTTP 路由转发，不包含业务逻辑
  - `codegraph/storage/` — 只做读写，不做业务
  - `codegraph/cli/` — 只做命令解析和参数传递，不包含核心逻辑
- **Pydantic v2** — 所有数据模型用 Pydantic BaseModel，用 `model_validate` 而非 `parse_obj`。
- **类型注解** — 所有函数必须带类型注解，返回值类型不能省略。
- **Node ID 规则** — 必须使用 PRD 定义的稳定可读 ID 格式（如 `src/app/api/auth.py::login`），不使用 UUID。
- **Confidence 机制** — 所有推断型关系必须带 `confidence` 和 `resolution` 字段，严格遵循 PRD Section 12.8 的 confidence 表。
- **import 规范** — 使用相对路径 import 包内模块，不使用 `sys.path` 修改。

### 前端规则
- **组件命名** — 页面组件放在 `pages/`，通用组件放在 `components/`。
- **API 调用** — 统一放在 `api/` 目录，组件不直接调用 fetch。
- **不要引入多余 UI 库** — 只用 Tailwind CSS + React Flow，不额外引入 Ant Design 等组件库。
- **状态管理** — 优先使用 React 内置状态（useState/useContext），不需要 Redux。

### 通用规则
- 不要编写空泛的注释（如 "This function does X"），用有意义的函数名和类型注解代替。
- 不要提前抽象。三个类似的代码块比一个过早的抽象更可取。
- 不要添加 PRD 未要求的错误处理或验证逻辑。只在系统边界（用户输入、外部 API）做校验。

## API Rules

- 任何接口修改必须同步检查：路由路径、请求参数（Pydantic model）、响应格式、状态码。
- Dashboard 前端调用和后端 API 必须保持同步。修改 API 响应格式后，必须更新前端 `api/` 层。
- 所有 API 路径以 `/api/` 开头。
- PRD Section 16 定义的 API 是必需的，不要随意重命名或删除。

## Database Rules

- SQLite 数据库文件存储在 `.codegraph/index.sqlite`。
- 数据库文件是索引产物，任何时候都可以通过 `codegraph index --force` 重建。
- 不要在数据库迁移中破坏 `.codegraph/graph.json` 和 `.codegraph/symbols.json`，它们是互备存储。
- Evidence Pack 导出文件（JSON + Markdown）存储在 `.codegraph/evidence_packs/`。

## Frontend Rules

- **6 个页面**必须全部实现：ProjectOverview, SymbolSearch, SymbolDetail, GraphExplorer, ImpactView, EvidencePackViewer。
- **Graph Explorer** 默认只展示局部图（center node + depth 1/2），不展示全仓库大图。
- **Confidence 展示** — 所有调用关系边必须在 UI 上显示 confidence 值，低于 0.6 的边用视觉警告。
- **Evidence Pack Viewer** 必须展示每个推荐项的 `reason`，不能只展示黑盒结果。
- **Dashboard 是证据验证界面**，不是主产品。不要为了 Dashboard 炫酷而忽略 MCP 工具链的完整性。

## Backend Rules

- **Controller (api/routes)** — 只做参数解析和响应返回，不包含业务逻辑。
- **Service/Engine (indexer, evidence, graph)** — 核心业务逻辑在这里。每个模块职责单一。
- **Repository/Store (storage)** — 数据读写，不包含业务判断。
- **Models (graph/models.py, evidence/models.py)** — 纯数据定义，不包含方法逻辑。
- **DTO** — 使用 Pydantic model 作为请求/响应 DTO，不额外定义。

## Agent / AI Rules

- 本项目本身是一个 AI Agent 工具，以下规则适用于项目自身的 MCP 工具和 Evidence Pack 处理逻辑：
- **MCP 工具优先** — MCP Agent 应优先按需调用 `search_symbols`、`get_symbol`、`get_callers`、`get_callees`、`get_neighbors`、`get_impact`、`repo_status` 等细粒度工具，而不是依赖 Evidence Pack。
- **Evidence Pack 定位** — 可选的任务范围快照，供人类或非 MCP Agent 使用。默认 summary-only，不替代读源码。
- **禁止生成 Reading Plan** — Evidence Pack 不包含 reading_plan。Agent 有能力自己决定阅读顺序。
- **禁止生成 Agent Instructions** — Evidence Pack 不包含 agent_instructions。不用硬编码建议教 Agent 做任务。
- **禁止默认返回大 JSON / 大源码** — Evidence Pack 默认只返回摘要和符号 ID 列表，按需获取源码。
- **Impact 不自动扩张** — Impact 分析只返回直接上下游（1-hop），不自动展开全链。
- **不自动修改用户配置文件** — 不自动修改用户的 CLAUDE.md / Cursor rules / 项目配置，除非用户显式执行 install 命令且可 uninstall。
- **不可退化原则** — MCP 工具不能退化为简单的 grep/glob 包装器，每次查询必须利用索引图谱结构化返回。

## Deployment Rules

- 项目目前没有部署需求，纯本地工具。
- Dashboard 默认地址：`http://localhost:8765`（PRD 指定）。
- FastAPI 服务在 `codegraph dashboard` 命令中启动，不需要单独配置 Nginx。
- 不要将 `.codegraph/` 目录纳入版本控制（已在 `.gitignore` 中）。
- 环境变量：目前不需要，后续如有需要（如端口配置）再添加。**需人工确认**。

## Security Rules

- 本项目是本地工具，不涉及用户数据上传，但仍然：
- 不要将 `.codegraph/` 索引文件中的代码片段提交到公开仓库（索引可能包含敏感代码）。
- 日志中不要输出文件完整内容，只输出文件路径和符号名。
- 不要硬编码任何路径，路径通过 CLI 参数或配置传入。
- 创建 `.gitignore` 时必须包含：`.codegraph/`, `__pycache__/`, `*.pyc`, `node_modules/`, `dist/`, `build/`, `.venv/`, `venv/`。

## Git Rules

- **不要自动 commit** — 任何修改后，通知用户变更内容，由用户决定是否 commit。
- **不要自动 push** — 项目未配置远程仓库时禁止 push。
- **修改前后查看 git status** — 开始工作前和完成修改后，必须检查 git status 确认文件状态。
- **不要混合任务** — 一个分支只做一个功能/任务，不要在一次修改中混合多个不相关的变更。

## Testing & Verification

每次修改后按以下顺序验证：

0. **Code Review** — 任何代码修改后，先调用 `/code-review` skill（已安装 CodeRabbit 版本于 `.agents/skills/code-review/`）对当前 diff 进行审查，发现潜在的 correctness bug 和可优化点。需要先安装 `coderabbit` CLI 并认证才能使用。
1. **构建检查** — 后端：`pip install -e backend` 无报错；前端：`npm run build` 无报错。（命令需确认）
2. **测试** — `pytest backend/tests/` 通过。（需确认）
3. **CLI 命令验证** — 修改涉及的命令必须手动执行验证输出格式。
4. **Schema 验证** — 修改了 Graph Schema 或 Evidence Pack Schema 后，必须验证输出的 JSON 符合 PRD 定义的 Schema。
5. **Dashboard 页面检查** — 前端修改后，手动打开页面确认渲染和交互正确。

## Known Pitfalls

- **Confidence 机制容易被遗忘** — 新增调用关系解析时，记得同时设置 `confidence` 和 `resolution`。
- **Node ID 不一致** — 不同模块生成的 Node ID 格式必须完全一致，否则图谱查询会断裂。始终以 PRD Section 12.5 的规则为准。
- **Evidence Pack 越界** — 最容易犯的错误是 Evidence Pack 做得太重：加 reading plan、加 agent instructions、默认返回大段源码。必须保持 summary-only 定位。
- **Dashboard 过度开发** — 容易在 Dashboard 上花过多时间追求视觉效果，而 MCP 工具链尚未完整实现。必须严格遵守 Phase 顺序。
- **PRD 与当前实现可能不一致** — 项目仅有 PRD，无实际代码。实际开发中的目录结构、命令名、Schema 字段可能会与 PRD 有出入，在 CLAUDE.md 中持续更新。

## Response Format After Changes

每次修改代码后，必须按以下格式总结：

```
## 修改总结

**修改文件：**
- `backend/codegraph/indexer/parser_python.py`（新增）
- `backend/codegraph/indexer/graph_builder.py`（修改）

**修改内容：**
1. 实现了 Python AST 解析器，提取 class/function/method 节点
2. 实现了同文件函数调用关系提取
3. 为每条调用边附加了 confidence 和 resolution 字段

**修改原因：**
Phase 1 索引器开发，PRD Section 12 和 18 定义了 Node/Edge Schema 和 AST 解析规则。

**验证方式：**
1. `pytest backend/tests/` 通过
2. 对 demo 项目执行 `codegraph index` 验证 graph.json 格式符合 Schema
3. 人工检查部分调用边是否被正确识别

**风险/后续待办：**
- 跨文件调用解析尚未实现，将在下个 PR 完成
- 低置信度边的 warning 机制尚未集成到 MCP 工具返回
```
