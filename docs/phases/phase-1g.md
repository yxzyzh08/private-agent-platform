# Phase 1G: CUI AskUserQuestion 交互支持

## 目标

让 CUI 支持 Claude 的选项式提问（AskUserQuestion），用户可以在浏览器对话流中直接点选回答，实现与 Claude Code CLI 原生终端一致的交互体验。

## 前置条件

- Phase 1F 完成（CUI UI 优化已上线）

## 技术背景

### 问题

Claude Code 的 `AskUserQuestion` 工具在 CLI 终端中渲染交互式选项供用户选择。但 CUI 以 `-p`（print）模式 + `--output-format stream-json` 运行 Claude CLI，stdin 为 `inherit`，无交互式终端——AskUserQuestion 的内建 UI 不可用。

### 方案

**MCP 工具替代法**：复用 Permission 的 MCP 双向通信模式。

1. 扩展现有 `cui-permissions` MCP Server，新增 `ask_user` 工具
2. 通过 `--disallowedTools AskUserQuestion` 禁用内建工具
3. Claude 改用 MCP 版 `ask_user`，走 HTTP 轮询等待用户回答
4. 前端在消息流中内联渲染问题卡片，用户点选后提交

### 架构流程

```
Claude CLI (--disallowedTools AskUserQuestion)
    ↓ 调用 mcp__cui-permissions__ask_user
MCP Server (cui-permissions/ask_user)
    ↓ HTTP POST /api/questions/notify → 返回 questionId
CUI Backend (QuestionTracker)
    ↓ SSE 事件 question_request
CUI Frontend (AskUserQuestionCard 内联组件)
    ↓ 用户点选
    ↓ POST /api/questions/:id/answer
CUI Backend 更新状态为 'answered'
    ↓ MCP Server 轮询 GET /api/questions/:id → 检测到 answered
返回给 Claude CLI → 继续执行
```

## 任务清单

### 任务依赖关系

```
1G.2 → 1G.3 → 1G.1 → 1G.4（后端链路）
                  ↘ 1G.5（SSE 推送，依赖 1G.2）
1G.6 → 1G.9 → 1G.7 → 1G.8 → 1G.10（前端链路）
                               ↘ 1G.11（错误处理）
1G.10 + 1G.11 → 1G.12 → 1G.13（收尾）
```

### 需求 1: MCP Server 扩展

- [x] **1G.1** MCP Server 新增 `ask_user` 工具
  - **依赖**：1G.2, 1G.3
  - **输入**：`web/cui/src/mcp-server/index.ts`
  - **改动**：
    1. `ListToolsRequestSchema` handler 新增 `ask_user` 工具定义，inputSchema 包含 `questions` 数组（1-4 个问题，每个含 question/header/options/multiSelect）。注：1-4 限制来自 Claude Code CLI AskUserQuestion 原生规格
    2. `CallToolRequestSchema` handler 新增 `ask_user` 分支：
       - HTTP POST 到 `/api/questions/notify`，payload 含 questions + streamingId
       - 获取返回的 `questionId`
       - **轮询策略**：循环 `GET /api/questions/:id`，检测 `status` 字段：
         - `pending` → 继续等待
         - `answered` → 读取 `answers` 字段，组装为 MCP 工具返回值
       - 超时处理：1 小时超时，超时消息修正为 "timed out after 1 hour"（修复现有 approval_prompt 的消息 bug）
    3. **抽取共享轮询函数**：将 `approval_prompt` 和 `ask_user` 的 HTTP POST + 轮询逻辑抽取为 `pollForResult(url, checkFn, timeoutMs)` 辅助函数，避免代码重复
    4. 新增 `QuestionNotifyResponse`、`QuestionPollResponse` 类型定义
  - **验收标准**：
    - [x] MCP Server 启动后 `ask_user` 工具出现在工具列表中
    - [x] 调用 `ask_user` 时正确 POST 到 CUI Backend
    - [x] 轮询 `GET /api/questions/:id` 正确等待用户回答并返回结果
    - [x] 超时时返回合理的默认响应（消息为 "1 hour"）
    - [x] `approval_prompt` 和 `ask_user` 共享轮询辅助函数，无重复代码

