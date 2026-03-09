# Phase 1A: 平台基础设施 + cui Web UI 部署

**分支**: `feat/phase-1a-devbot`
**Tag**: `v0.1.0`
**目标**: 搭建平台核心基础设施（事件总线、工具注册、配置系统、日志追踪），部署 cui Web UI 让 Owner 通过浏览器直接使用 Claude Code CLI
**预计时长**: 3 周

**完成条件**: 平台核心基础设施（事件总线、工具注册、配置系统、日志追踪）已就绪；Owner 通过浏览器访问 cui Web UI，能与 Claude Code 交互（需求澄清、代码执行、结果查看）；后台任务支持关闭浏览器后继续执行；ntfy 推送任务完成通知；Docker Compose 一键启动

---

## Session 边界建议

> Phase 1A 共 28 个任务，分 6 个任务组。建议按任务组划分 AI 工作 session，每次 session 完成一个任务组后 commit 并更新文档。

| Session | 任务组 | 范围 | 预计任务数 |
|---------|--------|------|-----------|
| Session 1 | 1A — 项目基础设施 | Task 1.1 ~ 1.5 | 5 |
| Session 2 | 1B — 工具层基础 | Task 1.6 ~ 1.10 | 5 |
| Session 3 | 1C — 平台核心 | Task 1.11 ~ 1.17 | 7 |
| Session 4 | 1D — Web UI (cui) 集成 | Task 1.18 ~ 1.20b | 5 |
| Session 5 | 1E — 安全基础 | Task 1.21 ~ 1.22 | 2 |
| Session 6 | 1F — 平台入口 + 部署 | Task 1.23 ~ 1.26 | 4 |

---

## 1A — 项目基础设施

### Task 1.1: 创建项目目录结构

**状态**: [x] 完成
**依赖**: 无
**产出文件**: `core/`, `tools/`, `channels/`, `agents/`, `config/`, `data/`, `tests/`, `web/cui/`

**描述**:
按 `docs/requirement.md` 第 11 节定义的目录结构创建所有目录和 `__init__.py`。

**验收标准**:
- [x] 所有目录已创建（core, tools, channels, agents, config, data, tests, web 及子目录）
- [x] 每个 Python 包含 `__init__.py`
- [x] `data/` 目录下创建 `knowledge/`, `chroma/`, `agents/`, `sessions/` 子目录
- [x] `web/cui/` 目录预留（源码在 Task 1.18 集成）

**测试命令**:
```bash
python -c "import core; import tools; import channels; import agents; print('OK')"
```

---

### Task 1.2: 创建 pyproject.toml（uv 项目配置 + 代码质量工具链）

**状态**: [x] 完成
**依赖**: Task 1.1
**产出文件**: `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`

**描述**:
使用 uv 管理项目依赖。配置 ruff + pre-commit 自动强制执行代码规范。

**验收标准**:
- [x] `pyproject.toml` 的 `[project.dependencies]` 包含 Phase 1A 所需依赖（FastAPI, LiteLLM, ChromaDB, PyGitHub, APScheduler, redis, httpx）
- [x] `pyproject.toml` 的 `[project.optional-dependencies]` 定义 dev 依赖（pytest, pytest-cov, pytest-asyncio, ruff, pre-commit）
- [x] LiteLLM 版本号锁定（`litellm==1.81.6`）
- [x] `[tool.ruff]` 配置 Linter 规则：target-version py311, line-length 120, select E/F/I/B/UP/ASYNC
- [x] `[tool.ruff.format]` 配置 Formatter
- [x] `.pre-commit-config.yaml` 配置 hooks：ruff check + ruff format
- [x] `uv sync` 成功安装所有依赖
- [x] `uv.lock` 已生成

**测试命令**:
```bash
uv sync && uv run python -c "import fastapi; import litellm; print('OK')"
uv run ruff check . --preview
uv run ruff format --check .
```

---

### Task 1.3: 创建 .env.example + .gitignore

**状态**: [x] 完成
**依赖**: Task 1.1
**产出文件**: `.env.example`, `.gitignore`

**验收标准**:
- [x] `.env.example` 包含 `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET`, `REDIS_URL`, `NTFY_TOPIC`
- [x] 每个变量附有注释说明，不包含任何真实密钥
- [x] `.gitignore` 忽略 `.env`、`data/`、`__pycache__/`、`.pytest_cache/`、`*.pyc`、IDE 配置、`web/cui/node_modules/`

---

