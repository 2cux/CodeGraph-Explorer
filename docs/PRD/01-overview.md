# 1. 产品概述

## 1.1 产品名称

**CodeGraph Explorer**

---

## 1.2 产品形态

**Local Code Graph Index + MCP Toolkit for AI Coding Agents**

中文定位：

> 面向 AI 编码 Agent 的本地代码图谱索引与 MCP 工具集。

---

## 1.3 一句话说明

CodeGraph Explorer is a Python-first local code graph index and MCP toolkit for AI coding agents.
It helps agents query symbols, callers, callees, local subgraphs, impact, tests, and index freshness through structured tools instead of repeatedly grep/glob/read scanning the repository.

CodeGraph Explorer 是一个 Python-first 的本地代码图谱索引与 MCP 工具集，用于帮助 AI 编码 Agent 通过结构化工具查询符号、调用关系、局部子图、影响面、测试信号和索引新鲜度，减少重复 grep、glob 和文件读取。

---

## 1.4 核心定位

本产品不是代码搜索工具，不是代码知识图谱 Dashboard，也不是任务上下文生成器。

它的核心目标是：

> 让 AI 编码 Agent 通过 MCP 协议按需调用结构化图查询工具，替代低效的 grep/glob/read 循环扫描。

核心能力优先级：

```text
1. MCP 细粒度图查询
2. 可靠索引与新鲜度检测
3. Impact / neighbors / callers / callees
4. Dashboard 作为证据验证界面
5. Evidence Pack 作为可选快照
```

因此，本产品采用：

```text
MCP-first, Dashboard as evidence verifier
```

含义：

1. MCP 细粒度图查询工具是 Agent 的主入口。
2. Dashboard 是人类验证索引质量和调用关系置信度的界面。
3. Evidence Pack 是可选的非 MCP 快照（供人类查看或非 MCP Agent 使用）。
4. CLI 命令是开发调试入口，MCP 工具是 Agent 工作入口。
5. HTTP API 是内部实现能力，供 Dashboard 消费。
6. MCP、CLI、Dashboard 必须共用同一套索引和图谱查询引擎。

---

# 2. 产品目标

## 2.1 要解决的问题

AI 编码 Agent 在中大型代码库中执行任务时，通常需要反复做这些事情：

```text
搜索文件 → 阅读源码 → 推断调用关系 → 找相关测试 → 判断影响面 → 决定修改位置
```

这个过程存在几个问题：

1. Agent 每次任务都重复探索代码库；
2. token 和工具调用消耗高（反复 grep/glob/read）；
3. 容易漏掉关键模块；
4. 对调用链和影响面的理解不稳定；
5. 开发者很难验证 Agent 为什么选择这些文件；
6. Agent 拿到的是零散搜索结果，不是结构化的图查询结果。

CodeGraph Explorer 要把这个流程改成：

```text
预索引代码库 → 构建代码图谱 → Agent 通过 MCP 工具按需查询 → 结构化返回
```

Agent 不再需要自己 grep/glob/read 扫描，而是：

```text
search_symbols("login")
get_symbol("src/app/api/auth.py::login")
get_callers("src/app/api/auth.py::login")
get_callees("src/app/api/auth.py::login")
get_neighbors("src/app/api/auth.py::login", depth=2)
get_impact("src/app/api/auth.py::login")
repo_status()
```

---

## 2.2 产品核心输出

本产品最重要的输出不是全量图谱，不是搜索结果列表，也不是任务上下文包，而是：

```text
MCP 细粒度图查询工具
```

即：Agent 通过 MCP 协议按需调用的结构化代码图查询接口。

每个 MCP 工具必须返回：

1. 结构化的符号信息（ID、类型、签名、位置）
2. 调用关系（callers / callees，带 confidence）
3. 局部子图（center node + depth，不扩展全图）
4. 影响面（1-hop only，不自动扩张）
5. 索引新鲜度（是否过期、覆盖率、低置信度边比例）
6. 每条调用边的 confidence 和 resolution

