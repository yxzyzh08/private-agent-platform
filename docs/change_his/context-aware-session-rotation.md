# 设计方案：上下文感知的 Session 轮换机制

**状态**: 待审阅
**影响范围**: Phase 1A 平台基础设施 (扩展), Phase 1B 开发机器人 (核心)
**日期**: 2026-03-08

---

## 目录

1. [问题定义](#1-问题定义)
2. [关键发现：Claude CLI 的能力边界](#2-关键发现claude-cli-的能力边界)
3. [两种执行模式的差异分析](#3-两种执行模式的差异分析)
4. [方案设计](#4-方案设计)
5. [详细架构](#5-详细架构)
6. [对现有任务的影响分析](#6-对现有任务的影响分析)
7. [新增任务清单](#7-新增任务清单)
8. [风险与缓解](#8-风险与缓解)
9. [决策记录](#9-决策记录)

---

## 1. 问题定义

### 1.1 核心矛盾

Claude CLI 有上下文窗口限制（200K tokens）。当开发机器人处理复杂 Issue（大型代码库、多文件修改、长推理链）时，单次 CLI 调用可能耗尽上下文，导致：

- CLI 内部触发 auto-compact（~95% 时），**有损压缩**降低推理质量
- 达到 max_turns 后强制停止，任务**未完成**
- 复杂任务只能依赖 CLI 自身的压缩策略，平台**无法干预**

### 1.2 目标

让开发机器人（DevAgent）具备**上下文生命周期管理能力**：

1. **感知** — 知道 CLI 子进程的上下文使用情况
2. **决策** — 判断何时需要轮换 session
3. **执行** — 优雅地结束当前 session，携带进度摘要启动新 session
4. **验证** — 确认轮换后任务能继续推进

---

## 2. 关键发现：Claude CLI 的能力边界

### 2.1 可用的数据源

| 数据源 | 获取方式 | 内容 | 实时性 |
|--------|---------|------|--------|
| Result JSON | `--output-format json` 返回值 | `session_id`, `total_cost_usd`, `num_turns`, `duration_ms`, `is_error`, `subtype` | 调用结束后 |
| Session JSONL | `~/.claude/projects/<path>/sessions/<uuid>.jsonl` | 每轮 `usage.input_tokens`, `output_tokens`, `cache_*_tokens` | 实时追加 |
| Statusline API | stdin JSON（仅交互模式） | `used_percentage`, `remaining_percentage`, `context_window_size` | 实时 |

### 2.2 可用的 CLI 控制手段

| 手段 | 命令 | 用途 |
|------|------|------|
| 恢复会话 | `--resume <session_id>` | 在已有会话上继续对话 |
| 续接最近会话 | `--continue` | 恢复当前目录最近的会话 |
| 分叉会话 | `--fork-session` | 基于已有会话创建新分支 |
| 指定会话 ID | `--session-id <uuid>` | 使用特定 session ID |
| 预算上限 | `--max-budget-usd <amount>` | 限制单次调用花费 |
| 不持久化 | `--no-session-persistence` | print 模式不保存会话 |

### 2.3 CLI 自身的上下文管理

```
上下文使用量
  │
  0%──────────────80%──────95%────100%
  │                │        │       │
  │   正常工作区    │  黄区   │ 自动   │ 强制
  │                │        │ compact│ 停止
```

- **80%**：我们的 `ContextPruner` 阈值（用于 AgentRuntime）
- **95%**：CLI 内部 auto-compact 触发点（有损，不可控）
- **100%**：无法继续，CLI 停止

### 2.4 关键限制

1. **Print 模式无 Statusline**：`claude -p` 不提供实时 `used_percentage`，Statusline 仅限交互模式
2. **无法从外部触发 `/compact`**：Print 模式不接受交互命令
3. **JSONL 是唯一的实时数据源**：但需要文件轮询，且 token 计数是累积值而非当前上下文大小
4. **auto-compact 不可配置**：无法调整 95% 这个阈值

---

## 3. 两种执行模式的差异分析

### Mode A — Phase 1A 平台基础设施: cui 直接交互

```
Owner → cui Web UI → Claude Code CLI（交互模式）→ 代码修改
```

- CLI 运行在**交互模式**，有 Statusline、有 `/compact`、有 `/clear`
- cui 的 ProcessManager 管理 CLI 进程生命周期
- **平台不需要介入**：Owner 可以看到上下文使用量，手动 `/clear`
- **结论**：Mode A 无需 session 轮换机制，cui + CLI 交互模式自身已足够

### Mode B — Phase 1B 开发机器人: GitHub Issue 自动化

```
GitHub Webhook → DevAgent → AgentRuntime → claude_code_cli tool → CLI 子进程
                                                                    ↓
                                                              （print 模式，无交互）
```

- CLI 运行在 **print 模式**（`claude -p`），无 Statusline、无 `/compact`
- 单次调用可能执行几十轮 tool_use（读文件、改代码、运行测试...）
- 任务复杂度不可控（取决于 Issue 难度）
- **平台必须介入**：因为 Owner 不在场，无法手动干预

**结论**：Session 轮换机制仅需要作用于 Mode B（Phase 1B 的 GitHub Issue 自动化流程）。

---

## 4. 方案设计

### 4.1 总体策略：三层防御

```
┌─────────────────────────────────────────────┐
│  第一层：任务分解（主动避免上下文耗尽）        │
│  DevAgent 将复杂 Issue 拆成多步，每步独立调用  │
├─────────────────────────────────────────────┤
│  第二层：上下文监控 + 主动轮换                 │
│  监控 JSONL 日志，接近阈值时优雅结束并续接     │
├─────────────────────────────────────────────┤
│  第三层：结果检测 + 自动重试                   │
│  CLI 调用结束后检查任务是否完成，未完成则重试   │
└─────────────────────────────────────────────┘
```

### 4.2 为什么需要三层？

| 层 | 解决的问题 | 失败场景 |
|----|-----------|---------|
| 第一层（任务分解） | 从源头减少单次调用的上下文需求 | 分解不准确，某步仍然过大 |
| 第二层（主动轮换） | 在 auto-compact 前介入，保证推理质量 | JSONL 解析延迟，监控不及时 |
| 第三层（结果重试） | 兜底：即使前两层失败，仍能恢复 | 任务本身不可完成 |

### 4.3 执行流程

```
                 GitHub Issue 到达
                       │
                       ▼
              ┌─────────────────┐
              │  DevAgent 分析   │
              │  Issue 类型和    │
              │  复杂度          │
              └────────┬────────┘
                       │
                       ▼
              ┌─────────────────┐
              │ 第一层：任务分解  │
              │                 │
              │ 简单 Issue:     │
              │   → 单步执行    │
              │                 │
              │ 复杂 Issue:     │
              │   → 拆成多步    │
              │   (分析→实现→   │
              │    测试→修复)   │
              └────────┬────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
      ┌───────┐   ┌───────┐   ┌───────┐
      │ Step 1│   │ Step 2│   │ Step 3│    每步独立 CLI 调用
      │       │   │       │   │       │
      └───┬───┘   └───┬───┘   └───┬───┘
          │            │            │
          ▼            ▼            ▼
   ┌─────────────────────────────────────┐
   │  第二层：上下文监控（每步内部）        │
   │                                     │
   │  CLI 子进程运行                      │
   │      │                              │
   │      ├── 后台线程轮询 session JSONL  │
   │      │    ├── 计算 token 使用量      │
   │      │    ├── < 80%: 继续           │
   │      │    └── ≥ 80%: 标记需轮换     │
   │      │                              │
   │      ├── CLI 正常结束 → 返回结果     │
   │      └── 需轮换 → 等当前轮完成后中止 │
   │                                     │
   └──────────────────┬──────────────────┘
                      │
                      ▼
   ┌─────────────────────────────────────┐
   │  第三层：结果检测                     │
   │                                     │
   │  检查 CLI 返回值：                   │
   │  ├── subtype: "success"             │
   │  │   └── 步骤完成 → 继续下一步      │
   │  ├── subtype: "error_max_turns"     │
   │  │   └── 上下文耗尽 → 摘要 + 重试   │
   │  └── subtype: "error_*"             │
   │      └── 真正错误 → 报告 Owner      │
   └─────────────────────────────────────┘
```

---

## 5. 详细架构

### 5.1 组件设计

```
tools/claude_code_cli.py
  │
  ├── ClaudeCodeCLI (BaseTool)        ← 已有，需扩展
  │     execute() 方法增加：
  │     ├── session JSONL 监控
  │     ├── token 使用量计算
  │     └── 返回值增加 token 统计
  │
  └── CLISessionMonitor (新增)         ← 内部类
        ├── start(session_id)
        ├── get_usage() → TokenUsage
        └── stop()

core/session_rotation.py               ← 新增模块
  │
  ├── RotationPolicy                   ← 策略接口
  │     should_rotate(usage) → bool
  │
  ├── ThresholdRotationPolicy          ← 基于阈值的策略
  │     threshold: float = 0.80
  │
  └── RotationContext                   ← 轮换上下文
        ├── generate_summary(session_log) → str
        ├── build_continuation_prompt(summary, remaining_task) → str
        └── record_rotation(event_bus)

agents/dev_agent.py
  │
  └── DevAgent
        ├── handle_issue()             ← 已有，需扩展
        │     增加：任务分解 + 多步执行编排
        │
        └── _execute_with_rotation()   ← 新增私有方法
              ├── 调用 claude_code_cli
              ├── 检查返回值和 token 使用
              ├── 判断是否需要继续
              └── 携带摘要重试
```

### 5.2 第一层：任务分解

DevAgent 在收到 Issue 后，先用 LLM 分析 Issue 复杂度，决定执行策略：

```python
# agents/dev_agent.py

class DevAgent:
    async def handle_issue(self, issue: GitHubIssue) -> None:
        # 1. 分析 Issue
        analysis = await self._analyze_issue(issue)

        # 2. 根据复杂度决定执行策略
        if analysis.complexity == "simple":
            # 简单 Issue：单步执行（如 typo 修复、小 bug）
            steps = [ExecutionStep(
                instruction=f"Fix this issue:\n{issue.title}\n{issue.body}",
                expected_output="PR ready"
            )]
        else:
            # 复杂 Issue：拆成多步
            steps = await self._decompose_issue(issue, analysis)

        # 3. 逐步执行，每步独立 CLI session
        result = await self._execute_steps(steps, issue.repo_path)

        # 4. 创建 PR
        if result.success:
            await self._create_pr(issue, result)


    async def _decompose_issue(self, issue, analysis) -> list[ExecutionStep]:
        """让 LLM 将复杂 Issue 拆分成可独立执行的步骤"""
        prompt = f"""Analyze this GitHub Issue and break it into sequential steps.
Each step should be completable in a single Claude Code session.

Issue: {issue.title}
{issue.body}

Analysis: {analysis.summary}

Output a JSON array of steps, each with:
- instruction: what to do in this step
- expected_output: how to verify this step succeeded
- estimated_complexity: simple/medium/complex
"""
        response = await self.runtime.call_llm(prompt)
        return parse_steps(response)
```

### 5.3 第二层：CLI 上下文监控

```python
# tools/claude_code_cli.py

import asyncio
import json
from pathlib import Path
from dataclasses import dataclass

@dataclass
class CLITokenUsage:
    """CLI 调用的 token 使用统计"""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    num_turns: int = 0
    session_id: str | None = None

    @property
    def estimated_context_tokens(self) -> int:
        """估算当前上下文大小（输入侧）

        注意：这是近似值。实际上下文包含系统 prompt、
        缓存内容等，精确值只有 CLI 内部知道。
        我们用最近一轮的 input_tokens 作为估算。
        """
        return self.input_tokens

    def usage_ratio(self, context_window: int = 200_000) -> float:
        """估算上下文使用率"""
        if context_window <= 0:
            return 0.0
        return self.estimated_context_tokens / context_window


class CLISessionMonitor:
    """监控 CLI 子进程的 session JSONL 文件，追踪 token 使用量"""

    def __init__(self, project_path: str, context_window: int = 200_000):
        self._project_path = project_path
        self._context_window = context_window
        self._session_id: str | None = None
        self._latest_usage = CLITokenUsage()
        self._monitor_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def _get_session_dir(self) -> Path:
        """获取 CLI 的 session 存储目录"""
        # Claude CLI 用 URL-encoded 路径作为项目目录名
        encoded = self._project_path.replace("/", "%2F")
        return Path.home() / ".claude" / "projects" / encoded / "sessions"

    async def start(self, session_id: str) -> None:
        """开始监控指定 session 的 JSONL 文件"""
        self._session_id = session_id
        self._stop_event.clear()
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _monitor_loop(self) -> None:
        """轮询 JSONL 文件，提取最新的 token 使用量"""
        session_file = self._get_session_dir() / f"{self._session_id}.jsonl"

        while not self._stop_event.is_set():
            try:
                if session_file.exists():
                    self._parse_latest_usage(session_file)
            except Exception:
                pass  # 文件可能正在被写入，忽略解析错误

            # 每 5 秒检查一次（平衡精度和 I/O 开销）
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=5.0
                )
                break
            except asyncio.TimeoutError:
                continue

    def _parse_latest_usage(self, session_file: Path) -> None:
        """从 JSONL 中提取最近一条 assistant 消息的 usage"""
        last_usage = None
        num_turns = 0

        with open(session_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("role") == "assistant" and "usage" in entry:
                        last_usage = entry["usage"]
                        num_turns += 1
                except json.JSONDecodeError:
                    continue

        if last_usage:
            self._latest_usage = CLITokenUsage(
                input_tokens=last_usage.get("input_tokens", 0),
                output_tokens=last_usage.get("output_tokens", 0),
                cache_read_tokens=last_usage.get("cache_read_input_tokens", 0),
                cache_creation_tokens=last_usage.get("cache_creation_input_tokens", 0),
                num_turns=num_turns,
                session_id=self._session_id,
            )

    def get_usage(self) -> CLITokenUsage:
        return self._latest_usage

    def should_rotate(self, threshold: float = 0.80) -> bool:
        """判断是否应该轮换 session"""
        return self._latest_usage.usage_ratio(self._context_window) >= threshold

    async def stop(self) -> None:
        self._stop_event.set()
        if self._monitor_task:
            await self._monitor_task
```

### 5.4 第三层：结果检测 + 自动续接

```python
# core/session_rotation.py

from dataclasses import dataclass

@dataclass
class RotationConfig:
    """Session 轮换配置"""
    # 上下文使用率阈值，超过则触发轮换
    context_threshold: float = 0.80
    # 最大轮换次数（防止无限循环）
    max_rotations: int = 3
    # 进度摘要的最大 token 数
    summary_max_tokens: int = 2000
    # CLI 上下文窗口大小
    context_window: int = 200_000


class SessionRotator:
    """管理 CLI session 的轮换生命周期"""

    def __init__(self, config: RotationConfig, runtime):
        self._config = config
        self._runtime = runtime  # AgentRuntime，用于调用 LLM 生成摘要
        self._rotation_count = 0
        self._history: list[RotationRecord] = []

    async def execute_with_rotation(
        self,
        cli_tool,
        initial_instruction: str,
        repo_path: str,
    ) -> CLIExecutionResult:
        """执行 CLI 调用，必要时自动轮换 session"""

        instruction = initial_instruction
        cumulative_changes: list[str] = []

        while self._rotation_count <= self._config.max_rotations:
            # 执行 CLI
            result = await cli_tool.execute({
                "instruction": instruction,
                "repo_path": repo_path,
            })

            # 记录本次执行的产出
            cumulative_changes.append(result.data.get("output", ""))

            # 检查结果
            if result.success and result.data.get("subtype") == "success":
                # 任务完成
                return CLIExecutionResult(
                    success=True,
                    output="\n".join(cumulative_changes),
                    rotations=self._rotation_count,
                    token_usage=result.data.get("token_usage"),
                )

            # 判断是否因上下文耗尽而停止
            subtype = result.data.get("subtype", "")
            token_usage = result.data.get("token_usage")
            needs_rotation = (
                subtype == "error_max_turns"
                or (token_usage and token_usage.usage_ratio() >= self._config.context_threshold)
            )

            if not needs_rotation:
                # 真正的错误，不是上下文问题
                return CLIExecutionResult(
                    success=False,
                    output="\n".join(cumulative_changes),
                    error=result.error,
                    rotations=self._rotation_count,
                )

            # 需要轮换：生成进度摘要，构建续接 prompt
            self._rotation_count += 1
            logger.info(
                "Session rotation triggered",
                rotation=self._rotation_count,
                max=self._config.max_rotations,
            )

            summary = await self._generate_progress_summary(
                original_task=initial_instruction,
                session_output=result.data.get("output", ""),
                repo_path=repo_path,
            )

            instruction = self._build_continuation_prompt(
                original_task=initial_instruction,
                progress_summary=summary,
                rotation_number=self._rotation_count,
            )

            # 记录轮换事件
            self._history.append(RotationRecord(
                rotation_number=self._rotation_count,
                reason=subtype,
                summary=summary,
            ))

        # 超过最大轮换次数
        return CLIExecutionResult(
            success=False,
            output="\n".join(cumulative_changes),
            error=f"Exceeded max rotations ({self._config.max_rotations})",
            rotations=self._rotation_count,
        )

    async def _generate_progress_summary(
        self,
        original_task: str,
        session_output: str,
        repo_path: str,
    ) -> str:
        """用 LLM 从 CLI 输出中提取进度摘要"""
        prompt = f"""You are summarizing progress on a coding task for handoff to a new session.

Original task:
{original_task}

Session output (what was accomplished):
{session_output[-8000:]}  # 截取最后 8000 字符，避免 prompt 过长

Summarize:
1. What files were modified and how
2. What tests were run and their results
3. What remains to be done
4. Any important context the next session needs

Keep the summary under {self._config.summary_max_tokens} tokens.
Be specific about file paths and code changes."""

        response = await self._runtime.call_llm(prompt)
        return response.content

    def _build_continuation_prompt(
        self,
        original_task: str,
        progress_summary: str,
        rotation_number: int,
    ) -> str:
        """构建续接 prompt"""
        return f"""You are continuing a coding task that was started in a previous session.
This is continuation #{rotation_number}.

## Original Task
{original_task}

## Progress So Far
{progress_summary}

## Your Job
Continue from where the previous session left off.
Focus on completing the REMAINING work described above.
Do NOT redo work that is already done.
After completing, run tests to verify everything works."""


@dataclass
class RotationRecord:
    rotation_number: int
    reason: str
    summary: str


@dataclass
class CLIExecutionResult:
    success: bool
    output: str
    error: str | None = None
    rotations: int = 0
    token_usage: CLITokenUsage | None = None
```

### 5.5 完整调用链

```
GitHub Issue 到达
       │
       ▼
DevAgent.handle_issue()
       │
       ├─ 1. _analyze_issue()         → 分析 Issue 类型和复杂度
       │     (1 次 LLM 调用，使用 AgentRuntime)
       │
       ├─ 2. ntfy 通知 Owner → 等待确认
       │
       ├─ 3. _decompose_issue()       → 复杂 Issue 拆分成多步
       │     (1 次 LLM 调用，使用 AgentRuntime)
       │
       ├─ 4. 对每个 step:
       │     │
       │     └─ SessionRotator.execute_with_rotation()
       │           │
       │           ├─ claude_code_cli.execute()
       │           │     ├─ 启动 CLI 子进程 (claude -p)
       │           │     ├─ CLISessionMonitor 后台监控 JSONL
       │           │     └─ 子进程结束 → 返回结果 + token 统计
       │           │
       │           ├─ 检查结果：完成? 上下文耗尽? 错误?
       │           │
       │           └─ 如需轮换:
       │                 ├─ _generate_progress_summary()  (1 次 LLM)
       │                 ├─ _build_continuation_prompt()
       │                 └─ 重新调用 claude_code_cli.execute()
       │
       ├─ 5. git_tool.create_pr()     → 创建 PR
       │
       └─ 6. Issue 评论 + ntfy 通知
```

### 5.6 配置集成

在 `config/platform.yaml` 中新增：

```yaml
session_rotation:
  # 是否启用 session 轮换（默认启用）
  enabled: true
  # 上下文使用率阈值（0.0 ~ 1.0）
  context_threshold: 0.80
  # 单次任务最大轮换次数
  max_rotations: 3
  # 进度摘要最大 token 数
  summary_max_tokens: 2000
  # CLI 上下文窗口大小
  context_window: 200000
  # JSONL 监控轮询间隔（秒）
  monitor_interval_seconds: 5
```

在 `core/constants.py` 中新增：

```python
# Session Rotation
SESSION_ROTATION_THRESHOLD = 0.80
MAX_SESSION_ROTATIONS = 3
ROTATION_SUMMARY_MAX_TOKENS = 2000
CLI_CONTEXT_WINDOW = 200_000
CLI_MONITOR_INTERVAL = 5  # seconds
```

---

## 6. 对现有任务的影响分析

### 6.1 需要修改的现有任务

| 任务 | 当前范围 | 需要增加的内容 | 改动量 |
|------|---------|--------------|--------|
| **Task 1.7** `claude_code_cli.py` | 简单的子进程封装 | + 解析 result JSON 中的 `session_id`；+ 返回 `CLITokenUsage` 统计；+ `CLISessionMonitor` 内部类；+ 从 JSONL 文件读取 token 使用量 | 中 |
| **Task 1.5** `constants.py` | 基础常量 | + `SESSION_ROTATION_THRESHOLD` 等 5 个常量 | 小 |
| **Task 1.5** `errors.py` | 基础异常 | + `SessionRotationError`、`ContextExhaustionError` | 小 |
| **Task 1B.5** `dev_agent.py` CLI 执行 | 单次 CLI 调用 | + 通过 `SessionRotator` 执行；+ 处理轮换结果 | 中 |

### 6.2 不需要修改的任务

| 任务 | 原因 |
|------|------|
| Task 1.13 `core/memory.py` | `ContextPruner` 服务于 AgentRuntime 的 LLM 调用，与 CLI 子进程的上下文管理是独立的 |
| Task 1.14 `core/agent_runtime.py` | AgentRuntime 编排 LLM tool_use 循环，CLI 上下文管理在 tool 层解决 |
| Task 1.11 `core/event_bus.py` | 已有 `publish()` 接口，轮换事件直接使用 |
| Task 1.20a `core/logging.py` | 已有 `get_logger()` 和 `@log_duration`，直接使用 |
| Task 1.15 `channels/base.py` | 渠道层不涉及 CLI 执行 |

### 6.3 为什么不改 `core/memory.py` 和 `core/agent_runtime.py`？

这是一个重要的架构决策：

```
                           AgentRuntime (core/agent_runtime.py)
                              │
                              │  管理 LLM API 调用的上下文
                              │  ContextPruner 在每次 LLM 调用前裁剪
                              │
                              ▼
                    ┌─────────────────────┐
                    │  tool_use 循环       │
                    │                     │
                    │  call LLM           │
                    │    ↓                │
                    │  tool_use?          │
                    │    ├─ yes → 执行工具 │ ← claude_code_cli 是其中一个工具
                    │    │        ↓       │
                    │    │   反馈结果     │
                    │    │        ↓       │
                    │    └── call LLM     │
                    │    ...              │
                    │    └─ no → 返回     │
                    └─────────────────────┘

AgentRuntime 的上下文 ≠ CLI 子进程的上下文
```

- **AgentRuntime 的上下文**：DevAgent 与 LLM 的对话（分析 Issue、决定调用哪个工具）—— 这通常很短，几轮就完成
- **CLI 子进程的上下文**：Claude CLI 内部读代码、改代码、运行测试 —— 这才是可能耗尽的部分

两者是完全独立的上下文空间。Session 轮换只需要在 `tools/claude_code_cli.py` 和 `agents/dev_agent.py` 层面解决。

---

## 7. 新增任务清单

### 建议：合并到现有 Phase 结构

这些任务不应作为独立 Phase，而应**插入到 Phase 1A 和 1B 的现有任务组**中。

#### Phase 1A 新增任务（插入 1B 工具层基础）

**Task 1.7a: CLI Session 监控与 Token 追踪**

```markdown
**状态**: [ ] 未开始
**依赖**: Task 1.7 (claude_code_cli.py)
**产出文件**: `tools/claude_code_cli.py` 扩展

**描述**:
扩展 claude_code_cli 工具，增加 session JSONL 监控能力和 token 使用统计。

**验收标准**:
- [ ] `CLITokenUsage` dataclass：input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, num_turns, session_id
- [ ] `CLISessionMonitor`：后台 asyncio task 轮询 JSONL 文件，提取最新 token 使用量
- [ ] `execute()` 返回值的 `data` 字段包含 `token_usage` (CLITokenUsage) 和 `session_id`
- [ ] 解析 CLI result JSON 中的 `session_id`、`num_turns`、`total_cost_usd`
- [ ] 监控轮询间隔可配置（默认 5 秒）
- [ ] CLI 子进程结束后监控自动停止
- [ ] 轮询文件不影响 CLI 子进程运行（只读、容错）

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_cli_session_monitor"
```
```

#### Phase 1B 新增任务（插入 1B.2 Issue 处理流程之后）

**Task 1B.4a: 实现 Session 轮换模块**

```markdown
**状态**: [ ] 未开始
**依赖**: Task 1.7a (CLI Token 追踪), Task 1.14 (AgentRuntime)
**产出文件**: `core/session_rotation.py`

**描述**:
实现 Session 轮换的核心逻辑：轮换策略、进度摘要生成、续接 prompt 构建。

**验收标准**:
- [ ] `RotationConfig` dataclass：阈值、最大轮换次数、摘要最大 token 等配置
- [ ] `SessionRotator.execute_with_rotation()`：封装 CLI 调用 + 轮换逻辑
- [ ] 进度摘要通过 LLM 生成（从 CLI 输出中提取关键信息）
- [ ] 续接 prompt 包含原始任务 + 进度摘要 + 明确的续接指令
- [ ] 轮换次数超限返回失败结果
- [ ] 每次轮换记录 `RotationRecord`（轮次、原因、摘要）
- [ ] 轮换事件通过事件总线发布（`session_rotated` 事件类型）
- [ ] 轮换配置从 `config/platform.yaml` 读取

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_session_rotation"
```
```

**Task 1B.5 (修改): 实现 Claude Code CLI 执行 + PR 创建**

```markdown
（在原有验收标准基础上新增）

**新增验收标准**:
- [ ] 通过 `SessionRotator.execute_with_rotation()` 执行 CLI（而非直接调用 cli tool）
- [ ] 复杂 Issue 先调用 LLM 分解为多步，每步独立执行
- [ ] Issue 评论包含轮换信息（如有）："Session rotated N times"
- [ ] 轮换失败时 ntfy 通知 Owner 并在 Issue 评论错误详情
```

**Task 1B.6a: Session 轮换集成测试**

```markdown
**状态**: [ ] 未开始
**依赖**: Task 1B.4a, Task 1B.5
**产出文件**: `tests/unit/test_session_rotation.py`

**验收标准**:
- [ ] 测试正常执行（无轮换）
- [ ] 测试单次轮换：模拟 CLI 返回 error_max_turns → 摘要 → 续接 → 成功
- [ ] 测试多次轮换：验证轮换计数和最大次数限制
- [ ] 测试轮换失败：超过 max_rotations 后正确报错
- [ ] 测试 CLISessionMonitor：模拟 JSONL 文件解析和 token 计算
- [ ] 测试进度摘要生成（mock LLM 调用）
- [ ] 测试续接 prompt 格式正确性
- [ ] 所有测试通过，覆盖率 ≥ 80%

**测试命令**:
```bash
uv run pytest tests/unit/test_session_rotation.py -v --cov=core/session_rotation --cov-report=term-missing
```
```

### 任务依赖关系图

```
Phase 1A:
  Task 1.7 (claude_code_cli)
       │
       ▼
  Task 1.7a (CLI Session 监控)  ← 新增
       │
       ▼
Phase 1B:
  Task 1B.3 (dev_agent) ──────┐
       │                       │
       ▼                       ▼
  Task 1B.4 (ntfy+确认)   Task 1B.4a (session_rotation)  ← 新增
       │                       │
       └───────┬───────────────┘
               ▼
  Task 1B.5 (CLI 执行+PR)  ← 修改
               │
               ▼
  Task 1B.6a (轮换集成测试)  ← 新增
               │
               ▼
  Task 1B.7 (集成测试)  ← 已有
```

---

## 8. 风险与缓解

### 8.1 技术风险

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| JSONL 文件路径编码方式变化（CLI 版本更新） | 低 | 监控失效 | 监控失败时 graceful degradation：回退到不监控模式，依赖第三层结果检测 |
| JSONL 中的 token 计数不准确（已知 bug #13783） | 中 | 阈值判断偏差 | 设保守阈值（80% 而非 90%），留足余量 |
| LLM 生成的进度摘要质量不足 | 中 | 续接后重复或遗漏工作 | 摘要 prompt 要求列出具体文件路径和修改内容（可验证信息） |
| 任务分解不准确（步骤过大或过小） | 中 | 某步仍然耗尽上下文 | 第二层监控 + 第三层重试兜底 |
| CLI 子进程异常退出，JSONL 不完整 | 低 | 无法获取 token 统计 | 监控容错：文件不存在或解析失败时返回零值 |

### 8.2 架构风险

| 风险 | 缓解措施 |
|------|---------|
| 过度工程化：轮换机制增加了系统复杂度 | 渐进实施：Phase 1B 先只实现第三层（结果检测+重试），验证需求真实存在后再加第一层和第二层 |
| 轮换摘要消耗额外 LLM token | 摘要用低成本模型（Haiku），限制 2000 tokens |
| 与 CLI 版本强耦合 | JSONL 解析作为独立类，CLI 路径作为配置项，便于适配 |

### 8.3 建议的实施顺序

**阶段一（Phase 1B 初期）：仅第三层**
- 最小可行方案：检查 CLI 返回值的 `subtype`
- 如果是 `error_max_turns`，用简单 prompt 重试
- 不需要 JSONL 监控，不需要 token 追踪
- 验证需求是否真实存在

**阶段二（Phase 1B 中期）：加第一层**
- 实现任务分解
- 复杂 Issue 拆成多步

**阶段三（Phase 1B 后期或 Phase 5）：加第二层**
- 实现 JSONL 监控
- 主动在 auto-compact 前轮换
- 完整的 `CLISessionMonitor`

---

## 9. 决策记录

### DR-1: Session 轮换放在 tool 层而非 core 层

**决策**：`CLISessionMonitor` 放在 `tools/claude_code_cli.py`，`SessionRotator` 放在 `core/session_rotation.py`。

**理由**：
- CLI 上下文管理是 CLI 工具的实现细节，不是所有智能体都需要
- AgentRuntime 的 ContextPruner 已经处理了 LLM API 调用的上下文
- 符合依赖方向：`tools/` 依赖 `core/`，`core/session_rotation` 提供通用策略，`tools/` 中 CLI 特定实现

### DR-2: 监控 JSONL 而非 Statusline

**决策**：通过轮询 session JSONL 文件获取 token 使用量，不使用 Statusline API。

**理由**：
- Statusline API 仅在交互模式可用，print 模式（`claude -p`）不支持
- JSONL 文件是 CLI 的标准持久化格式，稳定性高
- 已知 Statusline 有累积 token 计数 bug (#13783)

### DR-3: 阈值设为 80% 而非 90%

**决策**：上下文使用率阈值默认 80%。

**理由**：
- CLI auto-compact 在 95% 触发，需要留出安全边际
- JSONL 中的 token 计数可能不完全精确（cache tokens 的计算方式）
- 80% 留出 20% 余量，足够完成当前轮的 tool_use 并生成摘要

### DR-4: 进度摘要用 LLM 生成而非结构化提取

**决策**：轮换时通过 LLM 从 CLI 输出中生成进度摘要。

**理由**：
- CLI 输出格式不固定（包含代码片段、测试输出、错误信息等）
- LLM 能理解语义，提取"做了什么、还差什么"的关键信息
- 结构化提取过于脆弱，对 CLI 输出格式变化敏感

### DR-5: 渐进实施，第三层优先

**决策**：Phase 1B 先只实现第三层（结果检测+重试），验证需求后再加第一层和第二层。

**理由**：
- 避免过度工程化：可能大部分 Issue 都能在单次调用内完成
- 第三层实现成本最低（只检查返回值），但覆盖最关键场景
- 实际运行后的数据（多少 Issue 触发了轮换？质量如何？）决定是否需要更复杂的机制

---

## 附录 A：CLI Result JSON 参考

```json
{
  "type": "result",
  "subtype": "success",
  "session_id": "a1b2c3d4-...",
  "result": "I've fixed the bug by...",
  "total_cost_usd": 0.0523,
  "is_error": false,
  "duration_ms": 45000,
  "duration_api_ms": 32000,
  "num_turns": 12
}
```

`subtype` 可能值：
- `"success"` — 正常完成
- `"error_max_turns"` — 达到最大轮次限制（上下文相关）
- `"error_during_execution"` — 执行过程中出错

## 附录 B：Session JSONL Token Usage 参考

```json
{
  "role": "assistant",
  "content": "...",
  "usage": {
    "input_tokens": 85000,
    "output_tokens": 1200,
    "cache_creation_input_tokens": 50000,
    "cache_read_input_tokens": 20000
  }
}
```
