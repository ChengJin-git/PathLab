# PathLab Deployment

> 适用版本：`PathLab v1.0.5`

如果目标是给新服务器部署完整的 PathLab + AutoResearch（实现 codename：AutoResearch）Web 服务，先看
[`../server/backend/autoresearch/README.md`](../server/backend/autoresearch/README.md) 中的 `Deployment Quickstart` 与 `Apptainer Sandbox Reference`。本文档主要解释
`deploy/` 脚本、桌面打包和固定端口部署细节。AutoResearch / AutoResearch 于 `2026-06-23` 加入当前代码库。

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
2. 自动启动嵌入式 Redis（随机端口；Linux/macOS 使用 Redis + AOF，Windows 使用 Garnet）
3. 自动启动 Python sidecar，注入 `DATABASE_URL` 和 `REDIS_URL`
4. 应用退出时自动停止上述服务

数据目录（跨版本持久）：
- PostgreSQL：`{userData}/postgres-data/`
- Redis AOF：`{userData}/redis-data/`

---

## 二、固定端口 Web 部署

### 新服务器环境清单

部署固定端口 Web 服务前，先准备：

- Linux 基础工具：`git`、`curl`、`bash`、编译工具和 `pkg-config`。
- Python：Python 3.12、`python3-venv`、`python3-pip`、`uv`。
- Node：Node.js 18+ 和 `npm`。
- 服务：PostgreSQL 和 Redis。
- WSI 运行库：OpenSlide、OpenGL/GLib 运行库。
- GPU：与目标 Torch wheel 匹配的 NVIDIA driver/CUDA stack。
- AutoResearch sandbox：Apptainer，以及由 `deploy/build-autoresearch-sandbox.sh` 构建的 `.sif`。
- PathLab Settings：Web AutoResearch 继承 PathLab 的 LLM 和 Hugging Face 设置，不需要单独配置 `AUTORESEARCH_LLM_*`。

推荐的 AutoResearch Python 安装层：

```bash
cd pathlab/pathlab-client/server/backend/autoresearch
uv venv .venv --python 3.12
uv pip install -r ../../requirements.txt
uv pip install -r ../../requirements-test.txt
uv pip install -r requirements.txt  # server/backend/autoresearch/requirements.txt
```

构建 sandbox：

```bash
cd pathlab/pathlab-client
./deploy/build-autoresearch-sandbox.sh
```

如果 `/tmp` 空间不足：

```bash
APPTAINER_TMPDIR=/home/<service-user>/.apptainer-tmp ./deploy/build-autoresearch-sandbox.sh
```

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

这与 `PATHLAB_DEBUG=1` 下的 sidecar 端口保持一致，便于浏览器调试与反向代理复用。AutoResearch 不占用额外 HTTP 端口；AutoResearch 会话 API 由 Gateway 在 `/autoresearch` 与 `/api/autoresearch` 下提供。

### GPU 控制（CUDA_VISIBLE_DEVICES）

若机器上某几块 GPU 存在硬件故障，可在 `server/.env` 中设置 `CUDA_VISIBLE_DEVICES` 来全局排除坏卡。此设置会同时影响 `start.sh`、`hot-reload.sh` 和 `systemd` 三条部署链路下的所有训练和推理任务。

**配置方式：**

```bash
# 在 server/.env 中加一行（排除物理 GPU 2，只使用 GPU 0、1、3）
CUDA_VISIBLE_DEVICES=0,1,3
```

**生效范围：**

| 入口 | 生效机制 |
|---|---|
| `start.sh` | 已 `source server/.env`，直接继承 |
| `hot-reload.sh` | 已 `source server/.env`，直接继承 |
| `systemd/pathlab.service` | `EnvironmentFile=server/.env` 加载 |

**启动日志中的验证输出：**

```
  [GPU] CUDA_VISIBLE_DEVICES=0,1,3
  [GPU] 系统物理 GPU 索引: 0 1 2 3
  [GPU][✓] 配置有效
```

