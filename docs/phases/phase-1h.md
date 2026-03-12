# Phase 1H: CUI 项目文档查看器

## 目标

在 CUI 中新增项目文档查看功能（只读），支持 Markdown 渲染和 Mermaid 流程图语法。用户通过 Docs Tab 浏览当前项目的 `docs/` 目录，左侧目录树 + 右侧内容双栏布局，类 GitBook 阅读体验。

## 前置条件

- Phase 1G 完成（AskUserQuestion 交互支持已上线）

## 技术背景

### 现有能力

CUI 已具备：
- `react-markdown` v10 — Markdown 渲染（`MessageItem.tsx` 中已有 `markdownComponents` 配置）
- `prism-react-renderer` + `CodeHighlight` 组件 — 代码语法高亮（接口：`{code, language, showLineNumbers?, className?}`）
- `@tailwindcss/typography` — prose 排版样式
- `@testing-library/react` + `happy-dom` — React 组件测试基础设施（已安装）
- `useTheme` hook — 主题检测（CodeHighlight 已使用）
- `lucide-react` — 图标库（Folder, FolderOpen, FileText 等）
- `filesystem.routes.ts` — 通用文件系统 API（但安全边界不够专用）
- `ConversationsContext.selectedProjectPath` — 当前选中项目路径

### 方案选择

**专用 Docs API** 而非复用 filesystem API：
- 安全边界清晰：后端强制限制在 `docs/` 目录内
- API 语义专用化：返回文件元数据（大小、修改时间）
- 未来可扩展为需求文档展示平台

### 架构流程

```
用户点击 Docs Tab → 导航到 /docs 路由
    ↓
DocsView 组件加载 → GET /api/docs/tree?projectPath=<path>
    ↓
后端扫描 <projectPath>/docs/ → 返回目录树 JSON
    ↓
前端渲染左侧文件树（DocsSidebar）
    ↓
用户点击 .md 文件 → GET /api/docs/content?projectPath=<path>&filePath=<relative>
    ↓
后端安全校验 + 读取文件 → 返回原始 markdown
    ↓
前端 react-markdown + mermaid.js 渲染（DocsContent）
```

## 任务清单

### 任务依赖关系

```
1H.1（后端 API）→ 1H.3（前端 API service）
1H.2（npm 依赖）→ 1H.6（MermaidBlock）
1H.3 → 1H.4（DocsSidebar）
1H.3 → 1H.5（DocsContent）
1H.2 → 1H.5
1H.4 + 1H.5 + 1H.6 → 1H.7（DocsView 主容器）
1H.7 → 1H.8（路由 + Tab 集成）
1H.8 → 1H.9（空状态 + URL 恢复）
1H.9 → 1H.10（测试）
1H.10 → 1H.11（构建部署 + 文档同步）
```

### 需求 1: 后端 Docs API

