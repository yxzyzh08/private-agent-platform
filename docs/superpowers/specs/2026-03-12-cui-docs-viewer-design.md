# CUI 项目文档查看器 — 设计文档

**日期**: 2026-03-12
**Phase**: 1H
**状态**: 设计确认

---

## 1. 概述

### 1.1 目标

在 CUI 中新增项目文档查看功能（只读），支持 Markdown 渲染和 Mermaid 流程图语法。用户通过 Docs Tab 浏览当前项目的 `docs/` 目录，点击 `.md` 文件即可在右侧内容区渲染阅读。

### 1.2 范围

**Phase 1H 范围（当前）：**
- 仅浏览当前选中项目的 `docs/` 目录
- 只读查看，不支持编辑
- Markdown 渲染 + Mermaid 图表
- 左侧目录树 + 右侧内容的双栏布局

**远期演进方向（不在本 Phase 实现）：**
- 需求文档 Web 展示平台：需求机器人生成的多文档按人类友好形式展示
- 文档搜索
- 文档编辑

### 1.3 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 浏览范围 | 仅 `docs/` 目录 | 范围清晰，安全性好 |
| 入口位置 | 新增顶层 Docs Tab | 与现有 Tab 平级，易发现 |
| 布局 | 左侧目录树 + 右侧内容 | 经典双栏，类 GitBook 阅读体验 |
| 流程图语法 | Mermaid.js | 生态成熟，GitHub/GitLab 兼容 |
| 技术方案 | 专用 Docs API | 安全边界清晰，API 语义专用化，扩展性好 |
| 项目范围 | 仅当前选中项目 | 实现简单，与现有 selectedProjectPath 联动 |

---

## 2. 架构设计

### 2.1 数据流

```
用户点击 Docs Tab
    ↓
导航到 /docs 路由 → DocsView 组件加载
    ↓
GET /api/docs/tree?projectPath=<path>
    ↓
后端扫描 <projectPath>/docs/，返回目录树 JSON
    ↓
前端渲染左侧文件树（DocsSidebar）
    ↓
用户点击某个 .md 文件
    ↓
GET /api/docs/content?projectPath=<path>&filePath=<relative>
    ↓
后端安全校验 → 读取文件内容 → 返回原始 markdown
    ↓
前端 react-markdown + mermaid.js 渲染（DocsContent）
```

### 2.2 安全边界

- 后端强制校验 `filePath` 必须以 `docs/` 开头
- `realpath` 解析后必须在 `<projectPath>/docs/` 目录内（防路径穿越）
- 符号链接：`realpath` 解析自动处理，指向 `docs/` 外部的符号链接会被安全校验拒绝
- 只允许读取 `.md` 文件
- 只读操作，无写入端点
- 文件大小限制：单个文件不超过 1MB，超出返回 413
- Mermaid SVG 输出通过 DOMPurify 消毒后再注入 DOM，防止 XSS
- `projectPath` 安全说明：当前为单用户平台，接受任意路径为已知风险；远期可增加已知项目白名单校验

---

## 3. 后端 API 设计

实现文件：`src/routes/docs.routes.ts`（约 80-100 行）

### 3.1 GET /api/docs/tree

获取项目文档目录树。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| projectPath | string | 是 | 项目根目录绝对路径 |

**响应 200：**
```json
{
  "name": "docs",
  "path": "docs",
  "type": "directory",
  "children": [
    {
      "name": "progress.md",
      "path": "docs/progress.md",
      "type": "file",
      "size": 3200,
      "modifiedAt": "2026-03-12T10:30:00Z"
    },
    {
      "name": "phases",
      "path": "docs/phases",
      "type": "directory",
      "children": [
        {
          "name": "phase-1a.md",
          "path": "docs/phases/phase-1a.md",
          "type": "file",
          "size": 15600,
          "modifiedAt": "2026-03-08T14:20:00Z"
        }
      ]
    }
  ]
}
```

**行为：**
- 递归扫描 `<projectPath>/docs/`，最大递归深度 10 层
- 只返回 `.md` 文件和包含 `.md` 文件的目录
- 过滤隐藏文件/目录（`.` 开头）
- 跳过符号链接目录（防循环）
- 目录在前、文件在后，各自按名称升序排列

**错误响应：**
- 404：`docs/` 目录不存在
- 400：`projectPath` 缺失或无效

### 3.2 GET /api/docs/content

读取指定文档文件内容。

**Query 参数：**
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| projectPath | string | 是 | 项目根目录绝对路径 |
| filePath | string | 是 | 相对于项目根的文件路径（如 `docs/phases/phase-1a.md`） |

**响应 200：**
```json
{
  "content": "# Phase 1A — 平台基础设施...",
  "size": 15600,
  "modifiedAt": "2026-03-08T14:20:00Z"
}
```

