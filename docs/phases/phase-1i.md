# Phase 1I: CUI 手机屏幕适配

## 目标

让 CUI 在手机浏览器上有完整可用的体验。方案 B：CSS 响应式 + `useIsMobile` Hook，保持现有导航结构不变。

## 前置条件

- Phase 1H 完成

## 设计文档

详见 `docs/superpowers/specs/2026-03-13-cui-mobile-adaptation-design.md`

## 任务依赖关系

```
1I.1（useIsMobile Hook）→ 1I.3, 1I.4, 1I.5
1I.2（Home 页面响应式）独立
1I.3（RequirementPanel 移动端 overlay）
1I.4（ConversationHeader 移动端精简）
1I.5（ConversationView + MessageList 响应式）
1I.6（Header 高度响应式）独立
1I.1~1I.6 → 1I.7（构建验证 + 测试）
1I.7 → 1I.8（文档同步）
```

## 任务清单

### 1I.1 — useIsMobile Hook

**输入**：现有 hooks 目录 `web/cui/src/web/chat/hooks/`
**输出**：`useIsMobile.ts` + 导出到 `hooks/index.ts`

**实现**：
- `window.matchMedia('(max-width: 768px)')` 监听
- 返回 `boolean`
- SSR 安全：默认 `false`，`useEffect` 中初始化
- 导出到 `hooks/index.ts`

**验收标准**：
- [x] Hook 在 768px 以下返回 `true`
- [x] 窗口 resize 时实时响应
- [x] 单元测试通过

**测试命令**：`cd web/cui && npx vitest run tests/unit/useIsMobile.test.ts`

---

### 1I.2 — Home 页面响应式

**输入**：`Home.tsx`, `Header.tsx`
**输出**：移动端间距和字号适配

**实现**：
- 标题 "What is the next task?" 字号：默认 `text-xl`，桌面 `md:text-2xl`
- Composer 区域 padding 调整
- TaskList 卡片间距移动端更紧凑
- Header 高度：移动端 48px，桌面 60px

**验收标准**：
- [x] 375px 宽度下标题不溢出
- [x] 间距紧凑但不拥挤
- [x] 桌面端外观无变化

**测试命令**：`cd web/cui && npx vitest run tests/unit/`（确认无回归）

---

### 1I.3 — RequirementPanel 移动端全屏 overlay

**输入**：`Layout.tsx`, `RequirementPanel.tsx`, `useIsMobile` hook
**输出**：移动端全屏 overlay 模式

**实现**：
- `Layout.tsx` 中使用 `useIsMobile`
- 移动端：RequirementPanel 渲染为 `fixed inset-0 z-50` overlay
- 加半透明遮罩背景（点击关闭）
- 添加触摸滑动关闭（下滑关闭）
- 桌面端：保持现有并排行为不变

**验收标准**：
- [x] 移动端 RequirementPanel 全屏覆盖
- [x] 点击遮罩可关闭
- [x] 下滑手势可关闭
- [x] 桌面端行为无变化

**测试命令**：`cd web/cui && npx vitest run tests/unit/`

---

### 1I.4 — ConversationHeader 移动端精简

**输入**：`ConversationHeader.tsx`, `useIsMobile` hook
**输出**：移动端隐藏次要信息

**实现**：
- 使用 `useIsMobile` 条件渲染
- 移动端隐藏：commitSHA、additions/deletions 统计
- 标题加 `truncate` 限制宽度
- 保留：返回按钮、标题、归档按钮

**验收标准**：
- [x] 移动端只显示核心信息
- [x] 标题过长时截断显示
- [x] 桌面端显示完整信息

**测试命令**：`cd web/cui && npx vitest run tests/unit/`

---

### 1I.5 — ConversationView + MessageList 响应式

**输入**：`ConversationView.tsx`, `MessageItem.tsx`
**输出**：消息区域移动端适配

**实现**：
- Composer 区域 padding 移动端缩小（`px-2` → `px-1`）
- 代码块加 `overflow-x-auto`（防止撑破布局）
- 消息区域最大宽度移动端放宽

**验收标准**：
- [x] 代码块可横向滚动，不撑破布局
- [x] 消息区域间距合理
- [x] 桌面端无变化

**测试命令**：`cd web/cui && npx vitest run tests/unit/`

---

### 1I.6 — Composer 下拉菜单移动端适配

**输入**：`Composer.tsx`, `useIsMobile` hook
**输出**：下拉菜单在移动端用底部弹出替代

**实现**：
- Directory/Model 选择器在移动端用现有 Dialog bottom sheet 模式
- 或用 Tailwind 响应式类调整下拉位置和宽度
- 确保触摸友好（足够大的点击区域）

**验收标准**：
- [x] 移动端下拉菜单不被裁切
- [x] 选择操作触摸友好
- [x] 桌面端无变化

**测试命令**：`cd web/cui && npx vitest run tests/unit/`

---

### 1I.7 — 构建验证 + 测试

**输入**：所有改动完成
**输出**：构建通过，测试通过

**实现**：
- `cd web/cui && npm run build` 无错误
- `cd web/cui && npx vitest run` 全量测试通过
- Chrome DevTools 模拟 iPhone SE (375px) / iPhone 14 (390px) 验证

**验收标准**：
- [x] 构建成功
- [x] 全量测试通过（≥ 412 TypeScript tests）
- [x] 375px 宽度下所有页面可正常使用

**测试命令**：`cd web/cui && npm run build && npx vitest run`

---

### 1I.8 — 文档同步 + Git

**输入**：所有任务完成
**输出**：文档更新，代码提交

**实现**：
- 更新 `docs/phases/phase-1i.md` 标记所有任务 `[x]`
- 更新 `docs/progress.md`（Quick Status、Phase 概览、测试数）
- Commit + Tag

**验收标准**：
- [x] progress.md 更新
- [x] Git tag `v0.9.0`
