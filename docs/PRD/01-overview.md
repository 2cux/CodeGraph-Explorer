# 1. 产品概述

## 1.1 产品名称

**CodeGraph Explorer**

---

## 1.2 产品形态

**AI Coding Agent Plugin with Local Dashboard**

中文定位：

> 面向 AI 编码 Agent 的本地代码上下文插件。

---

## 1.3 一句话说明

CodeGraph Explorer 是一个运行在 AI 编码工具中的本地代码上下文插件。它通过预索引当前代码库，支持 Agent 使用斜杠命令获取任务级代码上下文包，并提供本地 Dashboard 让开发者可视化验证代码结构、调用关系、影响面和上下文推荐结果。

---

## 1.4 核心定位

本产品不是单纯的代码搜索工具，也不是单纯的代码知识图谱 Dashboard。

它的核心目标是：

> 当 AI 编码 Agent 面对一个具体任务时，系统能够告诉 Agent：应该从哪里开始读、哪些代码必须看、哪些关系可能受影响、哪些测试需要关注，以及哪些上下文可以直接用于完成任务。

因此，本产品采用：

```text
Agent-first, Dashboard-second
```

含义：

1. Agent 是主要使用方。
2. Dashboard 是人类验证和理解入口。
3. 插件命令是主入口。
4. HTTP API 是内部实现能力，不是用户主入口。
5. Dashboard 和 Agent 命令必须共用同一套索引、图谱和上下文生成逻辑。
6. 核心功能不是"展示图谱"，而是"为编码任务生成可执行上下文"。

---

# 2. 产品目标

## 2.1 要解决的问题

AI 编码 Agent 在中大型代码库中执行任务时，通常需要反复做这些事情：

```text
搜索文件 → 阅读源码 → 推断调用关系 → 找相关测试 → 判断影响面 → 决定修改位置
```

这个过程存在几个问题：

1. Agent 每次任务都重复探索代码库；
2. token 和工具调用消耗高；
3. 容易漏掉关键模块；
4. 对调用链和影响面的理解不稳定；
5. 开发者很难验证 Agent 为什么选择这些文件；
6. Agent 拿到的是零散文件，而不是任务导向的上下文。

CodeGraph Explorer 要把这个流程改成：

```text
预索引代码库 → 构建代码图谱 → 根据任务生成 Context Pack → Agent 按阅读计划执行
```

---

## 2.2 产品核心输出

本产品最重要的输出不是全量图谱，也不是搜索结果列表，而是：

```text
Task-aware Context Pack
```

即：面向具体编码任务的上下文包。

一个 Context Pack 必须回答：

1. 当前任务最相关的入口符号是什么？
2. 为什么这些符号相关？
3. 这些符号调用了什么？
4. 谁调用了这些符号？
5. 修改它们可能影响哪些文件？
6. 哪些测试需要关注？
7. Agent 应该按什么顺序阅读？
8. 哪些上下文应该进入 prompt？
9. 哪些调用关系可信度较低，需要谨慎处理？

---

# 3. 产品差异化原则

这一节是实现时必须遵守的产品原则，不能被削弱成普通代码搜索或普通图谱浏览器。

## 3.1 任务上下文优先

系统的核心命令是：

```text
/codegraph context <task>
```

该命令不是简单搜索，也不是简单导出文件，而是自动完成：

1. 任务意图识别；
2. 关键词提取；
3. 入口符号发现；
4. 调用链扩展；
5. 影响面分析；
6. 相关测试发现；
7. 推荐阅读顺序生成；
8. Agent 操作建议生成；
9. Markdown / JSON Context Pack 导出。

实现时必须把 `/codegraph context` 作为主链路，而不是附属功能。

---

## 3.2 Agent 可执行，而不只是人类可读

所有核心输出必须让 Agent 能直接使用。

系统不能只输出：

```text
这里有一些相关文件
```

而应该输出：

```text
先读这个入口函数
再读这个服务方法
然后检查这个模型
最后检查这些测试
修改时注意这些调用关系
低置信度边不要盲信
```

Context Pack 必须包含结构化字段，方便 Agent 程序化消费。

---

## 3.3 推荐结果必须可解释

系统推荐的每一个入口符号、相关符号、影响文件、测试文件，都必须带解释。

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
  "reason": "Matches task keywords: login, authentication; located in auth API module",
  "score": 0.92,
  "match_sources": ["symbol_name", "file_path", "module_name"],
  "confidence": 0.9
}
```

---

## 3.4 阅读顺序是核心能力

本产品不能只返回"相关文件列表"。

必须生成有序的 reading plan。

阅读计划要告诉 Agent：

1. 第一步读哪个符号；
2. 第二步读哪个依赖；
3. 哪些文件只需要摘要；
4. 哪些测试必须检查；
5. 为什么按这个顺序读。

这是本产品区别于普通代码图谱查询的关键能力。

---

## 3.5 影响面分析必须嵌入 Context Pack

对于以下任务类型：

```text
modify_existing_behavior
fix_bug
refactor
add_feature
write_tests
review_code
```

Context Pack 必须包含 impact 分析。

impact 至少包括：

1. upstream callers；
2. downstream callees；
3. affected files；
4. related tests；
5. risk level；
6. risk reasons。

---

## 3.6 Dashboard 是验证界面，不是主产品

Dashboard 的目标不是展示一个巨大而炫酷的全仓库图。

Dashboard 的核心用途是帮助开发者验证：

1. 为什么 Context Pack 选中了这些 entry points；
2. 调用关系是否合理；
3. 哪些边是低置信度；
4. 哪些文件被判断为受影响；
5. Agent 的 reading plan 是否合理；
6. 相关测试是否遗漏。

默认只展示局部图，不展示全仓库大图。

---

# 4. 目标用户

## 4.1 AI 编码工具用户

包括使用以下工具的开发者：

```text
Claude Code
Cursor
Codex
GitHub Copilot
Gemini CLI
```

他们希望 Agent 更快、更准确地理解当前代码库。

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
