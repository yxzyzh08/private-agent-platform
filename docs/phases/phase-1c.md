# Phase 1C: 开发机器人 — 需求驱动开发工作流

**分支**: `feat/phase-1c-requirement-workflow`
**Tag**: `v0.3.0`
**前置**: Phase 1B 完成（v0.2.0）
**目标**: Owner 在 cui 中通过与 Claude Code 多轮对话完成需求澄清和任务分解 → Owner 确认任务列表 → dev_bot 逐个调用 Claude CLI 执行（每个子任务=全新上下文）→ 验证 → 创建 PR。解决 Claude CLI 单次会话上下文膨胀导致质量下降的问题。
**预计时长**: 2 周

**完成条件**: Owner 在 cui 中与 Claude Code 对话完成需求澄清和任务分解 → Owner 确认任务列表 → 子任务逐个独立执行（每个任务全新 Claude CLI 上下文）→ 每个子任务完成后自动 commit checkpoint → 全部完成后创建 PR → ntfy 通知 Owner

---

## 与 Phase 1B 的关系

| 模式 | 触发方式 | 执行方式 | Phase |
|------|---------|---------|-------|
| **快速修复模式** | GitHub Issue（自动） | 单次 Claude CLI 调用 | 1B（不变） |
| **需求开发模式** | Owner 在 cui 中与 CLI 协作 | 人机协作澄清+分解 → 多次独立 Claude CLI 调用 | 1C（新增） |

Phase 1B 代码完全保留，Phase 1C 是独立的新代码路径。共享工具层（claude_code_cli/sdk、git_tool、notifier）。

---

## 工作流概览

```
┌─────────────────────────────────────────────────────────┐
│ 阶段 1: 需求澄清与任务分解（人机协作，Owner ↔ CLI 在 cui） │
│                                                         │
│  Owner: "我想给平台加一个 Telegram 渠道适配器"              │
│  Claude: "我需要确认几个问题：1) ... 2) ... 3) ..."        │
│  Owner: "1) xxx  2) xxx  3) xxx"                        │
│  Claude: "明白了。我建议分成以下 5 个任务：                 │
│    1. 实现 channels/telegram/channel.py                  │
│    2. 更新 dispatch.py 路由规则                            │
│    3. ..."                                               │
│  Owner: "任务 3 太大了，拆成两个"                          │
│  Claude: "好的，更新后的 6 个任务：..."                    │
│  Owner: "确认，开始执行"                                   │
│                                                         │
│  → 确认后持久化到 data/agents/dev_bot/workspace/task_plans/│
│  → 触发 dev_bot 自动执行                                  │
│                                                         │
│  ※ 整个过程是 Owner 和 Claude Code 在 cui 中的连续对话，  │
│    需求澄清和任务分解自然发生在同一个对话流中，             │
│    不是割裂的两个阶段。                                    │
└───────────────────────┬─────────────────────────────────┘
                        ↓
┌───────────────────────▼─────────────────────────────────┐
│ 阶段 2: 多任务串行执行（自动，后台运行）                    │
│                                                         │
│  for task in sorted_tasks:                              │
│      1. git status 检查（确保干净状态）                     │
│      2. 构建 prompt（任务描述 + 前序任务摘要）              │
│      3. 全新 Claude CLI 会话执行                          │
│      4. 生成结果摘要                                      │
│      5. 自动 commit checkpoint                           │
│      6. 可选：运行验证命令                                 │
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

**关键设计原则**：阶段 1 是人驱动的（Owner 通过 cui 与 Claude Code 对话），平台不介入。只有 Owner 确认任务列表后，才进入平台自动化的阶段 2（dev_bot 逐个执行子任务）。这意味着 `decompose_requirement()` 不是平台的自动化步骤，而是 Claude Code 在 cui 对话中的辅助能力——任务分解的质量由人机协作保证，而非 LLM 单独决定。

---

## 1C.1 — 数据模型与持久化

### Task 1C.1: 实现 core/task_planner.py — 数据结构与持久化

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `core/task_planner.py`, `tests/unit/test_task_planner.py`

**描述**:
定义 TaskPlan 和 SubTask 数据结构，实现 JSON 文件持久化。这是 Phase 1C 的基础数据层。

**数据结构定义**:

```python
@dataclass
class SubTask:
    task_id: str                    # "task-001"
    title: str                      # 简短标题
    description: str                # 详细描述（含验收标准）
    status: str                     # pending | in_progress | completed | failed | skipped
    depends_on: list[str]           # 依赖的 task_id 列表
    context_files: list[str]        # 任务需要关注的文件路径
    validation_command: str | None  # 验证命令（如 pytest 命令）
    result_summary: str             # 执行后的结果摘要（LLM 生成）
    checkpoint_sha: str             # 完成后的 git commit SHA
    attempt_count: int              # 已尝试次数
    max_attempts: int               # 最大重试次数（默认 2）
    files_changed: list[str]        # 变更的文件列表（git diff 获取）
    duration_ms: int                # 执行耗时

