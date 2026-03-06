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

这与 `PATHLAB_DEBUG=1` 下的 Python 服务端口保持一致，便于浏览器调试与反向代理配置复用。

## `start.sh` 当前行为

`./deploy/start.sh` 会执行以下动作：

1. 停掉占用 6100 / 6101 / 6102 的旧进程
2. 读取 `server/.env`（如果存在）
3. 检查 / 启动 Redis
4. 构建前端静态资源到 `src/renderer/dist`
5. 以固定端口启动 `server/main.py`
6. 将日志写入 `logs/`

该脚本是“直接执行型”的，不需要再传 `start` 子命令。

## `hot-reload.sh` 当前行为

`./deploy/hot-reload.sh` 支持以下目标：

- `frontend`
- `backend`
- `gateway`
- `preprocessing`
- `ai`
- `all`

它会在不整体重装环境的前提下，按目标服务重启对应组件，并继续使用固定端口。

## Nginx 配置现状

`nginx/pathlab.conf` 与 `nginx/pathlab-http-only.conf` 当前大致遵循：

- `/` → 前端构建产物
- `/api/` → `http://127.0.0.1:6100`
- `/preprocessing/` → `http://127.0.0.1:6101`
- `/ai/` → `http://127.0.0.1:6102`

HTTPS 版本额外包含证书配置；HTTP-only 版本仅保留反向代理与静态资源规则。

## systemd 模板现状

`systemd/pathlab.service` 使用 `server/main.py` 作为统一入口，并显式设置：

- `PATHLAB_DEBUG=1`
- `GATEWAY_PORT=6100`
- `PREPROCESSING_PORT=6101`
- `AI_PORT=6102`

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