### Task 1.4: 创建 config/platform.yaml + core/config.py (Config Loader)

**状态**: [x] 完成
**依赖**: Task 1.1
**产出文件**: `config/platform.yaml`, `core/config.py`

**描述**:
创建平台配置文件和配置加载器。`core/config.py` 负责读取 `config/platform.yaml`，提供全局配置访问接口，供 `constants.py` 和其他模块使用。

**验收标准**:
- [x] 包含 `platform`, `models`, `security`, `storage`, `channels` 所有配置段
- [x] models.default 设为 `claude-sonnet-4-6`，fallback 包含备选模型
- [x] 不包含任何 API Key（从 `.env` 读取）
- [x] 包含 `dispatch.routes` 路由规则配置（渠道→智能体映射，配置化）
- [x] 包含 `cui` 配置段（host, port, working_directory）
- [x] `core/config.py` 实现 `load_config(path)` 函数，返回解析后的配置字典
- [x] 配置加载失败时抛出明确异常（文件不存在、YAML 格式错误）
- [x] 提供 `get_config()` 单例访问接口，避免重复加载

**测试命令**:
```bash
python -c "import yaml; c = yaml.safe_load(open('config/platform.yaml')); print(c['platform']['name'])"
uv run pytest tests/unit/test_core.py -v -k "test_config"
```

---

### Task 1.5: 创建 core/errors.py + core/constants.py

**状态**: [x] 完成
**依赖**: Task 1.1
**产出文件**: `core/errors.py`, `core/constants.py`

**验收标准**:
- [x] `errors.py` 定义 `PlatformError`（基类）、`ToolError`、`ChannelError`、`PermissionDeniedError`、`RateLimitError`、`ValidationError`
- [x] `constants.py` 定义 `MAX_MESSAGE_LENGTH`, `RATE_LIMIT_PER_MINUTE`, `DEFAULT_MODEL`, `MAX_CONTEXT_TOKENS`, `MAX_TOOL_USE_ROUNDS = 10`, `MAX_INPUT_LENGTH = 16000`, `CONTEXT_ROUND_DEFINITION = "user+assistant pair"` 等常量
- [x] 常量值可被 `config/platform.yaml` 覆盖（通过 Task 1.4 的 `core/config.py` config loader）

**测试命令**:
```bash
python -c "from core.errors import PlatformError, PermissionDeniedError; from core.constants import RATE_LIMIT_PER_MINUTE; print('OK')"
```

---

## 1B — 工具层基础

### Task 1.6: 创建 tools/base.py (BaseTool)

**状态**: [x] 完成
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
- [x] `BaseTool` 为 ABC，`execute()` 为抽象方法
- [x] `validate_input()` 使用 `jsonschema` 库校验参数
- [x] 校验失败抛出 `ValidationError`
- [x] `ToolResult` dataclass 定义 `success`, `data`, `error` 字段
- [x] `cleanup()` 默认实现为空操作，子类可覆写

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_base_tool"
```

---

### Task 1.7: 实现 tools/claude_code_cli.py

**状态**: [x] 完成
**依赖**: Task 1.6 (BaseTool)
**产出文件**: `tools/claude_code_cli.py`

**描述**:
封装 Claude Code CLI 为异步子进程工具。Phase 1A 中 cui 直接调用 CLI，此工具供 Phase 1B GitHub Issue 自动化使用。

**验收标准**:
- [x] 继承 BaseTool，validate_input() 校验必填参数
- [x] 启动 claude 子进程，传入 `--output-format json`、`--permission-mode dontAsk`
- [x] 子进程超时（默认 10 分钟）自动终止
- [x] 子进程运行超过安全上限时终止并返回错误（防止无限循环）
- [x] 环境变量隔离：不传递 `ANTHROPIC_API_KEY` 到子进程

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_claude_code_cli"
```

---

### Task 1.8: 实现 tools/git_tool.py

**状态**: [x] 完成
**依赖**: Task 1.6 (BaseTool)
**产出文件**: `tools/git_tool.py`

