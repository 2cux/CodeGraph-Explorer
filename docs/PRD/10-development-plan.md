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
6. impact。

---

## Phase 3：Context Pack

实现：

1. task parser；
2. entry point ranking；
3. related symbol expansion；
4. impact integration；
5. related tests discovery；
6. reading plan；
7. agent instructions；
8. Markdown / JSON export。

---

## Phase 4：插件命令 / CLI

实现：

1. `codegraph index`；
2. `codegraph search`；
3. `codegraph explain`；
4. `codegraph impact`；
5. `codegraph context`；
6. `codegraph dashboard`。

---

## Phase 5：Dashboard

实现：

1. Project Overview；
2. Symbol Search；
3. Symbol Detail；
4. Graph Explorer；
5. Impact View；
6. Context Pack Viewer。

---

# 23. README 必须包含的演示命令

```bash
# install
pip install -e backend

# index demo repo
codegraph index ./examples/demo_python_project

# search symbols
codegraph search login

# explain symbol
codegraph explain src/app/api/auth.py::login

# analyze impact
codegraph impact src/app/api/auth.py::login

# build context pack
codegraph context "add MFA to login flow"

# open dashboard
codegraph dashboard
```

---

# 24. 最终交付物

编码 AI 最终应交付：

1. 可运行 Python 后端；
2. CLI / 插件命令模拟器；
3. 本地索引文件生成能力；
4. Graph Schema 实现；
5. Context Pack Schema 实现；
6. Symbol Search；
7. Callers / Callees；
8. Impact Analysis；
9. Context Pack Builder；
10. Reading Plan Generator；
11. Markdown / JSON Export；
12. FastAPI Local API；
13. React Dashboard；
14. Demo Python 项目；
15. README；
16. 基础测试。

---

# 25. 最终产品定义

CodeGraph Explorer 最终应实现为：

> 一个 Agent-first 的本地代码上下文插件。用户通过斜杠命令让 Agent 查询当前代码库的符号、调用链、影响面和任务上下文包；当用户需要人类视角时，可以一键打开本地 Dashboard 查看代码图谱、Context Pack 推荐理由和调用关系置信度。

核心命令：

```text
/codegraph index
/codegraph context <task>
/codegraph search <query>
/codegraph explain <file_or_symbol>
/codegraph impact <symbol>
/codegraph dashboard
```

最重要的命令是：

```text
/codegraph context <task>
```

因为它体现了本产品的核心差异化：

> 不是让 Agent 自己盲目搜索代码库，也不是只给 Agent 一个代码图谱查询接口，而是为具体编码任务生成最小、可信、可解释、可执行的代码上下文包。
