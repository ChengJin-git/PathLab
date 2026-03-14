# PathLab Deployment

> 适用版本：`PathLab v1.0.1`

`deploy/` 目录保存的是当前**固定端口 Web / 运维部署**所需脚本与配置，不是 Electron 桌面打包流程。

## 当前文件用途

- `start.sh`：完整启动脚本
- `hot-reload.sh`：按服务粒度热更新脚本
- `nginx/pathlab.conf`：HTTPS 反向代理模板
- `nginx/pathlab-http-only.conf`：HTTP-only 反向代理模板
- `systemd/pathlab.service`：systemd 单元模板

## 当前端口约定

部署脚本固定使用：

- Gateway: `6100`
- Preprocessing: `6101`
- AI: `6102`

这与 `PATHLAB_DEBUG=1` 下的 sidecar 端口保持一致，便于浏览器调试与反向代理复用。

## `start.sh` 当前行为

`./deploy/start.sh` 当前会依次执行：

1. 清理占用 `6100 / 6101 / 6102` 的旧进程
2. 按进程模式补充清理旧的 `server/main.py` / uvicorn / vLLM 相关残留进程
3. 检查并尽量启动 Redis
4. 如缺少 `node_modules/`，执行一次 `npm install --silent`
5. 用 Vite 构建前端到 `src/renderer/dist`
6. 导出 `PATHLAB_DEBUG=1` 与固定端口环境变量
7. 以 `nohup` 方式启动 `server/main.py`
8. 通过 `http://127.0.0.1:6100/health` 做 Gateway 健康检查
9. 将日志写入 `logs/backend.log`，并记录 `logs/backend.pid`

该脚本是“直接执行型”的，不需要额外传 `start` 子命令。

## `hot-reload.sh` 当前行为

`./deploy/hot-reload.sh` 支持以下目标：

- `frontend`
- `backend`
- `gateway`
- `preprocessing`
- `ai`
- `all`

当前实现里：

- `frontend` 会先构建到临时目录，补拷 `public/assets` / `public/images`，再原子替换 `dist/`
- `frontend` 在 `node_modules/` 缺失或 `vite` 可执行文件不完整时，会先执行一次 `npm install --silent`
- `backend` 会按 `AI → Preprocessing → Gateway` 顺序滚动重启
- `preprocessing` 会读取 `PREPROCESSING_WORKERS` 与 `PREPROCESSING_MAX_REQUESTS`

## Nginx 配置现状

`nginx/pathlab.conf` 与 `nginx/pathlab-http-only.conf` 当前大致遵循：

- `/` → `src/renderer/dist`
- `/api/` → `http://127.0.0.1:6100/`
- `/preprocessing/` → `http://127.0.0.1:6101/`
- `/ai/health` → `http://127.0.0.1:6102/health`
- `/ai/` → `http://127.0.0.1:6102/api/ai/`
- `/assets/` → 长缓存静态资源

HTTPS 版本额外包含证书与 SSL 配置；HTTP-only 版本仅保留静态资源与反向代理规则。

## systemd 模板现状

`systemd/pathlab.service` 使用 `server/main.py` 作为统一入口，并显式设置：

- `PATHLAB_DEBUG=1`
- `GATEWAY_PORT=6100`
- `PREPROCESSING_PORT=6101`
- `AI_PORT=6102`
- `PATHLAB_UPLOADS_DIR`
- `DATABASE_URL`

因此 systemd 模板与 shell 部署脚本的端口策略保持一致。

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