Evidence Pack 是辅助输出：
- 可选的任务范围快照
- 供人类查看或非 MCP Agent 使用
- 默认 summary-only
- 不包含 reading plan、agent instructions、实现建议

---

# 3. 产品差异化原则

这一节是实现时必须遵守的产品原则。

## 3.1 MCP 细粒度图查询优先

系统的核心交互模式是 MCP 工具按需调用：

```text
search_symbols
get_symbol
get_callers
get_callees
get_neighbors
get_impact
repo_status
build_evidence_pack  (可选快照)
```

Agent 自主决定调用顺序和深度，而不是接受预处理好的"上下文包"。

实现时必须把 MCP 工具作为主链路，Evidence Pack 作为辅助出口。

---

## 3.2 结构化替代 grep/glob/read

MCP 工具不能退化为简单的 grep/glob 包装器。

每个查询必须利用索引图谱结构化返回：

```text
search_symbols("login")
→ [
    {symbol_id, type, file_path, signature, match_sources, score},
    ...
  ]

get_callers("src/app/api/auth.py::login")
→ [
    {symbol_id, type, file_path, confidence, resolution},
    ...
  ]
```

不做纯文本匹配，不做文件全文返回，不做未索引的实时扫描。

---

## 3.3 推荐结果必须可解释

系统推荐的每一个查询结果，都必须带解释。

至少包含：

```text
reason
score
match_sources
confidence
source_location
```

不能只返回黑盒结果。

示例：

```json
{
  "symbol_id": "src/app/api/auth.py::login",
  "reason": "Matches search keywords: login, authentication; located in auth API module",
  "score": 0.92,
  "match_sources": ["symbol_name", "file_path", "module_name"],
  "confidence": 0.9
}
```

---

## 3.4 Impact 精确不扩张

Impact 分析只返回直接上下游（1-hop）。

不自动展开全链，不递归扩展。

输出：

1. upstream callers（直接调用者）；
2. downstream callees（直接下游）；
3. affected files；
4. related tests；
5. risk level；
6. risk reasons。

如果需要更深的影响链，Agent 可以自行用 get_neighbors 逐跳扩展。

---

## 3.5 Dashboard 是证据验证界面

Dashboard 的目标不是展示一个巨大而炫酷的全仓库图。

Dashboard 的核心用途是帮助开发者验证：

1. 索引是否覆盖了关键文件；
2. 调用关系是否合理；
3. 哪些边是低置信度；
4. 哪些文件被判断为受影响；
5. 索引新鲜度是否过期；
6. Evidence Pack 推荐是否合理。

默认只展示局部图，不展示全仓库大图。

---

## 3.6 Evidence Pack 是可选快照

Evidence Pack 的定位：

> Optional task-scoped snapshot for humans or non-MCP agents.

它不应该是 Agent 工作的主入口。MCP Agent 应优先按需调用细粒度工具。

Evidence Pack 的约束：
- 默认 summary-only（不返回大段源码）
- 不包含 reading plan（Agent 有能力自己决定阅读顺序）
- 不包含 agent instructions（不用硬编码建议教 Agent 做任务）
- 不包含实现建议（不与 Agent 推理能力冲突）
- 不做 token 换 token（不以大 JSON 替代源码阅读）

---

# 4. 目标用户

## 4.1 AI 编码工具用户（MCP Agent）

包括使用以下工具的开发者：

```text
Claude Code
Cursor
Codex
GitHub Copilot
Gemini CLI
```

他们希望 Agent 更高效、更准确地理解当前代码库，减少重复的文件扫描。

---

## 4.2 接手中大型项目的新成员

他们希望快速知道：

1. 项目有哪些核心模块；
2. 入口函数在哪里；
3. 某个功能由哪些文件组成；
4. 某个函数调用了哪些下游逻辑；
5. 哪些测试覆盖了相关逻辑。

---

## 4.3 做重构、修 bug、代码审查的工程师

他们希望快速判断：

1. 修改某个函数会影响谁；
2. 相关调用链是什么；
3. 哪些测试应该一起修改；
4. 当前变更风险有多高。
