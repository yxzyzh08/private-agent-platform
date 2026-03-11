# CLAUDE.md — AI 工作指南

> **定位**：本文件告诉 Claude Code **怎么工作**（流程、规范、工具）。
> 项目**要做什么**见 [`docs/requirement.md`](docs/requirement.md)，**做到哪了**见 [`docs/progress.md`](docs/progress.md)。

---

# 1. Session Recovery — MUST READ FIRST

> **每次新会话、`/clear`、或上下文压缩后，在做任何事之前，必须执行：**
>
> 1. **读取 `docs/progress.md`** — 查看 Quick Status 表：当前 Phase（N）、当前任务、工作分支
> 2. **读取 `docs/phases/phase-N.md`** — 找到第一个 `[ ]` 任务，阅读其**验收标准**和**测试命令**
> 3. **检查产出文件** — 该任务的产出文件是否已存在？如已有部分代码则先阅读理解再继续，避免覆盖已有工作
> 4. **切换到正确分支** — `git checkout <branch>`（如果是 git repo）
> 5. **运行测试** — `python -m pytest tests/ -v`（有测试时）确认 baseline
> 6. **一致性验证** — 对 phase 文件中已标记 `[x]` 的最近 3 个任务，快速检查其产出文件是否存在且测试通过。发现不一致时，优先修复再继续
> 7. **开始开发** — 无需等待用户指示，直接开始

当用户说 **"继续"、"continue"、"接着做"** 或类似指令时，同样执行上述步骤。

> **每完成一个任务，必须：**
> 1. 运行该任务的**测试命令**自验，通过才标 `[x]`
> 2. 更新 `docs/phases/phase-N.md`（标记任务 `[x]`）
> 3. 继续下一个任务
>
> **每完成一个任务组（如 1A、1B），批量更新：**
> 1. 更新 `docs/progress.md`（Quick Status 当前任务、进度、测试数）
> 2. Commit 代码 + 文档
>
> **涉及 CUI 前端改动时，必须重建并重启 Docker 容器（当前环境即研发环境）：**
> ```bash
> docker-compose build cui && docker-compose up -d cui
> ```
> 如遇 `ContainerConfig` 错误，先手动删除旧容器再重建：
> ```bash
> docker rm -f $(docker ps -aq --filter "name=cui") 2>/dev/null; docker-compose up -d cui
> ```
> 验证：浏览器 Ctrl+Shift+R 强制刷新，确认改动生效

**三层文档体系**：
```
CLAUDE.md                    ← Tier 1: 怎么工作（流程、规范、工具）
  ↓
docs/progress.md             ← Tier 2: 做到哪了（总览：当前Phase、各Phase状态）
  ↓
docs/phases/phase-N.md       ← Tier 3: 当前Phase详细任务（输入/输出/验收/测试命令）
```

---

# 2. Project Summary

**个人多智能体平台** — 运行在私有服务器上的多智能体调度平台。

**架构**：渠道层（Web UI / Telegram / GitHub Webhook）→ 调度层 → 智能体层 → 工具层 → 数据层（五层分离，详见 `docs/requirement.md` §3）

**技术栈**：Python 3.11+、FastAPI、asyncio、LiteLLM、ChromaDB、Redis、cui (Claude Code Web UI)、Docker Compose

**Phase 顺序**：平台基础设施 + cui 部署（Phase 1A）→ 开发机器人（Phase 1B: GitHub Issue 自动化）→ 知识库机器人（Phase 2）→ 客服机器人（Phase 3）→ 营销机器人（Phase 4）→ 增强功能（Phase 5）

完整需求见 `docs/requirement.md`，进度总览见 `docs/progress.md`，当前 Phase 详细任务见 `docs/phases/phase-N.md`。

---

# 3. Quick Reference Commands

| 场景 | 命令 |
|------|------|
| 安装依赖 | `uv sync` |
| 启动平台 | `uv run python main.py` |
| 运行所有测试 | `uv run pytest tests/ -v` |
| 运行单元测试 | `uv run pytest tests/unit/ -v` |
| 运行集成测试 | `uv run pytest tests/unit/ tests/integration/ -v` |
| Lint 检查 | `uv run ruff check .` |
| 格式化代码 | `uv run ruff format .` |
| Docker 启动 | `docker-compose up -d` |
| Docker 查看日志 | `docker-compose logs -f` |
| 检查配置 | `uv run python -c "import yaml; yaml.safe_load(open('config/platform.yaml')); print('OK')"` |
| CUI 前端重建部署 | `docker-compose build cui && docker-compose up -d cui` |

