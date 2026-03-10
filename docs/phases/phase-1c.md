# Phase 1C: 开发机器人 — 需求驱动开发工作流

**分支**: `feat/phase-1c-requirement-workflow`
**Tag**: `v0.3.0`
**前置**: Phase 1B 完成（v0.2.0）
**目标**: Owner 在 cui 中与 Claude Code 协作产出 phase-N.md（需求澄清+任务分解）→ Owner 确认后 CLI 调用平台 API → PhaseFileParser 解析 markdown 为 TaskPlan JSON → dev_bot 逐个独立执行子任务（每个=全新 CLI 上下文）→ 每完成一个回写 markdown `[x]` → 全部完成后创建 PR。
**预计时长**: 2 周

**完成条件**: Owner 在 cui 中与 Claude Code 对话完成需求澄清和任务分解，产出符合规范的 phase-N.md → Owner 说"提交执行" → CLI 调用 `POST /api/requirements/from-phase` → 平台解析 markdown → 子任务逐个独立执行 → 每个子任务完成后回写 phase-N.md 标 `[x]` + 自动 commit → 全部完成后创建 PR → ntfy 通知 Owner

---

## 与 Phase 1B 的关系

| 模式 | 触发方式 | 输入格式 | 执行方式 | Phase |
|------|---------|---------|---------|-------|
| **快速修复模式 (Mode B)** | GitHub Issue（自动） | Issue 标题+内容 | 单次 Claude CLI 调用 | 1B（不变） |
| **需求开发模式 (Mode C)** | Owner 在 cui 中说"提交执行" | phase-N.md 文件 | PhaseFileParser → 多次独立 CLI 调用 | 1C（新增） |

Phase 1B 代码完全保留，Phase 1C 是独立的新代码路径。共享工具层（claude_code_cli/sdk、git_tool、notifier）。

---

## 核心架构：Markdown-First + JSON Runtime

```
┌─────────────────────────────────────────────┐
│  Human Layer（人编辑、人可读）                 │
│                                             │
│  Source of Truth: docs/phases/phase-N.md    │
│  编辑者: Owner + Claude Code (在 cui 中)     │
│  格式: 与本项目 phase-1a/1b 完全一致的 md    │
└─────────────────────┬───────────────────────┘
                      │ PhaseFileParser（regex 解析）
                      ↓
┌─────────────────────▼───────────────────────┐
│  Machine Layer（程序读写、运行时状态）          │
│                                             │
│  Runtime State: TaskPlan JSON               │
│  存储: data/agents/dev_bot/workspace/       │
│        task_plans/<plan_id>.json            │
│  读写者: dev_bot (task_executor)            │
│  额外字段: result_summary, checkpoint_sha,  │
│           duration_ms, attempt_count 等     │
└─────────────────────────────────────────────┘
```

**关键原则**：
- phase-N.md 是 **Source of Truth**（人负责写、改、审）
- TaskPlan JSON 是 **Runtime State**（机器执行时生成，丢了可以从 md 重新解析）
- 每个子任务完成后 **双写**：更新 JSON + 回写 md `[ ]` → `[x]`

---

## 工作流概览

```
┌─────────────────────────────────────────────────────────┐
│ 阶段 0: 项目初始化（可选，仅新项目首次）                    │
│                                                         │
│  CLI 根据 config/templates/phase-template.md 生成        │
│  phase-N.md 骨架 + CLAUDE.md，Owner 在 cui 中继续补充    │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌───────────────────────▼─────────────────────────────────┐
│ 阶段 1: 需求澄清与任务分解（人机协作，Owner ↔ CLI 在 cui） │
│                                                         │
│  Owner: "我想给平台加一个 Telegram 渠道适配器"              │
│  Claude: "我需要确认几个问题：1) ... 2) ... 3) ..."        │
│  Owner: "1) xxx  2) xxx  3) xxx"                        │
│  Claude: "明白了。我把任务写入 phase 文件..."              │
│  → CLI 写入/更新 docs/phases/phase-N.md                  │
│  Owner: "确认，提交执行"                                   │
│  → CLI 调用 POST /api/requirements/from-phase            │
│                                                         │
│  ※ 需求澄清和任务分解是 Owner 和 CLI 在同一个对话流中      │
│    自然完成的。CLI 直接写文件，格式与本项目 phase-1a/1b    │
│    完全一致。Owner 确认后 CLI 调 API 触发执行。            │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌───────────────────────▼─────────────────────────────────┐
│ 阶段 2: 多任务串行执行（自动，后台运行）                    │
│                                                         │
│  PhaseFileParser 解析 phase-N.md → TaskPlan JSON         │
│                                                         │
│  for task in topological_sort(plan.tasks):              │
│      if task.status == "done": continue                 │
│      1. git status 检查（确保干净状态）                     │
│      2. 构建 prompt（任务描述 + 前序结果摘要）              │
│         ※ prompt 包含 "不要执行 Session Recovery" 覆盖    │
│      3. 全新 Claude CLI 会话执行                          │
│      4. Smart checkpoint（只在有未提交变更时 commit）       │
│      5. 回写 phase-N.md：该任务 [ ] → [x]               │
│      6. 更新 TaskPlan JSON（结果摘要、SHA 等）             │
│  失败时自动暂停，ntfy 通知 Owner                           │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌───────────────────────▼─────────────────────────────────┐
│ 阶段 3: 结果确认（Owner 审查 + PR 创建）                   │
│                                                         │
│  展示执行摘要（文件变更、测试结果）                         │
│  Owner 确认 → 创建 PR                                    │
│  或 Owner 回滚/继续修改                                   │
└─────────────────────────────────────────────────────────┘
```

**关键设计决策**：
1. **阶段 1 是人驱动的** — 平台不介入需求澄清和任务分解，这是 Owner 与 CLI 在 cui 中的人机协作
2. **CLI 写文件，平台读文件** — CLI 负责产出 phase-N.md，平台负责解析和执行
3. **Markdown 是 Source of Truth** — JSON 只是运行时状态，可以从 md 重建
4. **每个子任务=全新 CLI 上下文** — 解决上下文膨胀问题
5. **Smart Checkpoint** — 检查 `git status --porcelain`，CLI 可能已经 commit 了
6. **Session Recovery 覆盖** — prompt 中注入"不要执行 CLAUDE.md Session Recovery，直接做当前任务"

