# Phase 1A: 平台骨架 + Web UI 开发工具

**分支**: `feat/phase-1a-devbot`
**Tag**: `v0.1.0`
**目标**: 搭建平台核心基础设施，集成 cui Web UI 让 Owner 通过浏览器与 Claude Code 交互完成开发任务
**预计时长**: 3 周

**完成条件**: Owner 通过浏览器访问 cui Web UI，能与 Claude Code 交互（需求澄清、代码执行、结果查看）；后台任务支持关闭浏览器后继续执行；ntfy 推送任务完成通知；平台核心基础设施（事件总线、工具注册、配置系统）已就绪；Docker Compose 一键启动

---

## 1.0 — POC 验证（Phase 1A 前置，手动执行，非 Claude Code 自动任务）

### Task 1.0.1: Claude Code CLI POC 稳定性测试 🔧 手动

**状态**: [ ] 未开始
**依赖**: 无
**产出文件**: `docs/poc/claude_code_cli.md`

**描述**:
模拟 10 个不同类型的开发任务（新功能开发、Bug 修复、代码重构），逐个调用 Claude Code CLI 处理，记录成功率、失败原因、耗时。

**验收标准**:
- [ ] 准备 10 个模拟任务（覆盖新功能/Bug修复/重构三类）
- [ ] 逐个执行 `claude -p "{task}" --output-format json`
- [ ] 记录每次调用的 exit code、耗时、输出长度
- [ ] 成功率 ≥ 80%（8/10 成功完成）
- [ ] 产出 POC 报告文档

**测试命令**:
```bash
# 手动执行，记录结果到 POC 报告
claude -p "Create a simple FastAPI hello world app" --output-format json
```

---

### Task 1.0.2: 运行行为观察 🔧 手动

**状态**: [ ] 未开始
**依赖**: Task 1.0.1
**产出文件**: POC 报告（同 1.0.1）

**描述**:
订阅模式下无需关注 token 费用。此任务改为观察 CLI 运行行为：耗时分布、输出长度、是否出现无限循环等异常。

**验收标准**:
- [ ] 记录每次调用的耗时和输出长度（行数/字符数）
- [ ] 确认无异常长时间运行（>30 分钟无输出）的情况
- [ ] 结果记入 POC 报告

---

### Task 1.0.3: 网络中断恢复测试 🔧 手动

**状态**: [ ] 未开始
**依赖**: Task 1.0.1
**产出文件**: POC 报告（同 1.0.1）

**验收标准**:
- [ ] 模拟网络中断（断开 VPN/WiFi 后恢复）
- [ ] 记录 CLI 的错误处理行为
- [ ] 确认是否需要额外的重试逻辑

---

### Task 1.0.4: POC 结论 🔧 手动

**状态**: [ ] 未开始
**依赖**: Task 1.0.1, 1.0.2, 1.0.3
**产出文件**: POC 报告最终版

**验收标准**:
- [ ] 通过 → 更新 progress.md，进入 Phase 1A 正式开发
- [ ] 失败 → 记录失败原因，调整策略

---

## 1A — 项目基础设施

### Task 1.1: 创建项目目录结构

**状态**: [ ] 未开始
**依赖**: Task 1.0.4（POC 通过）
**产出文件**: `core/`, `tools/`, `channels/`, `agents/`, `config/`, `data/`, `tests/`, `web/cui/`

**描述**:
按 `docs/requirement.md` 第 11 节定义的目录结构创建所有目录和 `__init__.py`。

**验收标准**:
- [ ] 所有目录已创建（core, tools, channels, agents, config, data, tests, web 及子目录）
- [ ] 每个 Python 包含 `__init__.py`
- [ ] `data/` 目录下创建 `knowledge/`, `chroma/`, `agents/`, `sessions/` 子目录
- [ ] `web/cui/` 目录预留（源码在 Task 1.15 集成）

**测试命令**:
```bash
python -c "import core; import tools; import channels; import agents; print('OK')"
```

---

### Task 1.2: 创建 pyproject.toml（uv 项目配置 + 代码质量工具链）

**状态**: [ ] 未开始
**依赖**: Task 1.1
**产出文件**: `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`

**描述**:
使用 uv 管理项目依赖。配置 ruff + pre-commit 自动强制执行代码规范。

