# Phase 1B: 开发机器人 — GitHub Issue 自动化

**分支**: `feat/phase-1b-issue-automation`
**Tag**: `v0.2.0`
**前置**: Phase 1A 完成
**目标**: 平台首个真正的智能体（DevAgent）上线 — GitHub 创建 Issue 后，开发机器人通过 AgentRuntime 编排：自动分析 → ntfy 通知 Owner → Owner 通过 Web UI 确认 → 执行修复并提 PR（半自动模式）。支持 Claude Agent SDK 双轨执行和 Session 轮换
**预计时长**: 2 周

**完成条件**: GitHub 创建 Issue 后，开发机器人自动分析 Issue 类型 → ntfy 通知 Owner → Owner 通过 cui Web UI 确认 → Claude Code 执行修复 → Issue 下自动评论进度 → 自动创建 PR 并关联 Issue

---

## 1B.1 — GitHub Webhook 渠道

### Task 1B.1: 实现 channels/github_webhook/channel.py

**状态**: [x] 完成
**依赖**: Phase 1A（channels/base.py 已存在）
**产出文件**: `channels/github_webhook/channel.py`

**描述**:
GitHub Webhook 接收器，监听 Issue 创建事件。使用 FastAPI 路由接收 Webhook，验证 `X-Hub-Signature-256` 签名。

**验收标准**:
- [ ] 继承 BaseChannel
- [ ] FastAPI 路由 `POST /webhooks/github` 接收 Webhook
- [ ] 验证 `X-Hub-Signature-256` 签名（使用 `GITHUB_WEBHOOK_SECRET`）
- [ ] 签名验证失败返回 403 并记录日志
- [ ] 解析 `issues.opened` 事件，提取 Issue 标题和内容
- [ ] 调用 `on_message` 回调将事件传递给调度层

**测试命令**:
```bash
uv run pytest tests/unit/test_channels.py -v -k "test_github_webhook"
```

**测试用例**:
- test_github_webhook_valid_signature — 合法签名通过
- test_github_webhook_invalid_signature — 非法签名返回 403
- test_github_webhook_issue_opened — 正确解析 Issue 事件
- test_github_webhook_ignore_other_events — 忽略非 Issue 事件

---

### Task 1B.2: 更新 dispatch.py 路由规则

**状态**: [x] 完成
**依赖**: Task 1B.1
**产出文件**: `core/dispatch.py` 更新, `config/platform.yaml` 更新

**描述**:
在 `config/platform.yaml` 的 `dispatch.routes` 中添加 GitHub Webhook → 开发机器人的路由规则。

**验收标准**:
- [ ] `platform.yaml` 新增 GitHub Webhook 路由配置
- [ ] GitHub Webhook 消息路由到开发机器人

**测试命令**:
```bash
uv run pytest tests/unit/test_channels.py -v -k "test_dispatch_github"
```

---

## 1B.2 — Issue 处理流程

### Task 1B.3: 创建 agents/dev_agent.py + config/agents/dev.yaml

**状态**: [x] 完成
**依赖**: Task 1B.2, Phase 1A（agent_runtime 已存在）
**产出文件**: `agents/dev_agent.py`, `config/agents/dev.yaml`

**描述**:
创建开发机器人智能体，处理 GitHub Issue 事件。继承 BaseAgent，使用 AgentRuntime 执行。