**安全校验：**
1. `filePath` 必须以 `docs/` 开头
2. `filePath` 必须以 `.md` 结尾
3. `path.resolve(projectPath, filePath)` 的 `realpath` 必须在 `<projectPath>/docs/` 目录内
4. 文件大小不超过 1MB（`stat.size` 检查）
5. 任一校验失败返回对应错误码

**错误响应：**
- 403：路径校验失败（路径穿越、非 docs 目录、非 .md 文件）
- 404：文件不存在
- 413：文件超过 1MB 大小限制
- 400：参数缺失

---

## 4. 前端组件设计

### 4.1 路由

在 `ChatApp.tsx` 的 Router 中新增：
```
/docs           → DocsView（文档首页）
/docs?file=xxx  → DocsView（直接打开指定文件）
```

### 4.2 组件结构

```
DocsView (~150行)
├── DocsHeader — 顶部面包屑导航 + 项目名 + 返回 Home 按钮
├── DocsSidebar (~100行) — 左侧文件树
│   └── TreeNode (递归) — 目录/文件节点，可展开/折叠
└── DocsContent (~120行) — 右侧 Markdown 渲染区
    ├── react-markdown — Markdown 渲染（复用现有配置）
    ├── CodeHighlight — 代码块语法高亮（复用现有组件）
    └── MermaidBlock (~50行) — Mermaid 图表渲染（新增）
```

文件位置：`src/web/chat/components/DocsView/`

### 4.3 DocsView（主容器）

**状态管理：**
- `treeData: TreeNode | null` — 目录树数据，从 API 加载
- `selectedFile: string | null` — 当前选中的文件路径
- `fileContent: string | null` — 当前文件的 markdown 内容
- `loading: boolean` — 加载状态

**项目路径来源：**
- 从现有的 `ConversationsContext` 中获取 `selectedProjectPath`
- DocsView 通过 `useConversations()` hook 读取当前选中项目路径
- 若未选中项目（`selectedProjectPath` 为空），显示空状态提示

**行为：**
- 组件挂载时调用 `GET /api/docs/tree` 加载目录树
- URL 含 `?file=xxx` 时自动选中并加载该文件
- `selectedFile` 变化时调用 `GET /api/docs/content` 加载内容

### 4.4 DocsSidebar + TreeNode

**TreeNode 组件（递归）：**
- 目录节点：点击展开/折叠，显示 ▶/▼ 箭头 + 📁 图标
- 文件节点：点击选中并加载内容，选中态高亮，显示 📄 图标
- 缩进层级通过 `depth` prop 控制 `padding-left`

**样式：**
- 使用 Tailwind CSS，与现有 CUI 风格一致
- 暗色模式适配（复用现有 CSS 变量）

### 4.5 DocsContent

**Markdown 渲染：**
- 使用 `react-markdown`，配置与 `MessageItem.tsx` 中类似的 `markdownComponents`
- 代码块复用现有 `CodeHighlight` 组件
- 新增：`language === 'mermaid'` 时交给 `MermaidBlock` 渲染

**Prose 样式：**
- 使用 Tailwind Typography 插件（`prose prose-sm dark:prose-invert`）
- `max-width: 800px` 限制内容宽度，提升阅读体验

### 4.6 MermaidBlock（新增）

**职责：** 将 Mermaid 语法渲染为 SVG 图表

**实现：**
```typescript
// 伪代码
const mermaidPromise = import('mermaid'); // lazy import，按需加载
import DOMPurify from 'dompurify';

function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    mermaidPromise
      .then(({ default: mermaid }) => {
        return mermaid.render(uniqueId, code);
      })
      .then(({ svg }) => {
        // DOMPurify 消毒，防止 XSS
        const sanitized = DOMPurify.sanitize(svg, { USE_PROFILES: { svg: true } });
        setSvg(sanitized);
      })
      .catch((err) => setError(err.message));
  }, [code]);

  if (error) return <pre><code>{code}</code></pre>; // fallback 为原始代码
  return <div dangerouslySetInnerHTML={{ __html: svg }} />;
}
```

**要点：**
- `mermaid` 包通过 `lazy import` 按需加载（约 2MB gzipped），避免影响首屏
- 若 mermaid 模块加载失败（网络错误、chunk 加载失败），fallback 为纯文本代码块 + "Mermaid rendering unavailable" 提示
- SVG 输出通过 `DOMPurify.sanitize()` 消毒后再注入 DOM，防止 XSS
- 初始化时根据当前主题设置 `theme: 'dark'` 或 `'default'`
- 渲染失败时 fallback 为显示原始代码块 + 错误提示

### 4.7 Tab 集成

**实现方式：** 在 `TaskTabs` 组件中，Docs 不作为 Radix `<Tabs.Trigger>`，而是作为一个独立的导航链接（`<Link>`），视觉上与其他 Tab 样式一致但行为不同——点击导航到 `/docs` 路由而非切换列表过滤。

