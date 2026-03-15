# PathLab Deployment

> 适用版本：`PathLab v1.0.1`

本文档分两部分：
1. **桌面打包**（Electron AppImage / DMG / NSIS）— `scripts/` + `npm run build:linux|mac|win`
2. **固定端口 Web 部署**（服务器运维）— `deploy/` 目录的脚本与配置

---

## 一、桌面打包（Electron）

### 一键构建命令

```bash
npm run build:linux   # → dist/PathLab-*.AppImage
npm run build:mac     # → dist/PathLab-*.dmg
npm run build:win     # → dist/PathLab-*.exe  (需 Git Bash 或 WSL)
```

每条命令依次执行：

```
build:python     ← PyInstaller 打包 server/dist/main/（onedir）
prepare-redis    ← 准备嵌入式 redis-server 二进制
build            ← electron-vite 构建前端 + 主进程
electron-builder ← 打包成安装包，注入 extraResources
```

### 前提条件

| 依赖 | Linux | macOS | Windows |
|---|---|---|---|
| Node.js ≥ 18 | ✓ | ✓ | ✓ |
| Python ≥ 3.10 + pip | ✓ | ✓ | ✓ |
| PyInstaller | `pip install pyinstaller pyinstaller-hooks-contrib` | 同左 | 同左 |
| `pip install -r server/requirements.txt` | ✓ | ✓ | ✓ |
| redis-server（系统安装） | `apt install redis-server` | `brew install redis` | 见下方 |
| bash | 内置 | 内置 | Git Bash 或 WSL |
| openslide 系统库 | `apt install libopenslide-dev` | `brew install openslide` | 见下方 |

### 平台支持状态

| 平台 | 打包 | 运行时 | 说明 |
|---|---|---|---|
| **Linux x86_64** | ✅ 完整支持 | ✅ | 主要开发 / 发布平台 |
| **macOS (Apple Silicon / Intel)** | ✅ 支持 | ✅ | 需 Homebrew；Apple Silicon 自动选 arm64 PyInstaller |
| **Windows x64** | ✅ 支持 | ✅ | 构建需 Git Bash；Redis 由脚本自动下载 Garnet |

### Windows 特殊说明

Windows 上不存在官方 Redis 二进制，`prepare-redis.sh` 会自动下载 **Microsoft Garnet**（MIT 许可，Redis wire-protocol 兼容，微软研究院维护）替代：

```
scripts/prepare-redis.sh（Git Bash 中执行）
  ↓ 检测到 MINGW/MSYS 环境
  ↓ 从 github.com/microsoft/garnet/releases 下载最新 garnet-win-x64.zip
  ↓ 提取 GarnetServer.exe → resources/redis-server.exe
```

Garnet 默认绑定 `127.0.0.1`（比 Redis 更安全），`services-manager.ts` 在 Windows 下自动使用 Garnet 的 `--address` 参数替代 Redis 的 `--bind`，并省略不适用的 `--appendonly` / `--daemonize` 等 Redis 专有参数。

build 脚本要求 bash，在 Windows 上需用 Git Bash 执行：
```bash
npm run build:win
```

### 打包产物结构（打入 extraResources）

```
resources/
├── server/main/        ← Python sidecar（PyInstaller onedir bundle）
│   ├── main            ← 可执行文件（Linux/macOS）或 main.exe（Windows）
│   ├── _internal/      ← torch、transformers 等所有依赖
│   └── ...
├── redis-server        ← 嵌入式 Redis 二进制（Linux/macOS）
└── redis-server.exe    ← 嵌入式 Redis 二进制（Windows）
```

PostgreSQL 由 `embedded-postgres` npm 包在运行时自动管理，无需预置二进制。

### 运行时行为

打包后的 Electron 应用启动时：

1. 自动启动嵌入式 PostgreSQL（首次运行自动 `initdb`，约 3–5 秒）
2. 自动启动嵌入式 Redis（随机端口，AOF 持久化）
3. 自动启动 Python sidecar，注入 `DATABASE_URL` 和 `REDIS_URL`
4. 应用退出时自动停止上述服务

数据目录（跨版本持久）：
- PostgreSQL：`{userData}/postgres-data/`
- Redis AOF：`{userData}/redis-data/`

---

## 二、固定端口 Web 部署

### 当前文件用途

- `start.sh`：完整启动脚本
- `hot-reload.sh`：按服务粒度热更新脚本
- `nginx/pathlab.conf`：HTTPS 反向代理模板
- `nginx/pathlab-http-only.conf`：HTTP-only 反向代理模板
- `systemd/pathlab.service`：systemd 单元模板

### 当前端口约定

部署脚本固定使用：

- Gateway: `6100`
- Preprocessing: `6101`
- AI: `6102`

这与 `PATHLAB_DEBUG=1` 下的 sidecar 端口保持一致，便于浏览器调试与反向代理复用。

### `start.sh` 当前行为

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

### `hot-reload.sh` 当前行为

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

### Nginx 配置现状

`nginx/pathlab.conf` 与 `nginx/pathlab-http-only.conf` 当前大致遵循：

- `/` → `src/renderer/dist`
- `/api/` → `http://127.0.0.1:6100/`
- `/preprocessing/` → `http://127.0.0.1:6101/`
- `/ai/health` → `http://127.0.0.1:6102/health`
- `/ai/` → `http://127.0.0.1:6102/api/ai/`
- `/assets/` → 长缓存静态资源

HTTPS 版本额外包含证书与 SSL 配置；HTTP-only 版本仅保留静态资源与反向代理规则。

### systemd 模板现状

`systemd/pathlab.service` 使用 `server/main.py` 作为统一入口，并显式设置：

- `PATHLAB_DEBUG=1`
- `GATEWAY_PORT=6100`
- `PREPROCESSING_PORT=6101`
- `AI_PORT=6102`
- `PATHLAB_UPLOADS_DIR`
- `DATABASE_URL`

因此 systemd 模板与 shell 部署脚本的端口策略保持一致。

### 当前部署前提

- Python 环境可运行 `server/main.py`
- Node / Vite 构建链可生成前端静态资源
- PostgreSQL 可访问
- Redis 可访问
- Nginx（若需要反向代理）

### 常用路径

- 前端构建输出：`src/renderer/dist`
- 部署日志：`logs/`
- 后端环境变量：`server/.env`

### 相关文档

- [Project README](../../../README.md)
- [Server README](../server/README.md)
- [Frontend README](../src/renderer/README.md)
