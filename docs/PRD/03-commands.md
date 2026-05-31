# 11. MCP 工具与 CLI 命令需求

## 11.0 优先级说明

MCP 工具是 Agent 的主入口，CLI 是开发调试入口，两者共用同一查询引擎。

```text
MCP Tools (Agent 主入口) > CLI (开发调试) > Evidence Pack (可选快照)
```

---

# 11.1 MCP 工具定义

## 11.1.1 `search_symbols`

### 功能

搜索代码符号。

### 输入

```json
{
  "query": "login",
  "symbol_types": ["function", "method", "class"],
  "max_results": 10
}
```

### 返回

```json
[
  {
    "symbol_id": "src/app/api/auth.py::login",
    "type": "function",
    "name": "login",
    "file_path": "src/app/api/auth.py",
    "signature": "login(request: LoginRequest) -> LoginResponse",
    "location": { "line_start": 24, "line_end": 68 },
    "score": 0.92,
    "match_sources": ["symbol_name", "file_path"],
    "reason": "Symbol name matches 'login'"
  }
]
```

---

## 11.1.2 `get_symbol`

### 功能

获取符号详情。

### 输入

```json
{
  "symbol_id": "src/app/api/auth.py::login",
  "include_source": false
}
```

### 返回

```json
{
  "symbol_id": "src/app/api/auth.py::login",
  "type": "function",
  "name": "login",
  "file_path": "src/app/api/auth.py",
  "location": { "line_start": 24, "line_end": 68 },
  "signature": "login(request: LoginRequest) -> LoginResponse",
  "docstring": "Authenticate user and return LoginResponse.",
  "caller_count": 2,
  "callee_count": 5,
  "related_tests": ["src/app/tests/test_auth.py::test_login_success"]
}
```

**`include_source` 默认 `false`**。Agent 需要源码时显式传 `true`。

---

## 11.1.3 `get_callers`

### 功能

查询谁调用了指定符号。

### 输入

```json
{
  "symbol_id": "src/app/api/auth.py::login",
  "max_depth": 1
}
```

### 返回

```json
[
  {
    "symbol_id": "src/app/api/middleware.py::auth_middleware",
    "type": "function",
    "file_path": "src/app/api/middleware.py",
    "relation": "calls",
    "confidence": 0.85,
    "resolution": "import_match"
  }
]
```

---

## 11.1.4 `get_callees`

### 功能

查询指定符号调用了谁。

### 输入

```json
{
  "symbol_id": "src/app/api/auth.py::login",
  "max_depth": 1
}
```

### 返回

```json
[
  {
    "symbol_id": "src/app/services/auth.py::AuthService.validate_password",
    "type": "method",
    "file_path": "src/app/services/auth.py",
    "relation": "called_by",
    "confidence": 0.82,
    "resolution": "class_method_match"
  }
]
```

---

## 11.1.5 `get_neighbors`

### 功能

查询局部子图（center node + depth）。

### 输入

```json
{
  "symbol_id": "src/app/api/auth.py::login",
  "depth": 2,
  "direction": "both",
  "max_nodes": 50
}
```

### 返回

```json
{
  "center_node_id": "src/app/api/auth.py::login",
  "depth": 2,
  "nodes": [],
  "edges": [],
  "layout_hints": {
    "group_by": "file",
    "max_nodes": 50
  }
}
```

---

## 11.1.6 `get_impact`

### 功能

分析修改某个符号的影响面（1-hop only）。

### 输入

```json
{
  "symbol_id": "src/app/services/auth.py::AuthService.validate_token"
}
```

### 返回

```json
{
  "changed_symbol": "src/app/services/auth.py::AuthService.validate_token",
  "upstream_callers": [
    {
      "symbol_id": "src/app/api/auth.py::login",
      "file_path": "src/app/api/auth.py",
      "confidence": 0.85
    }
  ],
  "downstream_callees": [
    {
      "symbol_id": "src/app/security/jwt.py::decode_token",
      "file_path": "src/app/security/jwt.py",
      "confidence": 0.90
    }
  ],
  "affected_files": [
    {
      "file_path": "src/app/api/auth.py",
      "reason": "Contains direct caller",
      "priority": "high"
    }
  ],
  "related_tests": [
    {
      "symbol_id": "src/app/tests/test_auth.py::test_login_success",
      "file_path": "src/app/tests/test_auth.py"
    }
  ],
  "risk": {
    "level": "high",
    "reasons": [
      "Authentication-sensitive flow",
      "Multiple upstream callers"
    ]
  }
}
```

**不自动递归扩展。** Agent 如需更深影响链，自行用 `get_neighbors` 逐跳扩展。

---

## 11.1.7 `repo_status`

### 功能

