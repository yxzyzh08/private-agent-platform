# Phase 1D: cui 全流程集成 — 从对话到自动执行

**分支**: `feat/phase-1d-cui-integration`
**Tag**: `v0.4.0`
**前置**: Phase 1C 完成（v0.3.0）
**目标**: Owner 在 cui 中与 Claude Code 对话即可完成：新项目创建 → 需求澄清 → 任务分解 → phase-N.md 生成 → 一键提交执行 → 实时进度查看 → 干预控制（重试/跳过/终止）。全程不离开浏览器，不需要手动 curl。

**预计时长**: 2.5-3 周（跨 Python/TypeScript/React 三个技术栈）

**完成条件**: Owner 在 cui 浏览器中说"帮我创建一个 XXX 项目" → Claude Code 多轮对话澄清需求 → 自动生成 phase-1.md → Owner 说"提交执行" → Claude Code 通过 MCP Tool 调用平台 API → 平台自动初始化仓库 + 执行任务 → cui 侧边栏实时展示进度 → Owner 可随时重试/跳过/终止 → 完成后自动创建 PR + ntfy 通知

---

## 与 Phase 1A-1C 的关系

| 层次 | Phase 1A | Phase 1B | Phase 1C | Phase 1D（新增） |
|------|---------|---------|---------|---------|
| **触发方式** | Owner 在 cui 手动输入 | GitHub Issue Webhook | 手动 curl API | cui 对话 → MCP Tool 自动调用 |
| **执行方式** | 单次 CLI 交互 | 单次 CLI 调用 | 多任务串行执行 | 多任务串行执行（复用 1C） |
| **用户体验** | 命令行式对话 | 自动化，Owner 确认 | 需手动 curl | 全程浏览器内，零命令行 |

**核心原则**：
- Phase 1D **不修改** Phase 1C 后端逻辑，仅扩展（向后兼容新增）
- Phase 1B 的 GitHub Issue 处理完全不受影响
- 新增代码遵循 core 演进规则（只允许新增方法/可选参数）

---

## 核心架构：MCP Tool Bridge

```
┌─────────────────────────────────────────────────────────────┐
│  CUI Browser (React)                                        │
│                                                             │
│  ┌──────────────┐  ┌────────────────────────────────────┐  │
│  │  ChatView     │  │  RequirementPanel (新增)            │  │
│  │  (对话区)     │  │  ┌──────────────────────────────┐  │  │
│  │              │  │  │ Plan Status: ████░░ 3/5      │  │  │
│  │  Claude Code  │  │  │                              │  │  │
│  │  对话...      │  │  │ ✅ Task 1: 创建模块          │  │  │
│  │              │  │  │ ✅ Task 2: 添加测试          │  │  │
│  │              │  │  │ 🔄 Task 3: API 集成          │  │  │
│  │              │  │  │ ⏳ Task 4: 文档              │  │  │
│  │              │  │  │ ⏳ Task 5: E2E 测试          │  │  │
│  │              │  │  │                              │  │  │
│  │              │  │  │ [重试] [跳过] [终止]          │  │  │
│  │              │  │  └──────────────────────────────┘  │  │
│  └──────────────┘  └────────────────────────────────────┘  │
└────────────┬───────────────────────────┬───────────────────┘
             │ WebSocket (streaming)     │ REST + SSE
             ↓                           ↓
┌────────────▼───────────────────────────▼───────────────────┐
│  CUI Server (Express + TypeScript)                         │
│                                                             │
│  ClaudeProcessManager ──→ Claude CLI ──→ MCP Server        │
│                                          ↓                  │
│                              ┌───────────▼──────────────┐  │
│                              │ Platform MCP Tools (新增) │  │
│                              │                          │  │
│                              │ • init_project           │  │
│                              │ • submit_phase           │  │
│                              │ • get_plan_status        │  │
│                              │ • control_task           │  │
│                              │ • abort_plan             │  │
│                              └───────────┬──────────────┘  │
│                                          │ HTTP            │
│  /api/proxy/requirements/* ──────────────┤                 │
│  /api/proxy/projects/*     ──────────────┤                 │
└──────────────────────────────────────────┼─────────────────┘
                                           ↓
┌──────────────────────────────────────────▼─────────────────┐
│  Platform Backend (FastAPI + Python)                        │
│                                                             │
│  POST /api/projects/init              ← 新增               │
│  POST /api/requirements/from-phase    ← Phase 1C 已有      │
│  GET  /api/requirements/{id}          ← Phase 1C 已有      │
│  GET  /api/requirements/{id}/events   ← 新增 (SSE)         │
│  POST /api/requirements/{id}/abort    ← Phase 1C 已有      │
│  POST /api/requirements/{id}/tasks/{tid}/retry ← 已有      │
│  POST /api/requirements/{id}/tasks/{tid}/skip  ← 已有      │
└────────────────────────────────────────────────────────────┘
```

