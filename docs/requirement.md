# 个人多智能体平台 — 需求文档

**版本**: v0.10
**日期**: 2026-03-10
**状态**: 已确认，开发中

---

## 1. 项目定位

### 1.1 一句话描述

> 一个运行在私有服务器上的**多智能体调度平台**，提供统一的工具基础设施（手脚）和渠道接入层，支持多种专业智能体（大脑）横向扩展，各智能体独立运行、通过事件总线松耦合协作。

### 1.2 设计哲学

- **平台 = 工具层 + 渠道层 + 调度层**（很少改动）
- **智能体 = 配置文件 + 可选扩展代码**（频繁新增）
- **新增机器人不改平台核心**，只需添加配置文件
- **工具原子化**，所有智能体共享同一套工具注册表
- **渠道适配器模式**，新渠道只需实现统一接口
- **事件驱动**，智能体间通过事件总线解耦通信，不直接调用

---

## 2. 用户与角色

### 2.1 Owner（唯一管理员）

- 即本项目使用者本人
- 负责配置平台、管理智能体、上传知识库
- 通过 Web UI (cui) 与开发机器人交互（需求澄清、任务执行、结果查看）
- 通过 Telegram 私信接收客服/营销/知识库机器人的执行报告和告警
- 通过 ntfy 接收开发机器人的推送通知（任务完成/失败）

### 2.2 消息用户（Message Users）

- 通过 Telegram / 网站（Chatwoot）发消息给客服机器人的客户
- 无需账号，直接发消息即可交互
- 平台对其身份做安全过滤（白名单 / 配对码）

---

## 3. 核心架构

### 3.1 分层模型

```
┌─────────────────────────────────────────────────────────┐
│                    渠道层 (Channel Layer)                 │
│   Web UI (cui) | Telegram Bot | GitHub Webhook | Chatwoot│
└───────────────────────┬─────────────────────────────────┘
                        │ 消息输入 / 事件触发
┌───────────────────────▼─────────────────────────────────┐
│                   调度层 (Dispatch Layer)                 │
│   路由引擎：根据渠道 + 消息类型 → 分发给对应智能体         │
│   事件总线：智能体间异步通信（松耦合）                     │
└──────────┬──────────────────┬───────────────────────────┘
           │                  │
┌──────────▼──────┐  ┌────────▼────────┐  ┌──────────────┐
│   客服机器人     │  │   营销机器人     │  │  开发机器人   │
│  (Reactive)     │  │  (Proactive)    │  │  (Event)     │
└──────────┬──────┘  └────────┬────────┘  └──────┬───────┘
           │                  │                  │
┌──────────▼──────────────────▼──────────────────▼───────┐
│                   工具层 (Tool Layer)                    │
│  browser | knowledge_base | git | code_exec | scheduler │
│  http_api | file | send_message | web_search | event_bus│
└─────────────────────────────────────────────────────────┘
                        │ 共享基础设施
┌───────────────────────▼─────────────────────────────────┐
│                  数据层 (Data Layer)                      │
│   客户对话历史 | 知识库向量数据库 | 任务队列 | 配置存储    │
└─────────────────────────────────────────────────────────┘
```

### 3.2 执行引擎分工

| 智能体 | 执行引擎 | Phase | 理由 |
|--------|---------|-------|------|
| 开发机器人 | Claude Code CLI / Agent SDK（可配置切换） | Phase 1A/1B | 1A: cui 直接使用 CLI；1B: GitHub Issue 自动化，支持 subprocess 或 SDK 双轨执行 |
| 知识库机器人 | Claude API（asyncio while 循环编排） | Phase 2 | 文档提取+知识库管理，线性 tool_use 循环 |
| 客服机器人 | Claude API（asyncio while 循环编排） | Phase 3 | 线性 tool_use 循环，朴素实现调试成本低；Phase 5 视需求升级 LangGraph |
| 营销机器人 | Claude API + Playwright | Phase 4 | 需要浏览器控制，API 负责内容生成 |

### 3.3 统一 Agent 响应协议（借鉴 OpenClaw Open Responses）

平台内部使用**厂商中立的统一响应格式**，不直接暴露各模型厂商的原始 API 格式，确保模型可替换。

```python
@dataclass
class AgentResponse:
    # 基础字段
    response_id: str             # 唯一响应 ID
    agent_id: str                # 来源智能体
    session_id: str              # 会话 ID
    model: str                   # 实际使用的模型（e.g. claude-sonnet-4-6）

    # 内容（Phase 1 纯文本，Phase 5 扩展多模态）
    content: str                 # 文本内容
    finish_reason: str           # stop | tool_use | max_tokens | error

    # 工具调用
    tool_calls: list[ToolCall]   # 空列表表示无工具调用

    # 元数据
    usage: TokenUsage            # input_tokens, output_tokens
    latency_ms: int

@dataclass
class ToolCall:
    tool_name: str
    tool_input: dict
    tool_use_id: str             # 用于匹配工具返回结果
```

> **Phase 5 升级路径**：当有多模态需求（图片/音频/文件）时，`content` 字段升级为 `list[ContentBlock]`；当有延迟敏感场景时，增加 `AsyncGenerator` 流式输出支持。Phase 1-4 直接发送完整消息即可。

**厂商切换保障**：
- LiteLLM 负责将各厂商响应归一化到 `AgentResponse`
- 切换模型（Claude → GPT-4o → 通义）不影响调度层和渠道层代码
- Fallback 链：主模型失败时自动降级，记录 WARNING 日志

### 3.4 跨层基础设施 — 日志系统

日志是**平台基础设施**，与 config、errors、constants 同级，不是某个智能体或渠道的功能。所有层（渠道层、调度层、智能体层、工具层）统一使用同一套日志基础设施。

#### 3.4.1 设计原则

- **统一入口**：所有模块通过 `get_logger(__name__)` 获取 logger，禁止直接 `print()` 或自建 logger
- **结构化输出**：生产环境使用 JSON 格式（便于 `jq` 查询和未来接入日志聚合），开发环境使用人类可读格式
- **请求级追踪**：每个用户请求携带 `trace_id`，贯穿渠道 → 调度 → 智能体 → 工具全链路，日志中自动附加
- **性能可观测**：关键操作（LLM 调用、工具执行、渠道消息处理）自动记录耗时
- **安全脱敏**：API Key、Token 等敏感信息在日志输出前自动打码

#### 3.4.2 Trace ID 传播机制

```
用户消息 → 渠道层生成 trace_id（UUID）
         → 调度层透传 trace_id
         → 智能体层透传 trace_id
         → 工具层透传 trace_id
         → 所有日志自动附加 trace_id 字段
```

- `trace_id` 通过 Python `contextvars.ContextVar` 实现，无需手动传参
- 与事件总线的 `PlatformEvent.correlation_id` 对齐：事件发布时将当前 `trace_id` 写入 `correlation_id`
- 日志输出示例（JSON 格式）：
  ```json
  {"ts": "2026-03-08T10:30:00Z", "level": "INFO", "module": "tools.knowledge_base", "trace_id": "abc-123", "msg": "RAG query completed", "duration_ms": 45}
  ```

#### 3.4.3 日志级别策略

| 级别 | 用途 | 示例 |
|------|------|------|
| **DEBUG** | 开发调试信息，生产环境关闭 | 工具输入参数详情、LLM prompt 内容 |
| **INFO** | 关键业务流程节点 | 用户消息接收、智能体开始处理、工具调用完成、LLM 响应返回 |
| **WARNING** | 异常但可恢复的情况 | Fallback 模型降级、插件加载失败跳过、知识库相似度低、被吞掉的异常 |
| **ERROR** | 需要关注的错误 | 工具执行失败、LLM API 错误、渠道连接断开 |
| **CRITICAL** | 平台级故障 | Redis 连接丢失、所有模型不可用、主进程异常退出 |

#### 3.4.4 日志输出配置