@dataclass
class TaskPlan:
    plan_id: str                    # UUID
    requirement: str                # 原始需求文本（Owner 输入）
    clarification: str              # 澄清后的完整需求（多轮对话结论）
    source: str                     # "cui" | "github_issue"
    source_ref: str                 # 会话 ID 或 Issue URL
    status: str                     # draft | approved | executing | paused | completed | failed | aborted
    tasks: list[SubTask]            # 有序子任务列表
    branch: str                     # feature 分支名（如 feat/req-{short_id}）
    base_branch: str                # 基准分支（默认 main）
    repo_path: str                  # 工作仓库路径
    created_at: float
    updated_at: float
    completed_count: int            # 已完成任务数（计算字段）
    total_count: int                # 总任务数（计算字段）
```

**TaskPlanStore 接口**:
```python
class TaskPlanStore:
    def __init__(self, base_dir: str = "data/agents/dev_bot/workspace/task_plans/")
    def save(self, plan: TaskPlan) -> None         # 保存/更新
    def load(self, plan_id: str) -> TaskPlan | None
    def list_active(self) -> list[TaskPlan]        # status != completed/failed/aborted
    def delete(self, plan_id: str) -> None
```

**验收标准**:
- [ ] `SubTask` 和 `TaskPlan` dataclass 定义完整，支持 JSON 序列化/反序列化
- [ ] `TaskPlanStore` 实现 CRUD，数据存储在 `data/agents/dev_bot/workspace/task_plans/<plan_id>.json`
- [ ] 状态机转换合法性校验（如 `pending` 只能转 `in_progress`，不能直接转 `completed`）
- [ ] `topological_sort(tasks)` 函数：按 `depends_on` 拓扑排序，检测循环依赖抛出异常
- [ ] 使用 `get_logger(__name__)` 日志

**测试命令**:
```bash
uv run pytest tests/unit/test_task_planner.py -v
```

**测试用例**:
- test_subtask_serialization — SubTask JSON 序列化/反序列化
- test_taskplan_serialization — TaskPlan JSON 序列化/反序列化
- test_taskplan_store_crud — 保存、加载、列出、删除
- test_status_transition_valid — 合法状态转换
- test_status_transition_invalid — 非法状态转换抛异常
- test_topological_sort_linear — 线性依赖排序
- test_topological_sort_parallel — 无依赖任务保持原序
- test_topological_sort_cycle — 循环依赖检测

---

### Task 1C.2: 实现 core/task_planner.py — 任务计划提交与校验

**状态**: [ ] 未开始
**依赖**: Task 1C.1
**产出文件**: `core/task_planner.py` 扩展

**描述**:
接收 Owner 在 cui 中与 Claude Code 协作完成的任务分解结果，校验格式和约束后持久化为 TaskPlan。需求澄清和任务分解都是 Owner 通过 cui 与 Claude Code 对话完成的（人机协作），平台只负责接收最终确认的任务列表、校验合法性、持久化并触发执行。

**提交接口**:
```python
async def submit_task_plan(
    requirement: str,           # 原始需求描述
    clarification: str,         # 澄清后的完整需求
    tasks: list[dict],          # Owner 确认的子任务列表（来自 cui 对话）
    repo_path: str,             # 工作仓库路径
    source: str = "cui",
) -> TaskPlan:
    """校验并创建 TaskPlan，持久化后返回"""