**验收标准**:
- [x] 继承 BaseTool
- [x] 支持操作：`clone`, `checkout`, `commit`, `push`, `create_pr`
- [x] GitHub API 操作通过 PyGitHub（`GITHUB_TOKEN` 从环境变量读取）
- [x] PR 创建返回 PR URL

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_git_tool"
```

---

### Task 1.9: 实现 tools/event_bus_tool.py

**状态**: [x] 完成
**依赖**: Task 1.6 (BaseTool), Task 1.11 (event_bus.py)
**产出文件**: `tools/event_bus_tool.py`

**描述**:
封装事件总线操作为工具。注意依赖方向：`tools/` 可依赖 `core/` 的接口（`core/ ← tools/` 是允许的方向），event_bus_tool 通过构造函数注入 `EventBus` 实例，不直接 import core 模块的内部实现。

**验收标准**:
- [x] 继承 BaseTool
- [x] 通过构造函数注入 `EventBus` 实例（依赖注入，不在模块顶层 import core.event_bus）
- [x] 支持 `publish` 和 `subscribe` 操作
- [x] `publish` 需要 `event_type` 和 `payload` 参数
- [x] 事件符合 `PlatformEvent` schema

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v -k "test_event_bus_tool"
```

---

### Task 1.10: 工具层单元测试

**状态**: [x] 完成
**依赖**: Task 1.6 ~ 1.9
**产出文件**: `tests/unit/test_tools.py`

**验收标准**:
- [x] 包含所有工具的测试
- [x] 所有测试通过（35 个测试全部通过）
- [x] 工具层测试覆盖率 ≥ 80%（base 100%, cli 90%, event_bus 96%, git 62% — 整体 >80%）

**测试命令**:
```bash
uv run pytest tests/unit/test_tools.py -v --cov=tools --cov-report=term-missing
```

---

## 1C — 平台核心

### Task 1.11: 实现 core/event_bus.py

**状态**: [x] 完成
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
- [x] 使用 Redis Lists (LPUSH/BRPOP) 作为后端，通过 `redis-py` 异步客户端
- [x] `publish()` 将事件序列化后推入 Redis
- [x] `subscribe()` 注册处理函数，消费循环自动调用
- [x] 事件符合 `PlatformEvent` 数据结构
- [x] 进程重启后未消费的事件仍可被处理

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_event_bus"
```

---

### Task 1.12: 实现 core/tool_registry.py

**状态**: [x] 完成
**依赖**: Task 1.6 (BaseTool)
**产出文件**: `core/tool_registry.py`

**验收标准**:
- [x] `register(tool: BaseTool)` 注册工具实例
- [x] `get_tool(name: str, agent_id: str)` 获取工具，校验权限
- [x] 权限校验基于智能体配置的 `allowed_tools` 列表
- [x] 未授权调用抛出 `PermissionDeniedError`
- [x] `list_tools(agent_id: str)` 返回该智能体可用的工具列表

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_tool_registry"
```

---

### Task 1.13: 实现 core/memory.py

**状态**: [x] 完成
**依赖**: Task 1.5
**产出文件**: `core/memory.py`

**描述**:
对话记忆管理 + Context 窗口裁剪。供 Phase 1B+ 的 AgentRuntime 使用。

**验收标准**:
- [x] 消息以 JSONL 格式追加写入 `data/agents/<agent_id>/sessions/<session_id>/messages.jsonl`
- [x] `ContextPruner` 在 token 超过模型上限 80% 时截断最旧轮次，保留系统 Prompt + 最新 15 轮（1 轮 = 1 次 user 消息 + 1 次 assistant 回复，tool_result 附属于所在轮次）
- [x] 单条消息超过 8000 token 时截断并附注 `[内容已截断]`

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_memory"
```

---

### Task 1.14: 实现 core/agent_runtime.py

**状态**: [x] 完成
**依赖**: Task 1.12 (tool_registry), Task 1.13 (memory)
**产出文件**: `core/agent_runtime.py`

**描述**:
智能体运行循环，asyncio while 循环实现 tool_use 编排。供 Phase 1B+ 使用。

**验收标准**:
- [x] 通过 LiteLLM 调用模型，返回统一的 `AgentResponse`
- [x] 当模型返回 `tool_use` 时，执行工具并将结果反馈
- [x] tool_use 循环直到模型返回 `stop` 或达到 `MAX_TOOL_USE_ROUNDS`
- [x] 每轮调用前执行 `ContextPruner` 裁剪
- [x] 模型 Fallback：主模型失败时按 `config/platform.yaml` 降级
- [x] 用户输入净化：不直接拼接到系统 Prompt，过滤 Unicode 控制字符（C0/C1 控制码，保留换行和制表符），截断超过 `MAX_INPUT_LENGTH`（默认 16000 字符）的输入并附注 `[输入已截断]`

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_agent_runtime"
```

---

### Task 1.15: 实现 channels/base.py (BaseChannel)

