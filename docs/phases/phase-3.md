# Phase 3: 客服机器人

**分支**: `feat/phase-3-csbot`
**Tag**: `v0.3.0`
**前置**: Phase 2 完成（知识库已有内容）
**目标**: 用 Telegram 问产品问题，AI 能基于知识库回答

**完成条件**: Telegram 发消息后，AI 能基于知识库（Phase 2 已填充）回答产品问题；Bug 反馈自动触发开发机器人

---

> **待 Phase 2 完成后细化。** 以下为任务概览，详细的验收标准、接口规范和测试命令将在 Phase 2 Post-Phase 时补充。

## 任务概览

| # | 任务 | 状态 | 产出文件 |
|---|------|------|---------|
| 3.1 | 创建 `agents/reactive_agent.py`（客服机器人基类） | [ ] | `agents/reactive_agent.py` |
| 3.2 | 创建 `config/agents/customer_service.yaml` | [ ] | `config/agents/customer_service.yaml` |
| 3.3 | 实现客服对话流程：接收消息 → RAG 查询 → 回复 | [ ] | 客服机器人核心逻辑 |
| 3.4 | 实现多轮对话记忆（会话隔离） | [ ] | 会话管理 |
| 3.5 | 实现升级机制（知识库相似度连续 3 轮 < 0.6 → 通知 Owner） | [ ] | 升级逻辑 |
| 3.6 | 实现事件联动：Bug 反馈 → event_bus → 开发机器人创建 Issue | [ ] | 事件总线集成 |
| 3.7 | 客服机器人集成测试（含 RAG 回答验证） | [ ] | `tests/unit/test_agents/test_cs_bot.py` |
| 3.8 | 端到端验证 + 文档同步 + tag `v0.3.0` | [ ] | 本文件、Git tag |
