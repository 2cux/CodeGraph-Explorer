# 16. Local API 设计

API 是内部能力，供 MCP 工具、CLI 命令和 Dashboard 使用。

## 16.1 必须实现的 API

```http
GET /api/repo/summary
POST /api/repo/index

GET /api/symbols/search
GET /api/symbols/{symbol_id}
GET /api/symbols/{symbol_id}/callers
GET /api/symbols/{symbol_id}/callees
GET /api/symbols/{symbol_id}/neighbors
GET /api/symbols/{symbol_id}/impact

POST /api/evidence-pack

GET /api/graph/subgraph
GET /api/dashboard/stats
```

---

## 16.2 POST /api/evidence-pack

请求：

```json
{
  "task": "add MFA to login flow",
  "query": "login authentication MFA",
  "max_tokens": 3000,
  "include_tests": true,
  "depth": 2
}
```

返回：

```json
{
  "schema_version": "1.0.0",
  "pack_id": "evi_auth_mfa",
  "task": {},
  "repo": {},
  "entry_points": [],
  "related_symbols": [],
  "call_graph": {},
  "impact": {},
  "warnings": [],
  "exports": {
    "markdown_path": ".codegraph/evidence_packs/evi_auth_mfa.md",
    "json_path": ".codegraph/evidence_packs/evi_auth_mfa.json"
  }
}
```

**不包含 reading_plan、agent_instructions、recommended_context。**

---

## 16.3 GET /api/graph/subgraph

请求：

```http
GET /api/graph/subgraph?symbol_id=src/app/api/auth.py::login&depth=2
```

返回：

```json
{
  "center_node_id": "src/app/api/auth.py::login",
  "depth": 2,
  "nodes": [],
  "edges": [],
  "layout_hints": {
    "group_by": "file",
    "max_nodes": 100,
    "suggested_view": "local_call_graph"
  }
}
```

---

# 17. Dashboard 需求

Dashboard 是证据验证界面，不是主产品入口。

## 17.1 页面结构

```text
Dashboard
├── Project Overview（索引状态、覆盖率、新鲜度）
├── Symbol Search（符号搜索）
├── Symbol Detail（符号详情 + callers/callees）
├── Graph Explorer（局部调用图）
├── Impact View（影响面分析）
└── Evidence Pack Viewer（快照查看）
```

---

## 17.2 Project Overview

展示：

1. 项目名称；
2. 根路径；
3. 当前 commit；
4. 文件数量；
5. 符号数量；
6. 函数数量；
7. 类数量；
8. 调用边数量；
9. 最近索引时间；
10. 索引是否过期（stale warning）；
11. 解析失败文件数量；
12. 低置信度边比例。

---

## 17.3 Symbol Search

功能：

1. 输入关键词搜索；
2. 按类型过滤；
3. 按文件过滤；
4. 展示匹配分数；
5. 展示 match_sources；
6. 点击进入 Symbol Detail。

---

## 17.4 Symbol Detail

展示：

1. 符号名称；
2. 类型；
3. 文件路径；
4. 行号；
5. 函数签名；
6. docstring；
7. code preview（按需加载，非默认）；
8. callers；
9. callees；
10. related tests；
11. impact summary（1-hop）；
12. confidence warnings；
13. 打开局部图按钮。

---

## 17.5 Graph Explorer

功能：

1. 展示局部调用图；
2. 支持 depth 选择；
3. 支持节点类型过滤；
4. 点击节点查看详情；
5. 点击边查看 confidence；
6. 支持展开上游；
7. 支持展开下游；
8. 支持导出子图 JSON。

限制：

```text
默认不展示全仓库大图。
默认展示 center node + depth 1/2 neighbors。
```

---

## 17.6 Impact View

展示：

1. target symbol；
2. upstream callers（直接调用者）；
3. downstream callees（直接下游）；
4. affected files；
5. related tests；
6. risk level；
7. risk reasons；
8. low-confidence warnings。

**不自动递归扩展影响链。**

---

## 17.7 Evidence Pack Viewer

展示：

1. task；
2. entry points（symbol_id + reason + score）；
3. related symbols（symbol_id + relation）；
4. call graph（nodes + edges）；
5. impact（1-hop）；
6. warnings；
7. token estimate；
8. copy markdown；
9. export JSON。

重点：

> Evidence Pack Viewer 必须能解释为什么系统选择这些 entry points，每个推荐项必须展示 reason。