---

## 测试策略：三层验收

> **核心问题**：Phase 1C 的执行引擎依赖真实的 Claude CLI 进程和 git 仓库，开发过程中无法做真正的端到端测试。因此采用三层验收策略：

| 层级 | 范围 | 执行时机 | 外部依赖 | 可信度 |
|------|------|---------|---------|--------|
| **L1: 纯逻辑单元测试** | 数据结构、序列化、状态机、拓扑排序、PhaseFileParser、配置、错误类型 | 每个任务完成后立即运行 | 无 | 高 — 测什么就是什么 |
| **L2: Mock 集成测试** | TaskExecutor、DevAgent、API 端点的完整流程，但 Claude CLI 和 git 操作全部 mock | Task 1C.11 完成后运行 | 无（全 mock） | 中 — 验证组装逻辑，但 mock 通过 ≠ 真的能跑 |
| **L3: 真实端到端验收** | 真实 CLI 进程 + 真实 git repo + 真实 API 调用，执行一个包含 2-3 个简单任务的测试 phase 文件 | Task 1C.12 — 所有代码完成后，由 Owner 触发 | Claude CLI + API Key + 测试仓库 | 高 — 最终验收，确认真实可用 |

**开发过程的验收规则**：
- Task 1C.1 ~ 1C.2（纯逻辑）：L1 通过即可标 `[x]`
- Task 1C.3 ~ 1C.7（含 CLI/git 交互）：L1 + L2 通过即可标 `[x]`，但需在验收标准中**明确标注哪些是 mock**
- Task 1C.12（真实 E2E）：L3 通过才能标 `[x]`，这是整个 Phase 的最终验收门槛

**Mock 边界约定**（所有 L2 测试统一遵守）：

| 真实组件 | Mock 对象 | Mock 行为 |
|---------|----------|----------|
| `claude_code_cli.execute()` | `AsyncMock` | 返回 `{"success": True, "output": "模拟输出..."}` |
| `claude_code_sdk.execute()` | `AsyncMock` | 同上 |
| `git status --porcelain` | `subprocess mock` | 返回空字符串（干净状态） |
| `git add / commit / diff` | `subprocess mock` | 返回成功 + 模拟 SHA |
| `git checkout / clean` | `subprocess mock` | 返回成功 |
| `notifier.send()` | `AsyncMock` | 记录调用参数，不实际发送 |
| `LLM 摘要生成` | `AsyncMock` | 返回固定摘要文本 |

---

## 1C.1 — 数据模型与持久化

### Task 1C.1: 实现 core/task_planner.py — 数据结构与持久化

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `core/task_planner.py`, `tests/unit/test_task_planner.py`

**描述**:
定义 TaskPlan 和 SubTask 数据结构，实现 JSON 文件持久化。这是 Phase 1C 的基础数据层，SubTask 对应 phase-N.md 中的一个 `### Task` 块。

**数据结构定义**:

```python
@dataclass
class SubTask:
    task_id: str                    # "1C.3" — 与 phase-N.md 中的 Task ID 一致
    title: str                      # 简短标题（从 md 解析）
    description: str                # 详细描述（从 md 解析，含验收标准）
    status: str                     # pending | in_progress | completed | failed | skipped
    depends_on: list[str]           # 依赖的 task_id 列表（从 md **依赖** 字段解析）
    output_files: list[str]         # 产出文件列表（从 md **产出文件** 字段解析）
    validation_command: str | None  # 验证命令（从 md **测试命令** 代码块解析）
    result_summary: str             # 执行后的结果摘要（LLM 生成，运行时字段）
    checkpoint_sha: str             # 完成后的 git commit SHA（运行时字段）
    attempt_count: int              # 已尝试次数（运行时字段）
    max_attempts: int               # 最大重试次数（默认 2）
    files_changed: list[str]        # 变更的文件列表（git diff 获取，运行时字段）
    duration_ms: int                # 执行耗时（运行时字段）

@dataclass
class TaskPlan:
    plan_id: str                    # UUID
    phase_file: str                 # 源 phase-N.md 文件路径
    source: str                     # "cui" | "github_issue"
    source_ref: str                 # 会话 ID 或 Issue URL
    status: str                     # executing | paused | completed | failed | aborted
    tasks: list[SubTask]            # 有序子任务列表（从 md 解析）
    branch: str                     # feature 分支名
    base_branch: str                # 基准分支（默认 main）
    repo_path: str                  # 工作仓库路径
    created_at: float
    updated_at: float
    completed_count: int            # 已完成任务数（计算字段）
    total_count: int                # 总任务数（计算字段）
```

> **注意**：没有 `draft` / `approved` 状态。Owner 在 cui 中确认后才调 API，提交即执行。

**TaskPlanStore 接口**:
```python
class TaskPlanStore:
    def __init__(self, base_dir: str = "data/agents/dev_bot/workspace/task_plans/")
    def save(self, plan: TaskPlan) -> None         # 保存/更新
    def load(self, plan_id: str) -> TaskPlan | None
    def list_active(self) -> list[TaskPlan]        # status != completed/failed/aborted
    def delete(self, plan_id: str) -> None
```

**验收标准**（全部 L1 — 纯逻辑，无外部依赖）:
- [ ] `SubTask` 和 `TaskPlan` dataclass 定义完整，支持 JSON 序列化/反序列化
- [ ] `TaskPlanStore` 实现 CRUD，数据存储在 `data/agents/dev_bot/workspace/task_plans/<plan_id>.json`
- [ ] 状态机转换合法性校验（如 `pending` 只能转 `in_progress`，不能直接转 `completed`）
- [ ] `topological_sort(tasks)` 函数：按 `depends_on` 拓扑排序，检测循环依赖抛出异常
- [ ] 使用 `get_logger(__name__)` 日志