- [x] **1H.1** 新建 Docs API 路由
  - **新文件**：`web/cui/src/routes/docs.routes.ts`
  - **实现**：
    1. `GET /api/docs/tree` — 获取文档目录树
       - Query: `projectPath`（必填，项目根目录绝对路径）
       - 参数校验：`projectPath` 必须是绝对路径（以 `/` 开头），不含 null bytes
       - 递归扫描 `<projectPath>/docs/`，最大递归深度 10 层，总文件数上限 1000
       - 只返回 `.md` 文件和包含 `.md` 文件的目录
       - 过滤隐藏文件/目录（`.` 开头），跳过符号链接目录
       - 目录在前、文件在后，各自按名称升序排列
       - 返回结构：`{ name, path, type, size?, modifiedAt?, children? }`（单根节点，根节点即 `docs/` 目录）
       - 超过 1000 文件时返回中增加 `truncated: true` 标记
       - 错误：404（`docs/` 不存在）、400（参数缺失或格式非法）
    2. `GET /api/docs/content` — 读取指定文档文件
       - Query: `projectPath`（必填）、`filePath`（必填，相对于项目根）
       - 安全校验（按以下顺序，全部通过才返回内容）：
         1. `decodeURIComponent(filePath)` 确保完全解码（防双重编码绕过）
         2. 检查解码后的 `filePath` 不含 `..`
         3. `filePath` 必须以 `docs/` 开头
         4. `filePath` 必须以 `.md` 结尾
         5. `path.resolve()` + `fs.realpath()` 结果必须在 `<projectPath>/docs/` 内（最终防线）
         6. `stat.size` 不超过 1MB
       - 返回：`{ content, size, modifiedAt }`（使用 `res.json()` 返回 JSON，不直接返回 raw text）
       - 错误消息不返回服务端绝对路径，只返回用户提交的 `filePath`
       - 错误：403（路径校验失败）、404（文件不存在）、413（超过 1MB）、400（参数缺失）
       - 403 路径穿越尝试记录 WARNING 日志（含请求 filePath，不含 realpath）
    3. `createDocsRoutes()` 工厂函数（参照 `createFileSystemRoutes()` 模式）
  - **注册**：在 `cui-server.ts` 中引入并注册路由，**必须在 auth middleware 之后**（与 `/api/filesystem` 同级，约 L495 位置）
  - **验收标准**：
    - [x] `GET /api/docs/tree` 返回正确的目录树结构（单根节点）
    - [x] 只返回 `.md` 文件，非 `.md` 文件被过滤
    - [x] 空目录（无 `.md` 文件）不出现在返回结果中
    - [x] `GET /api/docs/content` 返回文件内容和元数据
    - [x] 路径穿越攻击（`../`）被 403 拒绝
    - [x] URL 编码绕过（`%2e%2e%2f`）被 403 拒绝
    - [x] 符号链接指向 `docs/` 外部时被 403 拒绝
    - [x] 超过 1MB 的文件返回 413
    - [x] `docs/` 目录不存在返回 404
    - [x] 递归深度超过 10 层时停止扫描
    - [x] 路由在 auth middleware 之后注册（需认证才能访问）
    - [x] 错误响应不泄露服务端绝对路径
  - **测试命令**：`cd web/cui && npx vitest run tests/unit/routes/docs.routes.test.ts`

### 需求 2: 前端依赖安装

- [x] **1H.2** 安装 Mermaid 和 DOMPurify 依赖
  - **输入**：`web/cui/package.json`
  - **操作**：
    1. `cd web/cui && npm install mermaid@^11 dompurify@^3`
    2. `npm install -D @types/dompurify@^3`
  - **验收标准**：
    - [x] `npm ls mermaid` 显示已安装
    - [x] `npm ls dompurify` 显示已安装
    - [x] TypeScript 编译无错误
    - [x] `npm run build` 构建成功
  - **测试命令**：`cd web/cui && npm run build`

### 需求 3: 前端 API Service

- [x] **1H.3** API Service 新增文档相关方法
  - **依赖**：1H.1
  - **输入**：`web/cui/src/web/chat/services/api.ts`
  - **改动**：
    1. 新增 `getDocsTree(projectPath: string)` 方法
       - 调用 `GET /api/docs/tree?projectPath=xxx`
       - 返回 `DocsTreeNode`
    2. 新增 `getDocsContent(projectPath: string, filePath: string)` 方法
       - 调用 `GET /api/docs/content?projectPath=xxx&filePath=xxx`
       - 返回 `{ content: string, size: number, modifiedAt: string }`
  - **类型定义**（新增到 `src/web/chat/types/index.ts`）：
    ```typescript
    interface DocsTreeNode {
      name: string;
      path: string;
      type: 'file' | 'directory';
      size?: number;
      modifiedAt?: string;
      children?: DocsTreeNode[];
    }
    ```
  - **验收标准**：
    - [x] TypeScript 编译无错误
    - [x] API 方法正确拼接 URL 和参数

### 需求 4: DocsSidebar 文件树组件