**验收标准**:
- [ ] `pyproject.toml` 的 `[project.dependencies]` 包含 Phase 1A 所需依赖（FastAPI, LiteLLM, ChromaDB, PyGitHub, APScheduler, redis, httpx）
- [ ] `pyproject.toml` 的 `[project.optional-dependencies]` 定义 dev 依赖（pytest, pytest-cov, pytest-asyncio, ruff, pre-commit）
- [ ] LiteLLM 版本号锁定（`litellm==X.Y.Z`）
- [ ] `[tool.ruff]` 配置 Linter 规则：target-version py311, line-length 120, select E/F/I/B/UP/ASYNC
- [ ] `[tool.ruff.format]` 配置 Formatter
- [ ] `.pre-commit-config.yaml` 配置 hooks：ruff check + ruff format
- [ ] `uv sync` 成功安装所有依赖
- [ ] `uv.lock` 已生成

**测试命令**:
```bash
uv sync && uv run python -c "import fastapi; import litellm; print('OK')"
uv run ruff check . --preview
uv run ruff format --check .
```

---

### Task 1.3: 创建 .env.example + .gitignore

**状态**: [ ] 未开始
**依赖**: Task 1.1
**产出文件**: `.env.example`, `.gitignore`

**验收标准**:
- [ ] `.env.example` 包含 `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, `REDIS_URL`, `NTFY_TOPIC`
- [ ] 每个变量附有注释说明，不包含任何真实密钥
- [ ] `.gitignore` 忽略 `.env`、`data/`、`__pycache__/`、`.pytest_cache/`、`*.pyc`、IDE 配置、`web/cui/node_modules/`

---

### Task 1.4: 创建 config/platform.yaml

**状态**: [ ] 未开始
**依赖**: Task 1.1
**产出文件**: `config/platform.yaml`

**验收标准**:
- [ ] 包含 `platform`, `models`, `security`, `storage`, `channels` 所有配置段
- [ ] models.default 设为 `claude-sonnet-4-6`，fallback 包含备选模型
- [ ] 不包含任何 API Key（从 `.env` 读取）
- [ ] 包含 `dispatch.routes` 路由规则配置（渠道→智能体映射，配置化）
- [ ] 包含 `cui` 配置段（host, port, working_directory）

**测试命令**:
```bash
python -c "import yaml; c = yaml.safe_load(open('config/platform.yaml')); print(c['platform']['name'])"
```

---

### Task 1.5: 创建 core/errors.py + core/constants.py

**状态**: [ ] 未开始
**依赖**: Task 1.1
**产出文件**: `core/errors.py`, `core/constants.py`

**验收标准**:
- [ ] `errors.py` 定义 `PlatformError`（基类）、`ToolError`、`ChannelError`、`PermissionDeniedError`、`RateLimitError`、`ValidationError`
- [ ] `constants.py` 定义 `MAX_MESSAGE_LENGTH`, `RATE_LIMIT_PER_MINUTE`, `DEFAULT_MODEL`, `MAX_CONTEXT_TOKENS`, `MAX_TOOL_USE_ROUNDS = 10` 等常量
- [ ] 常量值可被 `config/platform.yaml` 覆盖（通过 config loader）

**测试命令**:
```bash
python -c "from core.errors import PlatformError, PermissionDeniedError; from core.constants import RATE_LIMIT_PER_MINUTE; print('OK')"
```

---

## 1B — 工具层基础

### Task 1.6: 创建 tools/base.py (BaseTool)

**状态**: [ ] 未开始
**依赖**: Task 1.5 (errors.py)
**产出文件**: `tools/base.py`

**接口规范**:
```python
class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict  # JSON Schema

    async def validate_input(self, params: dict) -> bool:
        """JSON Schema 校验，失败抛 ValidationError"""

    @abstractmethod
    async def execute(self, params: dict) -> ToolResult:
        """子类实现具体逻辑"""

    async def cleanup(self) -> None:
        """可选：释放资源，默认无操作"""

@dataclass
class ToolResult:
    success: bool
    data: dict | None = None
    error: str | None = None
```

**验收标准**:
- [ ] `BaseTool` 为 ABC，`execute()` 为抽象方法
- [ ] `validate_input()` 使用 `jsonschema` 库校验参数
- [ ] 校验失败抛出 `ValidationError`
- [ ] `ToolResult` dataclass 定义 `success`, `data`, `error` 字段
- [ ] `cleanup()` 默认实现为空操作，子类可覆写

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_base_tool"
```

---

### Task 1.7: 实现 tools/claude_code_cli.py

**状态**: [ ] 未开始
**依赖**: Task 1.6 (BaseTool)
**产出文件**: `tools/claude_code_cli.py`

**描述**:
封装 Claude Code CLI 为异步子进程工具。Phase 1A 中 cui 直接调用 CLI，此工具供 Phase 1B GitHub Issue 自动化使用。