**关键设计决策**：

1. **MCP Tool 而非关键词监听**：Claude Code 原生理解工具调用，由 AI 自主判断何时调用 `submit_phase`，比关键词匹配更灵活可靠。无需修改 cui 的消息处理链路。

2. **SSE 推送进度**：Server-Sent Events（非 WebSocket），单向推送场景更简单、HTTP 原生支持、自动重连。采用**进程内 fan-out 模式**：TaskExecutor 发布事件到进程内 `PlanEventBroker`（asyncio.Queue 多路分发），SSE 端点注册/注销 Queue 接收事件。不经过 Redis EventBus（BRPOP 是竞争消费语义，不适合 SSE 广播场景）。

3. **cui Server 作代理**：前端通过 cui Server 代理调用 FastAPI 后端，统一认证、避免 CORS。

4. **项目初始化 API**：支持从零创建新项目（git init + phase 骨架），而非只对已有项目提交 phase 文件。

---

## 用户旅程（完整流程）

```
阶段 1：需求澄清（Owner ↔ Claude Code 对话，无平台参与）
┌──────────────────────────────────────────────────────┐
│  Owner: "帮我创建一个 hello-api 的 FastAPI 项目，     │
│          功能：一个 /hello 端点返回 greeting"          │
│  Claude: "好的，我先确认几个问题：                     │
│           1. 需要数据库吗？                            │
│           2. 需要认证吗？                              │
│           3. 部署方式？"                               │
│  Owner: "不需要数据库，不需要认证，Docker 部署"         │
│  Claude: "明白了，我来生成任务分解..."                  │
│                                                      │
│  → Claude Code 生成 phase-1.md 文件                   │
│  → 展示给 Owner 确认                                  │
└──────────────────────────────────────────────────────┘
    ↓
阶段 2：提交执行（Claude Code 通过 MCP Tool 操作）
┌──────────────────────────────────────────────────────┐
│  Owner: "看起来没问题，提交执行吧"                      │
│                                                      │
│  Claude Code 自动执行：                                │
│  1. 调用 MCP Tool `init_project`                      │
│     → 创建 /home/.../hello-api, git init              │
│  2. 将 phase-1.md 写入项目目录                         │
│  3. 调用 MCP Tool `submit_phase`                      │
│     → POST /api/requirements/from-phase               │
│     → 返回 plan_id                                    │
│  4. 告诉 Owner: "已提交，plan_id: xxx，请在右侧面板    │
│     查看执行进度"                                      │
└──────────────────────────────────────────────────────┘
    ↓
阶段 3：实时监控（RequirementPanel SSE 订阅）
┌──────────────────────────────────────────────────────┐
│  RequirementPanel 自动出现，通过 SSE 实时更新：        │
│                                                      │
│  📋 执行进度 [plan_id: xxx]                           │
│  ████████░░░░ 3/5 (60%)                              │
│                                                      │
│  ✅ Task 1: 创建项目结构  (45s)                       │
│  ✅ Task 2: 实现 /hello 端点  (2m 30s)                │
│  🔄 Task 3: 添加测试  (进行中...)                     │
│  ⏳ Task 4: Dockerfile                                │
│  ⏳ Task 5: 文档                                      │
│                                                      │
│  失败时：                                             │
│  ❌ Task 3: 测试失败  [重试] [重试+反馈] [跳过]        │
│  全局：[终止计划]                                      │
└──────────────────────────────────────────────────────┘
    ↓
阶段 4��完成
┌──────────────────────────────────────────────────────┐
│  ✅ 全部完成 (总耗时 8m 45s)                          │
│  📎 PR #42 已创建                                    │
│  📲 ntfy 通知已发送                                   │
└──────────────────────────────────────────────────────┘
```

---

## 任务分解

### Group A — 平台后端扩展

---

### Task 1D.1: 项目初始化 API

**状态**: [x] 完成
**依赖**: 无
**产出文件**: `routes/projects.py`, `tests/unit/test_projects_api.py`

**描述**:
新增 `POST /api/projects/init` 端点，接收项目名和描述，自动创建 git 仓库和 phase-1.md 骨架。

> **认证说明**：本平台为 Owner 单用户内网部署，API 通过 cui Server 代理层访问，不直接暴露到公网，无需额外认证。

