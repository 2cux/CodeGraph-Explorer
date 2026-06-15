# 26. Harness 统一执行框架

> 状态：**Phase 7（设计完成，待实现）**
>
> Harness 是 CodeGraph Explorer 的统一执行框架，用于管理所有 workflow 执行、run 状态、产物和日志。

---

## 26.1 定位

Harness 是 workflow / enrich / benchmark / doctor / agent A/B 等所有"可执行任务"的统一运行层。
它提供一致的：

- **Run 生命周期**（创建 → 运行 → 完成/失败 → 记录）
- **产物管理**（input / output / logs / artifacts / checkpoints / report）
- **事件系统**（on_start, on_complete, on_error, on_checkpoint）
- **CLI 入口**（`codegraph harness run <module>`）
- **MCP 工具包装**（MCP 工具透明通过 harness 执行并记录 run）

---

## 26.2 目录结构

### 26.2.1 代码目录

```
backend/codegraph/harness/
  __init__.py
  models.py          # Pydantic 模型：Run, RunState, RunConfig, Checkpoint, Artifact, RunEvent
  manifest.py        # 所有已注册模块的 manifest（名称、描述、版本、状态）
  registry.py        # 模块注册表：按 name 查找模块类
  runner.py          # HarnessRunner — 核心执行引擎（生命周期管理）
  context.py         # RunContext：单次运行的 input / output / working_dir
  store.py           # RunStore：持久化 run state → .codegraph/runs/<run-id>/
  artifacts.py       # ArtifactManager：产物收集和索引
  checkpoints.py     # CheckpointManager：检查点记录（v1 只记录，不阻塞）
  events.py          # EventBus：生命周期事件（on_start / on_complete / on_error / on_checkpoint）
  errors.py          # Harness 专用错误类型
  docs.py            # DocsGenerator：根据 run 产物自动生成 Markdown 文档
  cli.py             # CLI 命令：codegraph harness run|list|status|docs
  mcp_tools.py       # MCP harness wrapper：MCP 工具执行时透明包装为 run
  modules/
    __init__.py
    workflow_impact.py       # 迁移自 workflow.run_pre_edit_check()
    workflow_test_audit.py   # 迁移自 workflow.run_test_audit()
    workflow_explain.py      # 迁移自 workflow.run_explain()
    workflow_find.py         # 迁移自 workflow.run_find()
    enrich_prepare.py        # manifest 预留（enrich prepare）
    enrich_validate.py       # manifest 预留（enrich validate）
    enrich_import.py         # manifest 预留（enrich import）
    benchmark_gate.py        # manifest 预留（benchmark gate）
    doctor_run.py            # manifest 预留（doctor --repair）
    agent_ab_regression.py   # manifest 预留（agent A/B regression）
    mcp_execute.py           # manifest 预留（MCP tool execution wrapper）
```

### 26.2.2 Run 产物目录

每个 run 写入 `.codegraph/runs/<run-id>/`：

```
.codegraph/runs/<run-id>/
  ├── run.json           # Run 元数据（id, module, status, timestamps, input, output summary）
  ├── input.json         # 标准化输入参数（可重放）
  ├── output.json        # 标准化输出结果
  ├── logs/
  │   └── run.log        # 结构化日志（JSON lines）
  ├── artifacts/
  │   └── <module-specific>.json   # 模块特定产物
  ├── checkpoints/
  │   └── cp-<n>.json    # 检查点快照（v1：仅记录，不阻塞）
  └── report.md           # 自动生成的 Markdown 报告
```

---

## 26.3 核心模型

### 26.3.1 Run

```python
class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class Run(BaseModel):
    run_id: str                          # UUID 短格式，如 "r_20260615_a1b2c3d4"
    module: str                          # 模块名，如 "workflow_impact"
    status: RunStatus = RunStatus.PENDING
    created_at: str                      # ISO timestamp
    started_at: str | None = None
    completed_at: str | None = None
    duration_ms: int | None = None
    input: dict[str, Any] | None = None  # 标准化输入参数
    output: dict[str, Any] | None = None # 标准化输出结果
    error: str | None = None             # 失败时的错误信息
    checkpoints: list[Checkpoint] = []
    artifacts: list[Artifact] = []
    tags: list[str] = []                 # 如 ["mcp", "cli", "ci"]
    parent_run_id: str | None = None     # 父 run（用于子任务链）
```

### 26.3.2 RunConfig