### 需求 2: QuestionTracker 后端服务

- [x] **1G.2** 新建 QuestionTracker 服务
  - **新文件**：`web/cui/src/services/question-tracker.ts`
  - **实现**：
    1. `QuestionTracker extends EventEmitter`，复用 `PermissionTracker` 模式
    2. 核心方法：
       - `addQuestion(questions, streamingId)` → 创建 QuestionRequest（id, questions, streamingId, timestamp, status: 'pending'）
       - `getQuestion(id)` → 获取单个问题请求（含 status 和 answers）
       - `getQuestions(filter?)` → 按 streamingId/status 过滤
       - `answerQuestion(id, answers)` → 更新状态为 'answered'，存储用户选择
       - `removeQuestionsByStreamingId(streamingId)` → 会话结束清理
    3. 事件发射：`question_request`（新问题）、`question_answered`（已回答）
  - **验收标准**：
    - [x] addQuestion 正确创建并存储问题请求
    - [x] getQuestion 返回完整的单条记录（含 status 和 answers）
    - [x] answerQuestion 正确更新状态和存储答案
    - [x] removeQuestionsByStreamingId 清理指定会话的所有问题
    - [x] 事件正确发射

- [x] **1G.3** 新建 Question API 路由
  - **依赖**：1G.2
  - **新文件**：`web/cui/src/routes/question.routes.ts`
  - **端点**：
    1. `POST /api/questions/notify` — MCP Server 发送问题请求
       - Body: `{ questions: Question[], streamingId: string }`
       - Response: `{ success: true, id: string }`
    2. `GET /api/questions/:id` — 获取单个问题请求（**MCP Server 轮询用**）
       - Response: `{ question: QuestionRequest }` （含 status、answers）
       - 不存在返回 404
    3. `GET /api/questions` — 获取问题列表（前端恢复用）
       - Query: `?streamingId=xxx&status=pending|answered`
       - Response: `{ questions: QuestionRequest[] }`
    4. `POST /api/questions/:id/answer` — 用户提交选择
       - Body: `{ answers: Record<string, string | string[]> }`（**key 为 question 在数组中的 index（"0", "1", ...）**，value 为选中的 label 或 label 数组）
       - Response: `{ success: true }`
       - 不存在返回 404，非 pending 状态返回 400
  - **注册**：在 `cui-server.ts` 中引入 QuestionTracker 实例 + 注册路由（放在 auth middleware 之前，与 Permission 路由一致）
  - **验收标准**：
    - [x] POST /api/questions/notify 正确创建问题请求并返回 id
    - [x] GET /api/questions/:id 返回单条完整记录
    - [x] GET /api/questions 支持 streamingId 和 status 过滤
    - [x] POST /api/questions/:id/answer 正确更新答案
    - [x] 参数校验：缺少 questions/streamingId 返回 400
    - [x] 不存在的 id 返回 404

### 需求 3: Claude Process Manager 集成

- [x] **1G.4** ClaudeProcessManager 集成 AskUserQuestion 替代
  - **依赖**：1G.1
  - **输入**：`web/cui/src/services/claude-process-manager.ts`、`web/cui/src/cui-server.ts`
  - **改动**：
    1. `buildStartArgs()` 中：
       - `--disallowedTools` 新增 `AskUserQuestion`（追加到 mcpTools 逻辑旁）
       - `--allowedTools` 列表新增 `mcp__cui-permissions__ask_user`（加入 mcpTools 数组）
    2. `buildResumeArgs()` 中（**当前缺失，必须补充**）：
       - 在现有 MCP 配置块内，`--allowedTools` 追加 `mcp__cui-permissions__ask_user`
       - 新增 `--disallowedTools AskUserQuestion`（当前 resume 路径完全没有此参数）
    3. QuestionTracker 清理：在 `cui-server.ts` 的 `setupProcessManagerIntegration()` 方法中（与 Permission 清理同位置），监听 `process-closed` 事件，调用 `questionTracker.removeQuestionsByStreamingId(streamingId)`
  - **验收标准**：
    - [x] `buildStartArgs()` 输出包含 `--disallowedTools AskUserQuestion`
    - [x] `buildStartArgs()` 输出允许 `mcp__cui-permissions__ask_user`
    - [x] `buildResumeArgs()` 输出包含 `--disallowedTools AskUserQuestion`（**resume 场景**）
    - [x] `buildResumeArgs()` 输出允许 `mcp__cui-permissions__ask_user`（**resume 场景**）
    - [x] 进程结束后未回答的问题被清理（在 cui-server.ts 中）