**API 定义**:
```
POST /api/projects/init
{
  "name": "my-awesome-app",
  "description": "一个 Python Web 应用",
  "base_path": "/home/ecs-user/github_projects"  // 可选，使用配置默认值
}

Response 200:
{
  "project_name": "my-awesome-app",
  "repo_path": "/home/ecs-user/github_projects/my-awesome-app",
  "phase_file": "/home/ecs-user/github_projects/my-awesome-app/docs/phases/phase-1.md",
  "git_initialized": true
}

Response 400: { "detail": "Invalid project name: must match ^[a-zA-Z0-9][a-zA-Z0-9._-]*$" }
Response 404: { "detail": "Base path does not exist: ..." }
Response 409: { "detail": "Project directory already exists: ..." }
```

**初始化动作**:
1. 校验项目名（allowlist 正则 `^[a-zA-Z0-9][a-zA-Z0-9._-]*$`，禁止 `..`、`/`、空格）
2. 校验 `base_path`（必须是 `platform.yaml` 中 `project_initialization.allowed_base_paths` 白名单内的路径，防止路径穿越）
3. 创建项目目录 `{base_path}/{name}`
4. `git init` + 设置 git config（user.name/email 从 `platform.yaml` 的 `project_initialization.git_user` 读取）
5. 创建 `docs/phases/` 目录
6. 从 `config/templates/phase-template.md` 复制骨架到 `docs/phases/phase-1.md`
7. 创建 `.gitignore`（Python 默认）
8. 初始 commit
9. 创建失败时清理已创建的目录（原子性保证）

**验收标准**:
- [ ] 调用 API 后目录和 git 仓库正确创建
- [ ] phase-1.md 骨架文件存在且可被 PhaseFileParser 解析
- [ ] 项目名包含非法字符（空格、/、..）时返回 400
- [ ] base_path 不在白名单内时返回 400
- [ ] base_path 不存在时返回 404
- [ ] 项目目录已存在时返回 409 Conflict
- [ ] 创建失败时自动清理已创建的目录
- [ ] set_trace_id() 在入口调用
- [ ] 路由正确注册到 FastAPI app（通过 main.py `app.include_router`）

**测试命令**:
```bash
uv run pytest tests/unit/test_projects_api.py -v
```

---

### Task 1D.2: SSE 进度推送端点 + PlanEventBroker

**状态**: [x] 完成
**依赖**: 无
**产出文件**: `core/plan_event_broker.py`, `routes/requirements_sse.py`, `tests/unit/test_plan_event_broker.py`, `tests/unit/test_requirements_sse.py`

**描述**:
新增进程内事件分发器 `PlanEventBroker` 和 SSE 端点 `GET /api/requirements/{plan_id}/events`。

> **架构决策**：不使用 Redis EventBus（LPUSH/BRPOP 是竞争消费、消费即销毁的队列语义，不适合 SSE 多客户端广播）。采用**进程内 fan-out 模式**：`PlanEventBroker` 维护每个 plan_id 的订阅者 Queue 列表，TaskExecutor 发布事件时广播到所有 Queue，SSE 端点注册/注销 Queue。本平台单进程部署，无需 Redis 中转。

**PlanEventBroker 设计**:
```python
class PlanEventBroker:
    """进程内事件广播器，支持多 SSE 客户端订阅同一 plan 的事件。"""

    def __init__(self):
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)

    def subscribe(self, plan_id: str) -> asyncio.Queue:
        """SSE 端点调用：注册一个新 Queue 并返回。"""
        queue = asyncio.Queue()
        self._subscribers[plan_id].append(queue)
        return queue

    def unsubscribe(self, plan_id: str, queue: asyncio.Queue) -> None:
        """SSE 端点断开时调用：移除 Queue。"""
        self._subscribers[plan_id] = [q for q in self._subscribers[plan_id] if q is not queue]

    async def publish(self, plan_id: str, event: dict) -> None:
        """TaskExecutor 调用：广播事件到所有订阅者。"""
        for queue in self._subscribers.get(plan_id, []):
            await queue.put(event)
```

**SSE 事件 Schema**（1D.3 发布端必须遵循）:
```
event: plan_started
data: {"plan_id":"xxx","total_tasks":5,"timestamp":"..."}

event: task_started
data: {"plan_id":"xxx","task_id":"T.1","title":"创建模块","timestamp":"..."}

event: task_completed
data: {"plan_id":"xxx","task_id":"T.1","duration_ms":45000,"summary":"..."}

event: task_failed
data: {"plan_id":"xxx","task_id":"T.2","error":"Test failed","attempt":1}

event: plan_completed
data: {"plan_id":"xxx","total_tasks":5,"completed":5,"total_duration_ms":180000}

event: plan_failed
data: {"plan_id":"xxx","failed_task":"T.3","consecutive_failures":2}

event: plan_stopped
data: {"plan_id":"xxx","completed_tasks":3,"reason":"owner_requested"}
```