`server/main.py` 中的自动坏卡探测（`_detect_and_exclude_bad_gpus`）会尊重此配置：若检测到 `CUDA_VISIBLE_DEVICES` 已设，直接跳过自动排除逻辑，以运维配置为准。

### `start.sh` 当前行为

`./deploy/start.sh` 当前会先解析 Python 解释器，优先级为：

1. `PATHLAB_PYTHON` 显式指定的可执行文件或命令
2. `server/backend/autoresearch/.venv/bin/python`
3. `pathlab-client/venv/bin/python3`
4. 当前 `CONDA_PREFIX/bin/python3`
5. 系统 `python3`

这个顺序刻意把 AutoResearch venv 放在 Conda 前面，避免普通 Conda
环境缺少 OpenHands/FastAPI/AutoResearch 依赖时误启动失败。需要强制使用
其他环境时，设置 `PATHLAB_PYTHON=/path/to/python ./deploy/start.sh`。

`./deploy/start.sh` 当前会依次执行：

1. 检查 AutoResearch Python 包：`openhands.sdk`、`torch`、`kaggle`
2. 检查 `AUTORESEARCH_SANDBOX`、Apptainer 和 `AUTORESEARCH_SANDBOX_IMAGE` 指向的 sandbox image
3. 清理占用 `6100 / 6101 / 6102` 的旧进程
4. 按进程模式补充清理旧的 `server/main.py` / uvicorn / vLLM 相关残留进程
5. 检查并尽量启动 Redis
6. 如缺少 `node_modules/`，执行一次 `npm install --silent`
7. 用 Vite 构建前端到 `src/renderer/dist`
8. 导出 `PATHLAB_DEBUG=1` 与固定端口环境变量
9. 以 `nohup` 方式启动 `server/main.py`
10. 同时通过 `http://127.0.0.1:6100/health`、`6101/health`、`6102/health` 做三服务健康检查；TaskWorker 是无 HTTP 端口后台进程，通过 Redis 队列状态间接观察
11. 将日志写入 `logs/backend.log`，并记录 `logs/backend.pid`

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

- `backend` / `gateway` / `preprocessing` / `ai` 使用与 `start.sh` 相同的 Python 选择优先级，支持 `PATHLAB_PYTHON` 覆盖
- `frontend` 会先构建到临时目录，补拷 `public/assets` / `public/images`，再原子替换 `dist/`
- `frontend` 在 `node_modules/` 缺失或 `vite` 可执行文件不完整时，会先执行一次 `npm install --silent`
- `backend` 会按 `AI → Preprocessing → Gateway` 顺序滚动重启
- `preprocessing` 会读取 `PREPROCESSING_WORKERS` 与 `PREPROCESSING_MAX_REQUESTS`

### Nginx 配置现状

`nginx/pathlab.conf` 与 `nginx/pathlab-http-only.conf` 当前大致遵循：

- `/` → `src/renderer/dist`
- `/api/` → `http://127.0.0.1:6100/`
- `/autoresearch` 与 `/api/autoresearch/` → Gateway `6100`，由同一前端构建和 Gateway router 服务
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
- `DATABASE_URL`

默认模板不再覆盖 `PATHLAB_UPLOADS_DIR`，因此服务会沿用 `storage.json` 中保存的上传目录。
如果部署机需要固定外置存储路径，请在 systemd 覆盖文件或 `server/.env` 中显式设置 `PATHLAB_UPLOADS_DIR`。

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
- 上传目录：优先由 `PATHLAB_UPLOADS_DIR` 指定；未设置时沿用 `storage.json`，再回退到系统 app data 目录
- AutoResearch / AutoResearch workspace：默认位于上传目录下的 `autoresearch/`，可通过 `AUTORESEARCH_BASE_DIR` 覆盖；完整说明见 `server/backend/autoresearch/README.md`

### 相关文档

- [Project README](../../../README.md)
- [Server README](../server/README.md)
- [AutoResearch README](../server/backend/autoresearch/README.md)
- [Frontend README](../src/renderer/README.md)