### 需求 4: SSE 事件推送

- [x] **1G.5** QuestionTracker 事件接入 SSE 流
  - **依赖**：1G.2
  - **输入**：`web/cui/src/cui-server.ts`（实际接入位置，非 stream-manager.ts）
  - **改动**：
    1. 新建 `setupQuestionTrackerIntegration()` 方法（参照 `setupPermissionTrackerIntegration()` L614-641）
    2. 监听 QuestionTracker 的 `question_request` 事件，通过 `streamManager.broadcast()` 推送
    3. 事件格式：`{ type: 'question_request', data: QuestionRequest, streamingId, timestamp }`
    4. 在 `start()` 方法中调用 `setupQuestionTrackerIntegration()`
  - **验收标准**：
    - [x] 新问题创建时 SSE 正确推送 `question_request` 事件
    - [x] 事件包含完整的 questions 数据（question/header/options/multiSelect）
    - [x] 前端 EventSource 能接收到事件

### 需求 5: 前端内联问题卡片

- [x] **1G.6** 前端类型定义扩展
  - **输入**：`web/cui/src/types/index.ts`、`web/cui/src/web/chat/types/index.ts`
  - **改动**：
    1. 新增 `QuestionRequest` 接口（id, streamingId, questions, timestamp, status: 'pending' | 'answered', answers?）
    2. 新增 `Question` 接口（question, header, options, multiSelect）
    3. 新增 `QuestionOption` 接口（label, description, preview?）
    4. `StreamEvent` 联合类型新增 `question_request` 事件变体
  - **验收标准**：
    - [x] TypeScript 编译无错误
    - [x] 类型与后端 API 数据结构完全一致
    - [x] answers 的 key 类型为 string（question index: "0", "1", ...）

- [x] **1G.7** useConversationMessages hook 扩展
  - **依赖**：1G.6
  - **输入**：`web/cui/src/web/chat/hooks/useConversationMessages.ts`
  - **改动**：
    1. 新增状态：`currentQuestionRequest: QuestionRequest | null`
    2. `handleStreamMessage` 新增 `case 'question_request'` 处理
    3. 新增 `setCurrentQuestionRequest` setter
    4. 返回值新增 `currentQuestionRequest` 和 setter
  - **验收标准**：
    - [x] 收到 `question_request` 事件时正确更新状态
    - [x] 状态可被消费组件读取

- [x] **1G.8** AskUserQuestionCard 内联组件
  - **依赖**：1G.6, 1G.9
  - **新文件**：`web/cui/src/web/chat/components/AskUserQuestion/AskUserQuestionCard.tsx`
  - **实现**：
    1. 接收 `QuestionRequest` props，渲染在消息流中
    2. 支持 1-4 个问题纵向排列，每个问题独立区域
    3. 每个问题显示 header 标签 + question 文本 + 选项列表
    4. **单选模式**（multiSelect=false）：Radio button 组
    5. **多选模式**（multiSelect=true）：Checkbox 组
    6. **Other 选项**：固定追加在选项列表末尾，展开后显示 textarea 输入框
    7. **Preview 面板**：当任一选项有 preview 字段时，切换为左右布局（左侧选项列表，右侧 markdown 预览），使用现有 markdown 渲染能力
    8. **Submit 按钮**：所有问题都有选择后可点击，调用 `api.answerQuestion()`
    9. **已回答状态**：提交后卡片变为只读，显示已选项（✓ 标记），灰色背景
    10. 使用 Radix UI 组件（RadioGroup, Checkbox）+ Tailwind 样式，保持与现有 UI 风格一致
  - **验收标准**：
    - [x] 单选模式：点击选项正确选中，互斥
    - [x] 多选模式：可选中多个选项
    - [x] Other 选项：点击后展开文本输入框，输入内容作为自定义回答
    - [x] Preview：有 preview 的选项聚焦时右侧展示 markdown 渲染内容
    - [x] Submit：所有问题都有选择后按钮可用，提交后卡片变为只读
    - [x] 样式与 CUI 现有消息卡片风格一致
    - [x] 响应式：移动端纵向布局，桌面端支持左右布局（preview 时）