**SSE 端点实现方案**:
1. FastAPI `StreamingResponse` + `text/event-stream` content-type
2. 从 `PlanEventBroker.subscribe(plan_id)` 获取 Queue
3. `async for event in queue` 格式化为 SSE 文本发送
4. 客户端断开时 `finally` 块调用 `unsubscribe()` 清理
5. 心跳：心跳间隔从 `platform.yaml` 的 `sse.heartbeat_interval_seconds` 读取（默认 30s）

**验收标准**:
- [ ] PlanEventBroker 支持多客户端订阅同一 plan_id
- [ ] publish 广播到所有已注册 Queue
- [ ] unsubscribe 后不再收到事件
- [ ] SSE 端点返回 `text/event-stream` content-type
- [ ] 任务开始/完成/失败时推送对应事件
- [ ] 心跳机制防止连接超时（间隔可配置）
- [ ] 客户端断开后自动清理 Queue
- [ ] 不存在的 plan_id 返回 404

**测试命令**:
```bash
uv run pytest tests/unit/test_plan_event_broker.py tests/unit/test_requirements_sse.py -v
```

---

### Task 1D.3: TaskExecutor 事件发布

**状态**: [x] 完成
**依赖**: Task 1D.2（依赖 PlanEventBroker 和 SSE 事件 Schema 定义）
**产出文件**: `core/task_executor.py`（扩展），`agents/dev_agent.py`（扩展，注入 event_broker），`tests/unit/test_task_executor.py`（扩展）

**描述**:
在 TaskExecutor 的关键节点通过 `PlanEventBroker` 发布事件，供 SSE 端点消费。

**事件发布点**（共 7 个，事件格式遵循 1D.2 定义的 SSE 事件 Schema）:
- `execute_plan` 开始：`plan_started`
- `execute_subtask` 开始前：`task_started`
- `execute_subtask` 成功后：`task_completed`
- `execute_subtask` 失败后：`task_failed`
- `execute_plan` 全部成功结束：`plan_completed`
- `execute_plan` 因失败终止：`plan_failed`
- `request_stop` 调用：`plan_stopped`（区别于因失败暂停）

**扩展方式**（向后兼容）:
```python
from core.plan_event_broker import PlanEventBroker

# TaskExecutor.__init__ 新增可选参数
def __init__(self, ..., event_broker: PlanEventBroker | None = None):
    self._event_broker = event_broker

# 辅助方法 — 异常隔离，事件发布失败不影响任务执行
async def _emit(self, plan_id: str, event_type: str, data: dict):
    if self._event_broker:
        try:
            await self._event_broker.publish(plan_id, {"event": event_type, **data})
        except Exception:
            logger.warning("Failed to emit event %s for plan %s", event_type, plan_id, exc_info=True)
```

**EventBroker 注入路径**:
- `agents/dev_agent.py` 创建 TaskExecutor 时传入 `event_broker=` 参数
- `routes/requirements.py` 的 `from-phase` 端点通过 `request.app.state.plan_event_broker` 传递
- `main.py` 在 lifespan 中创建 `PlanEventBroker` 实例并挂载到 `app.state`

**验收标准**:
- [ ] `event_broker` 参数可选，为 None 时不影响现有行为（向后兼容）
- [ ] `_emit` 内部 try/except 隔离异常，事件发布失败仅记 WARNING 日志，不中断任务执行
- [ ] 7 个事件点全部���布正确的事件数据（遵循 1D.2 Schema）
- [ ] 事件数据包含 plan_id, task_id, timestamp 等关键字段
- [ ] `agents/dev_agent.py` 正确注入 event_broker 实例
- [ ] 现有全部测试通过（回归验证）

**测试命令**:
```bash
uv run pytest tests/unit/test_task_executor.py -v
uv run pytest tests/ -v  # 全量回归
```

---

### Group B — MCP Tool Bridge

---

### Task 1D.4: Platform MCP Server

**状态**: [ ] 未开始
**依赖**: Task 1D.1
**产出文件**: `web/cui/src/mcp-server/platform-tools.ts`, `web/cui/tests/unit/platform-tools.test.ts`

**描述**:
创建新的 MCP Server（独立进程），暴露平台 API 为 Claude Code 可调用的 MCP Tools。复制现有 `web/cui/src/mcp-server/index.ts`（`cui-permissions`）的模式。

**MCP Tools 定义**:

| Tool | 描述 | 调用的 API |
|------|------|-----------|
| `init_project` | 初始化新项目（git repo + phase 骨架） | POST /api/projects/init |
| `submit_phase` | 提交 phase-N.md 执行，返回 plan_id | POST /api/requirements/from-phase |
| `get_plan_status` | 查询执行进度 | GET /api/requirements/{plan_id} |
| `control_task` | 重试或跳过任务 | POST .../retry 或 .../skip |
| `abort_plan` | 终止执行计划 | POST .../abort |