检查索引新鲜度、覆盖率、低置信度边比例。

### 输入

```json
{}
```

### 返回

```json
{
  "indexed": true,
  "index_time": "2026-05-31T10:00:00Z",
  "stale": false,
  "total_files": 428,
  "indexed_files": 428,
  "total_symbols": 3912,
  "total_edges": 7436,
  "low_confidence_edge_ratio": 0.12,
  "failed_files": 0,
  "repo_root": "/path/to/project",
  "language": "Python"
}
```

---

## 11.1.8 `build_evidence_pack`

### 功能

生成 Evidence Pack（可选快照，供人类或非 MCP Agent 使用）。

### 输入

```json
{
  "task": "add MFA to login flow",
  "max_tokens": 3000,
  "include_tests": true,
  "depth": 2
}
```

### 返回

```json
{
  "pack_id": "evi_20260531_auth_mfa",
  "task": {
    "raw_request": "add MFA to login flow",
    "intent": "add_feature",
    "keywords": ["MFA", "login", "authentication"]
  },
  "entry_points": [],
  "related_symbols": [],
  "call_graph": {},
  "impact": {},
  "warnings": [],
  "exports": {
    "markdown_path": ".codegraph/evidence_packs/evi_20260531_auth_mfa.md",
    "json_path": ".codegraph/evidence_packs/evi_20260531_auth_mfa.json"
  }
}
```

**明确不包含：**
- `reading_plan`（Agent 有能力自己决定阅读顺序）
- `agent_instructions`（不用硬编码建议教 Agent 做任务）
- `recommended_context`（不默认返回大段源码）

**默认 summary-only**：entry points 只返回 symbol_id + reason + score，不返回源码。

---

# 11.2 CLI 命令

## 11.2.1 `codegraph index`

### 功能

扫描代码库，构建本地代码索引。

### 输入

```bash
codegraph index ./examples/demo_python_project
```

可选参数：

```text
--path
--language
--force
```

### 执行逻辑

1. 确认项目路径；
2. 扫描 `.py` 文件；
3. 忽略无关目录；
4. 解析 AST；
5. 提取 file、module、class、function、method、import、call、test；
6. 构建 Graph Schema；
7. 生成 `.codegraph/graph.json`；
8. 生成 `.codegraph/symbols.json`；
9. 写入 SQLite；
10. 返回索引摘要。

### 默认忽略目录

```text
.git
venv
.venv
node_modules
dist
build
__pycache__
.pytest_cache
.mypy_cache
```

### 输出示例

```text
CodeGraph indexed current repository.

Files indexed: 428
Symbols indexed: 3,912
Call edges: 7,436
Language: Python
Index path: .codegraph/
```

---

## 11.2.2 `codegraph status`

检查索引新鲜度。

```bash
codegraph status
```

输出同 `repo_status` MCP 工具。

---

## 11.2.3 `codegraph search`

```bash
codegraph search login
```

输出同 `search_symbols` MCP 工具。

---

## 11.2.4 `codegraph explain`

```bash
codegraph explain src/app/api/auth.py::login
```

输出同 `get_symbol` MCP 工具。

---

## 11.2.5 `codegraph callers`

```bash
codegraph callers src/app/api/auth.py::login
```

输出同 `get_callers` MCP 工具。

---

## 11.2.6 `codegraph callees`

```bash
codegraph callees src/app/api/auth.py::login
```

输出同 `get_callees` MCP 工具。

---

## 11.2.7 `codegraph neighbors`

```bash
codegraph neighbors src/app/api/auth.py::login --depth 2
```

输出同 `get_neighbors` MCP 工具。

---

## 11.2.8 `codegraph impact`

```bash
codegraph impact src/app/api/auth.py::login
```

输出同 `get_impact` MCP 工具。

---

## 11.2.9 `codegraph evidence`

```bash
codegraph evidence "add MFA to login flow"
```

输出同 `build_evidence_pack` MCP 工具。

---

## 11.2.10 `codegraph dashboard`

### 功能

启动并打开本地 Dashboard。

### 输入

```bash
codegraph dashboard
```

### 执行逻辑

1. 检查 `.codegraph/` 是否存在；
2. 如果不存在，提示先执行 index；
3. 启动 FastAPI 服务；
4. 提供 Dashboard 页面；
5. 自动打开浏览器。

默认地址：

```text
http://localhost:8765
```

---

## 11.2.11 `codegraph mcp`

### 功能

启动 MCP Server，供 MCP Agent 连接。

### 输入

```bash
codegraph mcp
```

### 执行逻辑

1. 检查 `.codegraph/` 是否存在；
2. 启动 MCP Server；
3. 注册全部 MCP 工具；
4. 等待 Agent 连接。