**验收标准**:
- [ ] 继承 BaseTool，validate_input() 校验必填参数
- [ ] 启动 claude 子进程，传入 `--output-format json`、`--permission-mode dontAsk`
- [ ] 子进程超时（默认 10 分钟）自动终止
- [ ] 子进程运行超过安全上限时终止并返回错误（防止无限循环）
- [ ] 环境变量隔离：不传递 `ANTHROPIC_API_KEY` 到子进程

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_claude_code_cli"
```

---

### Task 1.8: 实现 tools/git_tool.py

**状态**: [ ] 未开始
**依赖**: Task 1.6 (BaseTool)
**产出文件**: `tools/git_tool.py`

**验收标准**:
- [ ] 继承 BaseTool
- [ ] 支持操作：`clone`, `checkout`, `commit`, `push`, `create_pr`
- [ ] GitHub API 操作通过 PyGitHub（`GITHUB_TOKEN` 从环境变量读取）
- [ ] PR 创建返回 PR URL

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_git_tool"
```

---

### Task 1.9: 实现 tools/event_bus_tool.py

**状态**: [ ] 未开始
**依赖**: Task 1.6 (BaseTool), Task 1.11 (event_bus.py)
**产出文件**: `tools/event_bus_tool.py`

**验收标准**:
- [ ] 继承 BaseTool
- [ ] 支持 `publish` 和 `subscribe` 操作
- [ ] `publish` 需要 `event_type` 和 `payload` 参数
- [ ] 事件符合 `PlatformEvent` schema

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_event_bus_tool"
```

---

### Task 1.10: 工具层单元测试

**状态**: [ ] 未开始
**依赖**: Task 1.6 ~ 1.9
**产出文件**: `tests/unit/test_tools.py`

**验收标准**:
- [ ] 包含所有工具的测试
- [ ] 所有测试通过
- [ ] 工具层测试覆盖率 ≥ 80%

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v --cov=tools --cov-report=term-missing
```

---

## 1C — 平台核心

### Task 1.11: 实现 core/event_bus.py

**状态**: [ ] 未开始
**依赖**: Task 1.5 (errors.py, constants.py)
**产出文件**: `core/event_bus.py`

**描述**:
基于 **Redis Lists (LPUSH/BRPOP)** 实现事件总线。

**接口规范**:
```python
class EventBus:
    async def publish(self, event: PlatformEvent) -> None: ...
    async def subscribe(self, event_type: str, handler: Callable) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...

@dataclass
class PlatformEvent:
    event_id: str                # UUID，去重和幂等
    type: str
    source_agent: str
    payload: dict
    timestamp: datetime
    correlation_id: str
```

**验收标准**:
- [ ] 使用 Redis Lists (LPUSH/BRPOP) 作为后端，通过 `redis-py` 异步客户端
- [ ] `publish()` 将事件序列化后推入 Redis
- [ ] `subscribe()` 注册处理函数，消费循环自动调用
- [ ] 事件符合 `PlatformEvent` 数据结构
- [ ] 进程重启后未消费的事件仍可被处理

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_event_bus"
```

---

### Task 1.12: 实现 core/tool_registry.py

**状态**: [ ] 未开始
**依赖**: Task 1.6 (BaseTool)
**产出文件**: `core/tool_registry.py`

**验收标准**:
- [ ] `register(tool: BaseTool)` 注册工具实例
- [ ] `get_tool(name: str, agent_id: str)` 获取工具，校验权限
- [ ] 权限校验基于智能体配置的 `allowed_tools` 列表
- [ ] 未授权调用抛出 `PermissionDeniedError`
- [ ] `list_tools(agent_id: str)` 返回该智能体可用的工具列表

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_tool_registry"
```

---

### Task 1.13: 实现 core/memory.py

**状态**: [ ] 未开始
**依赖**: Task 1.5
**产出文件**: `core/memory.py`

**描述**:
对话记忆管理 + Context 窗口裁剪。供 Phase 1B+ 的 AgentRuntime 使用。

**验收标准**:
- [ ] 消息以 JSONL 格式追加写入 `data/agents/<agent_id>/sessions/<session_id>/messages.jsonl`
- [ ] `ContextPruner` 在 token 超过模型上限 80% 时截断最旧轮次，保留系统 Prompt + 最新 15 轮
- [ ] 单条消息超过 8000 token 时截断并附注 `[内容已截断]`

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_memory"
```

---

### Task 1.14: 实现 core/agent_runtime.py

**状态**: [ ] 未开始
**依赖**: Task 1.12 (tool_registry), Task 1.13 (memory)
**产出文件**: `core/agent_runtime.py`

**描述**:
智能体运行循环，asyncio while 循环实现 tool_use 编排。供 Phase 1B+ 使用。

**验收标准**:
- [ ] 通过 LiteLLM 调用模型，返回统一的 `AgentResponse`
- [ ] 当模型返回 `tool_use` 时，执行工具并将结果反馈
- [ ] tool_use 循环直到模型返回 `stop` 或达到 `MAX_TOOL_USE_ROUNDS`
- [ ] 每轮调用前执行 `ContextPruner` 裁剪
- [ ] 模型 Fallback：主模型失败时按 `config/platform.yaml` 降级
- [ ] 用户输入净化：不直接拼接到系统 Prompt，过滤控制字符、截断超长输入

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_agent_runtime"
```

