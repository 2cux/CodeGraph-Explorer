# 11. 插件命令需求

## 11.1 `/codegraph index`

### 功能

扫描当前代码库，构建本地代码上下文索引。

### 输入

```text
/codegraph index
```

CLI 模拟：

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

## 11.2 `/codegraph context <task>`

### 功能

根据自然语言任务生成 Agent 可执行的 Context Pack。

**这是本项目最核心功能。**

### 输入

```text
/codegraph context "add MFA to login flow"
```

CLI 模拟：

```bash
codegraph context "add MFA to login flow"
```

### 执行逻辑

1. 解析任务文本；
2. 判断 task intent；
3. 提取关键词；
4. 搜索候选符号；
5. 选择 entry points；
6. 扩展 1-hop / 2-hop 调用图；
7. 查询 callers；
8. 查询 callees；
9. 查找 related tests；
10. 分析 impact；
11. 计算 risk level；
12. 生成 recommended context；
13. 生成 reading plan；
14. 生成 agent instructions；
15. 导出 JSON；
16. 导出 Markdown；
17. 返回摘要。

### 输出必须包含

1. Entry Points；
2. Related Symbols；
3. Impact Files；
4. Related Tests；
5. Recommended Reading Order；
6. Risk Level；
7. Warnings；
8. Context Pack 文件路径。

### 输出示例

```text
Context Pack generated for task:
"add MFA to login flow"

Entry points:
1. src/app/api/auth.py::login
   reason: Matches login and auth keywords
   score: 0.92

2. src/app/services/auth.py::AuthService.validate_password
   reason: Direct callee in login flow
   score: 0.84

Recommended reading order:
1. src/app/api/auth.py::login
2. src/app/services/auth.py::AuthService.validate_password
3. src/app/models/user.py::User
4. src/app/tests/test_auth.py

Impact:
- Affected symbols: 7
- Affected files: 4
- Related tests: 2
- Risk level: medium

Warnings:
- Some method calls were resolved by attribute guess.
- Treat edges with confidence below 0.6 as weak signals.

Saved:
.codegraph/context_packs/ctx_auth_mfa.json
.codegraph/context_packs/ctx_auth_mfa.md
```

---

## 11.3 `/codegraph search <query>`

### 功能

搜索代码符号。

### 输入

```text
/codegraph search login
```

CLI 模拟：

```bash
codegraph search login
```

### 支持搜索对象

1. 文件路径；
2. 模块名；
3. 类名；
4. 函数名；
5. 方法名；
6. docstring；
7. import；
8. test。

### 输出示例

```text
Found 5 symbols:

1. src/app/api/auth.py::login
   type: function
   score: 0.96
   match_sources: symbol_name, file_path

2. src/app/services/auth.py::AuthService.login_user
   type: method
   score: 0.88
   match_sources: symbol_name

3. src/app/tests/test_auth.py::test_login_success
   type: test
   score: 0.74
   match_sources: test_name
```

---

## 11.4 `/codegraph explain <file_or_symbol>`

### 功能

解释某个文件或符号。

### 输入

```text
/codegraph explain src/app/api/auth.py
```

或：

```text
/codegraph explain src/app/api/auth.py::login
```

### 如果输入是文件，返回

1. 文件职责；
2. 定义的类；
3. 定义的函数；
4. imports；
5. 被哪些文件依赖；
6. 主要调用关系。

### 如果输入是符号，返回

1. 符号类型；
2. 函数签名；
3. 所在文件；
4. docstring；
5. callers；
6. callees；
7. related tests；
8. impact summary；
9. confidence warnings。

---

## 11.5 `/codegraph impact <symbol>`

### 功能

分析修改某个符号的潜在影响。

### 输入

```text
/codegraph impact src/app/services/auth.py::AuthService.validate_token
```

### 输出内容

1. upstream callers；
2. downstream callees；
3. affected files；
4. related tests；
5. risk level；
6. risk reasons；
7. recommended check order。

### 输出示例

```text
Impact analysis for:
src/app/services/auth.py::AuthService.validate_token

Upstream callers:
- src/app/api/auth.py::login
- src/app/api/auth.py::refresh_token

Downstream dependencies:
- src/app/security/jwt.py::decode_token
- src/app/models/user.py::User

Related tests:
- src/app/tests/test_auth.py
- src/app/tests/test_token.py

Risk level: high

Reasons:
- Authentication-sensitive flow
- Multiple upstream callers
- Related tests exist and should be updated
```

---

## 11.6 `/codegraph dashboard`

### 功能

启动并打开本地 Dashboard。

### 输入

```text
/codegraph dashboard
```

CLI 模拟：

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
