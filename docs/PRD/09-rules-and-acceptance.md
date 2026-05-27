# 20. 不可退化规则

编码 AI 实现时必须遵守以下规则。

## 20.1 不得退化为普通代码搜索工具

`/codegraph context <task>` 不能只返回搜索结果。

必须包含：

```text
entry_points
related_symbols
impact
recommended_context
reading_plan
agent_instructions
```

---

## 20.2 不得退化为普通图谱浏览器

Dashboard 不能成为唯一核心入口。

Agent 命令流必须完整可用。

---

## 20.3 不得退化为简单文件拼接器

Context Pack 不能只是把相关文件全文拼到一起。

必须进行：

1. 选择；
2. 排序；
3. 摘要；
4. token 控制；
5. 解释推荐理由。

---

## 20.4 不得隐藏不确定性

静态分析无法确定的关系必须标记为低置信度。

低于 0.6 的边必须进入 warnings。

---

## 20.5 不得省略 reading plan

每个 Context Pack 必须有 reading_plan。

不能只返回 unordered files。

---

## 20.6 修改类任务不得省略 impact

对于修改、修复、重构、加功能类任务，Context Pack 必须包含 impact。

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

## 21.2 Search 验收

执行：

```bash
codegraph search login
```

必须返回：

1. symbol_id；
2. type；
3. file_path；
4. score；
5. match_sources；
6. line_start / line_end。

---

## 21.3 Explain 验收

执行：

```bash
codegraph explain src/app/api/auth.py::login
```

必须返回：

1. 符号基本信息；
2. 源码位置；
3. 签名；
4. docstring；
5. callers；
6. callees；
7. related tests；
8. confidence warnings。

---

## 21.4 Impact 验收

执行：

```bash
codegraph impact src/app/api/auth.py::login
```

必须返回：

1. upstream callers；
2. downstream callees；
3. affected files；
4. related tests；
5. risk level；
6. risk reasons；
7. recommended check order。

---

## 21.5 Context Pack 验收

执行：

```bash
codegraph context "add MFA to login flow"
```

必须返回：

1. entry_points；
2. related_symbols；
3. call_graph；
4. impact；
5. recommended_context；
6. reading_plan；
7. agent_instructions；
8. warnings；
9. JSON 导出文件；
10. Markdown 导出文件。

并且：

1. 每个 entry point 必须有 reason；
2. 每个 related symbol 必须有 relation；
3. 每个 affected file 必须有 reason；
4. reading_plan 必须是有序步骤；
5. 低置信度边必须进入 warnings；
6. 不允许只返回文件列表。

---

## 21.6 Dashboard 验收

执行：

```bash
codegraph dashboard
```

必须：

1. 启动本地服务；
2. 打开浏览器；
3. 显示项目概览；
4. 支持符号搜索；
5. 支持查看符号详情；
6. 支持展示局部图；
7. 支持查看 Context Pack；
8. 能查看 confidence；
9. 能查看 Context Pack 的推荐理由。