```

**校验规则**:
- 子任务数量不超过 `max_subtasks` 配置值（默认 10），超出则拒绝并提示 Owner 拆分
- `depends_on` 中引用的 task_id 必须存在于任务列表中
- 拓扑排序无循环依赖
- 每个子任务必须有 title 和 description
- 自动为每个子任务的 description 追加敏感文件保护指令

**验收标准**:
- [ ] `submit_task_plan()` 校验并创建 `TaskPlan`，持久化到 JSON 文件
- [ ] 子任务数量超过 `max_subtasks` 时返回错误（不截断，让 Owner 调整）
- [ ] `depends_on` 引用不存在的 task_id 时校验失败
- [ ] 循环依赖检测（调用 `topological_sort()`）
- [ ] 每个子任务的 description 自动追加敏感文件保护指令
- [ ] 创建 TaskPlan 时 status 为 `approved`（因为 Owner 已在 cui 中确认）

**测试命令**:
```bash
uv run pytest tests/unit/test_task_planner.py -v -k "test_submit"
```

**测试用例**:
- test_submit_valid_plan — 合法任务列表提交成功
- test_submit_too_many_subtasks — 超出上限时拒绝
- test_submit_invalid_depends_on — 引用不存在的 task_id 时失败
- test_submit_cyclic_dependency — 循环依赖时失败
- test_submit_missing_required_fields — 缺少 title/description 时失败
- test_submit_auto_inject_sensitive_guard — 自动追加敏感文件指令

---

## 1C.2 — 多任务执行引擎

### Task 1C.3: 实现 core/task_executor.py — 核心执行逻辑

**状态**: [ ] 未开始
**依赖**: Task 1C.1
**产出文件**: `core/task_executor.py`, `tests/unit/test_task_executor.py`

**描述**:
多任务串行执行引擎。按拓扑序逐个执行子任务，每个子任务使用全新 Claude CLI 上下文。执行前检查 git 状态，执行后自动 commit checkpoint。

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
        """构建子任务 prompt：任务描述 + 前序任务摘要 + 注意事项"""

    async def generate_result_summary(self, raw_output: str, runtime: AgentRuntime) -> str:
        """用 LLM 从 CLI 输出中提取精炼结果摘要"""
```

**执行安全包装**（每个子任务）:
1. **前置检查**: `git status --porcelain` 必须为空（干净状态）
2. **记录起点**: `checkpoint_sha = git rev-parse HEAD`
3. **执行**: 调用 claude_code_cli/sdk，带子任务级超时
4. **成功后**: 自动 `git add -A && git commit`（checkpoint），记录 `files_changed`
5. **失败后**: `git checkout -- . && git clean -fd` 清理未提交变更

**Prompt 构建策略**:
```
## 任务：{title}

{description}

## 前置任务完成情况
- 任务1 "xxx": {result_summary}
- 任务2 "xxx": {result_summary}

## 需要关注的文件
- path/to/file1.py
- path/to/file2.py

## 注意事项
- 工作目录：{repo_path}
- 不要重复已完成的工作，代码已在 git 中
- 完成后运行：{validation_command}
- 禁止修改 .env、credentials 等敏感文件
```

**验收标准**:
- [ ] `execute_plan()` 按拓扑序串行执行所有子任务
- [ ] 每个子任务使用全新 Claude CLI/SDK 会话（调用 `tool.execute()`）
- [ ] 执行前 `git status --porcelain` 检查，非空则抛异常
- [ ] 执行成功后自动 git commit，commit message 包含 `[subtask N/M] {title}`
- [ ] 执行失败后自动 `git checkout -- . && git clean -fd` 清理
- [ ] `build_task_prompt()` 包含前序任务摘要和注意事项
- [ ] `generate_result_summary()` 通过 LLM 从 CLI 输出生成精炼摘要
- [ ] 每个子任务完成后持久化 plan 状态（防止中途崩溃丢失进度）

