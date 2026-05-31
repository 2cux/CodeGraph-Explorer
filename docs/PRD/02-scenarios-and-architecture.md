# 5. 核心使用场景

## 5.1 场景一：MCP Agent 按需探索代码库

Agent 收到任务 "add MFA to login flow"，不通过 grep/glob 扫描，而是调用 MCP 工具：

```text
search_symbols("login authentication MFA")
→ 返回匹配符号列表

get_symbol("src/app/api/auth.py::login")
→ 返回函数签名、docstring、源码位置

get_callees("src/app/api/auth.py::login")
→ 返回 login 调用的所有下游函数

get_neighbors("src/app/api/auth.py::login", depth=2)
→ 返回 2-hop 局部子图

get_impact("src/app/api/auth.py::login")
→ 返回直接上下游影响面、风险等级

repo_status()
→ 检查索引是否过期
```

Agent 自主决定调用顺序和深度，不需要系统预生成"上下文包"。

---

## 5.2 场景二：开发者用 CLI 快速查询

```bash
codegraph search login
codegraph explain src/app/api/auth.py::login
codegraph callers src/app/api/auth.py::login
codegraph callees src/app/api/auth.py::login
codegraph neighbors src/app/api/auth.py::login --depth 2
codegraph impact src/app/api/auth.py::login
```

---

## 5.3 场景三：开发者用 Dashboard 验证证据

```bash
codegraph dashboard
```

打开本地 Dashboard，验证：

1. 索引覆盖率和新进度；
2. 调用关系是否合理；
3. 哪些边是低置信度；
4. 影响面分析是否正确。

---

## 5.4 场景四：生成 Evidence Pack 快照

```bash
codegraph evidence "token expiration bug"
```

生成可选快照（summary-only），供：
- 人类开发者离线查看
- 非 MCP Agent 使用
- 任务上下文存档

---

# 6. 产品形态

产品由四部分组成：

```text
CodeGraph Explorer
├── MCP Tool Server（Agent 主入口）
├── CLI Commands（开发调试入口）
├── Local Runtime Service（索引与查询引擎）
└── Local Dashboard（证据验证界面）
```

## 6.1 MCP Tool Server

Agent 通过 MCP 协议调用的结构化查询工具。

第一版必须实现：

```text
search_symbols      — 搜索代码符号
get_symbol          — 获取符号详情
get_callers         — 查询调用者
get_callees         — 查询被调用者
get_neighbors       — 查询局部子图
get_impact          — 分析修改影响面（1-hop）
repo_status         — 检查索引新鲜度
build_evidence_pack — 可选快照导出
```

---

## 6.2 CLI Commands

开发调试用，与 MCP 工具共用同一查询引擎：

```bash
codegraph index
codegraph status
codegraph search
codegraph explain
codegraph callers
codegraph callees
codegraph neighbors
codegraph impact
codegraph evidence
codegraph dashboard
codegraph mcp
```

---

## 6.3 Local Runtime Service

负责实际计算：

1. 扫描代码库；
2. 解析 AST；
3. 提取符号；
4. 构建代码图谱；
5. 存储索引；
6. 查询调用链；
7. 分析影响面；
8. 生成 Evidence Pack；
9. 为 Dashboard 提供数据。

---

## 6.4 Local Dashboard

本地浏览器看板，用于人类查看和验证：

1. Project Overview；
2. Symbol Search；
3. Symbol Detail；
4. Graph Explorer；
5. Impact View；
6. Evidence Pack Viewer。

---

# 7. 非目标

第一版不做：

1. SaaS 平台；
2. 多用户权限；
3. 企业工作区；
4. PR Bot；
5. IDE 插件深度集成；
6. 云端代码上传；
7. 全量大图展示；
8. Neo4j；
9. 多语言全量支持；
10. 复杂 embedding RAG；
11. 100% 精准静态调用图承诺；
12. 生成 Reading Plan；
13. 生成 Agent Instructions；
14. 自动修改 CLAUDE.md / Cursor rules。

---

# 8. 技术栈

## 8.1 后端

```text
Python
FastAPI
Pydantic
NetworkX
SQLite
Python ast
Typer
MCP (Python SDK)
```

## 8.2 前端

```text
React
TypeScript
Vite
React Flow
Tailwind CSS
```

## 8.3 存储结构

本地生成：

```text
.codegraph/
├── graph.json
├── symbols.json
├── metadata.json
├── index.sqlite
└── evidence_packs/
    ├── evi_xxx.json
    └── evi_xxx.md
```

## 8.4 第一版语言支持

第一版只支持：

```text
Python
```

---

# 9. 系统架构

```text
User / MCP Agent
   ↓
MCP Tool Server (Agent 主入口)
   ↓
Local Runtime Service
   ↓
Code Index Engine
   ↓
Graph Store + Symbol Index
   ↓
Query Engine (search, callers, callees, neighbors, impact, status)
   ↓
├── MCP Tool Response
├── CLI Output
├── Dashboard API
└── Evidence Pack Export (可选快照)
```

核心实现原则：

```text
Graph Schema = 代码事实层
Query Engine = 结构化图查询层
MCP Tools = Agent 主入口
CLI = 开发调试入口
Dashboard = 人类证据验证入口
Evidence Pack = 可选非 MCP 快照
Local Runtime = 索引与查询引擎
```

---

# 10. 目录结构建议

```text
codegraph-explorer/
├── README.md
├── pyproject.toml
├── package.json
├── .gitignore
│
├── backend/
│   ├── codegraph/
│   │   ├── __init__.py
│   │   ├── cli/
│   │   │   ├── __init__.py
│   │   │   └── main.py
│   │   │
│   │   ├── indexer/
│   │   │   ├── scanner.py
│   │   │   ├── parser_python.py
│   │   │   ├── symbol_extractor.py
│   │   │   ├── call_extractor.py
│   │   │   └── graph_builder.py
│   │   │
│   │   ├── graph/
│   │   │   ├── models.py
│   │   │   ├── store.py
│   │   │   ├── query.py
│   │   │   └── impact.py
│   │   │
│   │   ├── mcp/
│   │   │   ├── tools.py
│   │   │   └── server.py
│   │   │
│   │   ├── evidence/
│   │   │   ├── models.py
│   │   │   ├── pack_builder.py
│   │   │   └── markdown_exporter.py
│   │   │
│   │   ├── api/
│   │   │   ├── main.py
│   │   │   ├── routes_repo.py
│   │   │   ├── routes_symbols.py
│   │   │   ├── routes_graph.py
│   │   │   └── routes_evidence.py
│   │   │
│   │   └── storage/
│   │       ├── file_store.py
│   │       └── sqlite_store.py
│   │
│   └── tests/
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── pages/
│   │   │   ├── ProjectOverview.tsx
│   │   │   ├── SymbolSearch.tsx
│   │   │   ├── SymbolDetail.tsx
│   │   │   ├── GraphExplorer.tsx
│   │   │   ├── ImpactView.tsx
│   │   │   └── EvidencePackViewer.tsx
│   │   ├── components/
│   │   └── api/
│   └── package.json
│
└── examples/
    └── demo_python_project/
```