**验收标准**:
- [ ] `dev_agent.py` 继承 BaseAgent
- [ ] `dev.yaml` 配置 name, type, allowed_tools, repos
- [ ] 注册事件订阅（`issues.opened` → `handle_issue`）
- [ ] Issue 创建后 AI 分析 Issue 类型（Bug/Feature/Refactor）和内容

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v -k "test_issue_analysis"
```

---

### Task 1B.4: 实现 ntfy 通知 + Owner 确认/拒绝流程

**状态**: [x] 完成
**依赖**: Task 1B.3
**产出文件**: `agents/dev_agent.py` 扩展, `core/notifier.py`

**描述**:
Issue 分析完成后通过 ntfy 推送通知 Owner。Owner 通过 cui Web UI 查看分析结果并确认或拒绝。包含超时处理（24h 无响应自动关闭）和状态持久化。

**验收标准**:
- [ ] 分析结果通过 ntfy 推送给 Owner（含 Issue 标题、类型、Web UI 链接）
- [ ] `core/notifier.py` 封装 ntfy HTTP API（`POST ntfy.sh/topic`）
- [ ] Owner 通过 cui Web UI 确认后流程继续到执行阶段
- [ ] Owner 拒绝后终止流程，Issue 评论"已拒绝"
- [ ] 24 小时无响应自动超时，Issue 评论"已超时关闭"
- [ ] 待确认状态持久化到 `data/agents/dev_bot/workspace/pending_issues.json`

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v -k "test_owner_confirm"
```

**测试用例**:
- test_owner_confirm_approve — Owner 确认后状态流转
- test_owner_confirm_reject — Owner 拒绝后状态终止
- test_owner_confirm_timeout — 超时后自动关闭
- test_owner_confirm_persistence — 待确认状态持久化和恢复
- test_ntfy_notification — ntfy 推送成功发送

---

### Task 1B.4a: Claude Agent SDK 集成评估 POC

**状态**: [ ] 未开始
**依赖**: Phase 1A
**产出文件**: `tools/claude_code_sdk.py`, `tests/unit/test_tools/test_claude_code_sdk.py`

**描述**:
安装 Claude Agent SDK，编写最小 POC 验证 `query()` 和 Hooks 在目标环境可用。封装为 `BaseTool` 子类，与 `claude_code_cli` 保持接口一致，支持通过配置切换。

**验收标准**:
- [ ] `claude-code-sdk` 包安装成功并加入 `pyproject.toml`
- [ ] `tools/claude_code_sdk.py` 实现 `ClaudeCodeSDK(BaseTool)`，`execute()` 调用 SDK `query()`
- [ ] Hooks 回调（PreCompact、Stop、PostToolUse）正常触发并记录日志
- [ ] 返回结构化结果：`session_id`、`cost_usd`、`num_turns`、`compact_count`、`needs_rotation`
- [ ] 对比 subprocess 和 SDK 执行同一任务的结果，记录评估结论
- [ ] `config/platform.yaml` 新增 `cli.backend: "subprocess" | "sdk"` 配置项

**测试命令**:
```bash
uv run pytest tests/unit/test_tools/test_claude_code_sdk.py -v
```

---

### Task 1B.4b: CUI /clear 命令支持

**状态**: [ ] 未开始
**依赖**: Phase 1A
**产出文件**: `services/cui/` 前后端修改

**描述**:
在 CUI 层面实现 /clear 等效功能：前端拦截命令，后端终止当前 CLI 子进程并启动新 session。

**验收标准**:
- [ ] CUI 前端拦截 `/clear` 命令（不发送到 CLI）
- [ ] 调用 CUI 后端 API 终止当前 CLI 子进程（SIGTERM）
- [ ] 后端创建新 session 记录
- [ ] 下一次用户输入时启动新 CLI 子进程
- [ ] 用户看到"上下文已清除，新会话已启动"确认消息

**测试命令**:
```bash
# 手动验证：在 cui 中输入 /clear，确认 session 重启
```

---

### Task 1B.5: 实现 Claude Code CLI/SDK 执行 + PR 创建

**状态**: [ ] 未开始
**依赖**: Task 1B.4, Task 1B.4a, Phase 1A（claude_code_cli 工具已存在）
**产出文件**: `agents/dev_agent.py` 扩展

**描述**:
Owner 确认后，调用 `claude_code_cli` 或 `claude_code_sdk`（根据配置）执行代码修复，运行测试，创建 PR 并在 Issue 下评论最终状态。支持复杂度自适应执行策略和 Session 轮换集成。

