# CodeGraph Explorer — CLI Usage Examples

All examples use the demo project at `examples/demo_python_project`.

> **Note:** Run `--root ./examples/demo_python_project` (or set `DEMO=./examples/demo_python_project` and use `--root "$DEMO"`) for commands that need the index. Alternatively, `cd examples/demo_python_project` first.

---

## 1. Index

```bash
$ codegraph index ./examples/demo_python_project

Scanning D:\project\CodeGraph-Explorer\examples\demo_python_project ...
Found 34 symbols and 52 relationships.
Index written to .codegraph/graph.json
  Files indexed: 9
  Symbols:       34
  Edges:         52
  SQLite:        .codegraph/index.sqlite
```

**`--force`** to re-index an already-indexed project:

```bash
$ codegraph index ./examples/demo_python_project --force
```

---

## 2. Search

```bash
$ codegraph search login --root "$DEMO"

Found 2 result(s) for 'login':

  [1.0] app/api/auth.py::login
       type: function  file: app/api/auth.py
       match: symbol_name, file_path

  [0.8] app/store/token_store.py::save_token
       type: function  file: app/store/token_store.py
       match: docstring
```

```bash
$ codegraph search user --root "$DEMO"

Found 3 result(s) for 'user':

  [1.0] app/models/user.py::User
       type: class  file: app/models/user.py
       match: symbol_name, file_path

  [0.9] app/api/users.py::get_users
       type: function  file: app/api/users.py
       match: qualified_name, file_path

  [0.9] app/api/users.py::get_user_by_name
       type: function  file: app/api/users.py
       match: qualified_name, file_path
```

```bash
$ codegraph search login --json --root "$DEMO"

{
  "results": [
    {
      "id": "app/api/auth.py::login",
      "symbol_id": "app/api/auth.py::login",
      "name": "login",
      "type": "function",
      "file_path": "app/api/auth.py",
      "score": 1.0,
      "match_sources": ["symbol_name", "file_path"]
    },
    ...
  ],
  "total": 2
}
```

---

## 3. Explain

```bash
$ codegraph explain app/api/auth.py::login --root "$DEMO"

Symbol: login (function)
  ID:     app/api/auth.py::login
  File:   app/api/auth.py:6
  Sig:    (username: str, password: str) -> str
  Doc:    Authenticate a user and return a session token.

Callers (1):
  <- main.py::main

Callees (2):
  -> app/store/token_store.py::save_token
  -> app/store/token_store.py::revoke_token
```

Shorter form with partial name resolution:

```bash
$ codegraph explain login --root "$DEMO"
```

---

## 4. Impact

```bash
$ codegraph impact app/api/auth.py::login --root "$DEMO"

Impact Analysis: login
  Symbol: app/api/auth.py::login
  Risk:   MEDIUM
    - Affects 1 upstream caller(s).
    - Depends on 1 downstream callee(s).
    - Sensitive code path — changes may affect security-related logic.
    - Public API surface — changes affect external interfaces.
    - No related tests detected — changes may lack regression coverage.
    - 1 low-confidence edge(s) detected — some relationships may be incomplete.

Affected Symbols (4):
  [DEF] app/api/auth.py::login (direct_definition)
  [D1]  main.py::main (upstream_caller)
  [D1]  app/store/token_store.py::save_token (downstream_call)
  [D1]  app/store/token_store.py::revoke_token (downstream_call)

Affected Files (3):
  !! app/api/auth.py [high]
       Direct definition in this file.
   - main.py [medium]
       Upstream caller at distance 1.
   - app/store/token_store.py [medium]
       Downstream callee at distance 1.

Recommendations:
  1. Read the definition of 'app/api/auth.py::login' to understand current behavior.
  2. Review direct callers: main.py::main — these invoke the changed symbol.
  3. Inspect direct callees: app/store/token_store.py::save_token — these are called by the changed symbol.
  4. Exercise caution — changes touch a security-sensitive code path.
  5. Consider adding tests to cover the change.
```

---

## 5. Evidence Pack

```bash
$ codegraph context "add MFA to login flow" --root "$DEMO"

Evidence Pack: ctx_20260527_071630_add
  Task:         add MFA to login flow
  Intent:       add_feature
  Entry Points: 5
  Related:      8
  Call Graph:   6 nodes, 5 edges
  Risk Level:   medium
  Markdown:     .codegraph/context_packs/ctx_20260527_071630_add.md
  JSON:         .codegraph/context_packs/ctx_20260527_071630_add.json

Entry Points:
  [0.97] app/api/auth.py::login
         Name matches: login, add; File path contains: auth
  [0.85] app/store/token_store.py::save_token
         Name matches: token
  [0.85] app/store/token_store.py::revoke_token
         Name matches: token
  [0.82] app/store/token_store.py::is_valid
         Name matches: token
  [0.80] app/store/token_store.py
         File path contains: token

Warnings:
  ! 1 edge(s) have confidence below 0.6 — treat these as weak signals.
```

The generated Markdown file provides a complete self-contained document:

```bash
$ head -30 .codegraph/context_packs/ctx_20260527_071630_add.md

# CodeGraph Evidence Pack

- **Pack ID:** `ctx_20260527_071630_add`
- **Schema Version:** 1.0.0
- **Repository:** demo_python_project

## Task

add MFA to login flow

- **Intent:** `add_feature`
- **Keywords:** mfa, login, flow

## Entry Points

- `app/api/auth.py::login`
  - **Type:** function
  - **File:** app/api/auth.py
  - **Reason:** Name matches: login, add
  - **Score:** 0.97
  ...
```

---

## 6. Dashboard

```bash
$ codegraph dashboard

Starting CodeGraph Dashboard at http://127.0.0.1:8765 ...

  Dashboard: http://127.0.0.1:8765
  API:       http://127.0.0.1:8765/api/repo/summary
  Press Ctrl+C to stop.
```

Open `http://localhost:8765` in a browser. The Dashboard provides:

| Page | URL | Description |
|------|-----|-------------|
| Overview | `/` | Index stats, file/symbol counts, confidence ratios |
| Search | `/search` | Search and filter symbols |
| Detail | `/symbol/:id` | Full symbol info with callers/callees |
| Graph | `/graph` | Interactive subgraph (React Flow) |
| Impact | `/impact` | Impact analysis with risk assessment |
| Context | `/context` | Generate and view Evidence Packs |

---

## Advanced Usage

### Specify project root explicitly

```bash
codegraph search login --root ./examples/demo_python_project
codegraph explain login --root ./examples/demo_python_project
```

### Control call chain depth

```bash
codegraph explain login --depth 3        # Explain with depth-3 call chain
codegraph impact login --depth 3         # Impact analysis with depth-3 traversal
codegraph context "fix login" --depth 3  # Evidence Pack with depth-3 call graph
```

### JSON output for programmatic consumption

```bash
codegraph search login --json
codegraph explain login --json
codegraph impact login --json
codegraph context "refactor auth" --json
```

### Token budget for Evidence Packs

```bash
codegraph context "refactor user authentication" --max-tokens 8000
```

### Dashboard in dev mode (with Vite HMR)

```bash
codegraph dashboard --dev
```