> **submit_phase 返回值必须包含 plan_id**：前端 Panel 通过 plan_id 建立 SSE 连接，这是 MCP Tool → Panel 联动的关键数据。

**实现方式**:
- 使用 `@modelcontextprotocol/sdk` 创建 MCP Server（StdioServerTransport，与 `cui-permissions` 相同）
- 通过 Node.js 原生 `fetch`（Node 18+ 内置）调用 Platform API（`PLATFORM_API_URL` 环境变量）
- 返回结构化 JSON 结果，Claude Code 可解读并告知用户

**验收标准**:
- [ ] MCP Server 可独立启动，`ListTools` 返回 5 个工具
- [ ] 每个工具的 `inputSchema` 正确定义
- [ ] 调用 `CallTool` 正确转发到 Platform API 并返回结果
- [ ] `submit_phase` 返回值包含 `plan_id` 字段
- [ ] 平台不可达时返回友好错误信息（非 crash）
- [ ] TypeScript 编译无错误

**测试命令**:
```bash
cd web/cui && npm test -- platform-tools
```

---

### Task 1D.5: MCP Server 注册到 Claude Code

**状态**: [ ] 未开始
**依赖**: Task 1D.4
**产出文件**: `web/cui/src/services/mcp-config-generator.ts`（扩展）

**描述**:
将 Platform MCP Server 注册到 cui 的 MCP 配置中，使 Claude Code 在 cui 中运行时自动加载平台工具。

> **已验证**：cui 已有 `MCPConfigGenerator`（`web/cui/src/services/mcp-config-generator.ts`），在启动时生成 MCP 配置 JSON 文件到 `/tmp/`，并通过 `ClaudeProcessManager.setMCPConfigPath()` + `--mcp-config` 参数传给 Claude CLI。该 JSON 的 `mcpServers` 对象支持多个 server 条目。

**注册方式**:
修改 `MCPConfigGenerator.generateConfig()` 方法，在已有的 `mcpServers` 对象中新增 `platform-tools` 条目：
```json
{
  "mcpServers": {
    "cui-permissions": { ... },
    "platform-tools": {
      "command": "node",
      "args": ["web/cui/dist/mcp-server/platform-tools.js"],
      "env": {
        "PLATFORM_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

> **注意**：`ClaudeProcessManager` 的 `--allowedTools` 列表（约 L695-701）需要同步更新，加入 5 个新 MCP Tool 名称，否则 Claude Code 不会使用这些工具。

**验收标准**:
- [ ] `MCPConfigGenerator` 生成的配置包含 `platform-tools` 条目
- [ ] Claude Code 在 cui 中启动后可调用 5 个平台工具
- [ ] 不影响现有 `cui-permissions` MCP Server 功能
- [ ] `PLATFORM_API_URL` 可通过环境变量覆盖
- [ ] `--allowedTools` 列表包含 5 个新工具名

**测试命令**:
```bash
cd web/cui && npm test -- mcp-config-generator
```

---

### Task 1D.6: Phase 生成 Prompt 模板

**状态**: [x] 完成
**依赖**: 无
**产出文件**: `config/templates/phase-generation-prompt.md`, `config/templates/claude-md-cui-workflow.md`

**描述**:
为 Claude Code 在 cui 中生成 phase-N.md 提供指导模板，确保生成的文件符合 PhaseFileParser 格式规范。

**phase-generation-prompt.md** — 注入到 Claude Code system prompt，指导需求分解：
- 需求澄清流程（至少确认：目标、技术栈、核心功能）
- phase-N.md 格式规范（Task header、状态、依赖、产出文件、测试命令）
- 任务粒度指导（每个任务 15-30 分钟 CLI 执行量）
- 常见项目类型示例（Python CLI、FastAPI、React）

**claude-md-cui-workflow.md** — 注入到用户项目的 CLAUDE.md，指导 MCP Tool 使用：
- 可用的 MCP Tools 列表和用途
- 工作流程：对话 → 生成 phase → init_project → submit_phase

**验收标准**:
- [ ] 模板覆盖需求澄清 → 任务分解 → 格式规范
- [ ] 模板示例可被 PhaseFileParser 正确解析
- [ ] cui-workflow 模板包含 MCP Tool 使用示例
- [ ] 与现有 `config/templates/claude-md-section.md` 不冲突

**测试命令**:
```bash
uv run pytest tests/unit/test_phase_templates.py -v
```

> 测试用例从模板中提取示例 phase 内容，验证 `parse_phase_file()` 可正确解析。

---

### Group C — CUI 前端扩展

---

### Task 1D.7: cui Server API 代理路由

**状态**: [ ] 未开始
**依赖**: Task 1D.1, Task 1D.2
**产出文件**: `web/cui/src/routes/platform-proxy.routes.ts`, `web/cui/tests/unit/platform-proxy.test.ts`

**描述**:
在 cui Server（Express）中添加代理路由，将前端对平台 API 的请求透传到 FastAPI 后端，避免 CORS 问题。

**代理路由**:
```
GET  /api/proxy/requirements/:planId          → GET  /api/requirements/:planId
GET  /api/proxy/requirements/:planId/events   → GET  /api/requirements/:planId/events (SSE 透传)
POST /api/proxy/requirements/:planId/abort    → POST /api/requirements/:planId/abort
POST /api/proxy/requirements/:planId/tasks/:taskId/retry → ...
POST /api/proxy/requirements/:planId/tasks/:taskId/skip  → ...
POST /api/proxy/projects/init                 → POST /api/projects/init
```

**SSE 代理技术要点**:
- 设置 `res.flushHeaders()` 立即发送响应头
- 禁用 compression middleware 对 SSE 路由的缓冲
- 设置 `Content-Type: text/event-stream`、`Cache-Control: no-cache`、`Connection: keep-alive`
- 客户端断开时清理上游 HTTP 连接（`req.on('close', ...)`)

**验收标准**:
- [ ] 代理路由正确转发请求和响应
- [ ] SSE 代理正确透传 event-stream（不缓冲，事件实时到达）
- [ ] 平台不可达时返回 502 Bad Gateway
- [ ] 响应头正确（Content-Type 保持不变）
- [ ] 客户端断开时清理上游连接

**测试命令**:
```bash
cd web/cui && npm test -- platform-proxy
```

---

### Task 1D.8: RequirementPanel 前端组件

**状态**: [ ] 未开始
**依赖**: Task 1D.7
**产出文件**: `web/cui/src/web/chat/components/RequirementPanel/RequirementPanel.tsx`, `web/cui/src/web/chat/components/RequirementPanel/TaskCard.tsx`, `web/cui/src/web/chat/components/RequirementPanel/index.ts`

**描述**:
在 cui 对话界面侧边新增 RequirementPanel 组件，通过 SSE 实时展示需求执行进度。

**组件结构**:
```
RequirementPanel/
  ├── RequirementPanel.tsx  — 主容器（SSE 连接 + 整体状态）
  ├── TaskCard.tsx          — 单个任务卡片（状态图标 + 标题 + 操作按钮）
  └── index.ts              — 导出