- [x] **1H.4** DocsSidebar + TreeNode 递归组件
  - **依赖**：1H.3
  - **新文件**：`web/cui/src/web/chat/components/DocsView/DocsSidebar.tsx`
  - **实现**：
    1. `DocsSidebar` 接收 `treeData: DocsTreeNode`（单根节点，即 API 返回的根 `docs/` 目录）、`selectedFile: string | null`、`onSelectFile: (path: string) => void`
    2. `TreeNode` 递归组件：
       - 目录节点：点击展开/折叠，显示 ▶/▼ 箭头 + `FolderOpen`/`Folder` 图标（lucide-react）
       - 文件节点：点击触发 `onSelectFile`，选中态高亮背景，显示 `FileText` 图标
       - 缩进层级通过 `depth` prop 控制 `padding-left`（每层 16px）
    3. 根目录 `docs/` 默认展开
    4. 展开/折叠状态在组件生命周期内保持（切换文件后目录不会重新折叠），无需跨页面持久化
    5. 样式：Tailwind CSS，复用现有 CSS 变量，暗色模式适配
  - **验收标准**：
    - [x] 目录可展开/折叠
    - [x] 文件点击触发选择回调
    - [x] 选中文件高亮显示
    - [x] 切换文件后目录展开状态保持
    - [x] 多层嵌套目录正确缩进
    - [x] 暗色模式样式正确

### 需求 5: DocsContent Markdown 渲染组件

- [x] **1H.5** DocsContent 组件
  - **依赖**：1H.2, 1H.3
  - **新文件**：`web/cui/src/web/chat/components/DocsView/DocsContent.tsx`
  - **实现**：
    1. 接收 `content: string | null` 和 `loading: boolean` 和 `filePath: string | null`
    2. 抽取共享 markdown 组件配置：
       - 新建 `web/cui/src/web/chat/components/shared/markdownComponents.ts`
       - 将 `MessageItem.tsx` 中的 `markdownComponents`（code→CodeHighlight 映射）抽取到此公共模块
       - `MessageItem.tsx` 改为引用公共模块
       - DocsContent 在公共模块基础上扩展 mermaid 分支：`language === 'mermaid'` 时交给 `MermaidBlock` 渲染
       - 文档场景下 CodeHighlight 不截断（传入 prop 或调大默认显示行数）
    3. 使用 `react-markdown` 渲染，**不启用 `rehype-raw` 插件**（防止 markdown 内嵌 `<script>` 执行）
    4. Prose 样式：`prose prose-sm dark:prose-invert`，`max-width: 800px`
    5. 顶部显示文件路径和元数据（文件大小、修改时间）
    6. 加载中状态：spinner
  - **验收标准**：
    - [x] Markdown 正确渲染（标题、列表、表格、链接、图片引用）
    - [x] 代码块语法高亮正常
    - [x] Mermaid 代码块渲染为图表（见 1H.6）
    - [x] prose 排版样式美观
    - [x] 加载状态正确显示

### 需求 6: MermaidBlock 图表渲染组件

- [x] **1H.6** MermaidBlock 组件
  - **依赖**：1H.2
  - **新文件**：`web/cui/src/web/chat/components/DocsView/MermaidBlock.tsx`
  - **实现**：
    1. 接收 `code: string` prop（Mermaid 语法文本）
    2. `mermaid` 包通过动态 `import()` 按需加载，避免影响首屏
    3. 调用 `mermaid.render()` 生成 SVG
    4. SVG 输出通过 `DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true } })` 消毒后注入 DOM
    5. 初始化时设置 `securityLevel: 'strict'`（显式写出，防未来版本默认值变化），根据 `useTheme` hook 设置 `theme: 'dark'` 或 `'default'`
    6. 错误处理：
       - Mermaid 模块加载失败 → 显示原始代码块 + "Mermaid rendering unavailable" 提示
       - Mermaid 语法错误 → 显示原始代码块 + 错误消息
  - **验收标准**：
    - [x] flowchart 语法正确渲染为流程图
    - [x] sequence diagram 语法正确渲染为时序图
    - [x] 暗色模式下图表主题切换为 dark
    - [x] 无效 Mermaid 语法 fallback 为代码块显示
    - [x] DOMPurify 消毒后 SVG 正常显示（无 XSS）
  - **测试命令**：`cd web/cui && npx vitest run tests/unit/components/MermaidBlock.test.ts`

### 需求 7: DocsView 主容器