**测试命令**:
```bash
uv run pytest tests/unit/test_task_planner.py -v
```

**测试用例**（L1）:
- test_subtask_serialization — SubTask JSON 序列化/反序列化
- test_taskplan_serialization — TaskPlan JSON 序列化/反序列化
- test_taskplan_store_crud — 保存、加载、列出、删除
- test_status_transition_valid — 合法状态转换
- test_status_transition_invalid — 非法状态转换抛异常
- test_topological_sort_linear — 线性依赖排序
- test_topological_sort_parallel — 无依赖任务保持原序
- test_topological_sort_cycle — 循环依赖检测

---

### Task 1C.2: 实现 core/phase_parser.py — PhaseFileParser

**状态**: [ ] 未开始
**依赖**: Task 1C.1
**产出文件**: `core/phase_parser.py`, `tests/unit/test_phase_parser.py`

**描述**:
解析 phase-N.md 文件为 TaskPlan JSON 的核心模块（~120 行）。使用 regex 解析（格式高度一致，无需 AST 库）。同时提供回写功能：子任务完成后将 `[ ]` → `[x]` 写回 markdown。

**解析目标格式**（与 phase-1a/1b/1c 完全一致）:
```markdown
### Task {ID}: {TITLE}

**状态**: [ ] 未开始  /  [x] 完成
**依赖**: Task 1C.1, Task 1C.2  /  无
**产出文件**: `file1.py`, `file2.py`

**描述**:
多行描述文本...

**验收标准**:
- [ ] 标准 1
- [ ] 标准 2

**测试命令**:
```bash
uv run pytest tests/unit/test_xxx.py -v
```
```

**核心接口**:
```python
@dataclass
class PhaseTask:
    """从 markdown 解析出的原始任务数据"""
    task_id: str            # "1C.3"
    title: str              # "实现 core/task_executor.py — 核心执行逻辑"
    status: str             # "x" or " " (from checkbox)
    depends_on: list[str]   # ["1C.1", "1C.2"]
    output_files: list[str] # ["core/task_executor.py", "tests/..."]
    description: str        # 完整描述文本（含验收标准）
    validation_command: str | None  # 测试命令代码块内容
    line_start: int         # 在文件中的起始行号（用于回写）

def parse_phase_file(content: str) -> list[PhaseTask]:
    """解析 phase-N.md 内容，返回任务列表"""

def parse_phase_file_safe(file_path: str) -> tuple[list[PhaseTask], list[str]]:
    """安全版本：返回 (tasks, errors)，部分解析失败不影响其他任务"""

def update_task_status(file_path: str, task_id: str, new_status: str = "x") -> bool:
    """回写：将指定任务的 [ ] → [x]（或反向），返回是否成功"""

def phase_tasks_to_subtasks(tasks: list[PhaseTask]) -> list[SubTask]:
    """PhaseTask → SubTask 转换（补充运行时字段默认值）"""
```

**Regex 模式**:
```python
_TASK_HEADER = re.compile(r'^### Task ([\w.]+):\s*(.+)', re.MULTILINE)
_STATUS = re.compile(r'^\*\*状态\*\*:\s*\[([ x])\]', re.MULTILINE)
_DEPENDS = re.compile(r'^\*\*依赖\*\*:\s*(.+)', re.MULTILINE)
_OUTPUT = re.compile(r'^\*\*产出文件\*\*:\s*(.+)', re.MULTILINE)
_TEST_CMD = re.compile(r'```bash\n(.*?)```', re.DOTALL)
```

**验收标准**（全部 L1 — 用真实 phase 文件做输入，无需 mock）:
- [ ] `parse_phase_file()` 正确解析 phase-1a.md（28 个任务）和 phase-1b.md（15 个任务）
- [ ] 解析结果包含 task_id、title、status、depends_on、output_files、description、validation_command
- [ ] `parse_phase_file_safe()` 部分解析失败时返回错误列表，不中断
- [ ] `update_task_status()` 回写 `[ ]` → `[x]` 后，re-parse 结果正确（用 tmp_path 副本测试，不改真实文件）
- [ ] `phase_tasks_to_subtasks()` 将已完成任务（`[x]`）映射为 `status="completed"`
- [ ] 模块不超过 150 行，无外部依赖（只用 re + dataclasses）

**测试命令**:
```bash
uv run pytest tests/unit/test_phase_parser.py -v
```

**测试用例**（L1 — 直接用项目真实 phase 文件验证，可信度高）:
- test_parse_phase_1a — 解析 phase-1a.md，验证 28 个任务
- test_parse_phase_1b — 解析 phase-1b.md，验证 15 个任务
- test_parse_task_fields — 验证单个任务所有字段解析正确
- test_parse_depends_on — 依赖字段解析（多个依赖、"无"）
- test_parse_output_files — 产出文件解析（反引号包裹的路径）
- test_parse_status_done — 已完成任务 `[x]` 解析
- test_parse_status_pending — 未完成任务 `[ ]` 解析
- test_parse_safe_partial_failure — 部分任务格式错误不中断
- test_update_task_status — 回写 `[ ]` → `[x]`（tmp_path 副本）
- test_update_task_status_idempotent — 已完成任务再次回写无变化
- test_phase_tasks_to_subtasks — PhaseTask → SubTask 转换

---

## 1C.2 — 多任务执行引擎

### Task 1C.3: 实现 core/task_executor.py — 核心执行逻辑

**状态**: [ ] 未开始
**依赖**: Task 1C.1, Task 1C.2
**产出文件**: `core/task_executor.py`, `tests/unit/test_task_executor.py`

**描述**:
多任务串行执行引擎。按拓扑序逐个执行子任务，每个子任务使用全新 Claude CLI 上下文。执行前检查 git 状态，执行后 smart checkpoint + 回写 markdown。

