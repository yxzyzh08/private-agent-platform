# 部署指南

> 本文档描述研发环境和生产环境的部署方式。当前处于**研发模式**。

---

## 当前部署模式：研发模式（宿主机直接运行）

研发阶段所有应用服务在宿主机直接运行，方便调试和快速迭代。仅 Redis 保留 Docker。

### 架构

```
宿主机
├── Platform (FastAPI)       → localhost:8000  ← uv run python main.py
├── CUI (Node.js)            → localhost:3001  ← cd web/cui && npm start
└── Docker
    └── Redis                → localhost:6379  ← docker-compose up -d redis
```

### 启动步骤

```bash
# 1. 启动 Redis（Docker）
docker-compose up -d redis

# 2. 启动 Platform（宿主机）
uv run python main.py

# 3. 启动 CUI（宿主机）
cd web/cui && npm start
```

### CUI 开发热重载

```bash
# 开发模式（自动重启后端 + 前端热更新）
cd web/cui && npm run dev

# 仅重新构建前端
cd web/cui && npm run build

# 生产模式启动
cd web/cui && npm start
```

### 停止服务

```bash
# 停止 Redis
docker-compose stop redis

# Platform 和 CUI：直接 Ctrl+C 终止终端进程
```

---

## 生产部署模式：Docker Compose（全容器化）

稳定后切换为全 Docker 部署。

### 架构

```
Docker Compose
├── platform    → :8000
├── cui         → :3001
└── redis       → :6379
```

### 启动

```bash
docker-compose up -d
```

### CUI 重建部署

```bash
docker-compose build cui && docker-compose up -d cui
```

如遇 `ContainerConfig` 错误：
```bash
docker rm -f $(docker ps -aq --filter "name=cui") 2>/dev/null
docker-compose up -d cui
```

---

## 研发模式 → 生产模式 切换

### 切换到生产模式

```bash
# 停止宿主机服务（Ctrl+C 终止 Platform 和 CUI）

# 全容器化启动
docker-compose up -d
```

### 切换到研发模式

```bash
# 停止应用容器（保留 Redis）
docker-compose stop platform cui

# 宿主机启动
uv run python main.py          # Terminal 1
cd web/cui && npm run dev       # Terminal 2
```