```python
class RunConfig(BaseModel):
    module: str                          # 模块名
    log_level: str = "INFO"
    checkpoint_enabled: bool = True      # v1 始终 True
    checkpoint_interval: int = 0         # 0 = 手动 only（v1 不自动 checkpoint）
    artifact_retention_days: int = 30
    max_log_lines: int = 10000
    tags: list[str] = []
```

### 26.3.3 Checkpoint

```python
class Checkpoint(BaseModel):
    checkpoint_id: str                   # "cp-001"
    run_id: str
    sequence: int                        # 序号 1, 2, 3...
    label: str                           # 人类可读标签，如 "symbols resolved"
    recorded_at: str                     # ISO timestamp
    state_snapshot: dict[str, Any]       # 模块定义的快照数据
```

Checkpoint v1 规则：
- 只记录，不阻塞执行
- 模块内部决定何时记录 checkpoint
- 不实现 resume/rerun from checkpoint

### 26.3.4 Artifact

```python
class Artifact(BaseModel):
    artifact_id: str                     # "art-001"
    run_id: str
    name: str                            # 人类可读名称
    path: str                            # 相对于 run 目录的路径
    media_type: str                      # "application/json" | "text/markdown" | "text/plain"
    size_bytes: int
    created_at: str
```

### 26.3.5 RunEvent

```python
class RunEventType(str, Enum):
    RUN_STARTED = "run.started"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    CHECKPOINT_RECORDED = "checkpoint.recorded"
    ARTIFACT_PRODUCED = "artifact.produced"
    LOG_ENTRY = "log.entry"

class RunEvent(BaseModel):
    event_id: str
    run_id: str
    event_type: RunEventType
    timestamp: str                       # ISO
    payload: dict[str, Any] | None = None
```

---

## 26.4 核心组件

### 26.4.1 HarnessRunner（runner.py）

核心执行引擎。管理单个 run 的完整生命周期。

```python
class HarnessRunner:
    """统一执行引擎。管理 run 生命周期、事件、checkpoint 和产物。"""

    def __init__(self, store: RunStore, event_bus: EventBus, config: RunConfig): ...
    def run(self, module_name: str, **input_params) -> Run: ...
    def run_async(self, module_name: str, **input_params) -> Run: ...  # 预留
```

`run()` 生命周期：

1. **validate** — 验证模块名存在、输入参数合法
2. **create** — 创建 Run 实例（status=PENDING），写入 run.json
3. **start** — status=RUNNING，记录 started_at，触发 `run.started` 事件
4. **execute** — 调用模块的 `execute(context)` 方法
5. **checkpoint** — 模块内部可随时调用 `context.checkpoint(label, snapshot)`
6. **collect** — 收集 artifacts
7. **complete/fail** — status=COMPLETED/FAILED，记录 completed_at，触发事件
8. **generate_report** — 调用 DocsGenerator 生成 report.md

### 26.4.2 RunContext（context.py）

单次运行的上下文对象，模块通过它访问 harness 能力。

```python
class RunContext:
    """传递给每个模块的运行时上下文。"""
    run: Run
    config: RunConfig
    run_dir: Path                        # .codegraph/runs/<run-id>/
    store: RunStore
    artifacts: ArtifactManager
    checkpoints: CheckpointManager
    logger: RunLogger

    def checkpoint(self, label: str, snapshot: dict) -> Checkpoint: ...
    def add_artifact(self, name: str, data: bytes | str, media_type: str) -> Artifact: ...
    def log(self, level: str, message: str, **extra) -> None: ...
```

### 26.4.3 RunStore（store.py）

持久化 run 数据到 `.codegraph/runs/<run-id>/`。

```python
class RunStore:
    """管理 .codegraph/runs/ 目录下的 run 持久化。"""
    def __init__(self, cg_dir: Path): ...          # cg_dir = .codegraph/
    def create_run(self, run: Run) -> Path: ...     # 创建 run 目录和 run.json
    def update_run(self, run: Run) -> None: ...     # 更新 run.json
    def load_run(self, run_id: str) -> Run: ...     # 读取 run.json
    def list_runs(self, module: str|None, limit: int) -> list[Run]: ...
    def delete_run(self, run_id: str) -> None: ...
    def prune_runs(self, keep_days: int) -> int: ... # 清理过期 run
```

### 26.4.4 ArtifactManager（artifacts.py）