**状态**: [x] 完成
**依赖**: Task 1.5
**产出文件**: `channels/base.py`

**描述**:
渠道抽象基类。Phase 1B (GitHub Webhook) 和 Phase 3 (Telegram) 将继承此基类。

**验收标准**:
- [x] `BaseChannel` 为 ABC
- [x] `start()`, `stop()`, `send()` 为抽象方法
- [x] `verify_user()` 默认实现基于 `allowed_users` 白名单
- [x] `Message` dataclass 定义文本消息结构

**测试命令**:
```bash
uv run pytest tests/unit/test_channels.py -v -k "test_base_channel"
```

---

### Task 1.16: 实现 core/dispatch.py + core/channel_manager.py

**状态**: [x] 完成
**依赖**: Task 1.15
**产出文件**: `core/dispatch.py`, `core/channel_manager.py`

**描述**:
渠道生命周期管理 + 消息路由框架。Phase 1A 无活跃渠道，框架就绪供 Phase 1B 使用。

**验收标准**:
- [x] `channel_manager`: `register()`, `start_all()`, `stop_all()`，单个渠道启动失败不影响其他
- [x] `dispatch`: 路由规则从 `config/platform.yaml` 的 `dispatch.routes` 读取（配置化，不硬编码）
- [x] 未知消息类型记录 WARNING 日志

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_dispatch or test_channel_manager"
```

---

### Task 1.17: 核心模块 + 渠道基类单元测试

**状态**: [x] 完成
**依赖**: Task 1.11 ~ 1.16
**产出文件**: `tests/unit/test_core.py`, `tests/unit/test_channels.py`

**验收标准**:
- [x] 包含所有核心模块和渠道基类的测试（73 个测试）
- [x] 所有测试通过
- [x] 核心模块测试覆盖率 ≥ 80%（config 100%, dispatch 100%, tool_registry 100%, memory 98%, channel_manager 90%, base 100%）

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py tests/unit/test_channels.py -v --cov=core --cov=channels --cov-report=term-missing
```

---

## 1D — Web UI (cui) 集成

### Task 1.18: cui POC 验证（Gate Task）

**状态**: [x] 完成
**依赖**: Task 1.1
**产出文件**: `web/cui/` 完整源码, `docs/poc/cui-poc-report.md`

**描述**:
**Gate Task**：在正式配置 cui 之前，先做 POC 验证，确认 cui 的实际能力和集成方式。POC 结果将决定 Task 1.19 和 Task 1.20 的具体实施方案。

Fork wbopan/cui 仓库，将源码复制到 `web/cui/` 目录，本地构建和运行，逐项验证以下能力。

**POC 验证清单**:
- [x] `web/cui/` 包含 cui 完整源码（保留 Apache-2.0 LICENSE）
- [x] `cd web/cui && npm install && npm run build` 成功
- [ ] `npm run dev` 启动后浏览器能访问（需 Owner 手动验证）
- [ ] 能与本机 Claude Code CLI 正常交互（需 Owner 手动验证）
- [x] **远程访问能力**：支持 `--host 0.0.0.0` 和 `~/.cui/config.json` 配置
- [x] **后台任务能力**：内置 ProcessManager，独立子进程，关闭浏览器后继续
- [x] **ntfy 推送能力**：内置 notification-service.ts，支持自定义 ntfy URL
- [x] **Docker 化能力**：无内置 Dockerfile，需自建（方案已记录在 POC 报告中）

**产出**:
编写 `docs/poc/cui-poc-report.md`，包含：
1. 每项验证的结果（通过/不通过/需适配）
2. cui 的实际配置机制和限制
3. 对 Task 1.19 和 Task 1.20 的具体方案建议（基于 POC 发现）
4. 如发现 cui 不满足需求，提出替代方案

**测试命令**:
```bash
cd web/cui && npm install && npm run build
```

**Gate 规则**:
- POC 全部通过 → 按 POC 报告中的方案执行 Task 1.19 和 Task 1.20
- POC 部分不通过 → 根据报告调整 Task 1.19/1.20 的验收标准后再执行
- POC 发现根本性问题 → 暂停 1D 任务组，与 Owner 讨论替代方案

---

### Task 1.19: 配置 cui 远程访问 + 认证

**状态**: [x] 完成
**依赖**: Task 1.18 (POC 通过后)
**产出文件**: `~/.cui/config.json`, `/etc/systemd/system/cui.service`

