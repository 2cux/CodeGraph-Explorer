# 5. 核心使用场景

## 5.1 场景一：Agent 修改功能

用户输入：

```text
/codegraph context "add MFA to login flow"
```

系统返回：

1. 登录相关入口函数；
2. 认证服务相关方法；
3. 用户模型；
4. session / token 相关依赖；
5. 相关测试；
6. 调用链；
7. 影响文件；
8. 风险等级；
9. 推荐阅读顺序；
10. Agent 修改建议。

---

## 5.2 场景二：Agent 修 bug

用户输入：

```text
/codegraph context "fix token expiration bug"
```

系统应返回：

1. token 相关函数；
2. JWT decode / encode 逻辑；
3. token 配置来源；
4. 相关测试；
5. 可能受影响的 API；
6. 风险提示。

---

## 5.3 场景三：开发者解释符号

用户输入：

```text
/codegraph explain src/app/api/auth.py::login
```

系统返回：

1. 函数职责；
2. 函数签名；
3. 所在文件；
4. docstring；
5. callers；
6. callees；
7. related tests；
8. 影响摘要。

---

## 5.4 场景四：开发者查看图谱

用户输入：

```text
/codegraph dashboard
```

系统打开本地 Dashboard。

用户可以：

1. 搜索符号；
2. 查看函数详情；
3. 查看局部调用图；
4. 查看影响面；
5. 查看 Context Pack；
6. 复制 Markdown 给 Agent。

---

# 6. 产品形态

产品对用户表现为一个插件，但内部由三部分组成：

```text
CodeGraph Explorer
├── Plugin Command Layer
├── Local Runtime Service
└── Local Dashboard
```

## 6.1 Plugin Command Layer

负责接收用户在 Agent 工具中的斜杠命令。

第一版必须实现：

```text
/codegraph index
/codegraph context <task>
/codegraph search <query>
/codegraph explain <file_or_symbol>
/codegraph impact <symbol>
/codegraph dashboard
```

如果暂时无法接入真实 Agent 插件系统，可以先用 CLI 模拟同名命令：

```bash
codegraph index
codegraph context "add MFA to login flow"
codegraph search login
codegraph explain src/app/api/auth.py::login
codegraph impact src/app/api/auth.py::login
codegraph dashboard
```

---

## 6.2 Local Runtime Service

负责实际计算：

1. 扫描代码库；
2. 解析 AST；
3. 提取符号；
4. 构建代码图谱；
5. 存储索引；
6. 查询调用链；
7. 分析影响面；
8. 生成 Context Pack；
9. 为 Dashboard 提供数据。

---

## 6.3 Local Dashboard

本地浏览器看板，用于人类查看和验证：

1. Project Overview；
2. Symbol Search；
3. Symbol Detail；
4. Graph Explorer；
5. Impact View；
6. Context Pack Viewer。

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
11. 100% 精准静态调用图承诺。

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
Typer 或 Click
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
└── context_packs/
    ├── ctx_xxx.json
    └── ctx_xxx.md
```

## 8.4 第一版语言支持

第一版只支持：

```text
Python
```

后续再扩展：

```text
TypeScript
Java
Go
Rust
```

---

# 9. 系统架构

```text
User / Agent
   ↓
Plugin Commands
   ↓
Local Runtime Service
   ↓
Code Index Engine
   ↓
Graph Store + Symbol Index
   ↓
Context Query Engine
   ↓
├── Agent Command Response
└── Dashboard API
```

核心实现原则：

```text
Graph Schema = 代码事实层
Context Pack Schema = Agent 任务上下文层
Plugin Commands = Agent 使用入口
Dashboard = 人类验证入口
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
│   │   ├── context/
│   │   │   ├── models.py
│   │   │   ├── pack_builder.py
│   │   │   ├── ranking.py
│   │   │   ├── reading_plan.py
│   │   │   └── markdown_exporter.py
│   │   │
│   │   ├── api/
│   │   │   ├── main.py
│   │   │   ├── routes_repo.py
│   │   │   ├── routes_symbols.py
│   │   │   ├── routes_graph.py
│   │   │   └── routes_context.py
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
│   │   │   └── ContextPackViewer.tsx
│   │   ├── components/
│   │   └── api/
│   └── package.json
│
└── examples/
    └── demo_python_project/
```