- [x] **1H.7** DocsView 主容器组件
  - **依赖**：1H.4, 1H.5, 1H.6
  - **新文件**：
    - `web/cui/src/web/chat/components/DocsView/DocsView.tsx`
    - `web/cui/src/web/chat/components/DocsView/DocsHeader.tsx`
    - `web/cui/src/web/chat/components/DocsView/index.ts`
  - **实现**：
    1. `DocsView` 主容器：
       - 状态：`treeData`、`selectedFile`、`fileContent`、`loading`
       - 从 `ConversationsContext` 的 `selectedProjectPath` 获取当前项目路径（注意：初始值可能为 null，由 1H.9 空状态处理）
       - 组件挂载时调用 `api.getDocsTree()` 加载目录树
       - `selectedFile` 变化时调用 `api.getDocsContent()` 加载内容
       - 布局：flex 容器，左侧 DocsSidebar（固定 220px 宽），右侧 DocsContent（flex-1）
    2. `DocsHeader`（可内嵌在 DocsView 中，也可独立文件，视代码量决定）：
       - 左侧：返回按钮（← Home，`navigate('/')`）+ 面包屑（Docs / 子目录 / 文件名）
       - 右侧：项目名称
    3. `index.ts`：导出 DocsView
  - **验收标准**：
    - [x] 组件挂载后自动加载目录树
    - [x] 点击文件后右侧正确渲染 markdown 内容
    - [x] 面包屑导航正确显示当前路径
    - [x] 返回按钮正确导航回首页
    - [x] 布局：左侧目录树固定宽度，右侧内容区自适应

### 需求 8: 路由 + Tab 集成

- [x] **1H.8** 路由注册 + Docs Tab 导航链接
  - **依赖**：1H.7
  - **输入**：`ChatApp.tsx`、`TaskTabs.tsx`
  - **改动**：
    1. `ChatApp.tsx`：
       - 新增 `<Route path="/docs" element={<Layout><DocsView /></Layout>} />`
       - **包裹 `<Layout>`**（保持全局导航一致性），DocsHeader 作为页面内 header
       - 使用 `React.lazy` + `<Suspense fallback={...}>` 延迟加载 DocsView
    2. `TaskTabs.tsx`：
       - 在 `<TabsList>` 末尾放置独立的 `<Link to="/docs">` 导航链接
       - **不作为 Tab trigger**，而是样式一致的独立链接，避免与 Tabs value/onValueChange 语义冲突
       - 使用与 Tab trigger 相同的 CSS 类，保持视觉统一
       - 当 URL 路径为 `/docs` 时不需要特殊处理（用户已离开 Home 页）
  - **验收标准**：
    - [x] CUI 首页 Tab 栏显示 Tasks / Agents / Archive + Docs 链接
    - [x] 点击 Docs 导航到 `/docs` 路由，DocsView 正确加载
    - [x] 从 Docs 页返回首页后 Tasks tab 正常显示
    - [x] 其他 Tab 功能不受影响
    - [x] TypeScript 编译无错误
  - **测试命令**：`cd web/cui && npm run build`

### 需求 9: 空状态 + URL 恢复

- [x] **1H.9** 空状态处理和 URL 文件直达
  - **依赖**：1H.8
  - **输入**：`DocsView.tsx`、`DocsContent.tsx`
  - **改动**：
    1. 空状态处理：
       - 未选中项目（`selectedProjectPath` 为 null）：居中提示 "请先选择一个项目"
       - 项目无 `docs/` 目录（API 返回 404）：居中提示 "当前项目没有 docs/ 目录"
       - 未选中文件：右侧显示欢迎内容——文档统计（文件数）+ 最近修改的前 5 个文件列表（可点击快速打开）
         - 提取逻辑：前端从树结构中递归扁平化所有文件节点，按 `modifiedAt` 降序排序，取前 5 个
       - 文件加载中：spinner
       - URL 指向不存在的文件（`?file=docs/nonexistent.md`）：显示"文件不存在"提示，自动清除 URL 参数，回退到欢迎页
    2. URL 文件直达：
       - 支持 `/docs?file=docs/phases/phase-1a.md` 格式
       - 组件挂载时读取 `searchParams.get('file')`，自动选中并加载该文件
       - 切换文件时更新 URL search params（`setSearchParams`）
  - **验收标准**：
    - [x] 五种空/异常状态均正确展示（含不存在文件的处理）
    - [x] URL 带 `?file=xxx` 时自动打开指定文件
    - [x] URL 指向不存在文件时回退到欢迎页
    - [x] 切换文件时 URL 同步更新
    - [x] 欢迎页文件列表可点击打开（按修改时间降序排列）

