# Phase 4: 营销机器人

**分支**: `feat/phase-4-marketing`
**Tag**: `v0.4.0`
**前置**: Phase 3 完成 + Zhihu POC 通过
**目标**: 按计划自动发布引流文章，Telegram 报告结果

**完成条件**: 按定时任务发布引流文章，Telegram 收到报告

---

> **待 Phase 3 完成后细化。** 以下为任务概览，详细的验收标准、接口规范和测试命令将在 Phase 3 Post-Phase 时补充。

## POC 验证（Phase 4 前置）

| # | 任务 | 状态 | 产出文件 |
|---|------|------|---------|
| 4.0.1 | Playwright + 知乎 POC：手动操作发布 3 篇测试文章 | [ ] | `docs/poc/zhihu.md` |
| 4.0.2 | 观察 1 周：验证是否遭遇验证码、封号或限流 | [ ] | POC 报告 |
| 4.0.3 | POC 结论：通过 → 进入 Phase 4；失败 → 启用博客/RSS 替代方案 | [ ] | POC 报告 |

## 正式开发

| # | 任务 | 状态 | 产出文件 |
|---|------|------|---------|
| 4.1 | 实现 `tools/browser.py`（Playwright 浏览器自动化） | [ ] | `tools/browser.py` |
| 4.2 | 实现 `tools/web_search.py`（Serper/Tavily 搜索） | [ ] | `tools/web_search.py` |
| 4.3 | 实现 `tools/scheduler_tool.py`（APScheduler 定时任务） | [ ] | `tools/scheduler_tool.py` |
| 4.4 | 创建 `agents/marketing_agent.py`（营销机器人） | [ ] | `agents/marketing_agent.py` |
| 4.5 | 创建 `config/agents/marketing.yaml` | [ ] | `config/agents/marketing.yaml` |
| 4.6 | 实现文章生成 + 发布流程（知乎或博客/RSS 替代方案） | [ ] | 营销机器人核心逻辑 |
| 4.7 | 营销机器人集成测试 | [ ] | `tests/unit/test_agents/test_marketing_bot.py` |
| 4.7a | Phase 4 基础设施适配（见下方详细描述） | [ ] | `core/errors.py`, `tests/conftest.py` |
| 4.8 | 端到端验证 + 文档同步 + tag `v0.4.0` | [ ] | 本文件、Git tag |

---

### Task 4.7a: Phase 4 基础设施适配

**状态**: [ ] 未开始
**参考**: `docs/requirement.md` §3.5 横切面需求演进路线

**验收标准**:
- [ ] **安全 — Cookie 管理**：`data/sessions/` 目录 Cookie 文件 `chmod 600`；Cookie 失效时暂停任务并发送 Telegram 告警
- [ ] **安全 — 账号隔离**：营销机器人使用专用账号，不共享主号凭证
- [ ] **错误**：`core/errors.py` 新增 `BrowserError`（页面加载失败）、`CookieExpiredError`
- [ ] **存储**：文章发布记录持久化到 `data/agents/marketing_bot/workspace/published_articles.json`
- [ ] **日志**：`tools/browser.py` 和 `agents/marketing_agent.py` 使用 `get_logger(__name__)`，浏览器操作记录耗时
- [ ] **配置**：`config/agents/marketing.yaml` 创建，声明 `allowed_tools` 和 `schedule` 配置
- [ ] **测试**：`tests/conftest.py` 新增 `mock_playwright`、`mock_scheduler` fixtures
