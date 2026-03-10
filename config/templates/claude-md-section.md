# 10. Task Plan — 需求开发模式 (Phase 1C)

当 Owner 在 cui 中与你完成需求澄清和任务分解后：

1. 将任务写入 `docs/phases/phase-N.md`，格式参考 `config/templates/phase-template.md`
2. 每个任务必须包含：`### Task {N.X}: {标题}`、`**状态**`、`**依赖**`、`**产出文件**`、`**描述**`、`**验收标准**`、`**测试命令**`
3. Owner 确认后，调用平台 API 提交执行：

```bash
curl -X POST http://localhost:8000/api/requirements/from-phase \
  -H "Content-Type: application/json" \
  -d '{"phase_file": "docs/phases/phase-N.md", "repo_path": "/path/to/repo"}'
```

4. 平台会自动：
   - 解析 markdown 为任务计划
   - 按依赖顺序逐个执行任务（每个任务使用全新 CLI 上下文）
   - 每完成一个任务回写 markdown `[x]` + 自动 commit
   - 全部完成后通过 ntfy 通知 Owner

5. 查询进度：`GET /api/requirements/{plan_id}`
6. 控制执行：
   - 重试：`POST /api/requirements/{plan_id}/tasks/{task_id}/retry`
   - 跳过：`POST /api/requirements/{plan_id}/tasks/{task_id}/skip`
   - 终止：`POST /api/requirements/{plan_id}/abort`
