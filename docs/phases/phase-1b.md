# Phase 1B: GitHub Issue 自动化

**分支**: `feat/phase-1b-issue-automation`
**Tag**: `v0.2.0`
**前置**: Phase 1A 完成
**目标**: GitHub 创建 Issue 后，机器人自动分析 → ntfy 通知 Owner → Owner 通过 Web UI 确认 → 执行修复并提 PR（半自动模式）
**预计时长**: 2 周

**完成条件**: GitHub 创建 Issue 后，开发机器人自动分析 Issue 类型 → ntfy 通知 Owner → Owner 通过 cui Web UI 确认 → Claude Code 执行修复 → Issue 下自动评论进度 → 自动创建 PR 并关联 Issue

---

## 1B.1 — GitHub Webhook 渠道

### Task 1B.1: 实现 channels/github_webhook/channel.py

**状态**: [ ] 未开始
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

**状态**: [ ] 未开始
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

**状态**: [ ] 未开始
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

**状态**: [ ] 未开始
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

### Task 1B.5: 实现 Claude Code CLI 执行 + PR 创建

**状态**: [ ] 未开始
**依赖**: Task 1B.4, Phase 1A（claude_code_cli 工具已存在）
**产出文件**: `agents/dev_agent.py` 扩展

**描述**:
Owner 确认后，调用 `claude_code_cli` 工具执行代码修复，运行测试，创建 PR 并在 Issue 下评论最终状态。

**验收标准**:
- [ ] 调用 `claude_code_cli` 传入 Issue 内容和仓库路径
- [ ] 执行过程中 Issue 评论"执行中"
- [ ] 执行完成后运行测试验证
- [ ] 执行失败时 ntfy 通知 Owner 并记录错误详情
- [ ] 通过 `git_tool` 创建 PR（标题关联 Issue 编号）
- [ ] Issue 下评论"已完成"并附 PR 链接
- [ ] PR 描述包含 Issue 分析摘要和修改说明

**测试命令**:
```bash
uv run pytest tests/unit/test_agents/test_dev_bot.py -v -k "test_issue_execution"
```

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

## 1B.3 — 集成与验证

### Task 1B.7: Issue 流程集成测试

**状态**: [ ] 未开始
**依赖**: Task 1B.5, Task 1B.6
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

### Task 1B.10: Post-Phase 文档同步 + Git Tag

**状态**: [ ] 未开始
**依赖**: Task 1B.9

**验收标准**:
- [ ] 本文件所有任务标记 `[x]`
- [ ] `docs/progress.md` Quick Status 更新
- [ ] 测试数更新到 Test Count History
- [ ] `git tag -a v0.2.0 -m "Phase 1B: GitHub Issue 自动化"`
- [ ] 推送 tag 到远程