**测试命令**:
```bash
uv run pytest tests/unit/test_task_executor.py -v
```

**测试用例**:
- test_execute_plan_all_success — 3 个任务全部成功
- test_execute_plan_with_dependencies — 按依赖顺序执行
- test_execute_subtask_success — 单个子任务成功 + checkpoint commit
- test_execute_subtask_failure_cleanup — 失败后 git 清理
- test_dirty_git_state_rejected — 脏 git 状态拒绝执行
- test_build_task_prompt_with_summaries — prompt 包含前序摘要
- test_build_task_prompt_no_dependencies — 无依赖时的 prompt
- test_result_summary_generation — LLM 摘要生成（mock）
- test_plan_persisted_after_each_task — 每个子任务后 plan 已持久化

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

**验收标准**:
- [ ] 子任务失败后 plan.status 变为 "paused"，后续任务不执行
- [ ] 连续 2 个子任务失败后 plan.status 变为 "failed"
- [ ] 子任务超时后进程组被 kill（`os.killpg`）
- [ ] `retry_subtask()` 重置 task.status 为 pending 并重新执行
- [ ] `retry_subtask_with_feedback()` 将 feedback 追加到 task.description
- [ ] `skip_subtask()` 标记 skipped，如有后续任务依赖则返回警告列表
- [ ] `abort_plan()` kill 当前进程 + 标记 aborted + 保留 checkpoints
- [ ] `stop_current()` 立即 kill 进程组 + 持久化当前状态
- [ ] 所有失败/暂停/终止操作都发送 ntfy 通知

**测试命令**:
```bash
uv run pytest tests/unit/test_task_executor.py -v -k "test_failure"
```

**测试用例**:
- test_failure_pauses_plan — 单个失败暂停后续
- test_consecutive_failures_abort — 连续 2 个失败终止
- test_subtask_timeout — 超时 kill + 暂停
- test_retry_subtask — 重试成功
- test_retry_with_feedback — 带反馈重试
- test_skip_subtask_no_dependents — 无依赖者，跳过成功
- test_skip_subtask_with_dependents — 有依赖者，返回警告
- test_abort_plan — 终止保留 checkpoints
- test_stop_current_kills_process_group — 紧急停止 kill 进程组

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

**验收标准**:
- [ ] 子任务 commit 后运行 `git diff --name-only HEAD~1` 获取变更文件列表
- [ ] 变更文件与 `sensitive_patterns` 匹配时自动 `git reset --hard HEAD~1` 回滚
- [ ] 回滚后 ntfy 通知 Owner："子任务 X 修改了敏感文件 Y，已自动回滚"
- [ ] 敏感文件模式从 `config/platform.yaml` 读取，支持自定义
- [ ] 记录到审计日志

**测试命令**:
```bash
uv run pytest tests/unit/test_task_executor.py -v -k "test_sensitive"
```

**测试用例**:
- test_sensitive_file_detected — 检测到 .env 变更
- test_sensitive_file_rollback — 自动回滚
- test_no_sensitive_file — 正常文件不触发
- test_custom_sensitive_patterns — 自定义模式

---

## 1C.3 — DevAgent 集成与 API

### Task 1C.6: 扩展 agents/dev_agent.py — 需求开发模式入口

**状态**: [ ] 未开始
**依赖**: Task 1C.2, Task 1C.4
**产出文件**: `agents/dev_agent.py` 扩展

**描述**:
在 DevAgent 中新增需求开发模式的入口方法。DevAgent 作为薄调用层，核心逻辑在 core/task_planner.py 和 core/task_executor.py 中。