---

# 4. Phase Development Workflow

每个 Phase 必须按顺序经过以下步骤。**跳过任何一步都会导致文档与代码脱节。**

## Step 1 — Pre-Phase: Alignment Check（开始前验证起点）

```bash
python -m pytest tests/  # 记录当前测试数作为 baseline
```

然后**逐条交叉验证**：
- 对比 `docs/requirement.md` 该 Phase 的功能项 ↔ `docs/phases/phase-N.md` 的任务列表
- 有遗漏的功能项？**先补充任务到 phase 文件，再开始写代码**
- 对每个任务，搜索代码确认是否已被前序 Phase 提前实现
- 将已提前实现的任务标记 `Completed early in Phase N`
- 列出**实际需要做的任务**后再动手

## Step 2 — During Development: Cross-Phase Awareness（跨 Phase 感知）

当当前任务**顺带实现了未来 Phase 的功能**时：
- 立即在对应的 `docs/phases/phase-N.md` 找到未来任务，追加 `Completed early in Phase N`
- 在 `docs/progress.md` 的 Cross-Phase Early Completions 表中记录

## Step 3 — Post-Phase: Documentation Sync（文档同步）

所有代码写完、测试通过后，**逐项**核对：

1. `docs/requirement.md` 该 Phase 每个功能项 → 代码搜索验证已实现且有测试覆盖 → **只有逐项验证过的才标 `[x]`，不可整组打勾**
2. `docs/phases/phase-N.md` → 更新每个任务状态和验收标准勾选
3. `docs/progress.md` → 更新 Phase 进度、新增测试数、总测试数

## Step 4 — Post-Phase: Git Milestone

```bash
git tag -a v<X.Y.Z> -m "Phase N: <description>"
git push origin v<X.Y.Z>
```

## Step 5 — Post-Phase: Integration Validation（集成验证）

```bash
# 用 Telegram 发消息验证端到端流程
# 检查日志确认关键路径无错误
docker-compose logs --tail=50
```

---

# 5. Troubleshooting（问题排查方法论）

排查优先级：**复现问题 → 日志定位 → 单元测试隔离 → 渠道连接排查 → 回归验证**

## 场景一：可复现的问题

```
复现问题 → 日志定位 → 单元测试隔离 → 修复 → 回归验证
```

1. **复现**：确认问题存在、明确触发条件、建立稳定反馈循环
2. **日志定位**：结合复现时间点精确定位相关调用链
3. **单元测试隔离**：把复现条件缩小到最小范围
4. **修复 + 回归验证**：用同样的复现步骤确认问题已解决

## 场景二：无法复现的问题（偶发 / 环境相关）

```
收集现场信息 → 日志分析 → 构造近似场景 → 防御性修复
```

- 日志是唯一线索，优先分析
- 尽量根据日志信息**构造近似的复现场景**，而不是盲改代码

## 常用排查命令

```bash
# 日志
docker-compose logs -f agent-platform

# 隔离测试
python -m pytest tests/unit/<module>.py -v -k "<test_name>"

# 渠道连接
curl https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe
```

---

# 6. Code Rules（不可违反的规范）

