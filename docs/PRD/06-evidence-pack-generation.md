# 14. Evidence Pack 生成逻辑

Evidence Pack 是可选快照。MCP Agent 应优先使用细粒度工具，不应依赖 Evidence Pack。

## 14.1 输入

```text
task text
max_tokens (default 3000)
include_tests (default true)
depth (default 2)
```

---

## 14.2 处理步骤

```text
任务文本
  ↓
intent 识别
  ↓
关键词提取
  ↓
符号搜索
  ↓
entry point ranking
  ↓
调用图扩展（depth limited）
  ↓
impact analysis（1-hop only）
  ↓
related tests discovery
  ↓
warnings 收集
  ↓
JSON / Markdown export
```

**注意：没有 reading plan 生成，没有 agent instructions 生成。**

---

## 14.3 Entry Point 排序规则

entry point 分数来源：

1. symbol name match；
2. file path match；
3. module name match；
4. docstring match；
5. test relation；
6. call graph centrality；
7. task intent relevance。

每个 entry point 必须包含：

```text
reason
score
match_sources
```

**默认只返回 symbol_id + reason + score，不返回源码。**

---

## 14.4 Token 控制规则

Evidence Pack 默认 summary-only。

当超过 token 预算时，按以下顺序降级：

1. entry points 只保留 symbol_id + reason + score；
2. related symbols 只保留 symbol_id + relation；
3. call graph 只保留 1-hop edge 列表；
4. 低置信度边只放入 warnings；
5. 不返回任何源码片段。

---

# 15. Markdown 导出格式

Evidence Pack 可导出 Markdown 供人类阅读。

格式：

````markdown
# CodeGraph Evidence Pack

## Task

add MFA to login flow

## Entry Points

- `src/app/api/auth.py::login`
  - Reason: Matches login and auth keywords
  - Score: 0.92

- `src/app/services/auth.py::AuthService.validate_password`
  - Reason: Direct callee in login flow
  - Score: 0.84

## Related Symbols

- `src/app/services/auth.py::AuthService.validate_password` (callee, high)
- `src/app/models/user.py::User` (shared_model, medium)
- `src/app/tests/test_auth.py::test_login_success` (test, high)

## Impact Summary

Risk level: medium

Affected files:
- `src/app/api/auth.py` (critical)
- `src/app/services/auth.py` (high)
- `src/app/tests/test_auth.py` (high)

## Call Graph

Center: `src/app/api/auth.py::login`
Depth: 2
Edges: 7 (2 low confidence)

## Warnings

- Some calls were resolved by heuristic matching.
- Static analysis may miss dynamic imports.
- Index is 3 days old. Consider re-indexing.
````