**实际方案**: VPN（OpenVPN）内网访问，cui 绑定 10.8.0.1:3001，Bearer Token 认证

**验收标准**（已调整为 VPN 方案）:
- [x] cui 支持从 VPN 内网访问（10.8.0.1:3001）
- [x] VPN 加密传输（等效 HTTPS 安全性）
- [x] Bearer Token 认证机制保护
- [x] 从浏览器能正常使用 cui 全部功能
- [x] cui 由 systemd 管理，开机自启，崩溃自动重启
- [x] OpenVPN 服务修复（快照恢复后 IP 变更导致绑定失败）

**测试命令**:
```bash
# 具体命令根据 POC 报告确定的方案填写
curl -k https://your-server:port/  # 验证 HTTPS 可达
```

---

### Task 1.20: 配置 ntfy 推送通知

**状态**: [x] 完成
**依赖**: Task 1.18 (POC 通过后)
**产出文件**: `~/.cui/config.json`（notifications 段）

**验收标准**:
- [x] 后台任务完成后 Owner 手机收到推送通知
- [x] ntfy topic 通过 ~/.cui/config.json 配置（topic: cgs-dev-910czf）
- [x] iOS ntfy App 已安装并订阅 topic，推送验证通过

**测试命令**:
```bash
# 手动验证：启动 cui，提交一个后台任务，关闭浏览器，等待推送
curl -d "Test notification" ntfy.sh/${NTFY_TOPIC}
```

---

### Task 1.20a: 实现平台日志基础设施

**状态**: [x] 完成
**依赖**: Task 1.5
**产出文件**: `core/logging.py`

**描述**:
日志是平台跨层基础设施，所有后续 Phase 的所有模块都依赖此模块。需实现：统一 logger 入口、结构化输出、请求级 trace_id 追踪、性能日志。详细需求见 `docs/requirement.md` §3.4。

**验收标准**:

*基础能力*:
- [x] 提供 `setup_logging(level, format)` 函数，统一配置 Python 标准 logging
- [x] 提供 `get_logger(name)` 便捷函数，各模块通过 `logger = get_logger(__name__)` 获取 logger
- [x] 日志级别可通过 `config/platform.yaml` 的 `logging.level` 或环境变量 `LOG_LEVEL` 配置，环境变量优先

*结构化输出*:
- [x] 支持两种输出格式，通过 `LOG_FORMAT` 环境变量或配置切换：
  - `text`（默认/开发）：人类可读格式，含时间戳、模块名、级别、消息
  - `json`（生产）：JSON 结构化格式，每行一个 JSON 对象，便于 `jq` 查询

*Trace ID 追踪*:
- [x] 提供 `trace_id` ContextVar，渠道层入口调用 `set_trace_id()` 生成 UUID
- [x] 所有日志输出自动附加当前 `trace_id` 字段（通过自定义 Filter 实现）
- [x] 提供 `get_trace_id()` 函数，供事件总线写入 `PlatformEvent.correlation_id`
- [x] 无 trace_id 时日志正常输出（字段值为 `-`），不报错

*性能日志*:
- [x] 提供 `@log_duration` 装饰器（支持同步和 async 函数），自动记录函数执行耗时 ms
- [x] 装饰器输出 INFO 级别日志，包含：函数名、耗时 ms、成功/失败

*文件输出（可选）*:
- [x] 支持通过 `logging.file` 配置输出到文件，使用 `RotatingFileHandler`（10MB/文件，保留 5 个）
- [x] 未配置 `logging.file` 时仅输出到 stdout

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_logging"
```

---

### Task 1.20b: 创建 tests/conftest.py 公共 Fixtures

**状态**: [x] 完成
**依赖**: Task 1.2
**产出文件**: `tests/conftest.py`

**描述**:
创建测试公共 fixtures，供所有测试模块共享。

**验收标准**:
- [x] 提供 `mock_config` fixture（加载测试用 platform.yaml）
- [x] 提供 `event_loop` fixture（pytest-asyncio mode="auto" 在 pyproject.toml 中配置）
- [x] 提供 `tmp_data_dir` fixture（临时 data 目录，测试后自动清理）
- [x] 配置 pytest-asyncio mode = "auto"

**测试命令**:
```bash
uv run pytest tests/ --co  # 验证 fixtures 可发现
```

---

## 1E — 安全基础

### Task 1.21: 实现速率限制

**状态**: [x] 完成
**依赖**: Task 1.5 (errors.py)
**产出文件**: `core/rate_limiter.py`

**验收标准**:
- [x] 基于滑动窗口的速率限制（per-user 粒度，与需求文档"单用户每分钟最多 10 条消息"一致）
- [x] 限制阈值从 `constants.py` 读取（RATE_LIMIT_PER_MINUTE = 10）
- [x] 超出限制抛出 `RateLimitError`
- [x] 不同用户独立计数（user_id 作为限流 key）

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_rate_limiter"
```

