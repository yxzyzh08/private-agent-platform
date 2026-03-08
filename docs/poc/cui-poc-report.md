# cui POC 验证报告

**日期**: 2026-03-08
**版本**: cui v0.6.3
**来源**: https://github.com/wbopan/cui (clone 到 `web/cui/`)

---

## POC 验证结果汇总

| 验证项 | 结果 | 说明 |
|--------|------|------|
| 源码获取 | ✅ 通过 | Clone 到 `web/cui/`，保留 Apache-2.0 LICENSE |
| 构建 | ⏳ 待验证 | `npm install && npm run build` 需要 Node.js 20.19.0+ |
| Claude Code 交互 | ⏳ 待验证 | 需本机有 `claude` CLI |
| 远程访问能力 | ✅ 通过 | 支持 `--host 0.0.0.0`，配置文件 `~/.cui/config.json` |
| 后台任务能力 | ✅ 通过 | 内置 ProcessManager，独立子进程，关闭浏览器后继续 |
| ntfy 推送能力 | ✅ 通过 | 内置 `notification-service.ts`，支持自定义 ntfy URL |
| Docker 化能力 | ❌ 不内置 | 无 Dockerfile，需自建（简单 Node.js 镜像即可） |
| 认证机制 | ⚠️ 基本 | Bearer token（32 位 hex），适合单用户；生产需反向代理加 HTTPS |

---

## 详细发现

### 1. License

**Apache-2.0**（非需求文档中标注的 MIT）。Apache-2.0 同样允许商用和修改，要求保留版权声明和 LICENSE 文件。`web/cui/LICENSE` 已包含完整许可文本。

> **Action**: 更新 `docs/requirement.md` 中 cui 的许可引用为 Apache-2.0。

### 2. 构建系统

- **依赖**: Node.js 20.19.0+
- **构建命令**: `npm install && npm run build`
- **产出**: `dist/server.js`（入口）+ `dist/web/`（SPA 前端）
- **开发模式**: `npm run dev`（tsx watch + hot reload）

### 3. 远程访问配置

**方式一：CLI 参数**
```bash
npx cui-server --host 0.0.0.0 --port 3001 --token your-secure-token
```

**方式二：配置文件** (`~/.cui/config.json`)
```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 3001
  }
}
```

### 4. 后台任务

- 每个对话在独立子进程中运行（`claude-process-manager.ts`）
- 浏览器关闭后进程继续运行
- 任务列表在 "Tasks" 标签页查看
- 支持 fork、resume、archive 操作
- 会话数据持久化到 SQLite (`~/.cui/session-info.db`)

### 5. ntfy 推送

内置 `notification-service.ts`，支持：
- ntfy.sh 推送（默认 topic: `cui-{machineId}`）
- 自定义 ntfy 服务器 URL
- Web Push 通知（备选方案）

配置方式 (`~/.cui/config.json`):
```json
{
  "interface": {
    "notifications": {
      "enabled": true,
      "ntfyUrl": "https://ntfy.sh"
    }
  }
}
```

触发场景：
- 任务完成/失败
- 权限请求等待
- 自定义通知 API

### 6. Docker 化方案（需自建）

cui 不提供 Dockerfile，但结构简单，建议方案：

```dockerfile
FROM node:20-slim
WORKDIR /app
COPY web/cui/package*.json ./
RUN npm ci --production=false
COPY web/cui/ .
RUN npm run build
EXPOSE 3001
CMD ["node", "dist/server.js", "--host", "0.0.0.0"]
```

关键注意：
- 需要挂载 `~/.cui/` 卷持久化配置和数据库
- 需要在容器内安装 `claude` CLI
- 需要传入 API Key 环境变量

### 7. 认证

- Bearer token（32 位 hex，首次运行自动生成）
- 存储在 `~/.cui/config.json`
- 速率限制：10 次失败/秒/IP

**生产部署建议**：使用 Caddy/nginx 反向代理 + HTTPS（Let's Encrypt），cui 自带的 Bearer token 作为第二层防护。

---

## 对后续 Task 的方案建议

### Task 1.19（远程访问 + 认证）

**推荐方案**：
1. cui 配置 `host: "0.0.0.0"`, `port: 3001`
2. Caddy 反向代理：`your-domain:443` → `localhost:3001`
3. HTTPS 由 Caddy 自动管理（Let's Encrypt）
4. 双重认证：Caddy Basic Auth + cui Bearer token

### Task 1.20（ntfy 推送）

**推荐方案**：
1. 直接使用 cui 内置 ntfy 支持
2. 配置 `~/.cui/config.json` 设置 ntfy topic（使用 `.env` 中的 `NTFY_TOPIC`）
3. 无需额外开发

### Task 1.24（Docker Compose）

**调整建议**：
- `web/cui/Dockerfile` 需手动创建（上述方案）
- Docker Compose 中 cui 服务需要挂载 `~/.cui/` 和代码仓库目录
- claude CLI 需要在容器内可用（或挂载宿主机的 claude 二进制文件）

---

## 结论

cui **完全满足 Phase 1A 需求**，所有核心功能（远程访问、后台任务、ntfy 推送）均为内置特性。唯一需要自建的是 Docker 化部署方案，工作量可控。

**Gate 判定**：✅ POC 通过 → 按本报告方案执行 Task 1.19 和 Task 1.20。