**验收标准**:
- [ ] 调用 `claude_code_cli` 或 `claude_code_sdk` 传入 Issue 内容和仓库路径（根据 `cli.backend` 配置）
- [ ] 执行过程中 Issue 评论"执行中"
- [ ] 执行完成后运行测试验证
- [ ] 执行失败时 ntfy 通知 Owner 并记录错误详情
- [ ] 通过 `git_tool` 创建 PR（标题关联 Issue 编号）
- [ ] Issue 下评论"已完成"并附 PR 链接
- [ ] PR 描述包含 Issue 分析摘要和修改说明
- [ ] SDK 执行支持：当 `cli.backend=sdk` 时通过 `claude_code_sdk` 工具执行
- [ ] 复杂度自适应：简单 Issue 单次调用（`max_turns=100`）；中等 Issue 轻量分解（2-3 步）；复杂 Issue 完整分解 + 轮换
- [ ] Session 轮换集成：通过 `SessionRotator.execute_with_rotation()` 执行，轮换信息记录到 Issue 评论

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v -k "test_issue_execution"
```

---

### Task 1B.5a: Session 轮换核心模块

**状态**: [ ] 未开始
**依赖**: Task 1B.4a
**产出文件**: `core/session_rotation.py`, `tests/unit/test_session_rotation.py`

**描述**:
实现 Session 轮换的核心逻辑：轮换配置、进度摘要生成、续接 prompt 构建、轮换生命周期管理。

**验收标准**:
- [ ] `RotationConfig` dataclass：`context_threshold`（默认 0.80）、`max_rotations`（默认 3）、`summary_max_tokens`（默认 2000）
- [ ] `SessionRotator.execute_with_rotation()`：封装 CLI/SDK 调用 + 轮换逻辑
- [ ] 进度摘要通过 LLM 生成（从 CLI/SDK 输出中提取已完成工作和剩余任务）
- [ ] 续接 prompt 包含原始任务 + 进度摘要 + 明确的续接指令
- [ ] 轮换次数超过 `max_rotations` 返回失败结果
- [ ] 每次轮换记录 `RotationRecord`（轮次、原因、摘要）
- [ ] 轮换配置从 `config/platform.yaml` 的 `session_rotation` 节读取

**测试命令**:
```bash
uv run pytest tests/unit/test_session_rotation.py -v
```

**测试用例**:
- test_rotation_config_defaults — 默认配置值正确
- test_execute_no_rotation — 正常执行无需轮换
- test_execute_single_rotation — 模拟 max_turns 停止 → 摘要 → 续接 → 成功
- test_execute_max_rotations_exceeded — 超过最大轮换次数报错
- test_progress_summary_generation — 进度摘要 LLM 调用（mock）
- test_continuation_prompt_format — 续接 prompt 格式正确

---

### Task 1B.6: 实现 bug_report 事件自动创建 Issue

**状态**: [ ] 未开始
**依赖**: Task 1B.3, Phase 1A（event_bus 已存在）
**产出文件**: `agents/dev_agent.py` 扩展

**验收标准**:
- [ ] 订阅 `bug_report` 事件类型
- [ ] 收到事件后通过 `git_tool` 创建 GitHub Issue
- [ ] Issue 标题和内容从事件 payload 提取
- [ ] 创建后触发正常的 Issue 分析流程

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v -k "test_bug_report_to_issue"
```

---

### Task 1B.6a: Session 轮换集成测试

**状态**: [ ] 未开始
**依赖**: Task 1B.5a, Task 1B.5
**产出文件**: `tests/unit/test_session_rotation.py` 扩展, `tests/integration/test_session_rotation.py`

**验收标准**:
- [ ] SDK Hooks 触发轮换：模拟 `PreCompact` Hook 触发 → `SessionRotator` 记录事件
- [ ] subprocess 结果检测：模拟 CLI 返回 `error_max_turns` → 摘要 → 续接 → 成功
- [ ] 复杂度自适应路由：简单 Issue 走单次调用、复杂 Issue 走分解+轮换
- [ ] 多次轮换：验证轮换计数和最大次数限制
- [ ] 所有测试通过，`core/session_rotation.py` 覆盖率 ≥ 80%