| 环境 | 格式 | 输出目标 | 级别 |
|------|------|---------|------|
| 开发 (`LOG_FORMAT=text`) | 人类可读（带颜色） | 控制台 stdout | DEBUG |
| 生产 (`LOG_FORMAT=json`) | JSON 结构化 | 控制台 stdout（Docker 收集） | INFO |

- 日志级别通过 `config/platform.yaml` 的 `logging.level` 或环境变量 `LOG_LEVEL` 配置，环境变量优先
- Docker 环境下日志输出到 stdout，由 Docker 日志驱动统一管理（轮转、保留策略在 `docker-compose.yml` 中配置）
- 非 Docker 环境可选文件输出，通过 `logging.file` 配置路径，使用 `RotatingFileHandler`（默认 10MB/文件，保留 5 个）

#### 3.4.5 性能日志

关键操作自动记录耗时，便于定位性能瓶颈：

| 操作 | 记录内容 | 级别 |
|------|---------|------|
| LLM 调用 | 模型名、input/output tokens、耗时 ms、finish_reason | INFO |
| 工具执行 | 工具名、耗时 ms、成功/失败 | INFO |
| 渠道消息处理 | 渠道 ID、从接收到响应的总耗时 ms | INFO |
| 知识库查询 | 查询耗时 ms、返回文档数、最高相似度 | DEBUG |

#### 3.4.6 实现位置

| 文件 | 职责 |
|------|------|
| `core/logging.py` | `setup_logging()`、`get_logger()`、JSON/Text Formatter、trace_id ContextVar、性能日志装饰器 |
| `core/audit.py` | 审计日志（工具调用记录）、敏感信息脱敏 Filter |

#### 3.4.7 Phase 升级路径

- **Phase 1**：实现完整日志基础设施（结构化输出、trace_id、性能日志、脱敏），所有后续 Phase 直接使用
- **Phase 5**：如有需要，接入外部日志聚合（ELK/Loki），JSON 格式天然兼容，无需改动日志代码

### 3.5 横切面需求演进路线

横切面关注点（日志、安全、存储、配置、测试基础设施）贯穿所有 Phase，不能假设"Phase 1A 一次性铺设完毕"。下表明确每个 Phase 需要新增或扩展的横切面需求，确保不被遗漏。

> **使用方式**：每个 Phase 的详细任务文件（`docs/phases/phase-N.md`）末尾包含一个"基础设施适配"任务，该任务的验收标准直接引用本表。

#### 3.5.1 安全演进

| Phase | 新增安全需求 | 实现位置 |
|-------|------------|---------|
| 1A | 速率限制、审计日志、日志脱敏、工具 Schema 校验 | `core/rate_limiter.py`, `core/audit.py` |
| 1B | GitHub Webhook 签名验证 | `channels/github_webhook/channel.py` |
| 1C | 敏感文件变更检测与自动回滚、子任务 prompt 安全指令注入 | `core/task_executor.py` |
| 1D | 项目初始化 API 路径校验（allowlist 正则 + base_path 白名单，防穿越） | `routes/projects.py` |
| 2 | 知识库文件路径沙箱（防止越权读取） | `tools/file_tool.py` |
| 3 | 用户配对码验证、Prompt Injection 防护、输入净化 | `core/security.py`, `core/agent_runtime.py` |
| 4 | Cookie 安全管理（chmod 600）、账号隔离 | `tools/browser.py` |

#### 3.5.2 存储演进

| Phase | 新增存储需求 | 实现位置 |
|-------|------------|---------|
| 1A | Redis（事件总线）、会话 JSONL 基础设施 | `core/event_bus.py`, `core/memory.py` |
| 1C | TaskPlan JSON 文件持久化 | `data/agents/dev_bot/workspace/task_plans/` |
| 1D | 无新增存储需求（项目创建在 Owner 指定路径） | — |
| 2 | ChromaDB 向量库初始化 + 文档写入 | `tools/knowledge_base.py` |
| 3 | 客服会话持久化（多客户隔离） | `data/agents/cs_bot/sessions/` |
| 4 | 文章发布记录 + Cookie 存储 | `data/agents/marketing_bot/workspace/` |

#### 3.5.3 配置演进

| Phase | 新增配置需求 | 实现位置 |
|-------|------------|---------|
| 1A | `platform.yaml` 基础结构 | `config/platform.yaml` |
| 1B | `dispatch.routes` 新增 GitHub Webhook 路由、`dev.yaml`、`session_rotation` 配置 | `config/` |
| 1C | `task_planning` 配置节（超时、子任务数上限、敏感文件模式） | `config/platform.yaml` |
| 1D | `project_initialization` 配置节（allowed_base_paths、git_user）、`sse.heartbeat_interval_seconds` | `config/platform.yaml` |
| 2 | `knowledge_base.yaml`、知识库 sources 配置 | `config/agents/` |
| 3 | `customer_service.yaml`、Telegram 渠道配置 | `config/agents/` |
| 4 | `marketing.yaml`、调度 cron 配置 | `config/agents/` |

#### 3.5.4 测试基础设施演进

| Phase | 新增 Fixtures / Mock | 实现位置 |
|-------|---------------------|---------|
| 1A | `mock_config`, `tmp_data_dir`, `event_loop` | `tests/conftest.py` |
| 1B | `mock_github_webhook`, `mock_claude_cli`, `mock_claude_sdk`, `mock_session_rotator` | `tests/conftest.py` |
| 1C | `mock_task_planner`, `mock_task_executor`, `sample_task_plan`, `sample_subtasks` | `tests/conftest.py` |
| 1D | `mock_project_init`, `mock_sse_client`, `mock_plan_event_broker`, `sample_sse_events` | `tests/conftest.py` |
| 2 | `mock_chromadb`, `mock_git_repo` | `tests/conftest.py` |
| 3 | `mock_telegram`, `mock_knowledge_base` | `tests/conftest.py` |
| 4 | `mock_playwright`, `mock_scheduler` | `tests/conftest.py` |

#### 3.5.5 错误类型演进

| Phase | 新增异常类型 | 实现位置 |
|-------|------------|---------|
| 1A | `PlatformError`, `ToolError`, `ChannelError`, `PermissionDeniedError`, `RateLimitError`, `ValidationError` | `core/errors.py` |
| 1B | `WebhookVerificationError`, `SessionRotationError` | `core/errors.py` |
| 1C | `TaskPlanError`, `TaskExecutionError`, `SubtaskTimeoutError`, `DirtyGitStateError`, `SensitiveFileError`, `CyclicDependencyError` | `core/errors.py` |
| 1D | `ProjectInitError`（项目创建失败）、`SSEConnectionError`（SSE 连接异常） | `core/errors.py` |
| 2 | `KnowledgeBaseError`（索引失败、查询超时） | `core/errors.py` |
| 3 | `EscalationError`（升级通知失败）、`SessionError` | `core/errors.py` |
| 4 | `BrowserError`（页面加载失败）、`CookieExpiredError` | `core/errors.py` |

---

## 4. 智能体详细需求

### 4.1 客服机器人 (Customer Service Bot)

**驱动方式**: 用户消息触发（被动响应）

**功能需求**:

| # | 功能 | 优先级 |
|---|------|--------|
| CS-1 | 接收 Telegram / Chatwoot 消息 | P0 |
| CS-2 | 基于产品知识库（RAG）回答客户问题 | P0 |
| CS-3 | 意图识别：区分咨询 / 购买意向 / 投诉 / 闲聊 | P0 |
| CS-4 | 多轮对话记忆（同一会话上下文连贯） | P0 |
| CS-5 | 多客户并发服务（会话隔离） | P0 |
| CS-6 | 销售引导：识别购买意向后推进转化流程 | P1 |
| CS-7 | 无法解决时通知 Owner 介入（触发条件：知识库查询相似度连续 3 轮低于阈值） | P1 |
| CS-8 | 将 Bug 反馈写入事件总线（触发开发机器人） | P2 |

