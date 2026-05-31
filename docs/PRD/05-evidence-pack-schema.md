# 13. Evidence Pack Schema

Evidence Pack 是可选的任务范围快照，供人类或非 MCP Agent 使用。

它不是 Agent 工作的主入口。MCP Agent 应优先按需调用细粒度工具。

核心约束：
- 默认 summary-only（不返回大段源码）
- 不包含 reading_plan
- 不包含 agent_instructions
- 不包含 recommended_context（大段源码）
- 不包含实现建议

## 13.1 顶层结构

```json
{
  "schema_version": "1.0.0",
  "pack_id": "evi_20260531_auth_mfa",
  "task": {},
  "repo": {},
  "entry_points": [],
  "related_symbols": [],
  "call_graph": {},
  "impact": {},
  "warnings": [],
  "exports": {}
}
```

---

## 13.2 Task Schema

```json
{
  "raw_request": "add MFA to login flow",
  "intent": "add_feature",
  "keywords": ["login", "MFA", "authentication"],
  "constraints": {
    "max_tokens": 3000,
    "include_tests": true,
    "depth": 2
  }
}
```

Task intent 枚举：

```text
understand_code
modify_existing_behavior
add_feature
fix_bug
refactor
write_tests
review_code
analyze_impact
```

---

## 13.3 Entry Points Schema

```json
{
  "symbol_id": "src/app/api/auth.py::login",
  "type": "function",
  "name": "login",
  "file_path": "src/app/api/auth.py",
  "location": {
    "line_start": 24,
    "line_end": 68
  },
  "signature": "login(request: LoginRequest) -> LoginResponse",
  "reason": "Matches task keywords and appears to be authentication entry point",
  "score": 0.92,
  "match_sources": ["symbol_name", "file_path", "call_graph"]
}
```

**默认不包含源码。** Agent 需要源码时通过 `get_symbol(include_source=true)` 获取。

---

## 13.4 Related Symbols Schema

```json
{
  "symbol_id": "src/app/services/auth.py::AuthService.validate_password",
  "relation": "callee",
  "distance": 1,
  "direction": "outgoing",
  "reason": "Called by login",
  "importance": "high",
  "confidence": 0.82
}
```

importance 枚举：

```text
critical
high
medium
low
```

---

## 13.5 Call Graph Schema

```json
{
  "center": "src/app/api/auth.py::login",
  "depth": 2,
  "nodes": [
    {
      "id": "src/app/api/auth.py::login",
      "label": "login",
      "type": "function"
    }
  ],
  "edges": [
    {
      "source": "src/app/api/auth.py::login",
      "target": "src/app/services/auth.py::AuthService.validate_password",
      "type": "calls",
      "confidence": 0.82
    }
  ]
}
```

---

## 13.6 Impact Schema

```json
{
  "changed_symbol": "src/app/api/auth.py::login",
  "affected_symbols": [
    {
      "symbol_id": "src/app/tests/test_auth.py::test_login_success",
      "reason": "Likely validates login behavior",
      "impact_type": "test_coverage",
      "distance": 1,
      "confidence": 0.7
    }
  ],
  "affected_files": [
    {
      "file_path": "src/app/api/auth.py",
      "reason": "Defines target function",
      "priority": "critical"
    }
  ],
  "risk": {
    "level": "medium",
    "reasons": [
      "Authentication flow is security-sensitive",
      "Target function has multiple downstream dependencies"
    ]
  }
}
```

impact_type 枚举：

```text
direct_definition
upstream_caller
downstream_call
shared_model
import_dependency
test_coverage
config_dependency
unknown
```

risk level 枚举：

```text
low
medium
high
critical
```

---

## 13.7 Warnings Schema

```json
[
  {
    "type": "low_confidence_edge",
    "message": "Edge login → _internal_cache has confidence 0.45",
    "source": "src/app/api/auth.py::login",
    "target": "src/app/cache.py::_internal_cache",
    "confidence": 0.45
  },
  {
    "type": "stale_index",
    "message": "Index is 3 days old. Consider re-indexing."
  }
]
```

---

## 13.8 明确不包含的字段

以下字段不出现在 Evidence Pack 中：

| 字段 | 原因 |
|------|------|
| `reading_plan` | Agent 有能力自己决定阅读顺序 |
| `agent_instructions` | 不用硬编码建议教 Agent 做任务 |
| `recommended_context`（含源码） | 默认 summary-only，按需获取源码 |
| `implementation_suggestions` | 不与 Agent 推理能力冲突 |