### 收尾

- [x] **1H.10** 单元测试
  - **依赖**：1H.9
  - **测试范围**：
    1. **后端 `docs.routes.ts` 测试**（新文件：`web/cui/tests/unit/routes/docs.routes.test.ts`）
       - tree 端点：返回正确目录结构、只包含 .md 文件、空目录过滤、递归深度限制、总文件数上限
       - content 端点：返回文件内容、路径穿越防护（`../`）、URL 编码绕过防护（`%2e%2e`）、符号链接防护、非 .md 拒绝、超 1MB 返回 413、docs/ 不存在返回 404、参数缺失返回 400、错误响应不泄露绝对路径
    2. **前端组件测试**（新目录：`web/cui/tests/unit/components/`，使用已安装的 `@testing-library/react` + `happy-dom`）
       - DocsSidebar：目录展开/折叠、文件选中回调
       - MermaidBlock：渲染成功/失败 fallback
       - DocsView：加载目录树、空状态展示
  - **验收标准**：
    - [x] 新增后端测试全部通过
    - [x] 现有测试无回归
  - **测试命令**：`cd web/cui && npx vitest run`

- [x] **1H.11** 构建部署 + 文档同步
  - **依赖**：1H.10
  - **操作**：
    1. `cd web/cui && npm run build && npm start`（研发模式）
    2. 更新 `docs/phases/phase-1h.md` 标记所有任务 `[x]`
    3. 更新 `docs/progress.md`（Quick Status、测试数、Phase 1H 行）
    4. 更新 `docs/requirement.md`（新增 Phase 1H 验收用例）
    5. Git commit + tag `v0.8.0`
  - **验收标准**：
    - [x] 浏览器 Ctrl+Shift+R 强制刷新确认改动生效
    - [x] Docs Tab 可点击进入文档查看器
    - [x] 目录树正确显示 `docs/` 下的 `.md` 文件
    - [x] 点击文件正确渲染 Markdown 内容
    - [x] Mermaid 代码块渲染为图表
    - [x] 暗色模式下样式正常

## 关键设计决策

| 决策 | 理由 |
|------|------|
| 专用 Docs API 而非复用 filesystem API | 安全边界清晰，`docs/` 白名单限制，未来可扩展为需求文档平台 |
| Docs 作为独立 Link 而非 Tab trigger | 避免与现有 Tabs value/onValueChange 语义冲突——Tabs 控制列表过滤，Docs 导航到新路由 |
| `/docs` 路由包裹 `<Layout>` | 保持全局导航一致性，DocsHeader 作为页面内 header 而非替代 Layout |
| 抽取 `markdownComponents` 为共享模块 | MessageItem 和 DocsContent 共用 code→CodeHighlight 映射，避免重复维护 |
| Mermaid 动态 import 按需加载 | ~2MB 包体，避免影响首屏加载性能 |
| DOMPurify 消毒 + `securityLevel: 'strict'` | 双重 XSS 防护：Mermaid 内置安全 + DOMPurify 消毒 `dangerouslySetInnerHTML` 输出 |
| 不启用 `rehype-raw` 插件 | 防止 markdown 文件中内嵌 `<script>` 标签被执行 |
| 仅浏览当前项目 docs/ | 范围清晰，复用 `selectedProjectPath` 无需额外 UI |
| 1MB 文件大小限制 + 1000 文件数上限 | 防止大文件/大目录导致性能问题 |
| 递归深度 10 层 + 跳过符号链接 | 防止无限递归和符号链接循环 |
| projectPath 接受任意路径 | 单用户平台的已知风险，远期可增加项目白名单校验 |
| 安全校验先 `decodeURIComponent` 再检查 | 防止 URL 双重编码绕过（`%2e%2e%2f`）|

