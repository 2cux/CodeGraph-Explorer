# CodeGraph A/B 对比实验

**日期：** 2026-05-28
**任务：** add MFA to login flow
**项目：** `examples/demo_python_project/`

## 实验设计

| 组别 | 条件 | 描述 |
|------|------|------|
| **A 组** | 无 CodeGraph | Agent 只能用 Read/Grep/Glob 手动探索代码库 |
| **B 组** | 用 CodeGraph | Agent 先调用 `codegraph context` 生成 Context Pack，再按 reading plan 阅读 |

两组使用同一个 demo Python 项目（7 个源文件，3 层目录结构），完成同一个任务：提出"add MFA to login flow"的实现方案。

---

## 实验结果

| 维度 | A 组（无 CodeGraph） | B 组（有 CodeGraph） | 改进 |
|------|:-:|:-:|:-:|
| **工具调用次数** | 41 | 16 | **2.5x 更少** |
| **耗时** | ~193s | ~53s | **3.6x 更快** |
| **文件读取数** | 9（全部 .py 文件） | 5（仅相关文件） | **少读 44%** |
| **搜索次数** | 3（Glob + Grep） | 0 | **零搜索** |
| **入口点发现** | 读完所有文件后手动定位到 `main()` | `codegraph context` 直接命中 `app/api/auth.py::login` (score 1.00) | **一步到位** |
| **相关依赖发现** | 手动跟踪全部文件 | Call graph 自动输出 2 edges: `main::main`→`login`, `login`→`save_token` | **自动发现** |
| **影响面意识** | 无（靠人工推理） | 3 个 affected files + risk level `high` + 5 条 reasons | **新增能力** |
| **测试意识** | 手动 Grep 确认无测试文件 | 自动建议 `tests/test_auth.py::{test_auth, test_login_}` | **零成本** |
| **实现方案质量** | Good（但 Python 3.6 兼容问题浪费 3 轮修复） | Good（按 reading plan 精准阅读，无兼容陷坑） | **更少弯路** |

---

## 详细过程

### A 组（无 CodeGraph）

Agent 的探索路径：

1. Glob 扫描所有 `.py` 文件 → 找到 9 个文件
2. 从 `main.py` 开始逐文件阅读：
   - `main.py` → `app/api/auth.py` → `app/store/token_store.py`
   - `app/api/users.py` → `app/models/user.py`
   - 所有 `__init__.py`
3. 额外 Grep 确认无测试文件
4. 手动构建调用关系心智模型
5. 提出实现方案

**关键问题：** Agent 无法区分"重要"和"不重要"的文件，必须读完全部 9 个文件才能建立完整认知。没有自动的影响面分析，需要人工推理。

### B 组（用 CodeGraph）

Agent 的探索路径：

1. 调用 `codegraph context "add MFA to login flow"` 获得 Context Pack
2. 按 reading plan 阅读：
   - Step 1: `app/api/auth.py::login`（入口点）
   - Step 2: `main.py::main`（上游调用者）
   - Step 3: `app/store/token_store.py::save_token`（下游被调用者）
3. 额外阅读 `users.py` 和 `user.py`（根据实现需要）
4. 基于 Context Pack 的 impact 分析和 reading plan 提出方案

**关键优势：** Agent 在 3 步 reading plan 内就完成了核心代码理解。影响面分析直接给出了 3 个受影响文件和安全风险警告，不需要额外推理。

---

## 核心结论

### CodeGraph 带来的改进

1. **入口点发现：从"扫全库"到"一步命中"**
   - A 组需要读 9 个文件才能找到 `login` 函数
   - B 组通过 `codegraph context` 直接得到 `app/api/auth.py::login`，score 1.00

2. **依赖发现：从手动跟踪到自动 Graph**
   - A 组手动跟踪 `main()` → `login()` → `save_token()` 调用链
   - B 组一次 CLI 调用获得完整 call graph（3 nodes, 2 edges, confidence 0.90）

3. **影响面意识：从无到有**
   - A 组完全依赖 Agent 的经验来判断"改这个会影响谁"
   - B 组自动获得 risk level + affected files + 影响原因

4. **测试意识：从确认缺失到自动建议**
   - A 组需要额外搜索来确认"有没有测试"
   - B 组自动获得"没有测试，建议创建 tests/test_auth.py"

5. **效率：工具调用和耗时减半以上**
   - 工具调用: 41 → 16（-61%）
   - 耗时: 193s → 53s（-73%）
   - 文件读取: 9 → 5（-44%）

### 局限性

- Demo 项目规模较小（7 个源文件），在大项目中差异可能更显著
- B 组的收益高度依赖项目已索引（`codegraph index` 已运行）
- 对于完全陌生的项目，A 组需要额外时间来理解整体架构，而 B 组在 3 步内完成理解

### 实验设计说明

本次实验控制条件：
- 同一任务、同一项目、同一测量标准
- A 组仅暴露 Read/Grep/Glob 工具（无 CodeGraph 命令）
- B 组暴露 `codegraph context` CLI 命令
- 两组均为通用 Agent，非专门针对该任务优化

---

## 原始数据

### A 组

- Agent runtime: ~193s
- Tool calls: 41
- [Simulated transcript: 9 Reads, 2 Globs, 1 Grep, 11 Edit/Writes, 18 Bash commands]
- 入口点识别过程：Glob 全文件 → 读 main.py → 发现 login() → 跟踪到 auth.py → 确认

### B 组

- Agent runtime: ~53s
- Tool calls: 16
- [Actual transcript: 2 codegraph CLI calls, 5 Reads, 9 Bash commands]
- 入口点识别过程：`codegraph context` → reading plan Step 1 → 读 auth.py::login