---

### Task 1.15: 实现 channels/base.py (BaseChannel)

**状态**: [ ] 未开始
**依赖**: Task 1.5
**产出文件**: `channels/base.py`

**描述**:
渠道抽象基类。Phase 1B (GitHub Webhook) 和 Phase 3 (Telegram) 将继承此基类。

**验收标准**:
- [ ] `BaseChannel` 为 ABC
- [ ] `start()`, `stop()`, `send()` 为抽象方法
- [ ] `verify_user()` 默认实现基于 `allowed_users` 白名单
- [ ] `Message` dataclass 定义文本消息结构

**测试命令**:
```bash
uv run pytest tests/unit/test_channels.py -v -k "test_base_channel"
```

---

### Task 1.16: 实现 core/dispatch.py + core/channel_manager.py

**状态**: [ ] 未开始
**依赖**: Task 1.15
**产出文件**: `core/dispatch.py`, `core/channel_manager.py`

**描述**:
渠道生命周期管理 + 消息路由框架。Phase 1A 无活跃渠道，框架就绪供 Phase 1B 使用。

**验收标准**:
- [ ] `channel_manager`: `register()`, `start_all()`, `stop_all()`，单个渠道启动失败不影响其他
- [ ] `dispatch`: 路由规则从 `config/platform.yaml` 的 `dispatch.routes` 读取（配置化，不硬编码）
- [ ] 未知消息类型记录 WARNING 日志

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_dispatch or test_channel_manager"
```

---

### Task 1.17: 核心模块 + 渠道基类单元测试

**状态**: [ ] 未开始
**依赖**: Task 1.11 ~ 1.16
**产出文件**: `tests/unit/test_core.py`, `tests/unit/test_channels.py`

**验收标准**:
- [ ] 包含所有核心模块和渠道基类的测试
- [ ] 所有测试通过
- [ ] 核心模块测试覆盖率 ≥ 80%

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py tests/unit/test_channels.py -v --cov=core --cov=channels --cov-report=term-missing
```

---

## 1D — Web UI (cui) 集成

### Task 1.18: Fork 并集成 cui 源码

**状态**: [ ] 未开始
**依赖**: Task 1.1
**产出文件**: `web/cui/` 完整源码

**描述**:
Fork wbopan/cui 仓库，将源码复制到 `web/cui/` 目录，验证本地构建和运行。

**验收标准**:
- [ ] `web/cui/` 包含 cui 完整源码（保留 MIT LICENSE）
- [ ] `cd web/cui && npm install` 成功
- [ ] `npm run dev` 启动后浏览器能访问
- [ ] 能与本机 Claude Code CLI 正常交互（发送消息、收到回复、看到工具调用）

**测试命令**:
```bash
cd web/cui && npm install && npm run build
```

---

### Task 1.19: 配置 cui + 反向代理认证

**状态**: [ ] 未开始
**依赖**: Task 1.18
**产出文件**: `web/cui/` 配置更新, `config/nginx/` 或 `Caddyfile`

**描述**:
配置 cui 绑定到 `0.0.0.0` 支持远程访问，通过反向代理（nginx 或 Caddy）添加 HTTPS + Basic Auth 认证，确保只有 Owner 能访问。

**验收标准**:
- [ ] cui 配置 `host: "0.0.0.0"` 允许远程连接
- [ ] 反向代理配置 HTTPS（自签证书或 Let's Encrypt）
- [ ] Basic Auth 或 API Token 认证（防止未授权访问）
- [ ] 从外部浏览器通过 HTTPS 能访问 cui 并正常使用

**测试命令**:
```bash
curl -u owner:password https://your-server:port/health
```

---

### Task 1.20: 配置 ntfy 推送通知

**状态**: [ ] 未开始
**依赖**: Task 1.18
**产出文件**: `web/cui/` 配置更新

**描述**:
配置 cui 的 ntfy 推送通知功能，当后台任务完成或失败时推送到 Owner 手机。