## 改动文件清单

### 新增文件（9 个）

| 文件 | 任务 | 说明 |
|------|------|------|
| `web/cui/src/routes/docs.routes.ts` | 1H.1 | 后端 Docs API（tree + content） |
| `web/cui/src/web/chat/components/shared/markdownComponents.ts` | 1H.5 | 共享 markdown 组件配置（code→CodeHighlight 映射） |
| `web/cui/src/web/chat/components/DocsView/DocsView.tsx` | 1H.7 | 主容器组件 |
| `web/cui/src/web/chat/components/DocsView/DocsHeader.tsx` | 1H.7 | 面包屑导航（可选独立文件或内嵌 DocsView） |
| `web/cui/src/web/chat/components/DocsView/DocsSidebar.tsx` | 1H.4 | 文件树侧边栏 |
| `web/cui/src/web/chat/components/DocsView/DocsContent.tsx` | 1H.5 | Markdown 渲染区 |
| `web/cui/src/web/chat/components/DocsView/MermaidBlock.tsx` | 1H.6 | Mermaid 图表渲染 |
| `web/cui/src/web/chat/components/DocsView/index.ts` | 1H.7 | 导出 |
| `web/cui/tests/unit/routes/docs.routes.test.ts` | 1H.10 | 后端路由测试 |

### 修改文件（6 个）

| 文件 | 任务 | 改动 |
|------|------|------|
| `web/cui/src/cui-server.ts` | 1H.1 | 注册 docs routes（auth middleware 之后） |
| `web/cui/src/web/chat/ChatApp.tsx` | 1H.8 | 新增 `/docs` 路由（React.lazy + Suspense + Layout 包裹） |
| `web/cui/src/web/chat/components/Home/TaskTabs.tsx` | 1H.8 | 新增 Docs 导航链接 |
| `web/cui/src/web/chat/services/api.ts` | 1H.3 | 新增 getDocsTree + getDocsContent 方法 |
| `web/cui/src/web/chat/types/index.ts` | 1H.3 | 新增 DocsTreeNode 类型 |
| `web/cui/src/web/chat/components/MessageList/MessageItem.tsx` | 1H.5 | 抽取 markdownComponents 到共享模块，改为引用 |

## 已知限制

| 限制 | 说明 | 远期处理 |
|------|------|---------|
| 只渲染 `.md` 文件 | 图片等资源文件不在 tree 中展示，markdown 中引用的图片（如 `docs/images/xxx.png`）无法渲染 | 远期可增加静态资源服务端点 |
| 无文档编辑功能 | 当前仅只读浏览 | 远期可增加编辑模式 |
| 无全文搜索 | 只能通过目录树导航 | 远期可增加搜索端点 |
| 无无障碍标签 | 文件树和文档区未添加 ARIA 属性 | 远期补充 |

## 实现安全 Checklist

> 实现阶段的 code review 要点，确保安全设计落地。

- [x] `filePath` 校验前先 `decodeURIComponent()`（防双重编码绕过）
- [x] `mermaid.initialize()` 显式设置 `securityLevel: 'strict'`
- [x] 错误响应不返回服务器端绝对路径
- [x] 403 路径穿越尝试记录 WARNING 日志
- [x] `projectPath` 校验为绝对路径 + 不含 null bytes
- [x] 不启用 `rehype-raw` 插件
- [x] 使用 `res.json()` 返回内容，不使用 `res.send()` 直接返回 raw markdown
- [x] Docs API 路由注册在 auth middleware 之后

## 远期演进路径

| 演进方向 | 当前设计如何支持 |
|---------|----------------|
| 需求文档 Web 展示 | DocsContent 可扩展为多文档 Tab 切换，专用 API 可增加新端点 |
| 文档搜索 | DocsHeader 增加搜索框，后端增加全文搜索端点 |
| 文档编辑 | DocsContent 切换为编辑模式，后端增加写入端点 |
| 跨项目浏览 | DocsView 增加项目选择器，API 已支持 projectPath 参数 |