**核心类接口**:
```python
class TaskExecutor:
    def __init__(
        self,
        tool_registry: ToolRegistry,
        notifier: Notifier,
        config: dict,            # task_planning 配置节
    )

    async def execute_plan(self, plan: TaskPlan) -> TaskPlan:
        """按拓扑序逐个执行子任务，返回更新后的 plan"""

    async def execute_subtask(self, subtask: SubTask, plan: TaskPlan) -> SubTask:
        """执行单个子任务（含安全包装）"""

    def build_task_prompt(self, subtask: SubTask, plan: TaskPlan) -> str:
        """构建子任务 prompt：任务描述 + 前序摘要 + Session Recovery 覆盖"""

    async def generate_result_summary(self, raw_output: str, runtime: AgentRuntime) -> str:
        """用 LLM 从 CLI 输出中提取精炼结果摘要"""
```

**执行安全包装**（每个子任务）:
1. **前置检查**: `git status --porcelain` 必须为空（干净状态）
2. **记录起点**: `checkpoint_sha = git rev-parse HEAD`
3. **执行**: 调用 claude_code_cli/sdk，带子任务级超时
4. **Smart Checkpoint**: 检查 `git status --porcelain`，只在有未提交变更时 `git add -A && git commit`
5. **回写 Markdown**: 调用 `update_task_status(phase_file, task_id, "x")`
6. **持久化 JSON**: 更新 TaskPlan 并 save
7. **失败后**: `git checkout -- . && git clean -fd` 清理未提交变更

**Prompt 构建策略**:
```
## 重要：不要执行 CLAUDE.md 的 Session Recovery 流程
直接执行下面的任务，不需要读取 progress.md 或查找 [ ] 任务。

## 任务：{title}

{description}

## 前置任务完成情况
- Task 1C.1 "xxx": {result_summary}
- Task 1C.2 "xxx": {result_summary}

## 需要关注的文件
- {output_files}

## 注意事项
- 工作目录：{repo_path}
- 不要重复已完成的工作，代码已在 git 中
- 完成后运行：{validation_command}
- 禁止修改 .env、credentials 等敏感文件
```

**验收标准**（L1 + L2 混合，标注 mock 边界）:
- [ ] `execute_plan()` 按拓扑序串行执行所有子任务，跳过 `status == "completed"` 的
- [ ] 每个子任务使用全新 Claude CLI/SDK 会话（调用 `tool.execute()`）— **L2: mock CLI 返回成功**
- [ ] 执行前 `git status --porcelain` 检查，非空则抛异常 — **L2: mock subprocess**
- [ ] Smart Checkpoint：只在有未提交变更时 commit — **L2: mock git status 返回空/非空两种情况**
- [ ] 执行成功后调用 `update_task_status()` 回写 phase-N.md `[x]` — **L1: 用 tmp_path 真实文件验证**
- [ ] 执行失败后自动 `git checkout -- . && git clean -fd` 清理 — **L2: mock，验证调用参数**
- [ ] `build_task_prompt()` 包含 Session Recovery 覆盖指令 + 前序任务摘要 — **L1: 纯字符串断言**
- [ ] `generate_result_summary()` 通过 LLM 从 CLI 输出生成精炼摘要 — **L2: mock LLM**
- [ ] 每个子任务完成后持久化 plan 状态（防止中途崩溃丢失进度） — **L1: 检查 JSON 文件存在**

> **L3 验证点**（延迟到 Task 1C.12 真实 E2E 时验收）：
> - CLI 进程是否真的被正确启动和等待
> - Smart Checkpoint 在真实 git repo 中的行为
> - markdown 回写后 re-parse 结果是否一致

**测试命令**:
```bash
uv run pytest tests/unit/test_task_executor.py -v
```

**测试用例**（L1 标注纯逻辑，L2 标注需 mock）:
- test_execute_plan_all_success — **L2**: 3 个任务全部成功（mock CLI）
- test_execute_plan_skip_completed — **L2**: 跳过已完成的任务
- test_execute_plan_with_dependencies — **L2**: 按依赖顺序执行
- test_execute_subtask_success — **L2**: 单个子任务成功 + smart checkpoint（mock CLI + git）
- test_execute_subtask_cli_already_committed — **L2**: CLI 已 commit，不重复 commit（mock git status 返回空）
- test_execute_subtask_failure_cleanup — **L2**: 失败后 git 清理（mock CLI 返回失败 + mock git checkout）
- test_dirty_git_state_rejected — **L2**: 脏 git 状态拒绝执行（mock git status 返回非空）
- test_build_task_prompt_with_summaries — **L1**: prompt 包含前序摘要（纯字符串断言）
- test_build_task_prompt_session_recovery_override — **L1**: prompt 包含 Session Recovery 覆盖
- test_result_summary_generation — **L2**: LLM 摘要生成（mock LLM）
- test_plan_persisted_after_each_task — **L1**: 每个子任务后 JSON 文件已更新
- test_markdown_writeback_after_success — **L1**: 成功后 tmp_path 中 phase-N.md 标记 [x]

---

### Task 1C.4: 实现 core/task_executor.py — 失败处理与控制机制

**状态**: [ ] 未开始
**依赖**: Task 1C.3
**产出文件**: `core/task_executor.py` 扩展

**描述**:
实现子任务失败暂停、重试、跳过、终止、紧急停止等控制机制。

**失败处理策略**:
- 子任务失败 → 自动暂停后续任务 → plan.status = "paused" → ntfy 通知 Owner
- 连续 2 个子任务失败 → 自动终止 → plan.status = "failed" → ntfy 高优先级通知
- 子任务超时（默认 15min）→ kill 进程组 → 标记 failed → 暂停

**Owner 控制接口**:
```python
async def retry_subtask(self, plan: TaskPlan, task_id: str) -> TaskPlan:
    """重试失败的子任务"""

async def retry_subtask_with_feedback(
    self, plan: TaskPlan, task_id: str, feedback: str
) -> TaskPlan:
    """修改描述后重试（feedback 追加到 prompt）"""

async def skip_subtask(self, plan: TaskPlan, task_id: str) -> TaskPlan:
    """跳过子任务（检查是否有后续任务依赖它，警告 Owner）"""

async def abort_plan(self, plan: TaskPlan) -> TaskPlan:
    """终止整个计划，保留已完成的 checkpoints"""

async def stop_current(self) -> None:
    """紧急停止：kill 当前执行中的 CLI 进程组"""
```

