# CUI 手机屏幕适配设计

> **日期**：2026-03-13
> **方案**：方案 B — CSS 响应式 + useIsMobile Hook
> **原则**：不过度设计，保持现有导航结构，最小改动实现完整移动端体验

---

## 1. 现状分析

### 已有的移动端支持
- PWA meta 标签 + viewport 配置（`width=device-width, initial-scale=1.0, viewport-fit=cover`）
- Safe area CSS 变量（支持刘海屏）
- Dialog 组件有移动端底部弹出样式 + 触摸滑动关闭（768px 断点）
- Composer textarea 高度跟随 viewport

### 缺失的
- 无 CSS media queries 做响应式布局
- RequirementPanel 固定 `w-80` 并排，小屏挤压主内容
- ConversationHeader 信息过多，小屏溢出
- 间距/字号未做移动端调整
- Tailwind 响应式前缀几乎没用

---

## 2. 设计方案

### 2.1 基础设施

#### useIsMobile Hook

新建 `web/cui/src/web/chat/hooks/useIsMobile.ts`：

- 基于 `window.matchMedia('(max-width: 768px)')` 监听
- 返回 `boolean`
- 使用 `matchMedia` 事件监听（性能优于 resize）
- 与现有 Dialog 组件的 768px 断点保持一致
- SSR 安全：默认 `false`，`useEffect` 中更新

#### Tailwind 响应式策略

- 使用 Tailwind 默认断点，主要使用 `md: 768px`
- **mobile-first** 写法：默认移动端样式，`md:` 覆盖桌面端样式
- 不新增自定义断点

### 2.2 RequirementPanel（右侧进度面板）

**现状**：固定 `w-80`，与主内容并排显示

**移动端适配**：
- 当 `isMobile` 为 `true` 时，渲染为全屏 overlay
- 样式：`fixed inset-0 z-50`，覆盖整个屏幕
- 顶部保留关闭按钮
- 背景加半透明遮罩（点击遮罩关闭）
- 复用现有 Dialog 组件的触摸滑动关闭逻辑

**桌面端**：保持现有行为不变

### 2.3 Home 页面

#### Composer 区域
- 移动端 padding 缩小（`px-4` → `px-3`）
- 标题字号缩小：默认 `text-xl`，桌面端 `md:text-2xl`
- Directory/Model 选择器下拉：移动端复用 Dialog 的 bottom sheet 模式

#### TaskTabs + TaskList
- TaskItem 卡片间距微调（移动端更紧凑）
- TaskTabs 标签保持不变（已够紧凑）

### 2.4 ConversationView

#### ConversationHeader
- 移动端隐藏次要信息：commit SHA、additions/deletions 统计
- 只保留：返回按钮、标题（truncate 截断）、归档按钮
- 使用 `isMobile` 条件渲染隐藏次要元素

#### MessageList
- 消息区域移动端减小左右边距
- 代码块加 `overflow-x-auto` 支持横向滚动（防止撑破布局）

#### Composer
- 移动端键盘弹出时 textarea 自适应（已有逻辑，保持不变）
- 发送按钮保持当前大小（已触摸友好）

### 2.5 Header

- 移动端高度缩小：60px → 48px
- 设置按钮保持不变

---

## 3. 不做的事情（YAGNI）

- 不加底部导航栏
- 不加汉堡菜单
- 不做独立的 MobileLayout 组件树
- 不做横屏特殊处理
- 不做平板专属断点
- 不改现有导航流程（Home → 对话 → 返回）

---

## 4. 涉及文件清单

| 文件 | 改动类型 |
|------|---------|
| `web/cui/src/web/chat/hooks/useIsMobile.ts` | **新建** — hook |
| `web/cui/src/web/chat/components/Layout/Layout.tsx` | 修改 — RequirementPanel 移动端 overlay |
| `web/cui/src/web/chat/components/RequirementPanel/RequirementPanel.tsx` | 修改 — 全屏 overlay 模式 |
| `web/cui/src/web/chat/components/Home/Home.tsx` | 修改 — 间距/字号响应式 |
| `web/cui/src/web/chat/components/Home/Header.tsx` | 修改 — 高度响应式 |
| `web/cui/src/web/chat/components/ConversationView/ConversationView.tsx` | 修改 — 消息区域间距 |
| `web/cui/src/web/chat/components/ConversationHeader/ConversationHeader.tsx` | 修改 — 隐藏次要信息 |
| `web/cui/src/web/chat/components/Composer/Composer.tsx` | 修改 — 下拉菜单移动端适配 |
| `web/cui/src/web/chat/components/MessageList/MessageItem.tsx` | 修改 — 代码块横向滚动 |

---

## 5. 测试策略

- Chrome DevTools 移动端模拟器（iPhone SE / iPhone 14 / Pixel 7）
- 验证各页面在 375px / 390px / 414px 宽度下的布局
- 验证 RequirementPanel overlay 打开/关闭/滑动
- 验证键盘弹出时 Composer 不被遮挡
- 真机测试（可选）
