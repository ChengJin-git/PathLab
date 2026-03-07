# PathLab Python Backend

`server/` 是当前 Python sidecar 目录。它不是单一 FastAPI 应用，而是由 `main.py` 统一拉起 **Gateway / Preprocessing / AI** 三个服务进程。

## 当前启动方式

| 模式 | 端口策略 | 启动方式 | 说明 |
|------|---------|---------|------|
| 固定端口调试 | `5100 / 5101 / 5102` | `PATHLAB_DEBUG=1 python main.py` | 便于本地联调与前后端分离开发 |
| Electron sidecar | 动态端口 | Electron 主进程启动 | 自动寻找可用端口，并把 Gateway 端口通知给渲染层 |
| Web / 运维部署 | `6100 / 6101 / 6102` | `deploy/start.sh` 或 systemd | 部署脚本通过环境变量把 sidecar 切到固定端口 |

## 统一入口

- 文件：`server/main.py`
- 作用：
  - 在 debug / dynamic 两种模式间选择端口策略
  - 设置 `GATEWAY_PORT`、`PREPROCESSING_PORT`、`AI_PORT` 以及内部服务 URL
  - 启动 3 个 uvicorn 子进程
  - 通过标准输出宣布 Gateway 端口，供 Electron 读取
  - 在退出时统一清理子进程

## 当前目录结构

```text
server/
├── main.py                 # 统一入口，负责拉起 3 个服务
├── pyproject.toml          # 当前 Python 依赖声明（uv）
├── requirements.txt        # 兼容型依赖清单
├── uv.lock                 # uv 锁文件
├── main.spec               # PyInstaller 配置
├── gateway/                # 对外 API 网关
├── backend/
│   ├── ai/                 # AI 服务与任务实现
│   ├── auth/               # 认证模型与 FastAPI-Users 配置
│   ├── common/             # 配置、Redis、端口发现、通用工具
│   ├── database/           # SQLAlchemy 模型与仓储层
│   ├── deep-research/      # Deep Research vendored snapshot
│   ├── preprocessing/      # WSI 预处理与瓦片服务
│   └── storage/            # 存储统计、迁移、清理
├── build/                  # 打包产物目录
└── dist/                   # 打包产物目录
```

## 三个服务的职责

| 服务 | 当前职责 |
|------|----------|
| Gateway | 认证、用户管理、WSI / 任务 / 结果 / 聊天 / Deep Research / 存储 / 设置等对外 API |
| Preprocessing | WSI 信息、缩略图、DZI、tile、patch 计算、热图与 ROI 提取等底层接口 |
| AI | 训练、推理、特征提取与模型内部接口 |

## 运行依赖

- PostgreSQL：元数据与业务状态
- Redis：训练日志、任务进度、队列 / SSE / 部分缓存状态
- `uploads/`：WSI、特征缓存、模型、日志、标注及衍生文件

默认配置在 `backend/common/config.py` 中：

- `DATABASE_URL_DEFAULT=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab`
- `REDIS_URL_DEFAULT=redis://localhost:6379/0`
- 默认 `uploads` 根目录为 `pathlab-client/uploads`，也可由 `PATHLAB_UPLOADS_DIR` 或持久化配置覆盖

## 当前实现重点

- Gateway 启动时会初始化数据库、任务队列，并等待 AI / Preprocessing 服务 ready
- Preprocessing 挂载了独立 `heatmap_routes.py`
- AI 服务将训练与推理路由统一挂载在 `/api/ai`
- `main.spec` 用于将 sidecar 打包为独立可执行文件

## 相关文档

- [Gateway README](gateway/README.md)
- [Backend Services README](backend/README.md)
- [Database README](backend/database/README.md)
- [Storage README](backend/storage/README.md)