**进程组 Kill**:
```python
# 替代 process.kill()，确保子进程树被清理
os.killpg(os.getpgid(process.pid), signal.SIGTERM)
```

**验收标准**（L1 + L2 混合）:
- [ ] 子任务失败后 plan.status 变为 "paused"，后续任务不执行 — **L2: mock CLI 返回失败**
- [ ] 连续 2 个子任务失败后 plan.status 变为 "failed" — **L2: mock CLI 连续返回失败**
- [ ] 子任务超时后进程组被 kill（`os.killpg`）— **L2: mock process + mock os.killpg，验证调用**
- [ ] `retry_subtask()` 重置 task.status 为 pending 并重新执行 — **L1: 状态断言 + L2: mock CLI**
- [ ] `retry_subtask_with_feedback()` 将 feedback 追加到 task.description — **L1: 纯数据断言**
- [ ] `skip_subtask()` 标记 skipped，如有后续任务依赖则返回警告列表 — **L1: 纯逻辑**
- [ ] `abort_plan()` kill 当前进程 + 标记 aborted + 保留 checkpoints — **L2: mock process**
- [ ] `stop_current()` 立即 kill 进程组 + 持久化当前状态 — **L2: mock os.killpg**
- [ ] 所有失败/暂停/终止操作都发送 ntfy 通知 — **L2: mock notifier，验证调用参数**

> **L3 验证点**（延迟到 Task 1C.12）：
> - `os.killpg` 是否真正终止了 CLI 进程树
> - 超时后 git 清理是否恢复干净状态

**测试命令**:
```bash
uv run pytest tests/unit/test_task_executor.py -v -k "test_failure"
```

**测试用例**（全部 L2 — mock CLI/git/notifier）:
- test_failure_pauses_plan — 单个失败暂停后续
- test_consecutive_failures_abort — 连续 2 个失败终止
- test_subtask_timeout — 超时 kill + 暂停（mock os.killpg）
- test_retry_subtask — 重试成功
- test_retry_with_feedback — 带反馈重试
- test_skip_subtask_no_dependents — 无依赖者，跳过成功（L1 纯逻辑）
- test_skip_subtask_with_dependents — 有依赖者，返回警告（L1 纯逻辑）
- test_abort_plan — 终止保留 checkpoints
- test_stop_current_kills_process_group — 紧急停止 kill 进程组（mock os.killpg）

---

### Task 1C.5: 敏感文件保护与变更检测

**状态**: [ ] 未开始
**依赖**: Task 1C.3
**产出文件**: `core/task_executor.py` 扩展

**描述**:
每个子任务完成后检查 git diff，如果涉及敏感文件模式则自动回滚该子任务并通知 Owner。

**敏感文件模式**（可配置）:
```yaml
# config/platform.yaml
task_planning:
  sensitive_patterns:
    - ".env*"
    - "*credential*"
    - "*secret*"
    - "*.key"
    - "*.pem"
    - "*token*"
```

**验收标准**（L1 + L2 混合）:
- [ ] 子任务 commit 后运行 `git diff --name-only HEAD~1` 获取变更文件列表 — **L2: mock git diff 返回文件列表**
- [ ] 变更文件与 `sensitive_patterns` 匹配时自动 `git reset --hard HEAD~1` 回滚 — **L2: mock git reset，验证调用**
- [ ] 回滚后 ntfy 通知 Owner — **L2: mock notifier**
- [ ] 回滚后同时撤销 phase-N.md 的 `[x]` 回写 — **L1: 用 tmp_path 真实文件验证**
- [ ] 敏感文件模式从 `config/platform.yaml` 读取，支持自定义 — **L1: 纯配置读取**
- [ ] `fnmatch` 模式匹配逻辑正确 — **L1: 纯逻辑，测试各种文件名 vs 模式**
- [ ] 记录到审计日志 — **L2: mock audit**

**测试命令**:
```bash
uv run pytest tests/unit/test_task_executor.py -v -k "test_sensitive"
```

**测试用例**:
- test_sensitive_file_detected — **L1**: `.env` / `credentials.json` / `secret.key` 匹配检测
- test_sensitive_file_rollback — **L2**: mock git reset + 验证 markdown 回写撤销（tmp_path）
- test_no_sensitive_file — **L1**: `src/main.py` 等正常文件不触发
- test_custom_sensitive_patterns — **L1**: 自定义模式匹配

---

## 1C.3 — DevAgent 集成与 API

### Task 1C.6: 扩展 agents/dev_agent.py — 需求开发模式入口

**状态**: [ ] 未开始
**依赖**: Task 1C.2, Task 1C.4
**产出文件**: `agents/dev_agent.py` 扩展

**描述**:
在 DevAgent 中新增需求开发模式的入口方法。核心逻辑：接收 phase-N.md 路径 → PhaseFileParser 解析 → TaskPlan → execute_plan()。

**新增方法**:
```python
class DevAgent(BaseAgent):
    # ... Phase 1B 方法保持不变 ...

    async def execute_from_phase(
        self, phase_file: str, repo_path: str, source: str = "cui",
    ) -> TaskPlan:
        """
        接收 phase-N.md 路径，解析为 TaskPlan 并开始执行。
        1. parse_phase_file_safe() 解析 markdown
        2. 过滤出未完成任务（[ ]）
        3. phase_tasks_to_subtasks() 转换
        4. 创建 TaskPlan + feature 分支
        5. 启动 execute_plan()（后台）
        6. ntfy 通知 Owner
        """

    async def get_plan_status(self, plan_id: str) -> TaskPlan | None:
        """查询执行进度"""

    async def retry_task(self, plan_id: str, task_id: str, feedback: str = "") -> TaskPlan:
        """重试失败的子任务"""

    async def skip_task(self, plan_id: str, task_id: str) -> TaskPlan:
        """跳过子任务"""

    async def abort_plan(self, plan_id: str) -> TaskPlan:
        """终止计划"""
```