```python
class ArtifactManager:
    """管理 run 的产物文件。"""
    def __init__(self, run_dir: Path): ...
    def add(self, name: str, data: bytes | str, media_type: str) -> Artifact: ...
    def add_json(self, name: str, data: dict) -> Artifact: ...
    def add_markdown(self, name: str, content: str) -> Artifact: ...
    def list(self) -> list[Artifact]: ...
    def get(self, artifact_id: str) -> Artifact | None: ...
```

### 26.4.5 CheckpointManager（checkpoints.py）

```python
class CheckpointManager:
    """v1：只记录 checkpoint 到磁盘，不阻塞，不实现 resume。"""
    def __init__(self, run_dir: Path): ...
    def record(self, run_id: str, label: str, snapshot: dict) -> Checkpoint: ...
    def list(self) -> list[Checkpoint]: ...
    def get(self, checkpoint_id: str) -> Checkpoint | None: ...
```

### 26.4.6 EventBus（events.py）

```python
class EventBus:
    """同步事件总线。模块可以订阅生命周期事件。"""
    def subscribe(self, event_type: RunEventType, handler: Callable[[RunEvent], None]): ...
    def emit(self, event: RunEvent) -> None: ...
```

### 26.4.7 Registry（registry.py）

```python
class ModuleRegistry:
    """模块注册表。按 name 查找 HarnessModule 子类。"""
    def register(self, module_class: type[HarnessModule]) -> None: ...
    def get(self, name: str) -> type[HarnessModule]: ...
    def list_all(self) -> list[ModuleManifest]: ...
    def discover(self) -> None: ...  # 自动扫描 modules/ 目录
```

### 26.4.8 Manifest（manifest.py）

```python
class ModuleManifest(BaseModel):
    name: str                            # "workflow_impact"
    description: str                     # "Pre-edit impact analysis"
    version: str = "1.0.0"
    status: str = "active"               # "active" | "placeholder"
    category: str                        # "workflow" | "enrich" | "benchmark" | "doctor" | "agent" | "mcp"
    input_schema: dict | None = None     # JSON Schema for input params
    output_schema: dict | None = None    # JSON Schema for output
```

---

## 26.5 模块基类

```python
class HarnessModule(ABC):
    """所有 harness 模块的抽象基类。"""
    manifest: ModuleManifest

    @abstractmethod
    def execute(self, context: RunContext) -> dict[str, Any]:
        """执行模块逻辑，返回标准化输出 dict。"""
        ...
```

---

## 26.6 Phase 1 范围（本轮实现）

### 26.6.1 完全实现（active）

以下 4 个 workflow 模块需要完全实现，每个模块复用现有 `workflow.py` 中的核心逻辑：

| 模块名 | 复用函数 | 原位置 |
|--------|----------|--------|
| `workflow_impact` | `workflow.run_pre_edit_check()` | `backend/codegraph/workflow.py:96` |
| `workflow_test_audit` | `workflow.run_test_audit()` | `backend/codegraph/workflow.py:397` |
| `workflow_explain` | `workflow.run_explain()` | `backend/codegraph/workflow.py:441` |
| `workflow_find` | `workflow.run_find()` | `backend/codegraph/workflow.py:548` |

实现模式（以 `workflow_impact` 为例）：

```python
# modules/workflow_impact.py
from codegraph.harness.models import RunConfig
from codegraph.harness.context import RunContext
from codegraph.harness.registry import HarnessModule, ModuleManifest

class WorkflowImpactModule(HarnessModule):
    manifest = ModuleManifest(
        name="workflow_impact",
        description="Pre-edit impact analysis — analyze what callers, files, and tests are affected by planned edits.",
        version="1.0.0",
        status="active",
        category="workflow",
    )

    def execute(self, context: RunContext) -> dict[str, Any]:
        # 1. 从 context.run.input 获取参数
        # 2. 加载 GraphStore
        # 3. 委托给 workflow.run_pre_edit_check()
        # 4. 记录 checkpoint
        # 5. 添加 artifacts（output.json 等）
        # 6. 返回结果 dict
        ...
```

**关键原则：模块只做编排，所有核心逻辑委托给 `workflow.py` 中已有的函数，不复刻实现。**

### 26.6.2 Manifest 预留（placeholder）

以下模块本轮只创建文件和 manifest，`execute()` 抛出 `NotImplementedError`：