**工具权限**:
- ✅ `knowledge_base` — 查询产品知识库
- ✅ `send_message` — 回复用户
- ✅ `event_bus.publish` — 发布 bug_report 事件
- ❌ `browser` — 不允许
- ❌ `code_exec` — 不允许
- ❌ `git` — 不允许

**渠道配置**:
```yaml
listen:
  - telegram      # 来自客户的 DM
  - chatwoot      # 网站嵌入客服（Chatwoot Bot API）
notify_owner:
  channel: telegram
  trigger: "连续3轮知识库查询相似度 < 0.6"  # 可编码的具体阈值
```

**初始知识库文档**：
- `data/knowledge/faq.md` — 产品常见问题与解答
- `data/knowledge/pricing.md` — 产品定价方案与套餐对比

---

### 4.2 营销机器人 (Marketing Bot)

**驱动方式**: 定时任务 / Owner 手动触发（主动执行）

**功能需求**:

| # | 功能 | 优先级 |
|---|------|--------|
| MK-1 | 按计划登录知乎等平台，发布引流文章 | P0 |
| MK-2 | AI 根据主题自动生成高质量文章内容 | P0 |
| MK-3 | 文章结尾自然植入引导（指向自有网站） | P0 |
| MK-4 | 执行完毕后向 Owner 发送 Telegram 报告 | P0 |
| MK-5 | 支持多平台（知乎 / 小红书 / 公众号等可扩展） | P2（Phase 5）|
| MK-6 | 记录已发文章避免重复，维护发布日历 | P1 |
| MK-7 | Owner 通过 Telegram 命令临时调整发布计划 | P2 |

**账号策略**：使用**专用新账号**（非主号），避免主号因自动发文被封禁。首次需手动注册并完成手机验证，之后 Playwright 保存 Cookie 自动复用。

**Phase 2 前置条件（POC 验证）**：
在正式开发营销机器人前，需完成 1 周真实测试：
- 手动操作 Playwright 登录知乎专用账号，发布 3 篇测试文章
- 观察 1 周内是否遭遇验证码、封号或限流
- POC 通过 → 进入 Phase 2 正式开发
- POC 失败 → 启用替代方案：营销机器人改为自动生成文章发布到**自建博客**（Hugo/Jekyll 静态站），通过 RSS 推送，同时在社交平台手动分享链接。此方案无反爬风险，营销机器人核心逻辑（AI 生成内容 + 定时调度 + 报告）不变，仅去掉 Playwright 浏览器自动化部分

**Cookie 生命周期管理**：
- 每次执行前发送 HEAD 请求检测 Cookie 是否有效（访问登录态接口）
- Cookie 过期时自动通知 Owner（Telegram 告警），暂停本次任务，由 Owner 手动刷新
- Cookie 文件明文存储在 `data/sessions/`，通过文件权限（`chmod 600`）保护
- Cookie 有效期预警：执行前检测失败即告警，不做定时预测

**工具权限**:
- ✅ `browser` — 登录平台、发布内容
- ✅ `web_search` — 搜索热点话题
- ✅ `file` — 读写文章草稿、发布记录
- ✅ `scheduler` — 定时触发
- ✅ `send_message` — 向 Owner 报告
- ❌ `knowledge_base` — 不需要（内容由 AI 生成）
- ❌ `code_exec` — 不允许
- ❌ `git` — 不允许

**调度配置**:
```yaml
schedule:
  - cron: "0 9 * * MON,WED,FRI"
    task: "在知乎发布1篇引流文章"
    topic_source: "web_search:最近热门技术话题"

platforms:
  zhihu:
    account_type: dedicated
    cookie_file: data/sessions/zhihu_session.json
    login_required: manual_first_time
```

---

### 4.3 开发机器人 (Dev Bot)

**驱动方式**: Owner 通过 Web UI (cui) 直接交互（主要）/ GitHub Issue Webhook（自动化）