```

**功能**:
1. **进度总览**：进度条 + "3/5 完成"
2. **任务卡片列表**：每个任务显示状态图标 + 标题 + 耗时
   - ⏳ pending → 🔄 in_progress → ✅ completed / ❌ failed / ⏭️ skipped
3. **操作按钮**：
   - 失败任务：[重试] [重试+反馈] [跳过]
   - 运行中：[终止计划]
4. **SSE 订阅**：EventSource 连接 `/api/proxy/requirements/{planId}/events`
5. **自动显隐**：有活跃 plan 时展开，无时折叠
6. **planId 获取**：组件接收 `planId` prop（由 RequirementContext 提供），创建 EventSource 连接

**验收标准**:
- [ ] Panel 在无活跃 plan 时隐藏
- [ ] 接收到 planId 后自动创建 SSE 连接并显示
- [ ] 任务状态通过 SSE 实时更新
- [ ] 重试/跳过按钮调用正确的代理 API
- [ ] 终止按钮调用 abort API
- [ ] 全部完成时显示成功状态 + PR 链接（如有）
- [ ] SSE 连接断开时自动重连（EventSource 原生支持）

**测试命令**:
```bash
cd web/cui && npm test -- RequirementPanel
```

---

### Task 1D.9: Layout 集成 + RequirementContext

**状态**: [ ] 未开始
**依赖**: Task 1D.8
**产出文件**: `web/cui/src/web/chat/contexts/RequirementContext.tsx`, `web/cui/src/web/chat/components/Layout/Layout.tsx`（扩展）

**描述**:
将 RequirementPanel 集成到 cui Layout，通过 React Context 管理全局 plan 状态。

**MCP Tool → Panel 触发机制**（关键链路）:
```
Claude CLI 调用 submit_phase MCP Tool
  → MCP Server 调用 POST /api/requirements/from-phase
  → 返回 { plan_id: "xxx", ... }
  → MCP Server 返回结构化 JSON 给 Claude CLI
  → Claude CLI 输出 tool_result 到 stdout
  → cui Server streaming 解析 stdout（已有 WebSocket 推送机制）
  → 前端 ChatView 收到 tool_result 消息
  → 前端解析消息内容，检测到 plan_id 字段
  → 调用 RequirementContext.setPlanId("xxx")
  → RequirementPanel 自动显示并建立 SSE 连接