- [x] **1G.9** API Service 扩展
  - **依赖**：1G.6
  - **输入**：`web/cui/src/web/chat/services/api.ts`
  - **改动**：
    1. 新增 `answerQuestion(questionId: string, answers: Record<string, string | string[]>)` 方法
    2. 调用 `POST /api/questions/:id/answer`
    3. 新增 `getQuestionsByStreamingId(streamingId: string, status?: string)` 方法（用于页面恢复）
  - **验收标准**：
    - [x] API 调用正确发送到后端
    - [x] 错误处理与现有 API 方法一致

- [x] **1G.10** 消息列表集成
  - **依赖**：1G.7, 1G.8
  - **输入**：`web/cui/src/web/chat/components/MessageList/MessageItem.tsx`、`web/cui/src/web/chat/components/ConversationView/ConversationView.tsx`
  - **改动**：
    1. ConversationView 将 `currentQuestionRequest` 和 `handleQuestionAnswer` 传递给 MessageList
    2. MessageItem 或 MessageList 在消息流末尾（最新 assistant 消息之后）渲染 `AskUserQuestionCard`
    3. 提交回答后清除 `currentQuestionRequest` 状态
  - **验收标准**：
    - [x] 问题卡片出现在消息流中正确位置（最新 assistant 消息后）
    - [x] 回答后卡片保持可见（只读状态）
    - [x] 新消息到来时页面自动滚动正常

### 需求 6: 错误处理与边界情况

- [x] **1G.11** 错误处理与页面恢复
  - **依赖**：1G.10
  - **改动**：
    1. 页面刷新恢复：SSE 重连后通过 `GET /api/questions?streamingId=xxx&status=pending` 恢复未回答问题
    2. 提交失败：前端 toast 提示错误，保留用户选择状态，可重试
    3. 会话中断：进程退出时 QuestionTracker 自动清理（已在 1G.4 实现）
    4. 多个 pending 问题：MCP 工具调用是同步阻塞的（Claude 等待返回后才继续），正常情况不会出现多个 pending。如因异常出现，只显示最新的
  - **验收标准**：
    - [x] 页面刷新后未回答的问题卡片恢复显示
    - [x] 提交失败时用户选择不丢失
    - [x] 会话结束后未回答问题被正确清理

### 收尾

- [x] **1G.12** 单元测试
  - **依赖**：1G.10, 1G.11
  - **测试范围**：
    1. `QuestionTracker` 服务测试（CRUD、状态流转、清理、事件发射）
    2. `POST /api/questions/notify` 路由测试（成功、400、服务异常）
    3. `GET /api/questions/:id` 路由测试（成功、404）
    4. `POST /api/questions/:id/answer` 路由测试（成功、404、400）
    5. `GET /api/questions` 路由测试（过滤）
    6. MCP Server `ask_user` 工具测试（注册、HTTP 请求 mock、轮询逻辑、共享轮询函数）
    7. 前端 `AskUserQuestionCard` 组件测试（单选/多选/Other/Preview/Submit/只读状态）——需确认 CUI 项目是否已有 React 组件测试基础设施（@testing-library/react），如无则先配置
  - **验收标准**：
    - [x] 新增测试全部通过（37 新增测试：question-tracker 16 + question-routes 14 + mcp-ask-user 7）
    - [x] 现有测试无回归（33 files, 388 tests all passing）