**验收标准**:
- [ ] ntfy topic 配置到 cui 设置中
- [ ] 后台任务完成后收到 ntfy 推送
- [ ] 后台任务失败后收到 ntfy 推送（含错误摘要）
- [ ] 手机安装 ntfy app 能正常收到通知

**测试命令**:
```bash
# 手动验证：启动 cui，提交一个后台任务，关闭浏览器，等待 ntfy 推送
curl -d "Test notification" ntfy.sh/your-topic
```

---

## 1E — 安全基础

### Task 1.21: 实现速率限制

**状态**: [ ] 未开始
**依赖**: Task 1.5 (errors.py)
**产出文件**: `core/rate_limiter.py`

**验收标准**:
- [ ] 基于滑动窗口的速率限制
- [ ] 限制阈值从 `constants.py` 读取（RATE_LIMIT_PER_MINUTE = 10）
- [ ] 超出限制抛出 `RateLimitError`
- [ ] 不同用户独立计数

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_rate_limiter"
```

---

### Task 1.22: 实现审计日志 + 日志脱敏

**状态**: [ ] 未开始
**依赖**: Task 1.5
**产出文件**: `core/audit.py`

**验收标准**:
- [ ] 审计日志包含：时间、智能体 ID、工具名、参数摘要、结果状态
- [ ] 敏感信息自动脱敏（正则匹配 API Key、Token 等模式）
- [ ] 脱敏格式：`sk-ant-...****`（保留前缀 + 后 4 位）
- [ ] 日志输出到标准 logging + 可选文件

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_audit"
```

---

## 1F — 平台入口 + 部署

### Task 1.23: 实现 main.py

**状态**: [ ] 未开始
**依赖**: Task 1.16 (channel_manager), Task 1.12 (tool_registry), Task 1.11 (event_bus)
**产出文件**: `main.py`

**验收标准**:
- [ ] 加载 `.env` 环境变量
- [ ] 加载 `config/platform.yaml` 配置
- [ ] 初始化并注册所有工具
- [ ] 启动事件总线
- [ ] 启动 FastAPI 应用
- [ ] 提供 `GET /health` 端点（平台状态、Redis 连接、cui 服务状态）
- [ ] 优雅关闭：SIGINT/SIGTERM 时依次停止渠道 → 事件总线

**测试命令**:
```bash
uv run python -c "from main import create_app; app = create_app(); print('App created successfully')"
```

---

### Task 1.24: 创建 Dockerfile + docker-compose.yml

**状态**: [ ] 未开始
**依赖**: Task 1.23
**产出文件**: `Dockerfile`, `web/cui/Dockerfile`, `docker-compose.yml`

**描述**:
Docker Compose 配置，包含三个服务：Python 平台、cui Web UI、Redis。

**验收标准**:
- [ ] `Dockerfile`：Python 平台镜像（使用 uv）
- [ ] `web/cui/Dockerfile`：cui Node.js 镜像
- [ ] `docker-compose.yml` 定义三个服务：`platform`、`cui`、`redis`
- [ ] 环境变量通过 `.env` 文件注入
- [ ] 端口映射：FastAPI 8000、cui 3001、Redis 6379
- [ ] 共享卷：代码仓库目录、`~/.claude/` 会话数据、`data/` 运行时数据
- [ ] health check 配置

**测试命令**:
```bash
docker-compose config  # 验证配置语法
```

---

### Task 1.25: 端到端验证

**状态**: [ ] 未开始
**依赖**: Task 1.23, Task 1.24, Task 1.19, Task 1.20
**产出文件**: 无（验证性任务）

**描述**:
完整验证 Phase 1A 交付物。

**验收标准**:
- [ ] `docker-compose up -d` 一键启动成功
- [ ] 浏览器访问 cui Web UI，需要认证
- [ ] 认证后能与 Claude Code 交互（发送开发任务、看到代码阅读过程、收到回复）
- [ ] 提交后台任务，关闭浏览器，任务继续执行
- [ ] 任务完成后手机收到 ntfy 推送
- [ ] `GET /health` 返回所有服务状态正常
- [ ] `docker-compose logs` 无 ERROR 级别日志
- [ ] `uv run pytest tests/ -v` 所有测试通过

---

### Task 1.26: Post-Phase 文档同步 + Git Tag

**状态**: [ ] 未开始
**依赖**: Task 1.25

**验收标准**:
- [ ] 本文件所有任务标记 `[x]`
- [ ] `docs/progress.md` Quick Status 更新
- [ ] 测试数更新到 Test Count History
- [ ] `git tag -a v0.1.0 -m "Phase 1A: 平台骨架 + Web UI 开发工具"`
- [ ] 推送 tag 到远程