需求澄清和任务分解由 Owner 在 cui 中与 Claude Code 对话完成（人机协作），DevAgent 只负责接收确认后的任务列表并执行。

**新增方法**:
```python
class DevAgent(BaseAgent):
    # ... Phase 1B 方法保持不变 ...

    async def submit_requirement(
        self, requirement: str, clarification: str,
        tasks: list[dict], repo_path: str, source: str = "cui",
    ) -> TaskPlan:
        """接收 Owner 确认的需求和任务列表，校验后创建 feature 分支并开始执行"""

    async def get_plan_status(self, plan_id: str) -> TaskPlan | None:
        """查询执行进度"""

    async def retry_task(self, plan_id: str, task_id: str, feedback: str = "") -> TaskPlan:
        """重试失败的子任务"""

    async def skip_task(self, plan_id: str, task_id: str) -> TaskPlan:
        """跳过子任务"""

    async def abort_plan(self, plan_id: str) -> TaskPlan:
        """终止计划"""
```

**验收标准**:
- [ ] `submit_requirement()` 调用 `submit_task_plan()` 校验，创建 feature 分支，启动 `execute_plan()`，发送 ntfy 通知
- [ ] Phase 1B 的 `handle_issue()` 和 `execute_issue()` 完全不变
- [ ] DevAgent 文件不超过 500 行（核心逻辑在 core/ 模块中）
- [ ] 所有方法使用 `get_logger(__name__)` + trace_id

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v -k "test_requirement"
```

**测试用例**:
- test_submit_requirement — 提交任务列表 + 创建分支 + 启动执行
- test_get_plan_status — 查询进度
- test_retry_task — 重试失败子任务
- test_skip_task — 跳过子任务
- test_abort_plan — 终止计划
- test_phase1b_unchanged — 确认 Issue 流程不受影响

---

### Task 1C.7: 实现 API 端点 — 需求开发接口

**状态**: [ ] 未开始
**依赖**: Task 1C.6
**产出文件**: `main.py` 扩展

**描述**:
新增 REST API 端点供 cui 前端调用。这些端点是 cui 对话交互的后端支撑。

**新增端点**:
```
POST   /api/requirements          → 提交已确认的需求和任务列表（校验后直接开始执行）
GET    /api/requirements/{id}     → 查询 plan 状态和进度
POST   /api/requirements/{id}/abort      → 终止计划
POST   /api/requirements/{id}/tasks/{task_id}/retry   → 重试子任务
POST   /api/requirements/{id}/tasks/{task_id}/skip    → 跳过子任务
DELETE /api/requirements/{id}     → 删除计划
```

> **注意**：没有 `/approve` 端点。需求澄清和任务分解在 cui 对话中完成，Owner 确认后直接 POST `/api/requirements` 提交，提交即执行。

**验收标准**:
- [ ] 所有端点注册到 FastAPI app
- [ ] 请求/响应使用 Pydantic model 校验
- [ ] 每个请求生成 trace_id
- [ ] 错误返回标准 JSON（status_code + error message）
- [ ] `/health` 端点扩展包含活跃 plan 数量

**测试命令**:
```bash
uv run pytest tests/unit/test_requirement_api.py -v
```

**测试用例**:
- test_submit_requirement — POST 提交需求+任务列表，直接开始执行
- test_get_plan_status — GET 返回进度
- test_abort_plan — POST abort 终止
- test_retry_task — POST retry 重试
- test_skip_task — POST skip 跳过
- test_not_found — 不存在的 plan_id 返回 404

---

## 1C.4 — 配置与基础设施

### Task 1C.8: 更新配置和错误��型

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
class TaskPlanError(PlatformError): ...           # 任务分解错误
class TaskExecutionError(PlatformError): ...      # 子任务执行错误
class SubtaskTimeoutError(TaskExecutionError): ... # 子任务超时
class DirtyGitStateError(TaskExecutionError): ... # git 状态不干净
class SensitiveFileError(TaskExecutionError): ... # 敏感文件被修改
class CyclicDependencyError(TaskPlanError): ...   # 循环依赖
```

