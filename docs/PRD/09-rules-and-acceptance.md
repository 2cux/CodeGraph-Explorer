# 20. 不可退化规则

编码 AI 实现时必须遵守以下规则。

## 20.1 不得退化为 grep/glob 包装器

MCP 工具不能退化为简单的文本搜索包装器。

每个查询必须利用索引图谱结构化返回，带 symbol_id、confidence、resolution。

不做纯文本匹配，不做文件全文返回，不做未索引的实时扫描。

---

## 20.2 不得退化为普通图谱浏览器

Dashboard 不能成为唯一核心入口。

MCP 工具链必须完整可用。

---

## 20.3 Evidence Pack 不得越界

Evidence Pack 禁止包含：

1. reading_plan（Agent 有能力自己决定阅读顺序）
2. agent_instructions（不用硬编码建议教 Agent 做任务）
3. recommended_context（不默认返回大段源码）
4. implementation_suggestions（不与 Agent 推理能力冲突）

Evidence Pack 默认 summary-only。

---

## 20.4 不得隐藏不确定性

静态分析无法确定的关系必须标记为低置信度。

低于 0.6 的边必须进入 warnings。

---

## 20.5 Impact 不得自动扩张

Impact 分析只返回 1-hop 直接上下游。

不递归扩展，不自动展开全链。

Agent 如需更深影响链，自行用 get_neighbors 逐跳扩展。

---

## 20.6 不得自动修改用户配置

不自动修改用户的 CLAUDE.md / Cursor rules / 项目配置文件。

除非用户显式执行 install 命令且可 uninstall。

---

# 21. 验收标准

## 21.1 索引验收

执行：

```bash
codegraph index ./examples/demo_python_project
```

必须满足：

1. 生成 `.codegraph/graph.json`；
2. 生成 `.codegraph/symbols.json`；
3. 能识别文件、类、函数、方法；
4. 能识别 import；
5. 能识别同文件函数调用；
6. 能识别部分跨文件 import 调用；
7. 每个节点有稳定 ID；
8. 每条 calls 边有 confidence；
9. 输出索引摘要。

---

## 21.2 MCP 工具验收

### search_symbols

执行搜索，必须返回：

1. symbol_id；
2. type；
3. file_path；
4. score；
5. match_sources；
6. reason。

### get_symbol

必须返回：

1. 符号基本信息；
2. 源码位置；
3. 签名；
4. docstring；
5. caller_count / callee_count；
6. related_tests。

`include_source` 默认 `false`。

### get_callers / get_callees

必须返回每条边：

1. symbol_id；
2. file_path；
3. confidence；
4. resolution。

### get_neighbors

必须返回：

1. center_node_id；
2. depth；
3. nodes + edges；
4. layout_hints。

### get_impact

必须返回：

1. upstream callers；
2. downstream callees；
3. affected files；
4. related tests；
5. risk level；
6. risk reasons。

只返回 1-hop，不递归扩展。

### repo_status

必须返回：

1. indexed；
2. index_time；
3. stale；
4. total_files / indexed_files；
5. total_symbols / total_edges；
6. low_confidence_edge_ratio。

---

## 21.3 CLI 验收

执行：

```bash
codegraph search login
codegraph explain src/app/api/auth.py::login
codegraph callers src/app/api/auth.py::login
codegraph callees src/app/api/auth.py::login
codegraph neighbors src/app/api/auth.py::login --depth 2
codegraph impact src/app/api/auth.py::login
codegraph status
```

每个命令输出格式与对应的 MCP 工具一致。

---

## 21.4 Evidence Pack 验收

执行：

```bash
codegraph evidence "add MFA to login flow"
```

必须返回：

1. entry_points（summary-only，含 reason + score）；
2. related_symbols（含 relation）；
3. call_graph；
4. impact（1-hop）；
5. warnings；
6. JSON 导出文件；
7. Markdown 导出文件。

并且：

1. 每个 entry point 必须有 reason；
2. 每个 related symbol 必须有 relation；
3. 每个 affected file 必须有 reason；
4. 低置信度边必须进入 warnings。

**必须不包含：**
1. reading_plan；
2. agent_instructions；
3. recommended_context（含源码）；
4. implementation_suggestions。

---

## 21.5 Dashboard 验收

执行：

```bash
codegraph dashboard
```

必须：

1. 启动本地服务；
2. 打开浏览器；
3. 显示项目概览（含索引新鲜度）；
4. 支持符号搜索；
5. 支持查看符号详情；
6. 支持展示局部图；
7. 支持查看 Evidence Pack；
8. 能查看 confidence；
9. 能查看 Evidence Pack 的推荐理由。
