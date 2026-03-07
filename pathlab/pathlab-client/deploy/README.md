# PathLab Deployment

`deploy/` 目录保存的是当前**固定端口 Web / 运维部署**所需脚本与配置，而不是 Electron 桌面打包流程。

## 当前文件用途

- `start.sh`：完整启动脚本
- `hot-reload.sh`：按服务粒度热更新脚本
- `nginx/`：HTTP / HTTPS 反向代理模板
- `systemd/pathlab.service`：systemd 单元模板

## 当前端口约定

部署脚本固定使用：

- Gateway: `6100`
- Preprocessing: `6101`
- AI: `6102`

这套端口是**部署专用固定端口**；它不同于 `PATHLAB_DEBUG=1 python server/main.py` 默认使用的 `5100 / 5101 / 5102`。

## `start.sh` 当前行为

`./deploy/start.sh` 会执行以下动作：

1. 清理占用 `6100 / 6101 / 6102` 的旧进程
2. 读取 `server/.env`（如果存在）
3. 检查 / 启动 Redis
4. 在缺少 `node_modules` 时自动执行 `npm install --silent`
5. 使用 `src/renderer/vite.config.ts` 构建前端静态资源到 `src/renderer/dist`
6. 导出 `PATHLAB_DEBUG=1` 与 `GATEWAY_PORT / PREPROCESSING_PORT / AI_PORT`
7. 启动 `server/main.py`
8. 将日志写入 `logs/`

该脚本是“直接执行型”的，不需要再传 `start` 子命令。

## `hot-reload.sh` 当前行为

`./deploy/hot-reload.sh` 支持以下目标：

- `frontend`
- `backend`
- `gateway`
- `preprocessing`
- `ai`
- `all`

当前实现中：

- `frontend` 会重新构建 `src/renderer/dist`，然后原子替换目录
- `gateway` / `preprocessing` / `ai` 会分别用 `uvicorn` 重启指定服务
- `backend` 会按 `ai -> preprocessing -> gateway` 顺序滚动重启

## Nginx 配置现状

`nginx/pathlab.conf` 与 `nginx/pathlab-http-only.conf` 当前大致遵循：

- `/` → `src/renderer/dist`
- `/api/` → `http://127.0.0.1:6100/`
- `/preprocessing/` → `http://127.0.0.1:6101/`
- `/ai/` → `http://127.0.0.1:6102/api/ai/`
- `/ai/health` → `http://127.0.0.1:6102/health`

HTTPS 版本额外包含证书配置；HTTP-only 版本仅保留反向代理与静态资源规则。

## systemd 模板现状

`systemd/pathlab.service` 使用 `server/main.py` 作为统一入口，并显式设置：

- `PATHLAB_DEBUG=1`
- `GATEWAY_PORT=6100`
- `PREPROCESSING_PORT=6101`
- `AI_PORT=6102`
- `PATHLAB_UPLOADS_DIR=/path/to/pathlab-client/uploads`

因此 systemd 模板与 shell 部署脚本的端口策略是一致的。

## 当前部署前提

- Python 环境可运行 `server/main.py`
- Node / Vite 构建链可生成前端静态资源
- PostgreSQL 可访问
- Redis 可访问
- Nginx（若需要反向代理）

## 常用路径

- 前端构建输出：`src/renderer/dist`
- 部署日志：`logs/`
- 后端环境变量：`server/.env`

## 相关文档

- [Project README](../../../README.md)
- [Server README](../server/README.md)
- [Frontend README](../src/renderer/README.md)