```

**具体实现**:
1. 创建 `RequirementContext` — 管理 planId、panel 显隐状态
2. 在 `ChatApp.tsx` 中添加 `RequirementProvider`（遵循已有 `ConversationsContext`、`PreferencesContext` 模式）
3. Layout 从全宽改为 flex 两列布局，右侧条件渲染 RequirementPanel
4. **planId 提取**：在 ChatView 的消息渲染逻辑中，检测 tool_result 类型消息，如果内容包含 `plan_id` 字段，自动调用 `context.setPlanId()`
5. 面板可手动展开/折叠（toggle 按钮）

**验收标准**:
- [ ] RequirementPanel 在 Layout 中正确渲染（flex 两列）
- [ ] Context 跨组件共享 plan 状态
- [ ] MCP Tool submit_phase 返回的 plan_id 自动触发 Panel 显示
- [ ] 切换对话时 panel 状态正确清理
- [ ] 面板可手动展开/折叠
- [ ] Layout 修改最小侵入性，确保可回滚

**测试命令**:
```bash
cd web/cui && npm test -- Layout RequirementContext
```

---

### Group D — 集成测试与验收

---

### Task 1D.10: L2 集成测试（后端全流程）

**状态**: [x] 完成
**依赖**: Task 1D.3
**产出文件**: `tests/integration/test_cui_integration.py`

**描述**:
L2 集成测试，验证 Phase 1D 后端新增功能：项目初始化 → SSE 事件推送 → EventBus 集成。

**测试场景**:
1. `test_init_project_and_submit` — 初始化项目 + 提交执行 + 查询状态
2. `test_sse_events_flow` — Mock TaskExecutor 发布事件 → SSE 端点正确推送
3. `test_project_init_validation` — 非法项目名、已存在项目等边界情况
4. `test_event_bus_integration` — EventBus 事件正确传递到 SSE 端点

**验收标准**:
- [ ] 4 个测试场景全部通过
- [ ] Mock 层级：Mock CLI 执行，真实 API + EventBus

**测试命令**:
```bash
uv run pytest tests/integration/test_cui_integration.py -v
```

---

### Task 1D.11: 基础设施适配

**状态**: [x] 完成
**依赖**: Task 1D.10
**产出文件**: 无新增文件（验证性任务）

**描述**:
确保 Phase 1D 新增模块正确集成平台横切面基础设施。

**验收标准**:
- [ ] **日志**：所有新 Python 模块使用 `get_logger(__name__)`
- [ ] **日志修复**：`core/event_bus.py` 的 `logging.getLogger()` 改为 `get_logger()`（已知违规）
- [ ] **Trace ID**：项目初始化 API 入口调用 `set_trace_id()`
- [ ] **错误类型**：`core/errors.py` 新增 `ProjectInitError`、`SSEConnectionError`
- [ ] **配置**：`platform.yaml` 新增 `project_initialization` 配置节（`allowed_base_paths`、`git_user`）和 `sse.heartbeat_interval_seconds`
- [ ] **测试 Fixtures**：`tests/conftest.py` 新增 `mock_project_init`、`mock_sse_client`、`mock_plan_event_broker`、`sample_sse_events`
- [ ] **全量回归**：Python 端全部测试通过

**测试命令**:
```bash
uv run pytest tests/ -v  # 全量回归
```

---

### Task 1D.12: L3 端到端验收

**状态**: [ ] 未开始
**依赖**: Task 1D.9, Task 1D.11
**产出文件**: `tests/e2e/test_e2e_cui_workflow.py`

**描述**:
Owner 手动验收 — 在 cui 浏览器中完成完整的新项目创建工作流。

**验收步骤**:
```bash
# 1. 启动平台
docker-compose up -d

# 2. 打开 cui 浏览器
# 访问 http://your-server:3001

# 3. 在 cui 中对话
"帮我创建一个名为 hello-api 的 Python FastAPI 项目，
 功能：一个 /hello 端点返回 greeting 消息"

# 4. 观察 Claude Code 行为：
#    - 多轮需求澄清
#    - 生成 phase-1.md
#    - 使用 init_project MCP Tool 创建项目
#    - 使用 submit_phase MCP Tool 提交执行

