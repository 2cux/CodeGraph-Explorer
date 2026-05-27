# CodeGraph Explorer PRD — 索引目录

> 本文档将 PRD（`prd.md`）拆分为 10 个独立部分，便于按需读取。
> Claude 应优先读取本索引，然后根据任务需要加载相应部分。

---

## 各部分概要

| # | 文件 | 对应 PRD 章节 | 内容提要 | 适用场景 |
|---|------|---------------|----------|----------|
| 1 | [01-overview.md](01-overview.md) | §1–4 | 产品概述、目标、差异化原则、目标用户 | 理解产品定位 |
| 2 | [02-scenarios-and-architecture.md](02-scenarios-and-architecture.md) | §5–10 | 使用场景、产品形态、非目标、技术栈、架构、目录结构 | 了解技术选型和项目结构 |
| 3 | [03-commands.md](03-commands.md) | §11 | 全部 6 个插件命令的详细需求 | **实现 CLI 命令时必读** |
| 4 | [04-graph-schema.md](04-graph-schema.md) | §12 | Graph Schema（Node/Edge/Confidence） | **实现索引器/图模型时必读** |
| 5 | [05-context-pack-schema.md](05-context-pack-schema.md) | §13 | Context Pack 全部子 Schema | **实现 Context Pack 生成时必读** |
| 6 | [06-context-pack-generation.md](06-context-pack-generation.md) | §14–15 | Context Pack 生成逻辑、排序规则、Token 控制、Markdown 导出 | **实现 Context Pack 逻辑时必读** |
| 7 | [07-api-and-dashboard.md](07-api-and-dashboard.md) | §16–17 | Local API 设计 + Dashboard 6 页面需求 | **实现 API 和前端时必读** |
| 8 | [08-indexing-and-impact.md](08-indexing-and-impact.md) | §18–19 | 代码索引逻辑 + Impact 分析逻辑 | **实现索引器和影响分析时必读** |
| 9 | [09-rules-and-acceptance.md](09-rules-and-acceptance.md) | §20–21 | 不可退化规则 + 6 项验收标准 | **确认实现完整性时必读** |
| 10 | [10-development-plan.md](10-development-plan.md) | §22–25 | 5 个 Phase 开发顺序 + 最终交付物 + 产品定义 | **制定开发计划时必读** |

---

## 快速导航

### 如果你想理解产品定位
→ [01-overview.md](01-overview.md) — 核心定位、差异化原则

### 如果你要开始编码
| 阶段 | 必读文档 |
|------|----------|
| Phase 1: Schema + 索引器 | [04-graph-schema.md](04-graph-schema.md), [08-indexing-and-impact.md](08-indexing-and-impact.md) |
| Phase 2: 查询引擎 | [08-indexing-and-impact.md](08-indexing-and-impact.md) |
| Phase 3: Context Pack | [05-context-pack-schema.md](05-context-pack-schema.md), [06-context-pack-generation.md](06-context-pack-generation.md) |
| Phase 4: CLI | [03-commands.md](03-commands.md) |
| Phase 5: Dashboard | [07-api-and-dashboard.md](07-api-and-dashboard.md) |

### 如果你在做质量验证
→ [09-rules-and-acceptance.md](09-rules-and-acceptance.md)

### 如果你要看整体计划
→ [10-development-plan.md](10-development-plan.md)

---

## 原 PRD 文件

原始完整 PRD 文件保留在项目根目录：`prd.md`
