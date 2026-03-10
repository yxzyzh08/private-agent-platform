# CUI Workflow — MCP Tool Integration (Phase 1D)

当 Owner 在 cui 中与你对话时，你可以使用以下 MCP Tools 来管理项目开发：

## 可用的 MCP Tools

| Tool | 用途 | 何时使用 |
|------|------|---------|
| `init_project` | 初始化新项目（git repo + phase 骨架） | Owner 确认项目名称和描述后 |
| `submit_phase` | 提交 phase-N.md 开始执行 | Owner 确认任务分解后 |
| `get_plan_status` | 查询执行进度 | Owner 询问进度时 |
| `control_task` | 重试或跳过失败任务 | 任务失败需要处理时 |
| `abort_plan` | 终止整个执行计划 | Owner 要求停止时 |

## 标准工作流程

### 1. 需求澄清（对话）

与 Owner 多轮对话，确认：
- 项目名称和描述
- 技术栈选择
- 核心功能列表
- 部署方式

### 2. 生成任务分解

参考 `config/templates/phase-generation-prompt.md` 中的格式规范，生成 phase-1.md 内容。

### 3. 创建项目

```
使用 init_project MCP Tool:
  name: "project-name"
  description: "项目描述"
```

### 4. 写入 phase 文件

将生成的 phase-1.md 内容写入项目的 `docs/phases/phase-1.md`。

### 5. 提交执行

```
使用 submit_phase MCP Tool:
  phase_file: "/path/to/project/docs/phases/phase-1.md"
  repo_path: "/path/to/project"
```

### 6. 进度监控

执行会通过 SSE 在 RequirementPanel 中实时展示进度。Owner 可以：
- 查看每个任务的状态
- 对失败任务点击"重试"或"跳过"
- 点击"终止"停止整个计划

### 7. 完成

全部任务完成后：
- 自动创建 PR
- ntfy 通知 Owner
