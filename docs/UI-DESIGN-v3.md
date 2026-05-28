# CodeGraph Explorer — UI 设计规格 v3

> Graph-first Local Context Explorer。Agent-first 插件的轻量可视化验证前端。  
> 设计属性：开发者工具 · Minimal Swiss · 暗色优先 · 语义化 token 系统

---

## 目录

1. [产品定位与设计原则](#1-产品定位与设计原则)
2. [整体布局](#2-整体布局)
3. [Topbar](#3-topbar)
4. [Graph Canvas](#4-graph-canvas)
5. [节点设计](#5-节点设计)
6. [边设计](#6-边设计)
7. [节点与边的交互系统](#7-节点与边的交互系统)
8. [Right Inspector](#8-right-inspector)
9. [Context Pack Overlay](#9-context-pack-overlay)
10. [Reading Plan](#10-reading-plan)
11. [Index Status Popover](#11-index-status-popover)
12. [主题系统](#12-主题系统)
13. [排版规范](#13-排版规范)
14. [间距与尺寸规范](#14-间距与尺寸规范)
15. [颜色体系](#15-颜色体系)
16. [组件清单](#16-组件清单)
17. [关键交互流程](#17-关键交互流程)
18. [技术选型与图渲染方案](#18-技术选型与图渲染方案)
19. [实现优先级](#19-实现优先级)
20. [文案规范](#20-文案规范)

---

## 1. 产品定位与设计原则

### 产品定位

CodeGraph Explorer 是一个 **Agent-first** 的本地代码上下文插件。前端不是完整 SaaS Dashboard，而是轻量的 **Local Context Explorer**，用于可视化验证 Agent 的 Context Pack、代码关系图、影响面和阅读顺序。

### 核心体验

Graph-first：用户打开页面后，第一眼看到的是关系图。

### 设计原则

| 原则 | 说明 |
|------|------|
| **轻量** | 不是 SaaS Dashboard，不是后台管理，不是数据大屏 |
| **简约** | Minimal Swiss — 只展示必要信息，不冗余，不炫技 |
| **克制** | 颜色克制、动画克制、特效克制。一个页面只突出 1-2 个核心元素 |
| **开发者工具质感** | 参考 VS Code / Cursor / Sourcegraph / GitHub / Linear 的 design language |
| **呼吸感** | 8px 增量间距体系，舒适排版，不拥挤 |
| **可探索** | 点击节点展开详情，阅读计划引导理解，图谱支持自由探索 |
| **无障碍优先** | 对比度 ≥ 4.5:1，支持键盘导航，尊重 reduced-motion |

### 不是这些

❌ SaaS Dashboard | ❌ 后台管理系统 | ❌ 大型 Web 平台
❌ AI Studio 风格 | ❌ 数据大屏 | ❌ 复杂多页面应用
❌ 大侧边栏导航 | ❌ KPI 卡片大屏 | ❌ 花哨换肤
❌ Emoji 当图标 | ❌ 装饰性动画 | ❌ 纯色区分信息

### 风格归属

- **主风格**：Minimal Swiss — 干净、留白、功能性、几何网格、无衬线
- **变体**：Dark Mode (OLED-friendly) — 深色背景 + 高对比度文字 + 语义化 accent
- **字体**：Inter（界面）+ JetBrains Mono（代码）
- **图标**：全部使用 SVG（Heroicons 或 Lucide），禁止 emoji 作为图标

---

## 2. 整体布局

```
┌──────────────────────────────────────────────────────────────┐
│ Topbar (36px) — 单行紧凑工具栏                                │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│                    ┌─────────────────────┐                    │
│                    │    Graph Canvas     │                    │
│                    │     (flex: 1)       │                    │
│                    │                     │                    │
│                    │  视觉主体：局部代码    │                    │
│                    │  关系图              │                    │
│                    │                     │                    │
│                    │  无选中节点 = 全图    │                    │
│                    │  有选中节点 = 聚焦图  │                    │
│                    │                     │                    │
│                    └─────────────────────┘                    │
│                                                              │
│  ┌───────────────┐                           ┌──────────────┐│
│  │Context Pack   │                           │Reading Plan  ││
│  │Overlay        │                           │FAB (右下角)   ││
│  │(左下浮层)      │                           │              ││
│  └───────────────┘                           └──────────────┘│
│                                                              │
└──────────────────────────────────────────────────────────────┘

Inspector 展开时：
┌──────────────────────────────────────────────────────────────┐
│ Topbar (36px)                                                │
├───────────────────────────────────┬──────────────────────────┤
│                                   │                          │
│          Graph Canvas             │    Right Inspector       │
│          (~70%)                   │    (~30%, 320-420px)     │
│                                   │                          │
│          自动压缩                  │   节点详情 / 边详情      │
│                                   │                          │
│                                   │                          │
└───────────────────────────────────┴──────────────────────────┘
```

- 全应用高度 = 100vh，无滚动
- Topbar = 36px 固定高度
- Graph Canvas 占据剩余所有空间
- Inspector 从右侧滑入，宽度 `--inspector-width`（30vw，min 320px，max 420px），展开时 graph 自动压缩
- Context Pack Overlay 浮动在 canvas 左下角，不参与布局流
- Reading Plan 浮动触发按钮在右下角

---

## 3. Topbar

### 3.1 规格

- 高度：**36px**（固定，不随内容变化）
- 背景：`var(--bg-panel)`
- 底部 border：1px solid `var(--border)`
- padding：0 8px
- 所有元素垂直居中，flex row，gap 6px

### 3.2 内容分段

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ◆ CodeGraph Explorer  │  my-app  │  main  │  a1b2c3d  │  ● Indexed      │
│                                                           │  ⌕  │  ⚡  │  ☰  │
└──────────────────────────────────────────────────────────────────────────┘
```

**左侧（项目信息）：**

| 元素 | 字体 | 字号 | 字重 | 颜色 |
|------|------|------|------|------|
| ◆ 图标 | — | 14px | — | `var(--text-secondary)` |
| CodeGraph Explorer | Inter | 12px | 600 | `var(--text-primary)` |
| 分隔符 `│` | — | — | — | `var(--text-muted)` |
| my-app（repo 名） | Inter | 11px | 400 | `var(--text-secondary)` |
| 分隔符 `│` | — | — | — | `var(--text-muted)` |
| main（branch） | JetBrains Mono | 11px | 400 | `var(--text-muted)` |
| 分隔符 `│` | — | — | — | `var(--text-muted)` |
| a1b2c3d（commit） | JetBrains Mono | 11px | 400 | `var(--text-muted)` |
| ● Indexed | Inter | 11px | 500 | `var(--success)` / `var(--text-muted)` |

**右侧（操作区）：**

| 元素 | 说明 | 交互行为 |
|------|------|---------|
| ⌕ | 符号搜索 | 点击展开 inline 输入框，300ms 防抖 |
| ⚡ | 命令/Task 输入 | 点击展开 inline 输入区域，回车生成 Context Pack |
| System ▼ | 主题切换 | segmented control 或 dropdown，System / Light / Dark |
| ☰ | 菜单（预留） | 预留扩展位 |

### 3.3 交互细节

- 搜索框展开：宽度 240px，border 1px `var(--border)`，圆角 4px，padding 4px 8px，字号 12px
- 搜索结果下拉：absolute，max-height 280px，overflow-y auto，border 1px `var(--border)`，背景 `var(--bg-elevated)`，z-index 100
- 命令输入展开：宽度 280px，placeholder "e.g. Add MFA to login flow"，字号 12px
- 所有 hover 态：背景变为 `var(--bg-subtle)`，transition 150ms ease
- 所有 active 态：背景变为 `var(--bg-subtle)` pressed
- 不使用按钮边框，不使用圆形按钮，不使用大字号

---

## 4. Graph Canvas

### 4.1 规格

- 占据 topbar 下方所有剩余空间
- 背景：`var(--bg-canvas)`
- overflow: hidden，通过 SVG transform 实现平移缩放
- 支持拖拽平移 + 滚轮缩放（zoom range 0.25 - 3x）

### 4.2 画布状态

| 状态 | 展示内容 |
|------|---------|
| **empty**（未索引） | 居中提示，字号 12px `var(--text-secondary)` |
| **overview**（有数据，无选中） | dagre 布局全图。所有节点 normal 亮度，所有边 default 实线+标签 |
| **focused**（有选中节点） | 局部聚焦：active 节点居左~30%，related 围绕展开，dimmed 退暗 `opacity: 0.2`，边变为流水虚线 |

### 4.3 空状态

居中展示，`text-align: center`：

```
Empty state icon (SVG, 48×48, var(--text-muted))

No graph loaded.
Run \`codegraph index\` to scan your codebase,
or search for a symbol using the topbar search.

[Learn more about indexing →]
```

字号 12px，颜色 `var(--text-secondary)`。Link 用 `var(--accent)`。

### 4.4 图布局

- 使用 **dagre** 进行层次布局
- 默认方向：TB（Top → Bottom）
- center node 居中
- callers 在上方，callees 在下方
- 无选中时：dagre 布局全图
- 有选中时：dagre 局部重排 active + related 子图，dimmed 节点保持原位不变

---

## 5. 节点设计

### 5.1 节点视觉结构

```
┌──────────────────────────┐
│░ func                    │  ← 左侧 2px 彩色竖条 + type 标签
│ authenticate             │  ← name，主文字
│ src/auth.py:42           │  ← file_path:line，辅助信息
│ conf 0.95                │  ← confidence
└──────────────────────────┘
```

### 5.2 节点尺寸

| 属性 | 值 |
|------|-----|
| 圆角 | 4px（小圆角，开发者工具风格） |
| border | 1px solid `var(--border)` |
| 左侧彩色竖条 | 2px width，`border-radius: 0 0 0 0` |
| padding | 6px 10px |
| min-width | 110px |
| max-width | 190px |
| 背景 | `var(--bg-panel)` |
| box-shadow | Light: `0 1px 2px rgba(0,0,0,0.04)`，Dark: `none` |

### 5.3 节点内部排版

| 元素 | 字体 | 字号 | 字重 | 颜色 |
|------|------|------|------|------|
| type 标签 | JetBrains Mono | 9px | 500 | `var(--text-muted)`，uppercase |
| name | JetBrains Mono | 12px | 500 | `var(--text-primary)` |
| file_path:line | JetBrains Mono | 9px | 400 | `var(--text-muted)` |
| confidence | JetBrains Mono | 9px | 400 | `var(--text-muted)` |

内部间距：`gap: 2px`，垂直 flex。文字不折行，超出 `text-overflow: ellipsis`。

### 5.4 节点类型 — 左侧竖条颜色

| 类型 | Light | Dark | 语义 |
|------|-------|------|------|
| `function` | `#2563EB` | `#60A5FA` | 蓝色 — 可执行代码 |
| `method` | `#7C3AED` | `#A78BFA` | 紫色 — 类成员 |
| `class` | `#059669` | `#34D399` | 绿色 — 结构定义 |
| `file` | `#6B7280` | `#9CA3AF` | 灰色 — 文件容器 |
| `test` | `#16A34A` | `#4ADE80` | 亮绿 — 测试覆盖 |
| `external_symbol` | `#D97706` | `#FB923C` | 橙色 — 外部依赖 |

> 使用 2px 左侧竖条，不覆盖节点主体色。这是开发者工具的典型风格（类比 VS Code 的 color decoration）。

### 5.5 节点状态样式

| 状态 | border | opacity | 其他 |
|------|--------|---------|------|
| **normal**（默认） | 1px `var(--border)` | 1.0 | — |
| **active**（被点击） | 1.5px `var(--accent)` | 1.0 | shadow: `0 0 0 2px var(--accent-alpha)` |
| **related**（与 active 相连） | 1px `var(--border-hover)` | 1.0 | — |
| **dimmed**（无关节点） | 1px `var(--border)` | 0.2 | 不接收 hover 事件 |

transition：`border-color 150ms ease, opacity 200ms ease, box-shadow 200ms ease`

### 5.6 节点交互

| 操作 | 行为 |
|------|------|
| 单击节点 | 设为 active，画布聚焦，Inspector 展开 |
| 双击节点 | 以该节点为中心重新加载 subgraph（depth=1） |
| Cmd/Ctrl+Click | 预留（将来在新面板打开） |
| 拖拽节点 | 局部位置调整，不触发重新布局 |

---

## 6. 边设计

### 6.1 边类型

| 类型 | 说明 |
|------|------|
| `calls` | 函数调用 |
| `imports` | 模块导入 |
| `contains` | 包含关系 |
| `tested_by` | 测试覆盖 |
| `references` | 引用关系 |

### 6.2 边基础样式

| 属性 | 值 |
|------|-----|
| 线宽 | 1px（hover 时 1.5px） |
| 箭头 | 小号实心三角，与线同色 |
| 标签 | 边中点，字号 9px，JetBrains Mono |
| 标签背景 | `<rect>` fill `var(--bg-canvas)`（遮罩线） |
| 标签颜色 | `var(--text-muted)` |

### 6.3 置信度颜色映射

| confidence | 线色 | 用途 |
|-----------|------|------|
| `>= 0.80` | `var(--edge-high)` | 正常信任 |
| `0.60 - 0.79` | `var(--edge-medium)` | 中等可信 |
| `< 0.60` | `var(--edge-low)` | 低可信度，警告 |

### 6.4 边状态系统

| 状态 | 触发条件 | 样式 |
|------|---------|------|
| **default** | 无选中节点 | 实线，显示 type 标签 |
| **active_flow** | 连接 active↔related | 虚线 + 流水动画，保留标签 |
| **dimmed** | 无关边 | `opacity: 0.1`，隐藏标签 |

### 6.5 流水虚线动画

```css
.edge-flow {
  stroke-dasharray: 5 3;
  animation: edge-flow 0.6s linear infinite;
}

@keyframes edge-flow {
  to { stroke-dashoffset: -8; }
}
```

- dasharray：5px 线段 + 3px 间隙
- 周期：0.6s
- 速度：线性匀速
- 语义：光点沿调用关系方向流动，表示数据/控制流方向
- 约束：只在 active↔related 的 5-15 条边上启用，不超过 20 条

### 6.6 边交互

| 操作 | 行为 |
|------|------|
| 点击边 | Inspector 显示 edge details |
| hover 边 | `stroke-width: 1.5px`，其余边 `opacity: 0.3` |
| hover 低置信度边 | 额外显示 tooltip "Low confidence (< 0.60)" |
| 边标签 hover | 同 hover 边 |

---

## 7. 节点与边的交互系统

### 7.1 状态转换图

```
                  ┌──────────────────────────────────────┐
                  │       默认状态 (overview)              │
                  │  所有节点 normal                      │
                  │  所有边 default（实线 + type 标签）     │
                  └──────────────┬───────────────────────┘
                                 │ 单击节点
                                 ▼
                  ┌──────────────────────────────────────┐
                  │       聚焦状态 (focused)               │
                  │  active → 居左 ~30% + accent border    │
                  │  related → 围绕 active + 正常亮度      │
                  │  dimmed → opacity 0.2（保持原位）      │
                  │  active↔related 边 → 流水虚线 + 标签   │
                  │  dimmed 边 → opacity 0.1, 无标签       │
                  │  Inspector 展开                        │
                  └──────────────┬───────────────────────┘
                                 │ 双击 canvas / Escape
                                 ▼
                  ┌──────────────────────────────────────┐
                  │       默认状态 (overview)              │
                  └──────────────────────────────────────┘
```

### 7.2 画布聚焦机制

单击节点后：
1. **active 节点自动平移到画布左侧约 30% 位置**（为 related 节点在右侧展开留空间）
2. **related 节点围绕 active 重新布局**（dagre 局部布局）
3. **dimmed 节点保持原位**，仅变透明度
4. **画布自动 zoom-to-fit**，使 active + related 节点群占画布主体的 70%
5. 动画过渡 `250ms ease-out`，使用 SVG transform transition

```
┌─────────────────────────────────────────────────┐
│  [dimmed]  [dimmed]                             │
│                      ┌─────────┐                │
│                      │ caller  │  [dimmed]      │
│    [dimmed]          └────┬────┘                │
│                           │ 流水虚线             │
│                     ┌─────▼──────┐              │
│  [dimmed]  ──────── │  active    │ ────────  ┌──┤
│                     │ (左侧30%)  │ 流水虚线   │...│
│                     └─────┬──────┘           └──┤
│                           │                     │
│    [dimmed]          ┌────▼─────┐               │
│                      │ callee   │               │
│                      └──────────┘    [dimmed]   │
│  [dimmed]         [dimmed]                      │
└─────────────────────────────────────────────────┘
```

### 7.3 完整交互序列

```
默认状态：
  所有节点 normal | 所有边 实线+标签

单击 node_A：
  → node_A 成为 active
  → 直接相连的节点成为 related
  → 其余节点 → dimmed (opacity 0.2)
  → active↔related 边 → 流水虚线
  → dimmed 边 → opacity 0.1
  → 画布平移聚焦到 active+related 子图
  → Inspector 展开显示 node_A 详情

单击另一节点 node_B：
  → node_B 成为 active
  → 重新计算 related/dimmed
  → 画布重新聚焦

单击边 edge_A→B：
  → Inspector 切换为边详情
  → 节点状态不变
  → 该边 hover 高亮

双击 canvas 空白 / 按 Escape：
  → 清除选中态
  → 所有节点 → normal
  → 所有边 → default（实线+标签）
  → Inspector 收起
  → 画布回到 overview 位置
```

---

## 8. Right Inspector

### 8.1 状态

| 状态 | 宽度 | 触发条件 |
|------|------|---------|
| 折叠 | 0 | 默认 / 关闭 / Escape |
| 展开-节点详情 | `--inspector-width` | 单击节点 |
| 展开-边详情 | `--inspector-width` | 单击边 |

展开/收起 transition：`width 200ms ease`

### 8.2 设计规格

| 属性 | 值 |
|------|-----|
| 背景 | `var(--bg-panel)` |
| border-left | 1px solid `var(--border)` |
| box-shadow | `none`（平面，开发者工具风格） |
| padding | 16px |
| 关闭按钮 x | 右上角，font-size 14px，颜色 `var(--text-muted)`，hover `var(--text-primary)` |
| 内部滚动 | overflow-y auto，max-height 100% |

### 8.3 节点详情内容

```
┌──────────────────────────────────────────────┐
│ ✕                                             │
│                                                │
│ FUNC                                          │
│ authenticate                                  │
│ src/auth.py:42-78                             │
│                                                │
│ ── Signature                                  │
│                                                │
│   def authenticate(                           │
│     username: str,                            │
│     password: str                             │
│   ) -> User                                   │
│                                                │
│ ── Summary                                    │
│                                                │
│ Authenticates user credentials against the     │
│ database. Called at login and token refresh.   │
│                                                │
│ ── Selection Reason                            │
│                                                │
│ Entry point for login flow.                    │
│ Match: name, docstring                         │
│ Confidence: 0.95                               │
│                                                │
│ ── Relations                                   │
│                                                │
│ Callers (3)                                    │
│  login                    calls    0.95        │
│  verify_token             calls    0.72        │
│  handle_session           calls    0.68 ⚠     │
│                                                │
│ Callees (2)                                    │
│  hash_password            calls    0.95        │
│  query_db                 calls    0.88        │
│                                                │
│ Tests (1)                                      │
│  test_authenticate        tests    0.90        │
│                                                │
│ ── Actions                                     │
│                                                │
│ [+ Add to Context Pack]                        │
│ [Generate Context Pack]                        │
│ [Analyze Impact]                               │
│ [View Source]                                  │
└────────────────────────────────────────────────┘
```

### 8.4 边详情内容

```
┌──────────────────────────────────────────────┐
│ ✕                                             │
│                                                │
│ EDGE                                           │
│ authenticate → verify_token                    │
│                                                │
│ ── Properties                                  │
│                                                │
│ Type:         calls                            │
│ Confidence:   0.72                             │
│ Resolution:   static_parse                     │
│                                                │
│ ── Source Location                              │
│                                                │
│   auth.py:45                                   │
│   result = verify_token(current_user.token)    │
│                                                │
│ ── Reason                                      │
│                                                │
│ Direct function call detected in AST parse.    │
│                                                │
│ ── ⚠ Low-confidence edge                       │
│                                                │
│ This edge was resolved at medium confidence    │
│ (0.72). Verify manually if this is a critical  │
│ code path.                                     │
│                                                │
│ [Navigate to Source]                            │
└────────────────────────────────────────────────┘
```

### 8.5 Section 规范

| 元素 | 样式 |
|------|------|
| Section 标题 `── title` | Inter 10px 600，`var(--text-secondary)`，padding `8px 0 4px`，border-top 1px solid `var(--border)` |
| 代码块 | 背景 `var(--bg-subtle)`，圆角 4px，padding 8px，JetBrains Mono 11px |
| 列表项 | Inter 11px，`var(--text-primary)`，行高 1.5 |
| 置信度 | 右对齐，JetBrains Mono 10px，`var(--text-muted)` |
| ⚠ 标记 | confidence < 0.60 显示 |
| 警告区块 | 背景 `var(--warning-bg)`，border-left 2px `var(--warning)`，padding 8px，font-size 11px |
| Actions 按钮 | outline：border 1px `var(--border)`，padding 4px 10px，字号 11px，圆角 4px，hover 背景 `var(--bg-subtle)` |

---

## 9. Context Pack Overlay

### 9.1 位置

Canvas 左下角浮动层。距离左下角 16px，z-index 10。

### 9.2 设计规格

| 属性 | 值 |
|------|-----|
| 宽度 | 300px |
| 最大高度 | 260px |
| 背景 | `var(--bg-elevated)` |
| border | 1px solid `var(--border)` |
| 圆角 | 6px |
| box-shadow | Light: `0 2px 8px rgba(0,0,0,0.06)`，Dark: `0 2px 8px rgba(0,0,0,0.25)` |
| padding | 12px |

### 9.3 收起态

```
┌──────────────────────────────────┐
│ ▸  Context Pack                   │
└──────────────────────────────────┘
```

单行，字号 11px，Inter 600。点击展开。

### 9.4 展开态

```
┌──────────────────────────────────────┐
│ ▾  Context Pack                    ✕ │
│                                       │
│   Add MFA to login flow              │
│   intent: authentication_security     │
│                                       │
│   3 entry points · 8 symbols          │
│   5 files · risk: medium              │
│   ⚠ 2 warnings                        │
│                                       │
│   [Copy Markdown]   [Export JSON]     │
└──────────────────────────────────────┘
```

所有文字 11px。统计用 `var(--text-secondary)`。数字用 JetBrains Mono 10px。

### 9.5 交互

- 点击标题栏展开/收起
- 点击 Copy Markdown → 复制到剪贴板 → 按钮文字变为 "Copied!" 1.5s 后恢复
- 点击 Export JSON → 触发 `.json` 文件下载
- 生成中：按钮 disabled + spinner → "Generating..."

---

## 10. Reading Plan

### 10.1 触发按钮

右下角 16px，z-index 10：

```
┌───────────────────────┐
│ ⌥  Reading Plan (4)  │
└───────────────────────┘
```

- outline 样式：border 1px `var(--border)`，背景 `var(--bg-elevated)`
- 圆角 6px，padding 6px 12px，字号 11px，Inter 500
- hover：背景 `var(--bg-subtle)`

### 10.2 展开面板

从右下角展开（或右侧弹出）：

```
┌────────────────────────────────────────┐
│ Reading Plan                        ✕  │
│                                         │
│ 1.  READ    authenticate                │
│     Review entry point for login flow   │
│                                         │
│ 2.  READ    verify_token                │
│     Understand token validation logic   │
│                                         │
│ 3.  READ    MFAForm class               │
│     MFA implementation details          │
│                                         │
│ 4.  READ    test_auth_mfa               │
│     Verify MFA integration              │
└────────────────────────────────────────┘
```

### 10.3 设计规格

| 属性 | 值 |
|------|-----|
| 宽度 | 320px |
| 最大高度 | 360px（overflow-y auto） |
| 背景 | `var(--bg-elevated)` |
| border | 1px solid `var(--border)` |
| 圆角 | 6px |
| box-shadow | 同 Context Pack Overlay |
| padding | 14px |

### 10.4 步骤设计

| 元素 | 样式 |
|------|------|
| 步骤编号 | Inter 12px 600，`var(--accent)`，宽度 20px |
| Action 标签 | JetBrains Mono 9px 500，`var(--text-muted)`，背景 `var(--bg-subtle)`，圆角 2px，padding 1px 4px，uppercase |
| Target | JetBrains Mono 11px 500，`var(--text-primary)` |
| Reason | Inter 10px，`var(--text-secondary)`，margin-top 2px |

行高 1.4。步骤间 gap 10px。

### 10.5 交互

- 点击步骤 → 图中对应节点短暂闪烁高亮（accent border flash 400ms）+ 画布聚焦到该节点
- 关闭面板 | 重新生成 Context Pack 时自动刷新

---

## 11. Index Status Popover

### 11.1 触发

点击 Topbar 中的 `● Indexed` 状态指示器。

### 11.2 设计规格

| 属性 | 值 |
|------|-----|
| 宽度 | 260px |
| 背景 | `var(--bg-elevated)` |
| border | 1px solid `var(--border)` |
| 圆角 | 6px |
| box-shadow | Light: `0 4px 12px rgba(0,0,0,0.08)`，Dark: `0 4px 12px rgba(0,0,0,0.35)` |
| padding | 14px |
| z-index | 200（> topbar） |

### 11.3 内容

```
┌──────────────────────────────────┐
│ Index Status                     │
│                                   │
│ Indexed   2026-05-27 10:30:42    │
│                                   │
│ Files     128                     │
│ Symbols   1,432                   │
│ Edges     3,891                   │
│ Failed    2                       │
│                                   │
│ Low conf  47 (1.2%)               │
│                                   │
│ [Re-index]                        │
└──────────────────────────────────┘
```

- 标题 "Index Status"：Inter 11px 600，`var(--text-primary)`
- 时间行：Inter 10px，label `var(--text-secondary)`，value `var(--text-primary)`
- 统计数据：key 左对齐 Inter 10px `var(--text-secondary)`，value 右对齐 JetBrains Mono 10px `var(--text-primary)`
- Failed > 0：value 颜色 `var(--error)`，行背景 `var(--error-alpha-bg)`
- Low conf > 5%：value 颜色 `var(--warning)`
- Re-index 按钮：outline，字号 10px，padding 4px 10px，点击后 spinner 替代文字

---

## 12. 主题系统

### 12.1 切换方式

Topbar 右侧小型 segmented control：

```
┌─────────┬─────────┬─────────┐
│  System │  Light  │  Dark   │
└─────────┴─────────┴─────────┘
```

| 属性 | 值 |
|------|-----|
| 高度 | 22px |
| 字号 | 10px，Inter 500 |
| 圆角 | 4px |
| 选中态 | 背景 `var(--bg-subtle)`，文字 `var(--text-primary)` |
| 非选中态 | 文字 `var(--text-muted)` |
| item padding | 0 8px |

### 12.2 切换规则

| 选择 | 行为 |
|------|------|
| System | 监听 `prefers-color-scheme` media query，跟随系统 |
| Light | 强制 light，忽略系统 |
| Dark | 强制 dark，忽略系统 |

- 通过 `data-theme` attribute 切换 CSS 变量，不 reload
- 持久化到 `localStorage('codegraph-theme')`
- 启动读取优先级：`localStorage > prefers-color-scheme > light`（fallback）

### 12.3 CSS 变量

```css
/* ── Light (default) ── */
:root,
[data-theme="light"] {
  --bg-canvas: #FAFBFC;
  --bg-panel: #FFFFFF;
  --bg-subtle: #F3F4F6;
  --bg-elevated: #FFFFFF;

  --border: #E5E7EB;
  --border-hover: #D1D5DB;

  --text-primary: #111827;
  --text-secondary: #6B7280;
  --text-muted: #9CA3AF;

  --accent: #2563EB;
  --accent-alpha: rgba(37, 99, 235, 0.12);
  --accent-hover: #1D4ED8;

  --warning: #D97706;
  --warning-bg: #FFFBEB;

  --error: #DC2626;
  --error-alpha-bg: rgba(220, 38, 38, 0.06);
  --success: #16A34A;

  /* Node type colors (light) */
  --node-function: #2563EB;
  --node-method: #7C3AED;
  --node-class: #059669;
  --node-file: #6B7280;
  --node-test: #16A34A;
  --node-external: #D97706;

  /* Edge confidence colors */
  --edge-high: #9CA3AF;
  --edge-medium: #D97706;
  --edge-low: #F59E0B;

  /* Inspector */
  --inspector-width: min(30vw, 420px);

  /* Shadows */
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.06);
  --shadow-lg: 0 4px 12px rgba(0,0,0,0.08);
}

/* ── Dark ── */
[data-theme="dark"] {
  --bg-canvas: #0B0E14;
  --bg-panel: #13161D;
  --bg-subtle: #1A1E27;
  --bg-elevated: #1A1E27;

  --border: #262B36;
  --border-hover: #333948;

  --text-primary: #E4E7EC;
  --text-secondary: #949AAB;
  --text-muted: #636B7E;

  --accent: #60A5FA;
  --accent-alpha: rgba(96, 165, 250, 0.12);
  --accent-hover: #93C5FD;

  --warning: #F59E0B;
  --warning-bg: #1A1500;

  --error: #EF4444;
  --error-alpha-bg: rgba(239, 68, 68, 0.08);
  --success: #22C55E;

  /* Node type colors (dark) */
  --node-function: #60A5FA;
  --node-method: #A78BFA;
  --node-class: #34D399;
  --node-file: #9CA3AF;
  --node-test: #4ADE80;
  --node-external: #FB923C;

  /* Edge confidence colors */
  --edge-high: #636B7E;
  --edge-medium: #D97706;
  --edge-low: #F59E0B;

  /* Shadows */
  --shadow-sm: none;
  --shadow-md: 0 2px 8px rgba(0,0,0,0.25);
  --shadow-lg: 0 4px 12px rgba(0,0,0,0.35);
}
```

### 12.4 Tailwind 集成

```js
// tailwind.config.js
module.exports = {
  theme: {
    extend: {
      colors: {
        canvas: 'var(--bg-canvas)',
        panel: 'var(--bg-panel)',
        subtle: 'var(--bg-subtle)',
        elevated: 'var(--bg-elevated)',
        border: 'var(--border)',
        'border-hover': 'var(--border-hover)',
        primary: 'var(--text-primary)',
        secondary: 'var(--text-secondary)',
        muted: 'var(--text-muted)',
        accent: 'var(--accent)',
        'accent-hover': 'var(--accent-hover)',
        warning: 'var(--warning)',
        'warning-bg': 'var(--warning-bg)',
        error: 'var(--error)',
        success: 'var(--success)',
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"SF Mono"', 'Menlo', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
      fontSize: {
        '9': '9px',
        '10': '10px',
        '11': '11px',
        '12': '12px',
        '13': '13px',
      },
      boxShadow: {
        'sm': 'var(--shadow-sm)',
        'md': 'var(--shadow-md)',
        'lg': 'var(--shadow-lg)',
      },
    },
  },
};
```

### 12.5 useTheme Hook

```typescript
type Theme = "system" | "light" | "dark";

function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("codegraph-theme") as Theme) || "system"
  );

  const resolved = useMemo(() => {
    if (theme === "system") {
      return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }
    return theme;
  }, [theme]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolved);
    localStorage.setItem("codegraph-theme", theme);
  }, [theme, resolved]);

  useEffect(() => {
    if (theme !== "system") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const handler = () => document.documentElement.setAttribute(
      "data-theme", mq.matches ? "dark" : "light"
    );
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  return { theme, setTheme, resolvedTheme: resolved };
}
```

---

## 13. 排版规范

### 13.1 字体栈

| 用途 | font-family |
|------|-------------|
| 界面文字（标题、标签、操作、正文） | `Inter, system-ui, -apple-system, sans-serif` |
| 代码文字（symbol_id、file_path、signature、confidence） | `"JetBrains Mono", "SF Mono", Menlo, monospace` |

> 来自 skill 推荐：**Minimal Swiss**（Inter/Inter）+ **Developer Mono**（JetBrains Mono/IBM Plex Sans）的混合。Single-family 系统保持视觉一致性。

### 13.2 字号字重表

| 用途 | font | size | weight | color |
|------|------|------|--------|-------|
| Topbar 应用名 | Inter | 12px | 600 | `--text-primary` |
| Topbar 辅助信息 | Inter | 11px | 400 | `--text-secondary/muted` |
| Panel/Section 标题 | Inter | 11px | 600 | `--text-primary` |
| Section 分隔线 `── title` | Inter | 10px | 600 | `--text-secondary` |
| 正文/label | Inter | 11px | 400 | `--text-primary` |
| 辅助正文 | Inter | 10px | 400 | `--text-secondary` |
| Symbol name | JetBrains Mono | 12px | 500 | `--text-primary` |
| symbol_id | JetBrains Mono | 10px | 400 | `--text-secondary` |
| file_path | JetBrains Mono | 9px | 400 | `--text-muted` |
| confidence | JetBrains Mono | 9px | 500 | `--text-muted` |
| Code/signature | JetBrains Mono | 11px | 400 | `--text-primary` |
| Node type 标签 | JetBrains Mono | 9px | 500 | `--text-muted` |
| Edge type 标签 | JetBrains Mono | 9px | 500 | `--text-muted` |
| Button 文字 | Inter | 11px | 500 | `--text-primary` |
| Popover 标题 | Inter | 11px | 600 | `--text-primary` |

### 13.3 行高

| 场景 | line-height |
|------|-------------|
| 正文 | 1.5 |
| 代码 | 1.6 |
| 标题/标签 | 1.3 |
| 紧凑列表 | 1.4 |

---

## 14. 间距与尺寸规范

### 14.1 间距体系（8px 增量）

| Token | px | 用途 |
|-------|-----|------|
| `--space-1` | 2px | 标签内部内边距 |
| `--space-2` | 4px | 节点/按钮内部小间距 |
| `--space-3` | 6px | 节点内部 gap |
| `--space-4` | 8px | Topbar item gap，元素间 gap |
| `--space-5` | 10px | 列表项间 gap |
| `--space-6` | 12px | Panel padding，section gap |
| `--space-7` | 14px | Popover/Overlay padding |
| `--space-8` | 16px | 大区块间距，浮动层距边缘 |

> 遵循 skill 的 `spacing-scale` 规则：4pt/8dp incremental。

### 14.2 尺寸表

| Token | 值 | 适用 |
|-------|-----|------|
| `--topbar-height` | 36px | 顶部工具栏 |
| `--inspector-width` | min(30vw, 420px) | 右侧详情面板 |
| `--overlay-width` | 300px | Context Pack Overlay |
| `--reading-plan-width` | 320px | Reading Plan |
| `--popover-width` | 260px | Index Status |
| `--node-min-width` | 110px | 节点最小宽 |
| `--node-max-width` | 190px | 节点最大宽 |
| `--radius-sm` | 4px | 节点、按钮、输入框 |
| `--radius-md` | 6px | 面板、浮层 |
| `--radius-lg` | 8px | 无，开发者工具用小圆角 |

---

## 15. 颜色体系

### 15.1 设计依据

来自 skill **Developer Tool / IDE** color palette (#81)：
- **Dark background** `#0B0E14`（接近 #0F172A 的优化版本）
- **Green accent** `#22C55E`（"run green" 语义，用于成功/active 状态）
- **Blue accent** `#60A5FA`（claude dark theme 兼容，用于交互态）
- **Slate neutrals**（代码编辑器经典的灰阶系统）

Light 主题适配为 Minimal Swiss 风格：
- **Clean white** `#FAFBFC` canvas（类似 GitHub）
- **Warm white** `#FFFFFF` panels
- **Slate grays** `#E5E7EB → #111827`

### 15.2 Light 主题

| CSS 变量 | Hex | 用途 |
|----------|-----|------|
| `--bg-canvas` | `#FAFBFC` | 画布背景（极浅灰，区分于纯白面板） |
| `--bg-panel` | `#FFFFFF` | 面板背景 |
| `--bg-subtle` | `#F3F4F6` | 弱化背景（代码块、hover、标签） |
| `--bg-elevated` | `#FFFFFF` | 浮层面板（popover、overlay、drawer） |
| `--border` | `#E5E7EB` | 默认边框 |
| `--border-hover` | `#D1D5DB` | hover 边框 |
| `--text-primary` | `#111827` | 主要文字 |
| `--text-secondary` | `#6B7280` | 次要文字 |
| `--text-muted` | `#9CA3AF` | 弱化文字 |
| `--accent` | `#2563EB` | 交互强调色（选中态、active、链接） |
| `--accent-alpha` | `rgba(37,99,235,0.12)` | accent 透明版本（选中 halo） |
| `--accent-hover` | `#1D4ED8` | accent hover |
| `--warning` | `#D97706` | 中置信度警告 |
| `--warning-bg` | `#FFFBEB` | 警告背景 |
| `--error` | `#DC2626` | 错误/高风险 |
| `--error-alpha-bg` | `rgba(220,38,38,0.06)` | 错误行背景 |
| `--success` | `#16A34A` | 成功/已索引 |

### 15.3 Dark 主题

| CSS 变量 | Hex | 用途 |
|----------|-----|------|
| `--bg-canvas` | `#0B0E14` | 画布背景（深色代码编辑器风格） |
| `--bg-panel` | `#13161D` | 面板背景 |
| `--bg-subtle` | `#1A1E27` | 弱化背景 |
| `--bg-elevated` | `#1A1E27` | 浮层面板 |
| `--border` | `#262B36` | 默认边框 |
| `--border-hover` | `#333948` | hover 边框 |
| `--text-primary` | `#E4E7EC` | 主要文字 |
| `--text-secondary` | `#949AAB` | 次要文字 |
| `--text-muted` | `#636B7E` | 弱化文字 |
| `--accent` | `#60A5FA` | 交互强调色 |
| `--accent-alpha` | `rgba(96,165,250,0.12)` | accent 透明版本 |
| `--accent-hover` | `#93C5FD` | accent hover |
| `--warning` | `#F59E0B` | 中置信度警告 |
| `--warning-bg` | `#1A1500` | 警告背景 |
| `--error` | `#EF4444` | 错误/高风险 |
| `--error-alpha-bg` | `rgba(239,68,68,0.08)` | 错误行背景 |
| `--success` | `#22C55E` | 成功/已索引（"run green"） |

### 15.4 一致性规则

- 所有颜色通过 CSS 变量引用，**不硬编码 hex**
- Light/Dark 通过 `data-theme` 切换，**不产生两个独立样式表**
- 信息传达不依赖颜色：error 行同时有 `--error-alpha-bg` 背景 + icon/text
- 对比度满足 WCAG AA（4.5:1），dark 模式下调低饱和度而非反转

---

## 16. 组件清单

```
src/
├── App.tsx                    // useTheme + Layout
├── main.tsx                   // 入口
├── index.css                  // CSS 变量 + Tailwind + global styles
├── api/
│   └── index.ts               // API 封装
├── types/
│   └── index.ts               // 类型定义
├── hooks/
│   └── useTheme.ts            // 主题切换 + localStorage
├── components/
│   ├── Layout.tsx             // 整体布局框架
│   ├── Topbar.tsx             // 36px 工具栏
│   ├── ThemeSwitcher.tsx      // System/Light/Dark segmented control
│   ├── SearchInput.tsx        // 搜索 + 下拉结果
│   ├── CommandInput.tsx       // Task 命令输入
│   ├── IndexStatus.tsx        // 索引状态指示器
│   ├── IndexPopover.tsx       // 索引状态弹窗
│   ├── GraphCanvas.tsx        // dagre + SVG 画布
│   ├── GraphNode.tsx          // 自定义节点渲染
│   ├── GraphEdge.tsx          // 自定义边渲染
│   ├── Inspector.tsx          // 右侧面板（展开/收起控制）
│   ├── NodeInspector.tsx      // 节点详情
│   ├── EdgeInspector.tsx      // 边详情
│   ├── ContextPackOverlay.tsx // Context Pack 浮层
│   ├── ReadingPlan.tsx        // Reading Plan 面板
│   ├── Button.tsx             // 通用 outline button
│   └── Spinner.tsx            // SVG spinner
```

---

## 17. 关键交互流程

### 17.1 打开页面

```
1. 读取 localStorage('codegraph-theme') → 无则检测 prefers-color-scheme
2. 设置 data-theme attribute
3. 渲染 Layout（Topbar + Canvas + 折叠的 Inspector）
4. GET /api/dashboard/stats
5. Topbar 索引状态更新
6. Canvas: 有数据 → overview 全图 | 无数据 → empty state
```

### 17.2 搜索符号

```
1. Topbar 点击 ⌕ → SearchInput 展开
2. 输入关键词，300ms debounce
3. GET /api/symbols/search → 下拉结果列表
4. 点击结果：
   a. GET /api/graph/subgraph?symbol_id=X&depth=1 更新画布
   b. GET /api/symbols/{id} 在 Inspector 显示
   c. 画布聚焦：active + related 高亮，其余 dimmed
   d. 边变为流水虚线
```

### 17.3 探索图谱

```
1. 单击节点 A（非当前 active）
2. A 成为 active，画布重排聚焦
3. 双击 A → 以 A 为中心 reload subgraph
4. 单击边 → Inspector 切换边详情
5. 双击 canvas 空白 / Escape → 清除选中，回到 overview
```

### 17.4 生成 Context Pack

```
1. Topbar 点击 ⚡ → CommandInput 展开
2. 输入 task → 回车
3. POST /api/context-pack → Overlay loading
4. 完成：Overlay 显示概要，entry points 闪烁，Reading Plan 按钮出现
5. Copy Markdown / Export JSON
```

### 17.5 查看 Reading Plan

```
1. Context Pack 生成后，右下角显示 Reading Plan 按钮
2. 点击展开面板
3. 点击步骤 → 对应节点闪烁高亮 + 画布聚焦
```

### 17.6 切换主题

```
1. Topbar 点击主题 switcher
2. 选择 Dark → data-theme 变为 "dark"
3. CSS 变量全部切换
4. 信息结构和布局不变
5. 持久化到 localStorage
```

---

## 18. 技术选型与图渲染方案

### 18.1 依赖清单

| 依赖 | 用途 |
|------|------|
| `react` + `react-dom` | 框架 |
| `typescript` | 类型 |
| `vite` + `@vitejs/plugin-react` | 构建 |
| `tailwindcss` + `postcss` + `autoprefixer` | CSS |
| `@dagrejs/dagre` | 图布局算法 |
| `@heroicons/react` 或 `lucide-react` | SVG 图标（替代 emoji） |

**零额外运行时**：无 Redux/Zustand，无 React Flow，无 react-router-dom。

### 18.2 图渲染：dagre + 纯 SVG

**不选择 React Flow 的理由：**
- 节点通常 < 50 个，不需要虚拟化
- 不需要力导向、不需要物理模拟
- 不需要 Minimap、Controls 等内置组件
- dagre 提供确定性布局结果，符合工具型产品的可预测性要求

**SVG 渲染方案：**

```
<svg width="100%" height="100%">
  <g transform="translate(panX, panY) scale(zoom)">
    <!-- 边层 -->
    {edges.map(e => (
      <g key={e.id}>
        <path d={computeBezier(e)} />       // 线
        <path d={computeBezier(e)} />       // 虚线（流水态）
        <text>type</text>                    // 标签
        <polygon />                          // 箭头
      </g>
    ))}
    <!-- 节点层 -->
    {nodes.map(n => (
      <g transform={`translate(${n.x},${n.y})`}>
        <foreignObject width={w} height={h}>
          <GraphNode data={n} />
        </foreignObject>
      </g>
    ))}
  </g>
</svg>
```

平移：`mousedown + mousemove → translate(dx, dy)`
缩放：`wheel → scale *= factor`

### 18.3 状态类型

```typescript
type ViewState<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "data"; data: T };
```

不引入外部状态管理，使用 React `useState` / `useReducer`。

---

## 19. 实现优先级

| P | 功能 | 预估 h |
|---|------|--------|
| **P0** | 主题系统（CSS 变量 + useTheme + ThemeSwitcher） | 1 |
| **P0** | Layout（Topbar + Canvas + Inspector 三栏） | 1.5 |
| **P0** | Topbar（布局、索引状态、搜索、命令输入） | 2 |
| **P0** | GraphCanvas + dagre 布局集成 | 3 |
| **P0** | GraphNode（custom node + 类型色条 + 状态切换） | 2 |
| **P0** | GraphEdge（边渲染 + 标签 + 流水虚线动画） | 2 |
| **P0** | 节点点击交互（active/related/dimmed + 画布聚焦） | 2 |
| **P1** | Inspector + NodeInspector | 2.5 |
| **P1** | EdgeInspector | 1 |
| **P1** | ContextPackOverlay | 1.5 |
| **P1** | ReadingPlan | 1 |
| **P2** | IndexPopover | 0.5 |
| **P2** | 动画/过渡润色 | 0.5 |
| **P2** | Copy / Export 功能 | 0.5 |
| **P3** | API 集成收尾、空/错误态 | 1 |

**总计：约 22h**

---

## 20. 文案规范

### 20.1 使用这些

| 术语 | 场合 |
|------|------|
| Context Pack | 上下文包 |
| Selection Reason | 选择原因 |
| Static Analysis | 静态分析 |
| Graph Resolution | 图解析 |
| Confidence | 置信度 |
| Reading Plan | 阅读计划 |
| Impact | 影响面 |
| Source Location | 源代码位置 |
| Low-confidence edge | 低置信度边 |
| Entry Point | 入口点 |
| Related Symbol | 相关符号 |
| Caller / Callee | 调用者 / 被调用者 |
| Re-index | 重新索引 |
| Export JSON / Copy Markdown | 导出/复制 |

### 20.2 禁止使用

❌ AI Analysis / AI Insight / AI 分析 — 都是静态分析，不要自称 AI
❌ Magic / 智能 / Dynamic — 不准确
❌ Beautiful / Awesome / Gorgeous — 不自夸
❌ Emoji 作为图标 — 用 Heroicons / Lucide SVG
❌ "This graph shows..." — 直接展示，不解释

### 20.3 文案风格

- 命令式：**Re-index**、**Search**、**Generate**、**Copy**、**Export**
- 开发者语言：symbol、edge、node、confidence、resolution、AST、dagre
- 简短：控制在 2-5 个词
- 不解释：直接展示，不加说明文案

---

> 本文档是 UI-DESIGN-v3 最终版本。所有设计决策已集成 UI/UX Pro Max skill 的设计智能（50+ 风格、161 色板、57 字体搭配、99 UX 指南），并针对 Developer Tool 场景进行了定制。外部开发时以此为准。
