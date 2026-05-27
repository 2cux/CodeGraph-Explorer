# 12. Graph Schema

Graph Schema 是代码事实层。

## 12.1 顶层结构

```json
{
  "schema_version": "1.0.0",
  "repo": {},
  "nodes": [],
  "edges": [],
  "indexes": {},
  "stats": {}
}
```

---

## 12.2 Repo Schema

```json
{
  "repo_id": "local:demo_project",
  "name": "demo_project",
  "root_path": "/absolute/path/to/demo_project",
  "languages": ["python"],
  "indexed_at": "2026-05-27T10:30:00+09:00",
  "commit_hash": "abc123",
  "indexer_version": "1.0.0",
  "file_count": 128,
  "symbol_count": 942
}
```

---

## 12.3 Node Schema

```json
{
  "id": "src/app/services/auth.py::AuthService.validate_token",
  "type": "method",
  "name": "validate_token",
  "qualified_name": "app.services.auth.AuthService.validate_token",
  "display_name": "AuthService.validate_token",
  "file_path": "src/app/services/auth.py",
  "module": "app.services.auth",
  "language": "python",
  "location": {
    "line_start": 42,
    "line_end": 78,
    "column_start": 4,
    "column_end": 20
  },
  "signature": "validate_token(self, token: str) -> User",
  "docstring": "Validate JWT token and return user.",
  "code_preview": "def validate_token(self, token: str) -> User:\n    ...",
  "visibility": "public",
  "tags": ["auth", "jwt", "user"],
  "metadata": {}
}
```

---

## 12.4 Node Types

第一版支持：

```text
repository
file
module
class
function
method
import
external_symbol
test
```

---

## 12.5 Node ID 规则

必须使用稳定、可读、可复现的 ID。

文件节点：

```text
src/app/api/auth.py
```

模块节点：

```text
module:app.api.auth
```

函数节点：

```text
src/app/api/auth.py::login
```

方法节点：

```text
src/app/services/auth.py::AuthService.validate_token
```

外部符号：

```text
external:fastapi.APIRouter
external:typing.Optional
```

不要使用随机 UUID 作为主 ID。

---

## 12.6 Edge Schema

```json
{
  "id": "edge_001",
  "type": "calls",
  "source": "src/app/api/auth.py::login",
  "target": "src/app/services/auth.py::AuthService.validate_token",
  "confidence": 0.82,
  "source_location": {
    "file_path": "src/app/api/auth.py",
    "line_start": 35,
    "line_end": 35
  },
  "metadata": {
    "call_expr": "auth_service.validate_token(token)",
    "resolution": "static_ast",
    "is_dynamic": false
  }
}
```

---

## 12.7 Edge Types

第一版支持：

```text
contains
defined_in
imports
calls
inherits
references
tested_by
```

说明：

| 边类型 | source | target | 说明 |
|--------|--------|--------|------|
| contains | file/module/class | class/function/method | 包含关系 |
| defined_in | class/function/method | file/module | 定义位置 |
| imports | file/module | module/external_symbol | import 关系 |
| calls | function/method | function/method/external_symbol | 调用关系 |
| inherits | class | class/external_symbol | 继承关系 |
| references | function/method | class/function/external_symbol | 引用关系 |
| tested_by | function/method | test | 测试关系 |

---

## 12.8 Confidence 机制

所有推断型关系必须带 confidence。

```json
{
  "confidence": 0.82,
  "metadata": {
    "resolution": "class_method_resolved"
  }
}
```

建议规则：

| resolution | confidence |
|------------|-----------:|
| exact_ast_match | 1.0 |
| same_file_exact | 0.95 |
| import_resolved | 0.9 |
| class_method_resolved | 0.8 |
| type_hint_resolved | 0.75 |
| test_name_heuristic | 0.65 |
| attribute_guess | 0.55 |
| external_symbol | 0.4 |
| unresolved | 0.2 |
