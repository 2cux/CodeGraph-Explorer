# 16. Local API 设计

API 是内部能力，供插件命令和 Dashboard 使用。

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

POST /api/context-pack

GET /api/graph/subgraph
GET /api/dashboard/stats
```

---

## 16.2 POST /api/context-pack

请求：

```json
{
  "task": "add MFA to login flow",
  "query": "login authentication MFA",
  "target_symbols": [],
  "max_tokens": 6000,
  "include_tests": true,
  "depth": 2
}
```

返回：

```json
{
  "schema_version": "1.0.0",
  "pack_id": "ctx_auth_mfa",
  "task": {},
  "repo": {},
  "entry_points": [],
  "related_symbols": [],
  "call_graph": {},
  "impact": {},
  "recommended_context": [],
  "reading_plan": [],
  "agent_instructions": {},
  "exports": {
    "markdown_path": ".codegraph/context_packs/ctx_auth_mfa.md",
    "json_path": ".codegraph/context_packs/ctx_auth_mfa.json"
  }
}
```

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

Dashboard 是人类验证入口，不是主产品入口。

## 17.1 页面结构

```text
Dashboard
├── Project Overview
├── Symbol Search
├── Symbol Detail
├── Graph Explorer
├── Impact View
└── Context Pack Viewer
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
10. 解析失败文件数量；
11. 低置信度边比例。

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
7. code preview；
8. callers；
9. callees；
10. related tests；
11. impact summary；
12. confidence warnings；
13. 生成 Context Pack 按钮；
14. 打开局部图按钮。

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
2. upstream callers；
3. downstream callees；
4. affected files；
5. related tests；
6. risk level；
7. risk reasons；
8. recommended reading order；
9. low-confidence warnings。

---

## 17.7 Context Pack Viewer

展示：

1. task；
2. entry points；
3. related symbols；
4. call graph；
5. impact；
6. recommended context；
7. reading plan；
8. agent instructions；
9. warnings；
10. token estimate；
11. copy markdown；
12. export JSON。

重点：

> Context Pack Viewer 必须能解释为什么系统选择这些上下文。