**验收标准**（L1 + L2 混合）:
- [ ] `execute_from_phase()` 解析 phase-N.md（**L1: 用真实 parser**），过滤未完成任务，创建 feature 分支（**L2: mock git**），启动 `execute_plan()`（**L2: mock executor**）
- [ ] 已完成任务（`[x]`）自动跳过（支持断点续跑）— **L1: 用 tmp_path phase 文件，部分标 [x]**
- [ ] Phase 1B 的 `handle_issue()` 和 `execute_issue()` 完全不变 — **L1: 导入检查 + 方法签名断言**
- [ ] DevAgent 文件不超过 500 行（核心逻辑在 core/ 模块中）— **L1: 行数断言**
- [ ] 所有方法使用 `get_logger(__name__)` + trace_id

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v -k "test_from_phase"
```

**测试用例**:
- test_execute_from_phase — **L2**: 解析 md + mock 创建分支 + mock 启动执行
- test_execute_from_phase_resume — **L1+L2**: 部分完成的 md（tmp_path），验证只传未完成任务给 executor
- test_execute_from_phase_parse_error — **L1**: 格式错误的 md 返回错误
- test_get_plan_status — **L1**: 从 TaskPlanStore 读取
- test_retry_task — **L2**: mock executor.retry_subtask
- test_skip_task — **L2**: mock executor.skip_subtask
- test_abort_plan — **L2**: mock executor.abort_plan
- test_phase1b_unchanged — **L1**: 确认 Issue 流程方法签名不变

---

### Task 1C.7: 实现 API 端点 — 需求开发接口

**状态**: [ ] 未开始
**依赖**: Task 1C.6
**产出文件**: `main.py` 扩展

**描述**:
新增 REST API 端点供 cui 中的 CLI 调用。核心端点是 `POST /api/requirements/from-phase`。

**新增端点**:
```
POST   /api/requirements/from-phase           → 解析 phase-N.md 并开始执行
       Body: { "phase_file": "docs/phases/phase-1.md", "repo_path": "/path/to/repo" }
GET    /api/requirements/{id}                 → 查询 plan 状态和进度
POST   /api/requirements/{id}/abort           → 终止计划
POST   /api/requirements/{id}/tasks/{tid}/retry  → 重试子任务（可选 feedback 参数）
POST   /api/requirements/{id}/tasks/{tid}/skip   → 跳过子任务
DELETE /api/requirements/{id}                 → 删除计划记录
```

> **注意**：没有 `/approve` 端点。Owner 在 cui 对话中确认后，CLI 直接调 `from-phase`，提交即执行。

**验收标准**（全部 L2 — 使用 FastAPI TestClient + mock DevAgent）:
- [ ] 所有端点注册到 FastAPI app — **L1: TestClient 路由检查**
- [ ] 请求/响应使用 Pydantic model 校验 — **L2: TestClient 发送非法 body 返回 422**
- [ ] `from-phase` 端点校验文件存在性和可读性 — **L2: TestClient + tmp_path**
- [ ] 每个请求生成 trace_id — **L2: 检查响应头或日志**
- [ ] 错误返回标准 JSON（status_code + error message）— **L2: TestClient**
- [ ] `/health` 端点扩展包含活跃 plan 数量 — **L2: mock TaskPlanStore**

**测试命令**:
```bash
uv run pytest tests/unit/test_requirement_api.py -v
```

**测试用例**（全部 L2 — FastAPI TestClient + mock DevAgent）:
- test_submit_from_phase — POST phase 文件路径（tmp_path 真实文件），mock DevAgent 执行
- test_submit_from_phase_file_not_found — 文件不存在返回 404
- test_submit_from_phase_parse_error — 格式错误文件返回 400
- test_get_plan_status — GET 返回进度（mock TaskPlanStore）
- test_abort_plan — POST abort 终止（mock DevAgent）
- test_retry_task — POST retry 重试（mock DevAgent）
- test_skip_task — POST skip 跳过（mock DevAgent）
- test_not_found — 不存在的 plan_id 返回 404

---

## 1C.4 — 模板与配置

### Task 1C.8: Phase 文件模板与 CLAUDE.md 扩展

**状态**: [ ] 未开始
**依赖**: Task 1C.2
**产出文件**: `config/templates/phase-template.md`, `config/templates/claude-md-section.md`

**描述**:
提供 phase-N.md 模板文件，供 CLI 在新项目初始化时使用。同时提供 CLAUDE.md 扩展模板，让 CLI 知道如何写 phase 文件和调用平台 API。

**phase-template.md 内容**:
```markdown
# Phase N: {PHASE_TITLE}

**分支**: `feat/{branch-name}`
**前置**: {前置条件}
**目标**: {一句话目标}

---

## {GROUP_TITLE}

### Task {N.1}: {TASK_TITLE}

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `{file1}`, `{file2}`

**描述**:
{详细描述}

**验收标准**:
- [ ] {标准 1}
- [ ] {标准 2}

**测试命令**:
```bash
{测试命令}
```
```

**claude-md-section.md 内容**（CLI 在 CLAUDE.md 中追加此节）:
```markdown
# 10. Task Plan — 需求开发模式 (Phase 1C)