| 规则 | 内容 |
|------|------|
| **文件行数** | 单文件不超过 500 行；拆分依据是**职责数量**而非行数 |
| **常量管理** | 禁止 magic numbers；所有可配置值集中在 `config/platform.yaml` 或 `constants.py` |
| **禁 God Class** | 单一类不得同时承担超过 3 个独立职责 |
| **禁 bare except** | 必须捕获具体异常类型 |
| **Silent Failure** | 被吞掉的异常必须记录 WARNING 级别日志 |
| **密钥安全** | API Key 存储在 `.env`，不写入配置文件，不提交到 git |
| **禁重复代码** | 共享逻辑抽取到独立模块，不允许 copy-paste |
| **工具原子化** | 每个工具独立可测试，不依赖其他工具 |
| **新增机器人** | 只添加配置文件 + 可选扩展代码，不改平台核心 |
| **渠道适配器** | 新渠道只实现 `BaseChannel` 接口，不修改调度层 |
| **异步 I/O** | 禁止在 async 函数中调用同步阻塞 I/O（如 `open()` 读大文件、`requests.get()`），使用 `aiofiles` 或 `httpx.AsyncClient` |
| **禁 import *** | 禁止 `from module import *`，防止命名空间污染 |
| **core 不导入 tools** | `core/` 不得 `import tools/` 中任何模块，通过 `tool_registry` 间接引用 |
| **测试覆盖率** | `core/` ≥ 80%、`tools/` ≥ 80%、`channels/` ≥ 70%、`agents/` ≥ 70% |
| **日志统一入口** | 所有模块通过 `from core.logging import get_logger; logger = get_logger(__name__)` 获取 logger，禁止 `print()`、禁止直接 `logging.getLogger()` |
| **日志必带 trace_id** | 渠道层入口生成 `trace_id`（ContextVar），全链路自动附加，无需手动传参 |
| **性能关键操作记日志** | LLM 调用、工具执行、渠道消息处理必须记录耗时（ms），使用 `core/logging.py` 提供的性能日志装饰器 |
| **日志级别准确** | DEBUG=调试详情，INFO=业务节点，WARNING=异常可恢复，ERROR=需关注错误，CRITICAL=平台故障；禁止滥用 ERROR 记录可恢复异常 |

**依赖方向**（单向无环）：
```
config / constants / errors
        ↑
      tools/  ←  core/  ←  agents/  ←  channels/  ←  main.py
```

---

# 7. Git Rules

## 分支策略
- `main`：始终保持稳定可运行
- `feat/<phase-or-feature>`：功能开发
- `fix/<description>`：Bug 修复

## Conventional Commits

```
feat: 添加 Telegram 渠道适配器
fix: 修复知识库查询超时问题
refactor: 将事件总线从内存队列迁移到 Redis
test: 添加客服机器人意图识别测试
docs: 更新 progress.md — Phase 1 完成
```

- Commit 小而原子化——一个 commit 只做一件逻辑上完整的事
- 禁止无意义 message（"update"、"fix"、"init"）
- 敏感文件（`.env`、`data/`）禁止提交

---

# 8. Agent Configuration Rules

当新增智能体时：

1. **只创建配置文件** `config/agents/<name>.yaml`，不修改 `core/` 任何文件
2. **配置格式**参考已有的 agent YAML 文件（见 `config/agents/` 目录）
3. **工具权限**：只声明该智能体真正需要的工具，遵循最小权限原则
4. **测试**：为新智能体创建 `tests/unit/test_agents/test_<name>.py`

### 新增智能体 Checklist（防遗漏横切面）

每次新增智能体时，逐项确认以下集成点已完成：

- [ ] **配置**：创建 `config/agents/<name>.yaml`，声明 `allowed_tools`
- [ ] **路由**：更新 `config/platform.yaml` 的 `dispatch.routes`，配置渠道→智能体映射
- [ ] **日志**：所有模块使用 `from core.logging import get_logger; logger = get_logger(__name__)`
- [ ] **Trace ID**：渠道入口调用 `set_trace_id()` 生成请求追踪 ID
- [ ] **审计**：工具调用经过 `core/audit.py` 审计记录
- [ ] **安全**：该 Phase 特定的安全需求已实现（参考 `docs/requirement.md` §3.5 演进路线）
- [ ] **错误处理**：必要时在 `core/errors.py` 新增异常类型
- [ ] **测试**：创建 `tests/unit/test_agents/test_<name>.py`，覆盖率 ≥ 70%
- [ ] **Fixtures**：`tests/conftest.py` 新增该智能体所需的 Mock fixtures

---

# 9. Core 模块演进规则

`core/` 是"极少改动"但**允许向后兼容扩展**的模块：

| 允许的操作 | 禁止的操作 |
|-----------|-----------|
| 新增方法、新增异常类型、新增配置项 | 修改已有方法签名（参数增减、返回值变更） |
| 新增可选参数（带默认值） | 删除已有公开接口 |
| 扩展数据结构（新增字段） | 重命名已有类或函数 |

**每次修改 `core/` 后**：
1. 运行 `uv run pytest tests/ -v` 全量测试
2. 确认已完成 Phase 的功能不受影响（回归验证）
3. 在 commit message 中注明修改了 `core/` 的哪个模块及原因

---