**UI 方案**：集成开源项目 [wbopan/cui](https://github.com/wbopan/cui)（MIT 许可），Fork 源码到 `web/cui/` 目录，支持后续定制。cui 基于 `@anthropic-ai/claude-code` 官方 SDK，原生支持 Claude Code CLI 的工具调用展示、流式输出、后台任务执行和 ntfy 推送通知。

**功能需求**:

**Web UI 驱动（Phase 1A — Owner 直接通过 cui 使用 Claude Code，不经过 AgentRuntime）**:

> **Mode A 是开发机器人的主要使用模式**，覆盖所有开发场景：新产品/新项目创建、新功能开发、代码重构、Bug 修复、性能优化等。cui 支持**多项目切换**——每个会话可指定不同的工作目录，Owner 可以在同一个 Web UI 中管理多个独立项目。其能力等同于 Claude Code CLI 的完整功能集，平台提供部署、认证和通知基础设施。Mode B（GitHub Issue 自动化）是 Mode A 的补充，自动化处理特定的 Issue 驱动工作流。

| # | 功能 | 优先级 |
|---|------|--------|
| DV-1 | Owner 通过 Web UI (cui) 下达开发任务（新功能、重构、修复等） | P0 |
| DV-2 | 多轮需求澄清对话（Claude Code 读取项目代码后主动提问，确认需求边界） | P0 |
| DV-3 | Claude Code 生成执行计划，Owner 在 Web UI 中确认 | P0 |
| DV-4 | Claude Code CLI 执行开发任务（cui 实时展示过程） | P0 |
| DV-5 | 运行测试，Web UI 展示执行结果（成功/失败/测试覆盖） | P0 |
| DV-6 | 创建 Pull Request 或直接提交到指定分支 | P0 |
| DV-7 | 后台任务执行（关闭浏览器后任务继续），通过 ntfy 推送完成通知 | P1 |

**GitHub Issue 驱动（Phase 1B — 开发机器人正式上线，通过 AgentRuntime 编排）**:

| # | 功能 | 优先级 |
|---|------|--------|
| DV-8 | 监听 GitHub Issue 创建事件（Webhook + 签名验证） | P0 |
| DV-9 | AI 分析 Issue（Bug / Feature / 优化），ntfy 推送通知 Owner | P0 |
| DV-10 | Owner 通过 Web UI 确认或拒绝执行 | P0 |
| DV-11 | Issue 下自动评论进度（分析中 → 执行中 → 已完成/失败） | P0 |
| DV-12 | 接收事件总线的 bug_report 自动创建 Issue | P1 |
| DV-13 | 支持多个代码仓库（通过配置文件定义列表） | P2（Phase 5）|
| DV-14 | Claude Agent SDK 集成：封装 `query()` 调用、Hooks 回调（PreCompact/Stop）、结构化返回值 | P0 |
| DV-15 | 复杂度自适应执行策略：简单 Issue 单次调用、中等 Issue 轻量分解、复杂 Issue 完整分解 + 轮换 | P0 |
| DV-16 | Session 轮换：任务分解 + 结果检测自动续接（进度摘要 → 续接 prompt → 新 session 继续） | P1 |
| DV-17 | CUI /clear 命令支持：前端拦截 → 后端终止当前 CLI 子进程 → 启动新 session | P1 |

**需求驱动开发（Phase 1C — 大需求分解 + 多任务独立执行，解决上下文膨胀问题）**:

> **Mode C 是 Mode A 的自动化升级**。采用 **Markdown-First + JSON Runtime** 架构：Owner 在 cui 中与 Claude Code 协作产出 phase-N.md（需求澄清+任务分解，格式与本项目 phase-1a/1b 一致）→ Owner 确认后 CLI 调用 `POST /api/requirements/from-phase` → 平台 PhaseFileParser 解析 markdown 为 TaskPlan JSON → dev_bot 逐个在全新 CLI 上下文中独立执行 → 每个子任务完成后回写 phase-N.md `[x]` + 更新 JSON → 全部完成创建 PR。phase-N.md 是 Source of Truth（人负责写改审），JSON 是 Runtime State（丢了可重建）。Mode B 和 Mode C 共存。

| # | 功能 | 优先级 |
|---|------|--------|
| DV-18 | 需求澄清与任务分解（人机协作）：Owner 在 cui 中与 Claude Code 多轮对话，协作产出 phase-N.md 文件（格式与项目现有 phase 文件一致） | P0 |
| DV-19 | PhaseFileParser：解析 phase-N.md 为 TaskPlan JSON（regex 解析，~120 行），支持回写 `[ ]` → `[x]` | P0 |
| DV-20 | （已合并到 DV-18，需求澄清和任务分解是同一个对话流中的连续过程） | — |
| DV-21 | 多任务串行执行：按拓扑序逐个调用 Claude CLI（每个子任务=全新上下文），prompt 含 Session Recovery 覆盖指令 | P0 |
| DV-22 | 上下文传递：前序任务的结果摘要注入后续任务的 prompt | P0 |
| DV-23 | Smart Checkpoint：检查 `git status --porcelain` 后选择性 commit + 回写 phase-N.md `[x]` | P0 |
| DV-24 | 失败处理：子任务失败自动暂停，支持重试/重试+反馈/跳过/终止 | P0 |
| DV-25 | 敏感文件保护：子任务修改 .env 等敏感文件时自动回滚 + 撤销 markdown 回写并通知 | P0 |
| DV-26 | 执行进度通知：ntfy 推送关键事件（开始、完成、失败），cui 展示实时进度 | P1 |
| DV-27 | 紧急停止：Owner 可随时终止执行，保留已完成的 checkpoints | P1 |
| DV-28 | 连续失败保护：连续 2 个子任务失败自动终止计划 | P1 |
| DV-29 | 需求开发 REST API：`POST /api/requirements/from-phase` 为核心端点，另含 abort/retry/skip 控制端点 | P0 |
| DV-30 | Phase 文件模板：提供 phase-template.md + CLAUDE.md 扩展模板，支持新项目初始化 | P1 |

**cui 全流程集成（Phase 1D — 从对话到自动执行，零命令行体验）**:

> **Mode D 是 Mode C 的 UI 升级**。Owner 在 cui 浏览器中与 Claude Code 对话即可完成全流程：需求澄清 → 任务分解 → 一键提交执行 → 实时进度查看 → 干预控制。Claude Code 通过 MCP Tool 自动调用平台 API，前端 SSE 订阅实时展示执行进度。

| # | 功能 | 优先级 |
|---|------|--------|
| DV-31 | 项目初始化 API：平台 API 自动创建 git 仓库 + phase 骨架，支持 Owner 从零创建新项目 | P1 |
| DV-32 | MCP Tool Bridge：Platform MCP Server 暴露 5 个工具（init_project、submit_phase、get_plan_status、control_task、abort_plan），Claude Code 原生理解并自主调用 | P0 |
| DV-33 | SSE 实时进度推送：进程内 PlanEventBroker fan-out + FastAPI SSE 端点，支持多客户端订阅 | P0 |
| DV-34 | RequirementPanel：cui 侧边栏实时展示执行进度（进度条 + 任务卡片 + 操作按钮），MCP Tool 返回 plan_id 自动触发 | P0 |

**工具权限**（Phase 1B 自动化流程使用）:
- ✅ `claude_code_cli` — 核心执行引擎（子进程调用）
- ✅ `claude_code_sdk` — Agent SDK 执行引擎（编程式调用，可配置替代 CLI）
- ✅ `git` — 仓库操作
- ✅ `github_api` — Issue / PR / Webhook
- ✅ `event_bus.subscribe` — 监听 bug_report 事件
- ❌ `browser` — 不需要
- ❌ `knowledge_base` — 不需要
- ❌ `send_message` — 不需要（Phase 1A 用 cui 交互，通知用 ntfy）

> **说明**：Phase 1A 中 Owner 直接通过 cui Web UI 与 Claude Code 交互，不经过平台的 AgentRuntime。平台为 cui 提供基础设施（部署、认证、推送通知）。Phase 1B 的 GitHub Issue 自动化才使用平台的 AgentRuntime + 工具层。

**仓库配置**（`config/agents/dev.yaml`）：
```yaml
github:
  repos:
    - owner: "your-username"
      name: "private-agent-platform"
      branch: "main"
    # 可随时追加更多仓库
```

**Phase 1 前置条件（POC 验证）**：
- 模拟 10 个开发任务**逐个**测试 Claude Code CLI 稳定性（个人平台串行处理，不测并发）
- 观察运行行为：记录耗时分布和输出长度，确认无异常长时间运行（订阅模式，无需关注 token 费用）
- 验证网络中断场景下的恢复能力

**运行安全控制**（订阅模式，无需 token 费用管控）：
- 单次 Claude Code CLI 调用设超时保护（默认 10 分钟），防止无限循环
- 超时后自动终止子进程，ntfy 通知 Owner

**安全约束**：
- Phase 1 初期在本机直接运行（沙箱模式 off），清除 `ANTHROPIC_API_KEY` 等敏感环境变量后传入专用受限 Token
- 仓库写权限通过 `GITHUB_TOKEN` 受限（只有目标仓库的 PR 权限）
- cui Web UI 通过反向代理 + 认证保护（nginx/Caddy + Basic Auth 或 API Token）
- Phase 5 有真实安全需求时升级至独立 Docker 容器运行

---

### 4.4 知识库机器人 (Knowledge Base Bot)

**驱动方式**: 定时任务（自动同步）+ Owner Telegram 命令（手动管理）

**功能需求**:

| # | 功能 | 优先级 |
|---|------|--------|
| KB-1 | 自动从代码仓库提取文档（README、docstring、API 签名） | P0 |
| KB-2 | 将提取的内容写入 ChromaDB 向量知识库 | P0 |
| KB-3 | 定时检测代码仓库变更，增量更新知识库 | P0 |
| KB-4 | Owner 通过 Telegram 命令手动管理（如"把这篇文章加入知识库"、"刷新知识库"） | P0 |
| KB-5 | 从用户反馈（客服对话）中自动提炼 FAQ，补充知识库 | P1 |
| KB-6 | 知识库内容去重和质量评估 | P1 |
| KB-7 | 执行完毕后向 Owner 发送 Telegram 报告（新增/更新了哪些文档） | P0 |

**工具权限**:
- ✅ `knowledge_base` — 查询、写入、管理向量知识库
- ✅ `git` — 读取代码仓库（clone/pull）
- ✅ `file` — 读写文档文件
- ✅ `send_message` — 向 Owner 报告
- ✅ `event_bus.subscribe` — 监听 new_customer / bug_report 等事件提炼信息
- ❌ `browser` — 不需要
- ❌ `code_exec` — 不允许
- ❌ `claude_code_cli` — 不允许

**调度配置**:
```yaml
schedule:
  - cron: "0 2 * * *"           # 每天凌晨 2 点自动同步
    task: "从配置的代码仓库增量更新知识库"

sources:
  repos:                         # 从哪些仓库提取文档
    - owner: "your-username"
      name: "your-product"
      paths: ["README.md", "docs/", "src/**/*.py"]  # 提取范围
  manual:                        # Owner 手动添加的来源
    - data/knowledge/            # 本地知识库目录

commands:                        # Owner Telegram 命令
  - "/kb refresh"                # 立即全量刷新
  - "/kb add <url-or-text>"      # 手动添加内容
  - "/kb status"                 # 查看知识库状态（文档数、最后更新时间）
```

---

## 5. 工具层详细需求

所有工具原子化，任何智能体可按权限使用。

### 5.1 工具清单

| 工具名 | 功能描述 | 依赖 |
|--------|---------|------|
| `browser` | Playwright 浏览器自动化：导航、点击、截图、表单 | Playwright |
| `knowledge_base` | 向量数据库查询（RAG）+ 文档上传管理 | ChromaDB |
| `web_search` | 搜索引擎查询，返回摘要 | Serper / Tavily API |
| `file` | 读写本地文件，含沙箱路径限制 | 内置 |
| `http_api` | 通用 HTTP 请求（GET/POST/webhook） | httpx |
| `git` | git clone / commit / push / PR 创建 | PyGitHub + git |
| `claude_code_cli` | 启动 Claude Code 子进程，管理会话 | claude binary |
| `claude_code_sdk` | Claude Agent SDK 编程式调用，支持 Hooks 和结构化返回 | claude-code-sdk |
| `code_exec` | 沙箱内执行代码（Python / Bash） | Docker sandbox |
| `scheduler` | 注册 / 取消定时任务 | APScheduler |
| `send_message` | 向指定渠道发送消息（Telegram） | python-telegram-bot |
| `event_bus` | 发布 / 订阅平台内部事件 | Redis Queue（持久化，支持多进程） |

### 5.2 工具注册接口（统一规范）

```python
class BaseTool:
    name: str                    # 唯一标识
    description: str             # AI 用于决策的描述
    input_schema: dict           # JSON Schema 参数定义

    async def validate_input(self, params: dict) -> bool:
        """调用前 JSON Schema 校验，防止注入（借鉴 OpenClaw）"""
        ...

    async def execute(self, params: dict) -> ToolResult:
        """validate_input 通过后才执行"""
        ...
```

### 5.3 工具权限控制（直接声明模式）

Phase 1-4 每个智能体直接在配置文件中列出 `allowed_tools`，无需 Profile 中间层：

```yaml
# 智能体配置中直接声明（config/agents/customer_service.yaml）
tools:
  allowed: [knowledge_base, send_message, event_bus]
```

**运行时要求**：
- 工具白名单在调用前动态校验，不可绕过
- 未声明的工具，调用时返回 `PermissionDeniedError`

> **Phase 5 升级路径**：当智能体数量 > 4、工具集重叠明显时，再引入 Profile 系统（`config/tool_profiles.yaml`）减少重复配置。

---

## 6. 渠道层详细需求

### 6.1 渠道清单

| 渠道 | 用途 | 优先级 | 说明 |
|------|------|--------|------|
| Web UI (cui) | 开发机器人交互（需求澄清、任务执行、结果查看） | P0 | 开源 Claude Code Web UI，Fork 集成到 `web/cui/` |
| Telegram Bot | 客服输入 + Owner 通知 + 命令控制 | P0（Phase 3） | 官方 API，最稳定 |
| GitHub Webhook | 开发机器人 Issue 触发 | P0（Phase 1B） | 监听 issues.opened |
| Chatwoot | 网站嵌入客服组件 | P2（Phase 5）| 开源客服平台，Bot API 对接，Docker Compose 部署 |
| 飞书 | 暂不接入 | — | 未来如有需要再评估 |
| 微信 | 暂不接入 | — | 等待稳定方案 |

### 6.2 渠道适配器接口（简单继承）

Phase 1-4 使用简单继承，`BaseChannel` 包含所有必要接口，渠道直接继承并按需覆写：

```python
# channels/base.py

class BaseChannel:
    """所有渠道必须继承的基类"""
    id: str                          # 唯一标识
    on_message: Callable             # 收到消息时回调（注入调度层）
    dm_policy: str = "pairing"       # pairing | open
    allowed_users: list[str] = []    # 白名单用户 ID

    async def start(self): ...       # 启动监听
    async def stop(self): ...        # 优雅停止
    async def send(self, recipient: str, message: Message): ...
    async def verify_user(self, user_id: str) -> bool: ...

# 渠道直接继承，只覆写需要定制的方法
class TelegramChannel(BaseChannel): ...
class GitHubWebhookChannel(BaseChannel): ...
```

**设计原则**：
- Phase 1-4 渠道数 ≤ 3，简单继承比 Mixin 多继承更易调试
- 接口稳定：`start/stop/send/on_message` 四个核心方法不变

> **Phase 5 升级路径**：渠道数 ≥ 5、能力差异明显时（如需要 `VoiceMixin`、`ThreadingMixin`），再重构为 Mixin 模式。接口签名不变，调度层无需修改。

### 6.3 渠道插件化机制（Phase 5 实现，借鉴 OpenClaw）

> **Phase 1-4**：渠道数 ≤ 3，使用简单 import 在 `channel_manager.py` 中显式注册，无需插件发现机制。
> **Phase 5**：渠道数 ≥ 4 时，启用以下插件化机制。

渠道以**插件包**形式组织，平台启动时自动发现并加载，新增渠道无需修改核心代码：

```
channels/
├── base.py                  # BaseChannel 接口定义（平台核心，不改动）
├── telegram/                # 内置渠道（P0）
│   ├── __init__.py
│   └── channel.py
├── github_webhook/          # 内置渠道（P0）
│   └── channel.py
└── plugins/                 # 插件渠道（安装即生效）
    ├── chatwoot/            # Phase 5
    └── feishu/              # 未来扩展
```

**插件注册规范（Manifest + 动态 import）**：

每个插件目录包含 `manifest.yaml` 和 `channel.py`：

```
channels/plugins/chatwoot/
├── manifest.yaml       # 插件元数据（必须）
└── channel.py          # 实现 BaseChannel（必须）
```

`manifest.yaml` 格式：
```yaml
name: chatwoot
version: "1.0.0"
description: "Chatwoot 开源客服平台适配器"
entry: channel.py           # 入口文件
class: ChatwootChannel      # 导出的类名
requires:                   # 依赖的 Python 包（自动检测）
  - httpx>=0.27
config_schema:              # 插件专属配置的 JSON Schema
  type: object
  properties:
    api_url: {type: string}
    api_token: {type: string}
```

**动态加载流程**（`core/channel_manager.py`）：
1. 扫描 `channels/plugins/` 所有子目录，读取 `manifest.yaml`
2. 对比 `config/platform.yaml` 的 `channels.plugins` 启用列表，过滤未启用插件
3. 校验 `manifest.yaml` 格式（版本、必填字段）
4. 用 `importlib.import_module()` 动态加载 `channel.py`，实例化声明的类
5. 校验类是 `BaseChannel` 的子类（`issubclass` 检查）
6. 注册到渠道注册表

**隔离原则**：
- 单个插件加载失败 → 记录 `WARNING` 日志，跳过该插件，其他渠道正常启动
- 插件不得修改 `core/` 任何文件（CI 检查：插件 PR 不得包含 `core/` 的 diff）
- 插件依赖包不满足时，日志提示 `pip install` 命令后跳过

---

## 7. 事件总线需求

智能体间通过事件解耦，不直接调用。使用 **Redis Queue** 作为事件总线后端，保证进程重启后事件不丢失，支持多 worker 共享。

### 7.1 事件类型定义

| 事件类型 | 发布者 | 订阅者 | 描述 |
|----------|--------|--------|------|
| `bug_report` | 客服机器人 | 开发机器人 | 客户反馈 Bug，自动创建 Issue |
| `article_published` | 营销机器人 | Owner 通知 | 文章发布成功，附链接 |
| `pr_created` | 开发机器人 | Owner 通知 | PR 已提交，待审核 |
| `task_failed` | 任意机器人 | Owner 告警 | 任务执行失败，需介入 |
| `new_customer` | 客服机器人 | 数据存储 | 新客户首次联系，记录档案 |

### 7.2 事件结构

```python
@dataclass
class PlatformEvent:
    event_id: str                # UUID，去重和幂等
    type: str                    # 事件类型
    source_agent: str            # 来源智能体
    payload: dict                # 事件数据
    timestamp: datetime
    correlation_id: str          # 追踪链路
```

---

## 8. Agent 工作区与持久记忆需求（借鉴 OpenClaw）

每个智能体拥有独立的持久化工作区，支持跨会话记忆。

### 8.1 工作区结构

```
data/agents/
├── dev_bot/
│   └── workspace/
│       ├── MEMORY.md
│       └── issue_log.json     # 已处理 Issue 记录
├── kb_bot/
│   └── workspace/
│       ├── MEMORY.md
│       └── sync_log.json      # 知识库同步记录
├── cs_bot/
│   ├── workspace/
│   │   ├── MEMORY.md          # 智能体持久记忆（人类可读，版本控制友好）
│   │   └── notes/             # 临时工作文件
│   └── sessions/              # 对话历史（按 session_id 分目录）
└── marketing_bot/
    └── workspace/
        ├── MEMORY.md
        └── published_articles.json   # 已发文章记录
```

### 8.2 MEMORY.md 规范

- 纯文本 Markdown，智能体可读写，Owner 可直接编辑
- 每次会话结束后，智能体将关键信息提炼写入 MEMORY.md
- 新会话开始时，MEMORY.md 内容注入系统 Prompt（超过 2000 token 时自动摘要压缩）
- 结合 ChromaDB 向量搜索，支持"语义检索历史记忆"

### 8.3 会话持久化（借鉴 OpenClaw Session Persistence）

会话不仅存于内存，需持久化到磁盘，支持重启恢复和历史追溯。

**存储格式**（`data/agents/<agent_id>/sessions/<session_id>/`）：

```
sessions/
└── <session_id>/
    ├── messages.jsonl       # 增量追加，每行一条消息（delta 格式）
    ├── metadata.json        # 会话元数据（创建时间、模型、用户ID等）
    └── snapshot.json        # 压缩快照（每 30 轮或手动触发时生成）
```

**Delta 追加规范**（`messages.jsonl`）：
```jsonl
{"seq": 1, "role": "user",      "content": "...", "ts": 1700000001}
{"seq": 2, "role": "assistant", "content": "...", "ts": 1700000002, "tokens": 150}
{"seq": 3, "role": "tool_result","tool": "knowledge_base", "content": "...", "ts": 1700000003}
```
- 只追加、不修改；每次 `flush` 写入磁盘
- `snapshot.json` 是对 `messages.jsonl` 的压缩摘要，加载时优先读快照

### 8.4 Context 窗口裁剪策略

避免长会话超出模型上下文限制，分两级触发：

| 触发条件 | 裁剪动作 | 保留内容 |
|---------|---------|---------|
| 历史 token 超过模型上限的 80% | 截断最旧轮次（直接删除，无 LLM 摘要） | 系统 Prompt + 最新 15 轮 |
| 单条消息超过 8000 token | 截断该消息内容，附注 `[内容已截断]` | — |

**实现位置**：`core/memory.py` 的 `ContextPruner` 类，在每次调用 LLM 前执行。

> **设计说明**：去掉第一级"LLM 生成摘要"——摘要本身消耗 token 且可能出错，直接截断对客服机器人场景影响极小（用户不会在单次会话中聊超过 15 轮）。Phase 5 有真实长会话需求时再评估。

---

## 9. 配置系统需求

配置驱动，新增机器人不改代码。

### 9.1 平台配置（`config/platform.yaml`）

```yaml
platform:
  name: "My Agent Platform"
  owner_telegram_id: "YOUR_TELEGRAM_ID"

models:
  default: claude-sonnet-4-6
  fallback:
    - gpt-4o
    - qwen-plus
  # API Key 从 .env 读取（ANTHROPIC_API_KEY），不写入此文件
  # 触发 rate limit 时手动切换 Key；个人使用触发概率极低，无需自动轮换

security:
  dm_policy: pairing             # pairing | open
  allowed_users: []              # 空=使用配对码验证

storage:
  vector_db: chroma
  vector_db_path: ./data/chroma
  session_db: ./data/sessions

logging:
  level: INFO                    # DEBUG | INFO | WARNING | ERROR（环境变量 LOG_LEVEL 优先）
  format: text                   # text（开发）| json（生产）（环境变量 LOG_FORMAT 优先）
  # file: ./data/logs/platform.log  # 可选：文件输出（RotatingFileHandler，10MB × 5）

channels:
  plugins: []                    # 启用的插件渠道列表（如 chatwoot）
```

### 9.2 智能体配置（`config/agents/*.yaml`）

```yaml
# config/agents/customer_service.yaml
name: cs_bot
type: reactive
model: claude-sonnet-4-6

tools:
  allowed: [knowledge_base, send_message, event_bus]  # 直接声明，无需 Profile

workspace:
  memory_file: data/agents/cs_bot/workspace/MEMORY.md
  session_dir: data/agents/cs_bot/sessions/

channels:
  listen: [telegram, chatwoot]

knowledge_base:
  sources:
    - data/knowledge/faq.md
    - data/knowledge/pricing.md

persona: |
  你是专业客服助手，友善、简洁、专业。
  当用户有明确购买意向时，引导他们访问 [网站URL]。

escalation:
  similarity_threshold: 0.6      # 知识库查询相似度阈值
  consecutive_misses: 3          # 连续低于阈值的轮次
  action: notify_owner
```

---

## 9. 安全需求

| 需求 | 说明 |
|------|------|
| 新用户配对码 | 陌生用户首次联系，需输入配对码验证身份；**失败 5 次后锁定该用户 24h** |
| 工具白名单 | 每个智能体只能访问配置中声明的工具；运行时动态校验，不可绕过 |
| 路径沙箱 | `file` 工具限制在指定目录，禁止越权访问；禁止软链接穿透 |
| 命令审批 | `code_exec` 执行高危命令时，通知 Owner 确认；**高危命令黑名单**：`rm -rf`、`mkfs`、`dd`、`wget|curl ... | sh`、修改 `/etc/` 等 |
| 密钥隔离 | API Key 存储在 `.env`，不写入配置文件，不提交 git |
| Claude CLI 隔离 | 启动子进程时清除 `ANTHROPIC_API_KEY` 等环境变量；在独立容器内运行 |
| **GitHub Webhook 签名验证** | 所有 Webhook 请求必须携带 `X-Hub-Signature-256` 并校验；未通过者返回 403 且记录日志 |
| **Prompt Injection 防护** | 用户输入不得直接拼接到系统 Prompt；渠道输入需经过净化（过滤控制字符、截断超长输入） |
| **速率限制** | 单用户每分钟最多 10 条消息；API 调用加指数退避重试（最多 3 次）；**Phase 1 实现** |
| **事件总线 Schema 校验** | 所有事件必须符合 `PlatformEvent` 数据结构，拒绝格式异常的事件 |
| **审计日志** | 记录所有工具调用（时间、智能体、工具名、参数摘要、结果状态）；日志不含敏感数据明文；**Phase 1 实现** |
| **日志敏感信息脱敏** | API Key、Token 等敏感信息在日志中自动打码（借鉴 OpenClaw）；**Phase 1 实现** |
| **工具输入 Schema 校验** | 所有工具调用前做 JSON Schema 校验，防止参数注入（借鉴 OpenClaw）；**Phase 1 实现** |
| **Cookie 文件保护** | Session 文件明文存储，`chmod 600` 限制访问权限；私有服务器单用户场景下足够 |
| **Cookie 失效处理** | 检测到失效时暂停任务并发送 Telegram 告警，由 Owner 手动刷新；不做自动续期 |

> **沙箱策略**：Phase 1-4 使用 `off` 模式（本机直接执行），通过环境变量隔离和文件权限控制安全边界。Phase 5 有外部用户接入时评估是否需要容器沙箱。

---

## 10. 技术栈

| 层 | 技术 | 版本 | 说明 |
|----|------|------|------|
| 语言 | Python | 3.11+ | 主语言 |
| API 框架 | FastAPI | latest | 异步 Web 框架（GitHub Webhook 接收） |
| 智能体编排 | asyncio while 循环 | — | Phase 1-4 线性 tool_use 循环；Phase 5 再评估 LangGraph |
| 包管理 | uv | latest | 快速 Python 包管理，`uv.lock` 确保确定性构建 |
| 代码质量 | ruff + pre-commit | latest | Linter + Formatter 二合一，commit 前自动检查 |
| 模型统一接口 | LiteLLM | **锁定具体版本**（任务 1.2 时确定并写入 `pyproject.toml`） | 切换 Claude/GPT/通义；固定版本避免 breaking change |
| 知识库 / RAG | ChromaDB | latest | 本地向量数据库 |
| 浏览器自动化 | Playwright | latest | 营销机器人内容发布 |
| 任务调度 | APScheduler | 3.x | 定时营销任务 |
| 开发机器人 Web UI | cui (wbopan/cui) | Fork 集成 | Claude Code Web UI，MIT 许可，后台任务 + ntfy 推送 |
| 推送通知 | ntfy | latest | 开发机器人任务完成推送（替代 Telegram 通知） |
| Telegram SDK | python-telegram-bot | v20+ | 异步原生（Phase 3 客服机器人） |
| GitHub SDK | PyGitHub | latest | Issue / PR 操作 |
| 网站客服 | Chatwoot | latest | 开源客服平台，Phase 5 接入 |
| 事件总线 | Redis Queue | latest | 持久化，支持多进程；Docker Compose 一起启动 |
| 部署 | Docker Compose | latest | 一键启动所有服务 |

---

## 11. 项目目录结构

```
private-agent-platform/
│
├── core/                        # 平台核心（极少改动）
│   ├── agent_runtime.py         # 智能体运行循环（asyncio while 循环，Phase 5 评估 LangGraph）
│   ├── tool_registry.py         # 工具注册与权限控制
│   ├── channel_manager.py       # 渠道生命周期
│   ├── event_bus.py             # 事件总线（Redis Queue）
│   ├── dispatch.py              # 消息路由调度
│   ├── logging.py               # 日志基础设施（结构化输出、trace_id、性能日志）
│   ├── audit.py                 # 审计日志 + 敏感信息脱敏
│   ├── memory.py                # 对话记忆管理
│   ├── errors.py                # 自定义异常
│   └── constants.py             # 平台常量
│
├── tools/                       # 原子工具（可独立测试）
│   ├── base.py
│   ├── browser.py
│   ├── knowledge_base.py
│   ├── web_search.py
│   ├── file_tool.py
│   ├── git_tool.py
│   ├── claude_code_cli.py       # Claude Code 子进程封装
│   ├── code_exec.py
│   ├── scheduler_tool.py
│   ├── send_message.py
│   └── event_bus_tool.py
│
├── channels/                    # 渠道适配器（D 级改进：插件化）
│   ├── base.py                  # BaseChannel 接口（不改动）
│   ├── telegram/                # 内置渠道
│   │   └── channel.py
│   ├── github_webhook/          # 内置渠道
│   │   └── channel.py
│   └── plugins/                 # 插件渠道（Phase 5，自动发现）
│       └── chatwoot/            # Phase 5
│           └── channel.py
│
├── agents/                      # 智能体实现
│   ├── base_agent.py
│   ├── dev_agent.py             # 开发机器人（Phase 1B GitHub Issue 自动化）
│   ├── kb_agent.py              # 知识库机器人（Phase 2）
│   ├── reactive_agent.py        # 客服机器人（Phase 3）
│   └── proactive_agent.py       # 营销机器人（Phase 4）
│
├── web/                         # Web UI 前端
│   └── cui/                     # Claude Code Web UI（Fork 自 wbopan/cui，MIT）
│       ├── src/                 # cui 源码（TypeScript/Node.js）
│       ├── package.json
│       └── ...
│
├── config/                      # 配置文件（不含密钥）
│   ├── platform.yaml            # 平台配置（含 channels.plugins 启用列表）
│   └── agents/                  # 智能体配置（直接声明 allowed_tools）
│       ├── dev.yaml             # Phase 1
│       ├── knowledge_base.yaml  # Phase 2
│       ├── customer_service.yaml # Phase 3
│       └── marketing.yaml      # Phase 4
│
├── data/                        # 运行时数据（gitignore）
│   ├── knowledge/               # 知识库文档
│   │   ├── faq.md
│   │   └── pricing.md
│   ├── chroma/                  # 向量数据库
│   ├── agents/                  # Agent 工作区（B 级改进）
│   │   ├── cs_bot/workspace/MEMORY.md
│   │   ├── marketing_bot/workspace/MEMORY.md
│   │   └── dev_bot/workspace/MEMORY.md
│   └── sessions/                # 平台登录 Cookie（明文存储，chmod 600 保护）
│
├── tests/
│   ├── unit/                    # 单元测试（纯逻辑，无 IO，无网络）
│   │   ├── test_core.py
│   │   ├── test_tools.py
│   │   ├── test_channels.py
│   │   └── test_agents/
│   │       ├── test_cs_bot.py
│   │       ├── test_marketing_bot.py
│   │       └── test_dev_bot.py
│   ├── integration/             # 集成测试（本地服务，Mock 外部 API）
│   │   ├── test_dispatch.py     # 消息路由端到端
│   │   ├── test_event_bus.py    # 跨 Agent 事件联动
│   │   └── test_session.py      # 会话持久化读写
│   ├── live/                    # 真实 API 测试（需真实 Key，CI 手动触发）
│   │   ├── test_telegram_live.py
│   │   └── test_llm_live.py
│   └── conftest.py              # 公共 Fixtures
│
├── main.py
├── docker-compose.yml
├── .env.example
├── .pre-commit-config.yaml
├── pyproject.toml
└── uv.lock
```

---

## 12. 开发路线图与验收标准

### Phase 1A — 平台基础设施 + cui Web UI 部署

**前置条件**：完成 Claude Code CLI POC（10 个模拟任务逐个测试 + 运行行为观察），通过后再进入正式开发。

**目标**: 搭建平台核心基础设施（事件总线、工具注册、配置系统、日志追踪），部署 cui Web UI 让 Owner 通过浏览器直接使用 Claude Code CLI

| # | 验收用例 | 预期结果 |
|---|---------|---------|
| AC-1A.1 | 项目结构 | 所有目录和基础文件已创建，`uv sync` 成功 |
| AC-1A.2 | 工具基类 | `BaseTool` 可被子类继承，`execute()` + `validate_input()` 签名统一 |
| AC-1A.3 | 事件总线 | `event_bus.publish(event)` 后订阅者能收到（Redis Lists 持久化） |
| AC-1A.4 | 工具注册表 | 工具注册后，智能体只能调用配置中声明的工具 |
| AC-1A.5 | Web UI (cui) | 浏览器访问 cui，能与 Claude Code 交互（需求澄清、代码执行、结果查看） |
| AC-1A.6 | 后台任务 | 关闭浏览器后 Claude Code 任务继续执行 |
| AC-1A.7 | ntfy 推送 | 任务完成后手机收到 ntfy 推送通知 |
| AC-1A.8 | 安全基础 | cui 反向代理认证、速率限制、审计日志、日志脱敏、工具 Schema 校验均可用 |
| AC-1A.9 | Docker 启动 | `docker-compose up -d` 一键启动（cui + Python 平台 + Redis） |

---

### Phase 1B — GitHub Issue 自动化

**前置条件**：Phase 1A 完成

**目标**: GitHub 创建 Issue 后，机器人自动分析 → ntfy 通知 Owner → Owner 通过 Web UI 确认 → 执行修复并提 PR

| # | 验收用例 | 预期结果 |
|---|---------|---------|
| AC-1B.1 | GitHub Webhook | Issue 创建后 Webhook 触发开发机器人（含签名验证） |
| AC-1B.2 | Issue 分析 | AI 能正确分类 Issue（Bug / Feature / 优化） |
| AC-1B.3 | 半自动流程 | Issue 分析 → ntfy 通知 Owner → Owner 通过 Web UI 确认 → Claude Code 执行 |
| AC-1B.4 | Issue 评论 | Issue 下自动评论进度（分析中 → 执行中 → 已完成/失败） |
| AC-1B.5 | PR 关联 | 修复完成后自动创建 PR 并关联 Issue |
| AC-1B.6 | SDK 可用 | `claude_code_sdk` 工具可通过 `query()` 执行代码任务并返回结构化结果 |
| AC-1B.7 | CUI /clear | 在 cui 中输入 /clear 后当前 session 终止，新 session 启动，界面显示确认 |
| AC-1B.8 | 复杂度自适应 | 简单 Issue 单次调用完成；复杂 Issue 自动分解为多步执行 |
| AC-1B.9 | Session 轮换 | CLI 调用因 max_turns 停止后，自动生成进度摘要并启动新 session 续接 |

---

### Phase 1C — 需求驱动开发工作流

**前置条件**：Phase 1B 完成

**目标**: Owner 提供 phase-N.md 需求文件 → 平台自动解析为子任务 → 逐个独立执行 → 回写进度 → 失败可重试/跳过/终止

| # | 验收用例 | 预期结果 |
|---|---------|---------|
| AC-1C.1 | Phase 文件解析 | PhaseFileParser 正确解析 phase-N.md 为 TaskPlan JSON |
| AC-1C.2 | 多任务串行执行 | TaskExecutor 按序执行子任务，每个子任务独立 CLI 上下文 |
| AC-1C.3 | 进度回写 | 子任务完成后 phase-N.md 中 `[ ]` → `[x]` |
| AC-1C.4 | 失败处理 | 子任务失败自动暂停，支持 retry/skip/abort |
| AC-1C.5 | 敏感文件保护 | 修改 .env 等文件时自动回滚 + 通知 |
| AC-1C.6 | 连续失败保护 | 连续 2 个子任务失败自动终止计划 |
| AC-1C.7 | REST API | `POST /api/requirements/from-phase` 及控制端点正常工作 |

---

### Phase 1D — cui 全流程集成

**前置条件**：Phase 1C 完成

**目标**: Owner 在 cui 浏览器中对话即可完成全流程：新项目创建 → 需求澄清 → 一键提交执行 → 实时进度查看 → 干预控制

| # | 验收用例 | 预期结果 |
|---|---------|---------|
| AC-1D.1 | 项目初始化 API | `POST /api/projects/init` 创建 git 仓库 + phase 骨架 + 初始 commit |
| AC-1D.2 | MCP Tool Bridge | Claude Code 通过 MCP 工具自动调用平台 API（init_project、submit_phase 等） |
| AC-1D.3 | SSE 实时推送 | PlanEventBroker fan-out + SSE 端点，多客户端订阅实时事件 |
| AC-1D.4 | RequirementPanel | cui 侧边栏实时展示进度（进度条 + 任务卡片 + 操作按钮） |
| AC-1D.5 | 全流程 E2E | 从项目创建到任务执行到进度展示的完整链路验证 |

---

### Phase 2 — 知识库机器人

**前置条件**：Phase 1 完成

**目标**: 自动从代码仓库生成/更新产品知识库，Owner 可手动管理

| # | 验收用例 | 预期结果 |
|---|---------|---------|
| AC-2.1 | 文档提取 | 从代码仓库自动提取 README、docstring、API 签名 |
| AC-2.2 | 知识库写入 | 提取的内容成功写入 ChromaDB，可通过语义查询检索 |
| AC-2.3 | 增量更新 | 代码仓库变更后，知识库自动增量更新（不重复） |
| AC-2.4 | Owner 命令 | `/kb refresh`、`/kb add`、`/kb status` 命令正常工作 |
| AC-2.5 | 执行报告 | 同步完成后 Owner 收到 Telegram 报告 |

---

### Phase 3 — 客服机器人

**前置条件**：Phase 2 完成（知识库已有内容）

**目标**: 用 Telegram 问产品问题，AI 能基于知识库回答

| # | 验收用例 | 预期结果 |
|---|---------|---------|
| AC-3.1 | Telegram 渠道 | 客户消息触发客服机器人 |
| AC-3.2 | RAG 对话 | Telegram 发送产品问题，AI 基于知识库回答 |
| AC-3.3 | 多轮记忆 | 同一用户的第二条消息能感知到之前的对话上下文 |
| AC-3.4 | 升级机制 | 知识库相似度连续 3 轮 < 0.6 时通知 Owner |
| AC-3.5 | 事件联动 | Bug 反馈 → event_bus → 开发机器人自动创建 Issue |

---

### Phase 4 — 营销机器人

**前置条件**：Phase 3 完成 + Zhihu POC 通过（1 周真实测试，验证反爬可行性）

**目标**: 按计划自动发布引流文章，Telegram 报告结果

| # | 验收用例 | 预期结果 |
|---|---------|---------|
| AC-4.1 | Playwright 工具 | `browser.navigate(url)` 成功导航并返回页面内容 |
| AC-4.2 | 定时任务 | 定时任务在配置的 cron 时间触发 |
| AC-4.3 | 文章生成 | AI 生成文章包含主题内容 + 自然引导段落 |
| AC-4.4 | 发布 | 营销机器人成功发布文章（知乎或博客/RSS 替代方案） |
| AC-4.5 | 执行报告 | 任务完成后 Owner 收到 Telegram 报告（含文章链接） |

---

### Phase 5 — 增强（持续迭代）

- [ ] 接入 Chatwoot（开源客服平台，Docker Compose 部署，通过 Bot API 对接）
- [ ] 销售漏斗状态跟踪（客服机器人升级）
- [ ] 多仓库支持动态增减（开发机器人升级）
- [ ] Owner 管理界面（简单 Web UI）
- [ ] `code_exec` Docker 沙箱工具
- [ ] 升级评估：渠道插件发现机制（manifest.yaml + 动态 import，渠道数 ≥ 4 时）
- [ ] 升级评估：AgentResponse 多模态 + 流式输出
- [ ] 升级评估：LangGraph 编排（有复杂多 Agent 工作流需求时）
- [ ] 升级评估：Channel Mixin 模式（渠道数 ≥ 5 时）
- [ ] 升级评估：Tool Profile 系统（智能体数 > 4 时）
- [ ] 升级评估：Docker 容器沙箱（有外部用户接入时）

---

## 13. 测试规范（借鉴 OpenClaw，D 级改进）

### 13.1 测试分层

| 层级 | 目录 | 运行条件 | 速度 | 覆盖目标 |
|------|------|---------|------|---------|
| **单元测试** | `tests/unit/` | 始终可运行，无需外部服务 | < 30s | 核心逻辑 100% |
| **集成测试** | `tests/integration/` | 需启动本地 ChromaDB / asyncio loop | < 3min | 跨模块流程 |
| **Live 测试** | `tests/live/` | 需真实 API Key，手动触发 | 不限 | 外部服务连通性 |

**运行命令**：
```bash
# 日常开发（仅 unit）
python -m pytest tests/unit/ -v

# PR 合并前（unit + integration）
python -m pytest tests/unit/ tests/integration/ -v

# 手动验收（全部，含 live）
LIVE_TEST=1 python -m pytest tests/ -v
```

### 13.2 覆盖率门槛

```ini
# pytest.ini 或 pyproject.toml
[tool.pytest.ini_options]
addopts = "--cov=core --cov=tools --cov=channels --cov=agents --cov-fail-under=70"
```

| 模块 | 最低覆盖率 | 说明 |
|------|-----------|------|
| `core/` | **80%** | 平台核心，高标准 |
| `tools/` | **80%** | 工具原子化，需独立测试 |
| `channels/` | **70%** | 含外部 SDK 调用，适当 Mock |
| `agents/` | **70%** | while 循环 + tool_use 逻辑 |

### 13.3 Live 测试开关

Live 测试用环境变量控制，不影响普通 CI：

```python
# tests/live/test_llm_live.py
import pytest, os

@pytest.mark.skipif(not os.getenv("LIVE_TEST"), reason="需设置 LIVE_TEST=1")
async def test_claude_api_real():
    ...
```

---


*文档由 Claude Code 生成，基于需求沟通整理。最后更新：2026-03-10（v0.10 新增 DV-31~DV-34 Phase 1D cui 全流程集成功能点；§3.5 横切面表新增 Phase 1D 条目；§12 新增 Phase 1C/1D 验收用例）*