当 Owner 在 cui 中与你完成需求澄清和任务分解后：
1. 将任务写入 `docs/phases/phase-N.md`，格式参考 `config/templates/phase-template.md`
2. Owner 确认后，调用：`POST /api/requirements/from-phase` body: `{"phase_file": "docs/phases/phase-N.md", "repo_path": "<repo>"}`
3. 平台会自动解析 markdown、创建分支、逐个执行任务
```

**验收标准**（全部 L1 — 文件存在性 + parser 验证）:
- [ ] `config/templates/phase-template.md` 存在且格式与 phase-1a/1b 一致
- [ ] `config/templates/claude-md-section.md` 存在，说明了 CLI 的操作步骤
- [ ] 模板中的占位符清晰标注（`{PHASE_TITLE}` 等）
- [ ] PhaseFileParser 能正确解析模板生成的文件（填充占位符后解析）

**测试命令**:
```bash
uv run pytest tests/unit/test_phase_parser.py -v -k "test_parse_template"
```

**测试用例**（L1）:
- test_parse_template_filled — 用模板填充后的 phase 文件可被正确解析

---

### Task 1C.9: 更新配置和错误类型

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `config/platform.yaml` 扩展, `core/errors.py` 扩展

**描述**:
添加 Phase 1C 所需的配置项和错误类型。

**新增配置项**（`config/platform.yaml`）:
```yaml
task_planning:
  max_subtasks: 10                # 单次分解最大子任务数
  max_attempts_per_task: 2        # 单个子任务最大重试次数
  subtask_timeout_seconds: 900    # 子任务超时 15 分钟
  plan_timeout_seconds: 3600      # 整个需求超时 60 分钟
  default_max_turns: 150          # 子任务默认 max_turns
  summary_max_tokens: 1500        # 结果摘要长度限制
  consecutive_failure_limit: 2    # 连续失败自动终止阈值
  auto_pr: true                   # 全部完成后自动创建 PR
  sensitive_patterns:             # 敏感文件模式
    - ".env*"
    - "*credential*"
    - "*secret*"
    - "*.key"
    - "*.pem"
```

**新增异常类型**（`core/errors.py`）:
```python
class TaskPlanError(PlatformError): ...           # 任务计划错误
class TaskExecutionError(PlatformError): ...      # 子任务执行错误
class SubtaskTimeoutError(TaskExecutionError): ... # 子任务超时
class DirtyGitStateError(TaskExecutionError): ... # git 状态不干净
class SensitiveFileError(TaskExecutionError): ... # 敏感文件被修改
class CyclicDependencyError(TaskPlanError): ...   # 循环依赖
class PhaseParseError(TaskPlanError): ...         # Phase 文件解析错误
```

**验收标准**（全部 L1 — 纯逻辑，无外部依赖）:
- [ ] `platform.yaml` 包含 `task_planning` 配置节，所有值有合理默认值
- [ ] `core/errors.py` 新增 7 个异常类型，继承自 `PlatformError`
- [ ] 配置值可通过 `get_config()` 读取

**测试命令**:
```bash
uv run pytest tests/unit/test_config.py tests/unit/test_errors.py -v
```

---

### Task 1C.10: 修复已知问题 + 测试 Fixtures

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `tools/claude_code_cli.py` 修复, `tests/conftest.py` 扩展

**描述**:
修复 safety-reviewer 发现的现有问题，新增 Phase 1C 测试 fixtures。

**修复项**:
1. `claude_code_cli.py` 的 `agent_id="unknown"` → 改为接受参数传入
2. `claude_code_cli.py` 的 `process.kill()` → 改为 `os.killpg(os.getpgid(pid), signal.SIGTERM)`（进程组 kill）

**新增 Fixtures**:
```python
# tests/conftest.py
@pytest.fixture
def sample_phase_file(tmp_path):
    """生成标准格式的 phase-N.md 测试文件"""

@pytest.fixture
def sample_task_plan():
    """标准测试 TaskPlan（从 phase file 解析生成）"""

@pytest.fixture
def sample_subtasks():
    """标准测试 SubTask 列表"""

@pytest.fixture
def mock_task_executor():
    """Mock CLI 执行"""
```

**验收标准**（L1 — 回归测试 + fixture 可用性）:
- [ ] `ClaudeCodeCliTool.execute()` 接受 `agent_id` 参数，审计日志正确记录
- [ ] 超时 kill 使用 `os.killpg` 替代 `process.kill`（代码审查 + L3 验证）
- [ ] 新 fixtures 可被 Phase 1C 测试使用（在后续任务的测试中隐式验证）
- [ ] Phase 1B 现有 247 个测试全部通过（回归验证）

**测试命令**:
```bash
uv run pytest tests/ -v  # 全量回归，确认 247 个测试不受影响
```

---

## 1C.5 — 集成测试与文档

### Task 1C.11: L2 集成测试 — Mock 全流程

**状态**: [ ] 未开始
**依赖**: Task 1C.6, Task 1C.7
**产出文件**: `tests/integration/test_requirement_flow.py`

**描述**:
L2 级别的集成测试：验证从 API → DevAgent → PhaseFileParser → TaskExecutor → markdown 回写的完整组装逻辑。**Claude CLI 和 git 操作全部 mock**，验证的是"组件之间的接线是否正确"，而非"真实 CLI 能否执行任务"。

> **重要提醒**：L2 测试通过只能证明组装逻辑正确，**不能证明真实环境可用**。真实验收在 Task 1C.12。

**验收标准**（全部 L2 — mock CLI/git/notifier）:
- [ ] 测试完整成功路径：from-phase → 解析 → 3 个子任务全部成功 → markdown 全部 [x] → PR
- [ ] 测试断点续跑：phase-N.md 中 2 个 [x] + 2 个 [ ] → 只执行后 2 个
- [ ] 测试失败路径：子任务 2 失败 → plan 暂停 → retry → 成功 → 继续
- [ ] 测试跳过路径：子任务失败 → skip → 后续任务继续
- [ ] 测试终止路径：abort → 保留 checkpoints
- [ ] 测试超时路径：子任务超时 → 进程 kill → 暂停
- [ ] 测试敏感文件保护：子任务修改 .env → 自动回滚 + 撤销 markdown [x]
- [ ] 测试连续失败终止：2 个连续失败 → plan 终止
- [ ] **所有测试统一使用 Mock 边界约定表中定义的 mock 对象**

**Mock 策略**:
```python
# 统一 mock 工厂 — 所有 L2 集成测试共用
def make_mock_cli(results: list[dict]) -> AsyncMock:
    """按序返回预设结果，模拟 CLI 多次调用"""
    mock = AsyncMock()
    mock.execute.side_effect = results  # [{"success": True, ...}, ...]
    return mock