**验收标准**:
- [ ] `platform.yaml` 包含 `task_planning` 配置节，所有值有合理默认值
- [ ] `core/errors.py` 新增 6 个异常类型，继承自 `PlatformError`
- [ ] 配置值可通过 `get_config()` 读取

**测试命令**:
```bash
uv run pytest tests/unit/test_config.py tests/unit/test_errors.py -v
```

---

### Task 1C.9: 修复已知问题 + 测试 Fixtures

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
def mock_task_planner(): ...       # Mock LLM 分解结果

@pytest.fixture
def mock_task_executor(): ...      # Mock CLI 执行

@pytest.fixture
def sample_task_plan(): ...        # 标准测试 TaskPlan

@pytest.fixture
def sample_subtasks(): ...         # 标准测试 SubTask 列表
```

**验收标准**:
- [ ] `ClaudeCodeCliTool.execute()` 接受 `agent_id` 参数，审计日志正确记录
- [ ] 超时 kill 使用 `os.killpg` 替代 `process.kill`
- [ ] 新 fixtures 可被 Phase 1C 测试使用
- [ ] Phase 1B 现有测试全部通过（回归验证）

**测试命令**:
```bash
uv run pytest tests/ -v  # 全量回归
```

---

## 1C.5 — 集成测试与文档

### Task 1C.10: 集成测试 — 需求开发全流程

**状态**: [ ] 未开始
**依赖**: Task 1C.6, Task 1C.7
**产出文件**: `tests/integration/test_requirement_flow.py`

**描述**:
端到端集成测试：需求提交 → 分解 → 确认 → 多任务执行 → PR 创建。

**验收标准**:
- [ ] 测试完整成功路径：需求 → 分解 → approve → 3 个子任务全部成功 → PR
- [ ] 测试失败路径：子任务 2 失败 → plan 暂停 → retry → 成功 → 继续
- [ ] 测试跳过路径：子任务失败 → skip → 后续任务继续
- [ ] 测试终止路径：abort → 保留 checkpoints
- [ ] 测试超时路径：子任务超时 → 进程 kill → 暂停
- [ ] 测试敏感文件保护：子任务修改 .env → 自动回滚
- [ ] 测试连续失败终止：2 个连续失败 → plan 终止
- [ ] 所有测试 Mock claude_code_cli/sdk 和 git_tool

**测试命令**:
```bash
uv run pytest tests/integration/test_requirement_flow.py -v
```

---

### Task 1C.11: Phase 1C 基础设施适配

**状态**: [ ] 未开始
**依赖**: Task 1C.10
**参考**: `docs/requirement.md` §3.5 横切面需求演进路线

**描述**:
确保 Phase 1C 新增的模块正确集成平台横切面基础设施。

**验收标准**:
- [ ] **安全**：敏感文件变更检测已实现；子任务 prompt 包含安全指令
- [ ] **错误**：`core/errors.py` 新增异常类型已注册
- [ ] **日志**：所有新模块使用 `get_logger(__name__)`
- [ ] **Trace ID**：API 端点入口调用 `set_trace_id()`
- [ ] **审计**：子任务执行记录审计日志（agent_id 正确传递）
- [ ] **测试**：`tests/conftest.py` 新增 Phase 1C fixtures
- [ ] **配置**：`platform.yaml` 包含 `task_planning` 配置节

**测试命令**:
```bash
uv run pytest tests/ -v  # 全量回归
```

---

### Task 1C.12: Post-Phase 文档同步 + Git Tag

**状态**: [ ] 未开始
**依赖**: Task 1C.11

**验收标准**:
- [ ] 本文件所有任务标记 `[x]`
- [ ] `docs/requirement.md` 更新 Phase 1C 相关内容
- [ ] `docs/progress.md` Quick Status 更新
- [ ] 测试数更新到 Test Count History
- [ ] `git tag -a v0.3.0 -m "Phase 1C: 需求驱动开发工作流"`
- [ ] 推送 tag 到远程