**测试命令**:
```bash
uv run pytest tests/unit/test_session_rotation.py tests/integration/test_session_rotation.py -v --cov=core/session_rotation --cov-report=term-missing
```

---

## 1B.3 — 集成与验证

### Task 1B.7: Issue 流程集成测试

**状态**: [ ] 未开始
**依赖**: Task 1B.5, Task 1B.6, Task 1B.6a
**产出文件**: `tests/unit/test_agents/test_dev_bot.py` 扩展

**验收标准**:
- [ ] 测试完整流程：GitHub Webhook → Issue 分析 → ntfy 通知 → Owner 确认 → CLI 执行 → PR 创建 → Issue 评论
- [ ] 测试异常路径：Owner 拒绝、执行超时、PR 创建失败、确认超时
- [ ] 测试 bug_report 事件 → 自动创建 Issue → 触发分析流程
- [ ] 所有测试通过

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v --cov=agents --cov=channels/github_webhook --cov-report=term-missing
```

---

### Task 1B.8: 更新 main.py + docker-compose.yml

**状态**: [ ] 未开始
**依赖**: Task 1B.7
**产出文件**: `main.py` 更新, `docker-compose.yml` 更新

**验收标准**:
- [ ] `main.py` 注册 GitHub Webhook 渠道
- [ ] FastAPI 路由 `POST /webhooks/github` 可用
- [ ] `GET /health` 端点包含 GitHub Webhook 渠道状态

**测试命令**:
```bash
uv run python -c "from main import create_app; app = create_app(); print('App created successfully')"
```

---

### Task 1B.9: 端到端验证

**状态**: [ ] 未开始
**依赖**: Task 1B.8

**验收标准**:
- [ ] `docker-compose up -d` 一键启动成功
- [ ] 创建 GitHub Issue 后，手机收到 ntfy 分析通知
- [ ] Owner 通过 cui Web UI 确认后，Claude Code 开始执行
- [ ] 执行完成后 PR 自动创建并关联 Issue
- [ ] Issue 下评论完整（分析中 → 执行中 → 已完成）
- [ ] `docker-compose logs` 无 ERROR 级别日志

---

### Task 1B.9a: Phase 1B 基础设施适配

**状态**: [ ] 未开始
**依赖**: Task 1B.7
**参考**: `docs/requirement.md` §3.5 横切面需求演进路线

**描述**:
确保 Phase 1B 新增的模块正确集成平台横切面基础设施。

**验收标准**:
- [ ] **安全**：GitHub Webhook 签名验证（`X-Hub-Signature-256`）已实现，验证失败返回 403 并记录日志
- [ ] **错误**：`core/errors.py` 新增 `WebhookVerificationError`、`SessionRotationError` 异常类型
- [ ] **日志**：`channels/github_webhook/channel.py` 和 `agents/dev_agent.py` 使用 `get_logger(__name__)`
- [ ] **Trace ID**：GitHub Webhook 入口调用 `set_trace_id()` 生成请求追踪 ID
- [ ] **审计**：`claude_code_cli`、`claude_code_sdk` 和 `git_tool` 的工具调用经过审计记录
- [ ] **测试**：`tests/conftest.py` 新增 `mock_github_webhook`、`mock_claude_cli`、`mock_claude_sdk`、`mock_session_rotator` fixtures
- [ ] **配置**：`config/platform.yaml` 的 `dispatch.routes` 包含 GitHub Webhook 路由；`cli.backend` 配置项可用

**测试命令**:
```bash
uv run pytest tests/ -v  # 全量回归
```

---

### Task 1B.10: Post-Phase 文档同步 + Git Tag

**状态**: [ ] 未开始
**依赖**: Task 1B.9, Task 1B.9a

**验收标准**:
- [ ] 本文件所有任务标记 `[x]`
- [ ] `docs/progress.md` Quick Status 更新
- [ ] 测试数更新到 Test Count History
- [ ] `git tag -a v0.2.0 -m "Phase 1B: GitHub Issue 自动化"`
- [ ] 推送 tag 到远程
