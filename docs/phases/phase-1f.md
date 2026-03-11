# Phase 1F: CUI UI 优化 — 移除 History Tab + 批量操作增强

## 目标

优化 CUI 首页 Tab 结构：移除冗余的 History 页签（continuation 会话回归 Tasks），为 Archive 增加批量删除，为 Tasks 增加批量归档。

## 前置条件

- Phase 1E 完成（Agents Tab + 批量删除已上线）

## 任务清单

### 需求 1: 移除 History 页签

- [x] **1F.1** 移除 History Tab UI + 过滤逻辑调整
  - **输入**：TaskTabs.tsx、Home.tsx、TaskList.tsx
  - **改动**：
    1. TaskTabs.tsx：删除 History TabsTrigger，类型从 `'tasks' | 'agents' | 'history' | 'archive'` 缩减为 `'tasks' | 'agents' | 'archive'`
    2. Home.tsx：类型同步更新，`getFiltersForTab` 删除 history case
    3. TaskList.tsx：类型同步更新，`getFiltersForTab` 删除 history case，`getEmptyMessage` 删除 history case
    4. **关键**：Tasks tab 过滤条件从 `{ archived: false, hasContinuation: false, sessionType: 'user' }` 改为 `{ archived: false, sessionType: 'user' }`（去掉 `hasContinuation: false`，让 continuation 会话回归 Tasks 显示）
    5. Home.tsx 中 Tasks 的过滤条件同步更新
  - **后端影响**：`hasContinuation` 过滤参数在后端保留（通用 API 能力），但前端不再使用
  - **验收标准**：
    - [ ] Tab 栏只显示 Tasks / Agents / Archive 三个页签
    - [ ] 原 History 中的 continuation 会话在 Tasks tab 中正常显示
    - [ ] 切换 Tab 数据正确加载
    - [ ] TypeScript 编译无错误

### 需求 2: Archive 批量删除

- [x] **1F.2** Archive Tab 增加批量删除功能
  - **输入**：TaskList.tsx
  - **改动**：
    1. `isSelectable` 条件从 `activeTab === 'agents'` 扩展为 `activeTab === 'agents' || activeTab === 'archive'`
    2. 批量删除确认文案根据 tab 动态调整（agents: "agent session(s)", archive: "archived task(s)"）
  - **验收标准**：
    - [ ] Archive tab 显示 Select all checkbox 和批量操作工具栏
    - [ ] 选中多个归档任务后可一键批量删除
    - [ ] 删除后列表自动刷新
    - [ ] Agents tab 批量删除功能不受影响

### 需求 3: Tasks 批量归档

- [x] **1F.3** 后端批量归档 API
  - **输入**：session-info-service.ts、conversation.routes.ts
  - **改动**：
    1. session-info-service.ts：新增 `batchArchiveSessions(sessionIds: string[])` 方法，使用 SQLite 事务批量更新 `archived = 1`
    2. conversation.routes.ts：新增 `POST /api/conversations/batch-archive` 端点（位于 `/:sessionId` 路由之前），接受 `{ sessionIds: string[] }`，返回 `{ success: boolean, archivedCount: number }`
  - **验收标准**：
    - [ ] `POST /api/conversations/batch-archive` 正确批量归档指定会话
    - [ ] 空数组或缺少参数返回 400 错误
    - [ ] 事务保证原子性

- [x] **1F.4** 前端批量归档 UI
  - **输入**：api.ts、TaskList.tsx
  - **改动**：
    1. api.ts：新增 `batchArchiveSessions(sessionIds: string[])` 方法，调用 `POST /api/conversations/batch-archive`
    2. TaskList.tsx：
       - `isSelectable` 扩展为包含 `'tasks'` tab
       - 新增 `isBatchArchiving` 状态
       - 新增 `handleBatchArchive` 方法（confirm → 调用 API → 清空选择 → 刷新列表）
       - 批量工具栏根据 tab 显示不同按钮：Tasks 显示 Archive 按钮（Archive icon），Agents/Archive 显示 Delete 按钮（Trash2 icon）
  - **验收标准**：
    - [ ] Tasks tab 显示 Select all checkbox 和批量操作工具栏
    - [ ] 选中多个任务后可一键批量归档
    - [ ] 归档后任务从 Tasks 列表消失，出现在 Archive tab
    - [ ] Archive/Agents tab 的批量删除功能不受影响

### 收尾

- [x] **1F.5** TypeScript 单元测试
  - **测试范围**：
    1. `batchArchiveSessions` 后端 service 方法测试
    2. `POST /api/conversations/batch-archive` 路由测试（成功、400 错误、服务异常）
    3. 前端组件测试：各 tab 的 isSelectable 行为验证
  - **验收标准**：
    - [ ] 新增测试全部通过
    - [ ] 现有测试无回归

- [x] **1F.6** Docker 重建部署 + 文档同步
  - **操作**：
    1. `docker-compose build cui && docker-compose up -d cui`
    2. 更新 `docs/phases/phase-1f.md` 标记所有任务 `[x]`
    3. 更新 `docs/progress.md`（Quick Status、测试数）
    4. 更新 `docs/requirement.md`（新增 Phase 1F 验收用例）
    5. Git commit + tag
  - **验收标准**：
    - [ ] 浏览器 Ctrl+Shift+R 强制刷新确认改动生效
    - [ ] 三个需求全部可用

## 关键设计决策

| 决策 | 理由 |
|------|------|
| 后端保留 `hasContinuation` 过滤参数 | 通用 API 能力，不影响其他消费方，无需删除 |
| Tasks 过滤条件去掉 `hasContinuation: false` | 让 continuation 会话回归 Tasks 显示，避免数据消失 |
| 复用 Agents tab 的批量选择 UI 模式 | 一致的用户体验，减少新代码量 |
| 批量工具栏按钮根据 tab 动态切换 | Tasks 显示 Archive，Agents/Archive 显示 Delete，语义清晰 |
| 后端新增独立 batch-archive 端点 | 与 batch delete 模式一致，不复用 update 端点，保证语义清晰和原子性 |

## 改动文件清单

| 文件 | 任务 | 改动类型 |
|------|------|---------|
| `web/cui/src/web/chat/components/Home/TaskTabs.tsx` | 1F.1 | 删除 History tab |
| `web/cui/src/web/chat/components/Home/Home.tsx` | 1F.1 | 删除 history 过滤 |
| `web/cui/src/web/chat/components/Home/TaskList.tsx` | 1F.1, 1F.2, 1F.4 | 过滤 + 批量操作 |
| `web/cui/src/web/chat/services/api.ts` | 1F.4 | 新增 batchArchive API |
| `web/cui/src/services/session-info-service.ts` | 1F.3 | 新增 batchArchive 方法 |
| `web/cui/src/routes/conversation.routes.ts` | 1F.3 | 新增 batch-archive 路由 |
| `web/cui/tests/unit/services/session-info-service.test.ts` | 1F.5 | 新增测试 |
| `web/cui/tests/unit/routes/conversation.routes.test.ts` | 1F.5 | 新增测试 |