| 模块名 | category | 描述（manifest 中用） |
|--------|----------|----------------------|
| `enrich_prepare` | enrich | Generate bounded enrichment input from index |
| `enrich_validate` | enrich | Validate agent-produced enrichment JSON |
| `enrich_import` | enrich | Import validated enrichment into SQLite |
| `benchmark_gate` | benchmark | Run regression gate checks |
| `doctor_run` | doctor | Run `doctor --repair` to fix index health issues |
| `agent_ab_regression` | agent | Agent A/B regression testing |
| `mcp_execute` | mcp | MCP tool execution wrapper (auto-record runs) |

---

## 26.7 与现有代码的关系

### 26.7.1 复用清单

| 现有文件 | 复用方式 |
|----------|----------|
| `backend/codegraph/workflow.py` | workflow 模块的 `execute()` 直接委托调用 |
| `backend/codegraph/graph/store.py` | 加载 `GraphStore` 传入 workflow 函数 |
| `backend/codegraph/graph/models.py` | 复用 `GraphNode`, `GraphEdge` 等类型 |
| `backend/codegraph/storage/state_store.py` | 参考 `IndexStateStore` 的原子写入模式 |
| `backend/codegraph/reports/writer.py` | 参考 `ReportWriter` 的 Markdown 生成模式 |
| `backend/codegraph/storage/intermediate_store.py` | 参考 `IntermediateStore` 的 batch 文件管理 + prune 模式 |

### 26.7.2 不修改的文件

Phase 1 不修改以下现有文件（避免破坏现有功能）：

- `backend/codegraph/workflow.py` — 保持不变，harness 模块只调用它
- `backend/codegraph/mcp_server.py` — 保持不变，MCP 工具继续直接调用
- `backend/codegraph/cli/main.py` — 保持不变，现有 CLI 继续工作

Harness 的 CLI 命令（`codegraph harness ...`）作为**新命令**添加到 CLI，不影响现有命令。

---

## 26.8 CLI 接口

```bash
# 列出所有已注册模块
codegraph harness list

# 查看模块详情
codegraph harness info workflow_impact

# 执行一个 run
codegraph harness run workflow_impact \
  --files "src/server.py,src/auth.py" \
  --change-type refactor

# 查看 run 状态
codegraph harness status <run-id>

# 列出最近 runs
codegraph harness runs --module workflow_impact --limit 10

# 生成 run 的 Markdown 文档
codegraph harness docs <run-id>

# 清理过期 runs
codegraph harness prune --keep-days 30
```

---

## 26.9 MCP 集成（未来）

未来 MCP 工具可透明通过 harness 执行：

```python
# mcp_tools.py（Phase 2+）
def mcp_wrapped_tool(tool_name: str, harness_runner: HarnessRunner, **params):
    run = harness_runner.run(f"mcp_{tool_name}", source="mcp", **params)
    return run.output
```

本轮不实现此功能，仅预留接口。

---

## 26.10 设计原则

1. **复用优先** — 所有核心逻辑委托给现有函数，harness 只做编排
2. **不破坏现有** — Phase 1 不改 workflow.py、mcp_server.py 等现有文件
3. **Pydantic v2** — 所有模型使用 `BaseModel`，`model_validate` 构造
4. **原子写入** — 所有持久化使用 temp file + `os.replace()`
5. **类型注解** — 所有函数带完整类型注解
6. **checkpoint v1 最小化** — 只记录，不阻塞，不 resume
7. **日志结构化** — JSON lines 格式，方便工具解析
8. **CLI 优先** — Phase 1 CLI 是主入口，MCP 集成留到 Phase 2+

---

## 26.11 实现边界

### 本轮做

- Python 后端代码（harness/ 全部文件）
- Pydantic 模型定义
- HarnessRunner + RunContext + RunStore
- EventBus + CheckpointManager + ArtifactManager
- 4 个 active workflow 模块（委托给 workflow.py）
- 7 个 placeholder 模块（manifest only）
- CLI 命令（`codegraph harness ...`）
- DocsGenerator（从 run 生成 report.md）
- pytest 测试

### 本轮不做

- 前端 / dashboard
- SaaS / 多用户
- 外部 LLM API 调用
- ProviderRegistry
- 复杂任务队列
- 人工阻塞 checkpoint
- enrichment 深度实现
- benchmark 深度重构
- doctor 深度重构
- 任意 shell 执行器
- MCP 工具自动包装（mcp_execute 只做 manifest）
- run 的 resume/rerun 能力
