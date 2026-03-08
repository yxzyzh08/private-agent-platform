# Phase 2: 知识库机器人

**分支**: `feat/phase-2-kbbot`
**Tag**: `v0.2.0`
**前置**: Phase 1 完成
**目标**: 自动从代码仓库生成/更新产品知识库，Owner 可手动指令管理知识库内容

**完成条件**: 知识库机器人能自动从代码仓库生成产品文档并写入 ChromaDB；Owner 能通过 Telegram 命令手动添加/更新知识库内容

---

> **待 Phase 1 完成后细化。** 以下为任务概览，详细的验收标准、接口规范和测试命令将在 Phase 1 Post-Phase 时补充。

## 任务概览

| # | 任务 | 状态 | 产出文件 |
|---|------|------|---------|
| 2.1 | 实现 `tools/knowledge_base.py`（ChromaDB RAG 查询 + 文档管理） | [ ] | `tools/knowledge_base.py` |
| 2.2 | 实现 `tools/file_tool.py`（沙箱文件读写） | [ ] | `tools/file_tool.py` |
| 2.3 | 创建 `agents/proactive_agent.py`（主动型机器人基类） | [ ] | `agents/proactive_agent.py` |
| 2.4 | 创建 `agents/kb_agent.py`（知识库机器人） | [ ] | `agents/kb_agent.py` |
| 2.5 | 创建 `config/agents/knowledge_base.yaml` | [ ] | `config/agents/knowledge_base.yaml` |
| 2.6 | 实现自动化流程：从代码仓库提取文档 → 生成/更新知识库 | [ ] | 知识库机器人核心逻辑 |
| 2.7 | 实现 Owner 手动指令：通过 Telegram 命令管理知识库 | [ ] | Telegram 命令处理 |
| 2.8 | 上传初始知识库文档（FAQ + 产品说明） | [ ] | `data/knowledge/faq.md` |
| 2.9 | 知识库机器人集成测试 | [ ] | `tests/unit/test_agents/test_kb_bot.py` |
| 2.9a | Phase 2 基础设施适配（见下方详细描述） | [ ] | `core/errors.py`, `tests/conftest.py` |
| 2.10 | 端到端验证 + 文档同步 + tag `v0.2.0` | [ ] | 本文件、Git tag |

---

### Task 2.9a: Phase 2 基础设施适配

**状态**: [ ] 未开始
**参考**: `docs/requirement.md` §3.5 横切面需求演进路线

**验收标准**:
- [ ] **安全**：`tools/file_tool.py` 实现路径沙箱（限制知识库文件访问范围，禁止软链接穿透）
- [ ] **存储**：ChromaDB 初始化逻辑实现，向量库路径从 `config/platform.yaml` 的 `storage.vector_db_path` 读取
- [ ] **错误**：`core/errors.py` 新增 `KnowledgeBaseError`（索引失败、查询超时）
- [ ] **日志**：`agents/kb_agent.py` 和 `tools/knowledge_base.py` 使用 `get_logger(__name__)`，知识库查询记录耗时
- [ ] **配置**：`config/agents/knowledge_base.yaml` 创建，声明 `allowed_tools`
- [ ] **测试**：`tests/conftest.py` 新增 `mock_chromadb`、`mock_git_repo` fixtures