def make_mock_git(status_clean: bool = True) -> MagicMock:
    """模拟 git 操作：status/add/commit/diff/checkout"""
    ...
```

**测试命令**:
```bash
uv run pytest tests/integration/test_requirement_flow.py -v
```

---

### Task 1C.12: L3 真实端到端验收

**状态**: [ ] 未开始
**依赖**: Task 1C.11
**产出文件**: `tests/e2e/test_e2e_requirement.py`（脚本）, `tests/e2e/fixtures/test-phase.md`（测试用 phase 文件）

**描述**:
**Phase 1C 的最终验收门槛**。在真实环境中执行完整工作流：真实 Claude CLI 进程 + 真实 git repo + 真实 API 调用。这是 L1/L2 无法覆盖的"最后一公里"。

> **执行方式**：不是 `pytest` 自动运行，而是 **Owner 手动触发**的验收脚本。因为需要：
> 1. 真实的 Claude API Key（环境变量）
> 2. 一个可以安全操作的测试仓库（不是生产代码）
> 3. 平台服务已启动（`docker-compose up`）

**测试用 phase 文件**（`tests/e2e/fixtures/test-phase.md`）:
```markdown
# Phase E2E-Test: 端到端验收

**分支**: `feat/e2e-test`
**目标**: 验证需求驱动开发工作流

---

### Task E2E.1: 创建测试文件

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `test_output/hello.py`

**描述**:
创建一个简单的 Python 文件 `test_output/hello.py`，内容为一个 `greet()` 函数。

**验收标准**:
- [ ] `test_output/hello.py` 存在
- [ ] 包含 `def greet()` 函数

**测试命令**:
```bash
python -c "from test_output.hello import greet; print(greet())"
```

---

### Task E2E.2: 创建测试用例

**状态**: [ ] 未开始
**依赖**: Task E2E.1
**产出文件**: `test_output/test_hello.py`

**描述**:
为 `test_output/hello.py` 编写 pytest 测试。

**验收标准**:
- [ ] `test_output/test_hello.py` 存在
- [ ] pytest 通过

**测试命令**:
```bash
python -m pytest test_output/test_hello.py -v
```
```

**验收步骤**（Owner 手动执行）:
```bash
# 1. 确保平台运行
docker-compose up -d

# 2. 确保环境变量
export ANTHROPIC_API_KEY=sk-...

# 3. 调用 API 触发执行
curl -X POST http://localhost:8000/api/requirements/from-phase \
  -H "Content-Type: application/json" \
  -d '{"phase_file": "tests/e2e/fixtures/test-phase.md", "repo_path": "/tmp/e2e-test-repo"}'

# 4. 观察执行进度
curl http://localhost:8000/api/requirements/{plan_id}

# 5. 验收检查点（逐项手动确认）
```

**验收标准**（L3 — 全部真实环境，无 mock）:
- [ ] **CLI 启动**: 每个子任务确实启动了独立的 Claude CLI 进程（`ps aux | grep claude` 可观察）
- [ ] **任务执行**: E2E.1 生成 `test_output/hello.py`，E2E.2 生成 `test_output/test_hello.py`
- [ ] **Smart Checkpoint**: 每个子任务完成后有 git commit（`git log --oneline` 验证）
- [ ] **Markdown 回写**: `test-phase.md` 中 E2E.1 和 E2E.2 都变为 `[x]`
- [ ] **依赖顺序**: E2E.2 在 E2E.1 之后执行（commit 时间戳验证）
- [ ] **Session Recovery 覆盖**: CLI 没有去读 progress.md / 找 `[ ]` 任务（从 CLI 输出日志确认）
- [ ] **Prompt 传递**: E2E.2 的 prompt 包含 E2E.1 的结果摘要（从日志确认）
- [ ] **ntfy 通知**: 收到开始和完成通知
- [ ] **PR 创建**: 自动创建 PR（如 auto_pr=true）
- [ ] **断点续跑**: 手动将 E2E.1 标回 `[ ]`，重新触发，确认只执行 E2E.1（跳过已完成的 E2E.2 的前提下...如果有依赖则都重跑）

> **失败场景验收**（可选，推荐但不强制）：
> - [ ] 手动 kill CLI 进程 → plan 暂停 → retry → 恢复执行
> - [ ] 在 phase 文件中加入一个必定失败的任务 → 暂停 → skip → 继续

**测试命令**:
```bash
# 非 pytest，手动执行验收脚本
uv run python tests/e2e/test_e2e_requirement.py
```

---

### Task 1C.13: Phase 1C 基础设施适配

**状态**: [ ] 未开始
**依赖**: Task 1C.12
**参考**: `docs/requirement.md` §3.5 横切面需求演进路线

**描述**:
确保 Phase 1C 新增的模块正确集成平台横切面基础设施。

**验收标准**（L1 — 代码审查 + 全量回归测试）:
- [ ] **安全**：敏感文件变更检测已实现；子任务 prompt 包含安全指令
- [ ] **错误**：`core/errors.py` 新增异常类型已注册
- [ ] **日志**：所有新模块使用 `get_logger(__name__)`（grep 验证）
- [ ] **Trace ID**：API 端点入口调用 `set_trace_id()`（grep 验证）
- [ ] **审计**：子任务执行记录审计日志（agent_id 正确传递）
- [ ] **测试**：`tests/conftest.py` 新增 Phase 1C fixtures
- [ ] **配置**：`platform.yaml` 包含 `task_planning` 配置节

**测试命令**:
```bash
uv run pytest tests/ -v  # 全量回归
```

---

### Task 1C.14: Post-Phase 文档同步 + Git Tag

**状态**: [ ] 未开始
**依赖**: Task 1C.13

**验收标准**:
- [ ] 本文件所有任务标记 `[x]`
- [ ] `docs/requirement.md` 更新 Phase 1C 相关内容
- [ ] `docs/progress.md` Quick Status 更新
- [ ] 测试数更新到 Test Count History
- [ ] `git tag -a v0.3.0 -m "Phase 1C: 需求驱动开发工作流"`
- [ ] 推送 tag 到远程