# 5. 观察 RequirementPanel：
#    - 进度条更新
#    - 任务状态变化
#    - 完成后显示 PR 链接
```

**验收标准**（L3 — 全部真实环境）:
- [ ] Claude Code 正确使用 `init_project` 创建项目仓库
- [ ] Claude Code 生成的 phase-N.md 可被 PhaseFileParser 解析
- [ ] Claude Code 使用 `submit_phase` 提交执行
- [ ] RequirementPanel 实时显示任务进度（SSE 驱动）
- [ ] 任务失败时可通过 Panel 重试/跳过
- [ ] 全部完成后自动创建 PR
- [ ] ntfy 收到开始和完成通知
- [ ] Phase 1C 的全部 API 端点仍正常工作（回归）

**测试命令**:
```bash
# 手动验收脚本
uv run python tests/e2e/test_e2e_cui_workflow.py
```

---

### Task 1D.13: Post-Phase 文档同步 + Git Tag

**状态**: [ ] 未开始
**依赖**: Task 1D.12

**验收标准**:
- [ ] 本文件所有任务标记 `[x]`
- [ ] `docs/requirement.md` 更新：DV-26 cui 展示部分标记完成；新增 DV-31（项目初始化 API）、DV-32（MCP Tool Bridge）功能点并标记完成；§3.5 横切面表新增 Phase 1D 条目
- [ ] `docs/progress.md` Quick Status 更新
- [ ] 测试数更新到 Test Count History
- [ ] `git tag -a v0.4.0 -m "Phase 1D: cui 全流程集成"`
- [ ] 推送 tag 到远程

---

## MVP 优先级

> **P0 = 核心链路**（没有它功能不可用）；**P1 = 增强体验**（没有它功能可用但体验差）

| 优先级 | 任务 | 类型 | 必要性 |
|--------|------|------|--------|
| **P0 核心** | 1D.2 SSE 进度端点 + PlanEventBroker | Python 后端 | 实时进度的基础 |
| **P0 核心** | 1D.3 TaskExecutor 事件发布 | Python 后端 | 事件源 |
| **P0 核心** | 1D.4 Platform MCP Server | TypeScript | MCP 桥接 |
| **P0 核心** | 1D.5 MCP 注册到 cui | TypeScript | MCP 生效 |
| **P0 核心** | 1D.7 cui 代理路由 | TypeScript | 前端访问后端 |
| **P0 核心** | 1D.8 RequirementPanel | React | 进度展示 |
| **P1 增强** | 1D.1 项目初始化 API | Python 后端 | Owner 可手动 git init 替代 |
| **P1 增强** | 1D.6 Prompt 模板 | Markdown | Owner 可手动指导格式 |
| **P1 增强** | 1D.9 Layout 集成 | React | Panel 可独立测试 |
| **P1 质量** | 1D.10 L2 集成测试 | Python 测试 | 质量保障 |
| **P1 质量** | 1D.11 基础设施 | 验证 | 横切面完整性 |
| **P1 质量** | 1D.12 E2E 验收 | 手动验收 | 最终验证 |
| **P1 质量** | 1D.13 文档 + Tag | 文档 | 规范 |

---

## 技术决策记录

### SSE vs WebSocket vs 轮询

| 方案 | 优势 | 劣势 | 选择 |
|------|------|------|------|
| **SSE** | 单向推送最简单、HTTP 原生、自动重连 | 只支持服务端→客户端 | **✅ 采用** |
| WebSocket | 双向通信、零延迟 | 需维护连接状态、实现复杂 | ❌ 过度 |
| 轮询 | 实现最简单 | 浪费请求、有延迟 | ❌ 备选 |

### MCP Tool vs Slash Command vs 关键词监听

| 方案 | 优势 | 劣势 | 选择 |
|------|------|------|------|
| **MCP Tool** | Claude Code 原生支持、AI 自主判断何时调用 | 需创建 MCP Server | **✅ 采用** |
| Slash Command | 用户显式触发 | 需修改 cui 命令系统 | ❌ 侵入性高 |
| 关键词监听 | 无需额外工具 | 误触发风险、维护成本高 | ❌ 不可靠 |

### SSE 事件分发：进程内 fan-out vs Redis EventBus

| 方案 | 优势 | 劣势 | 选择 |
|------|------|------|------|
| **进程内 PlanEventBroker** | 简单、无 Redis 依赖、天然支持多客户端广播 | 不支持多进程 | **✅ 采用** |
| Redis EventBus (BRPOP) | 已有基础设施、持久化 | 竞争消费语义不适合广播、消费即销毁 | ❌ 架构不匹配 |
| Redis Pub/Sub | 支持广播、支持多进程 | 增加复杂度、本平台单进程不需要 | ❌ 过度 |

> **决策理由**：Redis EventBus 使用 LPUSH/BRPOP，一个事件被 BRPOP 后就从 Redis 中删除。如果 Owner 开两个浏览器标签，两个 SSE 连接中只有一个能收到事件。进程内 `PlanEventBroker` 使用 asyncio.Queue fan-out，天然支持多客户端广播，且本平台是单进程部署，无需 Redis 中转。

### 项目初始化方式

| 方案 | 优势 | 劣势 | 选择 |
|------|------|------|------|
| **平台 API** | 统一管理、可审计 | 需新增端点 | **✅ 采用** |
| Claude CLI 直接执行 | 无需新端点 | 不可审计、无统一管理 | ❌ 不可控 |
