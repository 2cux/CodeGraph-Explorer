# 14. Context Pack 生成逻辑

## 14.1 输入

```text
task text
optional target symbols
max_tokens
include_tests
depth
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
调用图扩展
  ↓
impact analysis
  ↓
related tests discovery
  ↓
recommended context selection
  ↓
reading plan generation
  ↓
agent instructions generation
  ↓
JSON / Markdown export
```

---

## 14.3 Entry Point 排序规则

entry point 分数来源：

1. symbol name match；
2. file path match；
3. module name match；
4. docstring match；
5. test relation；
6. call graph centrality；
7. task intent relevance；
8. exact target symbol match。

每个 entry point 必须包含：

```text
reason
score
match_sources
```

---

## 14.4 Context 选择规则

Context Pack 不允许简单拼接所有相关文件全文。

优先级：

1. target symbol 源码；
2. direct callees 源码；
3. direct callers 摘要；
4. related tests 源码或摘要；
5. file summaries；
6. low-confidence nodes 只给摘要；
7. external symbols 只给名称和来源。

---

## 14.5 Token 控制规则

当超过 token 预算时，按以下顺序降级：

1. 保留 entry points 源码；
2. 保留 critical related symbols 源码；
3. 将 medium / low related symbols 降级为 summary；
4. 将 callers 降级为列表；
5. 将低置信度边只放入 warnings；
6. 不返回无关文件全文。

---

# 15. Markdown 导出格式

每个 Context Pack 必须导出 Markdown。

格式：

````markdown
# CodeGraph Context Pack

## Task

add MFA to login flow

## Entry Points

- `src/app/api/auth.py::login`
  - Reason: Matches login and auth keywords
  - Score: 0.92

## Recommended Reading Order

1. `src/app/api/auth.py::login`
2. `src/app/services/auth.py::AuthService.validate_password`
3. `src/app/models/user.py::User`
4. `src/app/tests/test_auth.py`

## Impact Summary

Risk level: medium

Affected files:
- `src/app/api/auth.py`
- `src/app/services/auth.py`
- `src/app/tests/test_auth.py`

## Relevant Code

### src/app/api/auth.py::login

```python
def login(...):
    ...
```

## Agent Instructions

- Read the login entry point first.
- Inspect authentication service callees.
- Check related tests before editing.
- Treat low-confidence edges as weak signals.

## Warnings

- Some calls were resolved by heuristic matching.
- Static analysis may miss dynamic imports.
````
