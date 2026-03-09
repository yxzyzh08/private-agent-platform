# Session 轮换方案 — 变更摘要

**日期**: 2026-03-09
**状态**: 已落地到正式文档

---

## 背景

用户在 cui 中发现不支持 `/clear` 等命令，调研后发现 Claude Agent SDK（Python）可替代原有 CLI subprocess + JSONL 轮询方案。SDK 提供编程式 session 生命周期管理（`query()`、Hooks 回调、结构化返回值），使原方案中的 JSONL 文件轮询和 JSON 解析可被更可靠的事件驱动机制替代。

---

## 关键决策

| ID | 决策 | 理由 |
|----|------|------|
| DR-6 | Agent SDK 作为 Phase 1B 的 CLI 执行后端（双轨并行，可配置切换） | SDK 提供更好的 API 抽象；保留 subprocess 作为 fallback 降低风险 |
| DR-7 | CUI /clear 通过 session 重启实现（前端拦截 → 后端终止进程 → 新 session） | 不需要修改 Claude CLI 本身，实现简单 |
| DR-8 | 保留任务分解，不使用 SDK Subagents（Phase 1B） | 任务分解更透明可调试，Subagents 增加复杂度 |
| DR-9 | 简化三层防御为两层（任务分解 + 结果检测），去掉 JSONL 轮询层 | SDK Hooks 提供事件驱动的上下文感知；即使不用 SDK，结果检测也能覆盖核心场景 |
| DR-10 | CLAUDE.md 优化推迟到 Phase 1B 后期 | 先完成核心功能，效率优化不阻塞开发 |

---

## 落地影响

| 文档 | 变更 |
|------|------|
| `docs/requirement.md` | 新增 DV-14~DV-17（SDK 集成、复杂度自适应、Session 轮换、CUI /clear）；新增 `claude_code_sdk` 工具；新增 AC-1B.6~AC-1B.9 验收用例；更新横切面演进（配置/测试/错误类型） |
| `docs/phases/phase-1b.md` | 新增 Task 1B.4a（SDK POC）、1B.4b（CUI /clear）、1B.5a（Session 轮换核心）、1B.6a（轮换集成测试）；修改 Task 1B.5（增加 SDK 执行 + 复杂度自适应）；任务数 11→15 |
| `docs/progress.md` | Phase 1B 任务数更新为 0/15 |

---

## 归档说明

本文件是以下两份详细设计文档的精简摘要，原文已归档删除：
- `context-aware-session-rotation.md` — 原始三层防御设计方案
- `session-rotation-review-v2.md` — 基于 SDK 发现的改进评审

详细设计内容已落地到 `docs/requirement.md` 和 `docs/phases/phase-1b.md`，不再需要单独的设计文档。