**具体做法：**
- 在 Radix `<Tabs.List>` 之后（或末尾）放置一个样式相同的 `<Link to="/docs">Docs</Link>`
- 使用与 Tab trigger 相同的 CSS 类，保持视觉一致
- 不将 `'docs'` 加入 Radix Tabs 的 `value` union，避免架构冲突

**导航衔接：**
- 从 Docs 页通过面包屑 "← Home" 返回首页（`navigate('/')`）
- 返回时 Home 组件重新挂载，Radix Tabs 恢复默认值（`tasks`）
- 这是可接受的行为——用户从 Docs 返回后看到 Tasks 列表是合理的默认状态

### 4.8 空状态

| 场景 | 展示 |
|------|------|
| 项目无 `docs/` 目录 | 居中提示："当前项目没有 docs/ 目录" |
| 未选中文件 | 欢迎内容：文档统计（文件数）+ 最近修改的文件列表 |
| 文件加载中 | 骨架屏或 spinner |
| 未选中项目 | 提示选择项目 |

### 4.9 URL 结构

| URL | 说明 |
|-----|------|
| `/docs` | 文档首页，展示目录树，右侧显示欢迎页 |
| `/docs?file=docs/phases/phase-1a.md` | 直接打开指定文件，支持分享链接 |

---

## 5. 依赖变更

### 5.1 新增 npm 依赖

| 包 | 版本 | 用途 |
|----|------|------|
| `mermaid` | ^11 | Mermaid 图表渲染（锁定主版本，避免 breaking change） |
| `dompurify` | ^3 | SVG/HTML 消毒，防止 Mermaid 输出的 XSS |
| `@types/dompurify` | ^3 | DOMPurify TypeScript 类型定义 |

### 5.2 复用现有依赖

- `react-markdown` — Markdown 解析渲染
- `prism-react-renderer` — 代码语法高亮
- `@radix-ui/react-tabs` — Tab 组件
- `lucide-react` — 图标
- `react-router-dom` — 路由

---

## 6. 文件清单

### 6.1 新增文件

| 文件 | 行数估算 | 职责 |
|------|---------|------|
| `src/routes/docs.routes.ts` | ~80-100 | 后端 Docs API（tree + content） |
| `src/web/chat/components/DocsView/DocsView.tsx` | ~150 | 主容器组件 |
| `src/web/chat/components/DocsView/DocsHeader.tsx` | ~40 | 面包屑导航 |
| `src/web/chat/components/DocsView/DocsSidebar.tsx` | ~100 | 文件树侧边栏 |
| `src/web/chat/components/DocsView/DocsContent.tsx` | ~120 | Markdown 渲染区 |
| `src/web/chat/components/DocsView/MermaidBlock.tsx` | ~50 | Mermaid 图表渲染 |
| `src/web/chat/components/DocsView/index.ts` | ~5 | 导出 |

### 6.2 修改文件

| 文件 | 修改内容 |
|------|---------|
| `src/cui-server.ts` | 注册 docs routes |
| `src/web/chat/ChatApp.tsx` | 新增 `/docs` 路由 |
| `src/web/chat/components/Home/TaskTabs.tsx` | 新增 Docs Tab |
| `src/web/chat/services/api.ts` | 新增 `getDocsTree()` 和 `getDocsContent()` API 方法 |

---

## 7. 测试策略

### 7.1 后端测试

| 测试 | 覆盖内容 |
|------|---------|
| docs.routes 单元测试 | tree 端点返回正确目录结构 |
| | content 端点返回文件内容 |
| | 路径穿越防护（`../`、符号链接） |
| | 非 .md 文件拒绝读取 |
| | 文件超过 1MB 返回 413 |
| | docs/ 目录不存在返回 404 |
| | 参数缺失返回 400 |
| | 递归深度超过 10 层时停止扫描 |

### 7.2 前端测试

| 测试 | 覆盖内容 |
|------|---------|
| DocsView 组件测试 | 加载目录树并渲染侧边栏 |
| | 点击文件加载并渲染内容 |
| | 空状态正确展示 |
| DocsSidebar 测试 | 目录展开/折叠 |
| | 文件选中高亮 |
| MermaidBlock 测试 | Mermaid 语法渲染为 SVG |
| | 无效语法 fallback 为代码块 |

---

## 8. 远期演进路径

本设计为远期需求文档 Web 展示平台预留了扩展点：

| 演进方向 | 当前设计如何支持 |
|---------|----------------|
| 多文档友好展示 | DocsContent 组件可扩展为支持多文档 Tab 切换 |
| 需求机器人生成文档 | 专用 API 可扩展新端点返回生成的文档列表 |
| 文档搜索 | 可在 DocsHeader 增加搜索框，后端增加全文搜索端点 |
| 文档编辑 | DocsContent 可切换为编辑模式，后端增加写入端点 |
| 跨项目浏览 | DocsView 增加项目选择器，API 已支持 projectPath 参数 |
