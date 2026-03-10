# Phase 1E: CUI Agents Tab — 子代理会话分离 + 批量删除

## 目标

将 Agent Teams 模式创建的子代理会话从 Tasks tab 分离到新的 Agents tab，并提供批量删除功能。

## 任务清单

- [x] **1E.1** Types + SQLite Schema 迁移（session_type 列）
- [x] **1E.2** ClaudeHistoryReader 子代理检测
- [x] **1E.3** API Filter + 批量删除端点
- [x] **1E.4** 前端 API 客户端更新
- [x] **1E.5** TaskTabs 新增 Agents Tab
- [x] **1E.6** 过滤逻辑 — Tasks 排除子代理 + Agents 过滤
- [x] **1E.7** 批量选择 + 删除 UI（Agents Tab）
- [x] **1E.8** TypeScript 单元测试
- [x] **1E.9** Post-Phase 文档同步 + Git Tag

## 关键设计决策

| 决策 | 理由 |
|------|------|
| Detect-and-persist 模式 | 检测在 JSONL 解析时执行（已缓存），结果持久化到 SQLite，避免每次 API 调用重新解析 |
| Schema ALTER TABLE + DEFAULT | 简单迁移，无需数据迁移，existing sessions 自动为 `'user'` |
| 后端过滤（非前端） | sessionType 在 `applyFilters()` 中处理，API 契约清晰，前端不需要过滤全量数据 |
| 批量选择仅 Agents tab | 其他 tab 保持现有交互，避免 UI 变化过大 |
| JSONL 删除逻辑提取为 helper | 复用现有单条删除逻辑，batch 端点循环调用 |