- [x] **1G.13** 构建部署 + 文档同步
  - **依赖**：1G.12
  - **操作**：
    1. `cd web/cui && npm run build && npm start`（研发模式）
    2. 更新 `docs/phases/phase-1g.md` 标记所有任务 `[x]`
    3. 更新 `docs/progress.md`（Quick Status、测试数）
    4. 更新 `docs/requirement.md`（Phase 1G 验收用例标记 + 横切面表 3.5.4 补充 Phase 1G 测试 fixtures）
    5. Git commit + tag `v0.7.0`
  - **验收标准**：
    - [x] 浏览器 Ctrl+Shift+R 强制刷新确认改动生效
    - [ ] Claude 发出 AskUserQuestion 时，CUI 内联显示选项卡片（需 E2E 验证）
    - [ ] 用户点选后 Claude 继续执行（需 E2E 验证）

## 关键设计决策

| 决策 | 理由 |
|------|------|
| 扩展现有 `cui-permissions` MCP Server 而非新建 | 减少进程数和 MCP 配置复杂度，复用已有基础设施 |
| `--disallowedTools AskUserQuestion` 禁用内建工具 | 避免 CLI 在无终端环境下卡住，强制走 MCP 通道 |
| 内联消息流渲染（非浮层） | 用户需求：视觉自然，与对话上下文保持连贯 |
| 复用 Permission 的 HTTP 轮询模式 | 已验证可靠，1 小时超时足够，无需 WebSocket |
| MCP Server 轮询 `GET /api/questions/:id`（单条） | 比查列表更高效，避免 Permission 中两阶段查询的复杂性 |
| answers key 使用 question index（"0", "1"） | 比 question text 更健壮（无冲突风险、更简洁），前端按 index 构造 |
| 抽取共享 `pollForResult()` 辅助函数 | approval_prompt 和 ask_user 轮询模式几乎相同，遵守禁重复代码规则 |
| Other 选项固定追加 | 与 Claude Code CLI 行为一致——AskUserQuestion 总是自动提供 Other |
| Preview 使用左右分栏布局 | 与 Claude Code CLI 原生体验一致，代码片段/mockup 对比更直观 |
| QuestionTracker 清理在 cui-server.ts | 与 Permission 清理同位置（setupProcessManagerIntegration），统一管理 |

## 改动文件清单

### 新增文件（3 个）

| 文件 | 任务 | 说明 |
|------|------|------|
| `web/cui/src/services/question-tracker.ts` | 1G.2 | 问题跟踪服务 |
| `web/cui/src/routes/question.routes.ts` | 1G.3 | 问题 API 路由 |
| `web/cui/src/web/chat/components/AskUserQuestion/AskUserQuestionCard.tsx` | 1G.8 | 内联问题卡片组件 |

### 修改文件（7 个）

| 文件 | 任务 | 改动 |
|------|------|------|
| `web/cui/src/mcp-server/index.ts` | 1G.1 | 新增 `ask_user` 工具定义 + handler + 抽取共享轮询函数 |
| `web/cui/src/services/claude-process-manager.ts` | 1G.4 | `buildStartArgs()` + `buildResumeArgs()` 参数调整 |
| `web/cui/src/cui-server.ts` | 1G.3, 1G.4, 1G.5 | 注册 question routes + QuestionTracker 实例 + SSE 事件 + 进程清理 |
| `web/cui/src/types/index.ts` | 1G.6 | 新增 QuestionRequest 类型 + StreamEvent 扩展 |
| `web/cui/src/web/chat/hooks/useConversationMessages.ts` | 1G.7 | 处理 `question_request` 事件 |
| `web/cui/src/web/chat/services/api.ts` | 1G.9 | 新增 answerQuestion + getQuestionsByStreamingId API 方法 |
| `web/cui/src/web/chat/components/ConversationView/ConversationView.tsx` | 1G.10 | 传递 questionRequest + 集成渲染 |