---

### Task 1.22: 实现审计日志 + 日志脱敏

**状态**: [x] 完成
**依赖**: Task 1.5
**产出文件**: `core/audit.py`

**验收标准**:
- [x] 审计日志包含：时间、智能体 ID、工具名、参数摘要、结果状态
- [x] 敏感信息自动脱敏（正则匹配 API Key、Token 等模式）
- [x] 脱敏格式：`sk-ant-...****`（保留前缀 + 后 4 位）
- [x] 日志输出到标准 logging + 可选文件

**测试命令**:
```bash
uv run pytest tests/unit/test_core.py -v -k "test_audit"
```

---

## 1F — 平台入口 + 部署

### Task 1.23: 实现 main.py

**状态**: [x] 完成
**依赖**: Task 1.16 (channel_manager), Task 1.12 (tool_registry), Task 1.11 (event_bus)
**产出文件**: `main.py`

**验收标准**:
- [x] 加载 `.env` 环境变量
- [x] 加载 `config/platform.yaml` 配置
- [x] 初始化并注册所有工具
- [x] 启动事件总线
- [x] 启动 FastAPI 应用
- [x] 提供 `GET /health` 端点（平台状态、Redis 连接、cui 服务状态）
- [x] 优雅关闭：SIGINT/SIGTERM 时依次停止渠道 → 事件总线

**测试命令**:
```bash
uv run python -c "from main import create_app; app = create_app(); print('App created successfully')"
```

---

### Task 1.24: 创建 Dockerfile + docker-compose.yml

**状态**: [x] 完成
**依赖**: Task 1.23
**产出文件**: `Dockerfile`, `web/cui/Dockerfile`, `docker-compose.yml`

**描述**:
Docker Compose 配置，包含三个服务：Python 平台、cui Web UI、Redis。

**验收标准**:
- [x] `Dockerfile`：Python 平台镜像（使用 uv）
- [x] `web/cui/Dockerfile`：cui Node.js 镜像
- [x] `docker-compose.yml` 定义三个服务：`platform`、`cui`、`redis`
- [x] 环境变量通过 `.env` 文件注入
- [x] 端口映射：FastAPI 8000、cui 3001、Redis 6379
- [x] 共享卷：代码仓库目录、`~/.claude/` 会话数据、`data/` 运行时数据
- [x] health check 配置

**测试命令**:
```bash
docker-compose config  # 验证配置语法
```

---

### Task 1.25: 端到端验证

**状态**: [x] 完成
**依赖**: Task 1.23, Task 1.24, Task 1.19, Task 1.20, Task 1.20a
**产出文件**: 无（验证性任务）

**描述**:
完整验证 Phase 1A 交付物。

**验收标准**:
- [x] `docker-compose up -d` 一键启动成功（platform + redis，cui 由 systemd 管理）
- [x] 浏览器访问 cui Web UI，需要认证（Bearer Token）
- [x] 认证后能与 Claude Code 交互（Owner 验证通过）
- [x] ntfy 推送验证通过（iPhone 收到测试消息）
- [x] `GET /health` 返回 redis: connected，所有服务状态正常
- [x] `docker-compose logs` 无 ERROR 级别日志
- [x] `uv run pytest tests/ -v` 144 个测试全部通过

**说明**:
- Docker Compose v2 插件已安装（v2.35.0），修复了与 Docker Engine 28.x 的兼容问题
- main.py 修复：Redis URL 优先从环境变量 REDIS_URL 读取
- 测试修复：test_setup_logging_text 隔离 LOG_LEVEL 环境变量（uv run 自动加载 .env）

---

### Task 1.26: Post-Phase 文档同步 + Git Tag

**状态**: [x] 完成
**依赖**: Task 1.25

**验收标准**:
- [x] 本文件所有任务标记 `[x]`
- [x] `docs/progress.md` Quick Status 更新
- [x] 测试数更新到 Test Count History
- [x] `git tag -a v0.1.0 -m "Phase 1A: 平台骨架 + Web UI 开发工具"`
- [x] 推送 tag 到远程
