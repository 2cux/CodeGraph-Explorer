# 22. 推荐开发顺序

## Phase 1：Schema 与索引器

实现：

1. Pydantic models；
2. 文件扫描；
3. Python AST 解析；
4. 节点提取；
5. 边提取；
6. graph.json；
7. symbols.json。

---

## Phase 2：查询引擎

实现：

1. symbol search；
2. get symbol；
3. callers；
4. callees；
5. neighbors；
6. impact（1-hop only）；
7. repo status。

---

## Phase 3：MCP 工具

实现：

1. MCP Server 启动；
2. search_symbols tool；
3. get_symbol tool；
4. get_callers tool；
5. get_callees tool；
6. get_neighbors tool；
7. get_impact tool；
8. repo_status tool；
9. build_evidence_pack tool。

---

## Phase 4：CLI

实现：

1. `codegraph index`；
2. `codegraph status`；
3. `codegraph search`；
4. `codegraph explain`；
5. `codegraph callers`；
6. `codegraph callees`；
7. `codegraph neighbors`；
8. `codegraph impact`；
9. `codegraph evidence`；
10. `codegraph dashboard`；
11. `codegraph mcp`。

---

## Phase 5：Dashboard

实现：

1. Project Overview（含索引新鲜度）；
2. Symbol Search；
3. Symbol Detail；
4. Graph Explorer；
5. Impact View；
6. Evidence Pack Viewer。

---

## Phase 6：Evidence Pack

实现：

1. task parser；
2. entry point ranking；
3. related symbol expansion；
4. impact integration（1-hop）；
5. related tests discovery；
6. warnings collection；
7. Markdown / JSON export。

**注意：不含 reading plan、agent instructions、recommended_context。**

---

# 23. README 必须包含的演示命令

```bash
# install
pip install -e backend

# index demo repo
codegraph index ./examples/demo_python_project

# check status
codegraph status

# search symbols
codegraph search login

# explain symbol
codegraph explain src/app/api/auth.py::login

# query callers
codegraph callers src/app/api/auth.py::login

# query callees
codegraph callees src/app/api/auth.py::login

# query neighbors
codegraph neighbors src/app/api/auth.py::login --depth 2

# analyze impact
codegraph impact src/app/api/auth.py::login

# build evidence pack
codegraph evidence "add MFA to login flow"

# open dashboard
codegraph dashboard

# start MCP server
codegraph mcp
```

---

# 24. 最终交付物

编码 AI 最终应交付：

1. 可运行 Python 后端；
2. MCP Server（Agent 主入口）；
3. CLI（开发调试入口）；
4. 本地索引文件生成能力；
5. Graph Schema 实现；
6. Query Engine（search, callers, callees, neighbors, impact, status）；
7. Impact Analysis（1-hop only）；
8. Evidence Pack Builder（summary-only）；
9. Evidence Pack Schema 实现；
10. Markdown / JSON Export；
11. FastAPI Local API；
12. React Dashboard（证据验证界面）；
13. Demo Python 项目；
14. README；
15. 基础测试。

---

# 25. 最终产品定义

CodeGraph Explorer 最终应实现为：

> 一个 Python-first 的本地代码图谱索引与 MCP 工具集。AI 编码 Agent 通过 MCP 协议按需调用结构化图查询工具（search_symbols, get_symbol, get_callers, get_callees, get_neighbors, get_impact, repo_status），替代低效的 grep/glob/read 循环扫描；开发者通过 CLI 命令快速调试查询，通过 Dashboard 可视化验证索引质量、调用关系和影响面；Evidence Pack 作为可选的非 MCP 快照，供人类或非 MCP Agent 使用。

核心能力顺序：

```text
1. MCP 细粒度图查询
2. 可靠索引与新鲜度检测
3. Impact / neighbors / callers / callees
4. Dashboard 作为证据验证界面
5. Evidence Pack 作为可选快照
```

核心 MCP 工具：

```text
search_symbols
get_symbol
get_callers
get_callees
get_neighbors
get_impact
repo_status
build_evidence_pack
```

最重要的交互模式：

> MCP Agent 按需调用细粒度工具自主探索代码库，而不是接受预生成的"上下文包"。系统提供结构化图查询能力，Agent 保留推理和决策权。
