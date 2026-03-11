# PathLab Python Backend

> 适用版本：`PathLab v1.0.0`

`server/` 是当前 Python sidecar 目录。它不是单一 FastAPI 应用，而是由 `main.py` 统一拉起 **Gateway / Preprocessing / AI** 三个服务进程，并复用 `backend/` 下的共享模块。

## 当前启动方式

### 统一入口

- 文件：`server/main.py`
- 作用：
  - 选择固定端口或动态端口
  - 设置服务发现环境变量
  - 启动 3 个 uvicorn 进程
  - 在退出时统一清理子进程

### 两种端口模式

| 模式 | 端口 | 触发方式 |
|------|------|----------|
| 调试 / 固定端口 | Gateway `6100`、Preprocessing `6101`、AI `6102` | `PATHLAB_DEBUG=1` |
| Electron / 动态端口 | 3 个服务自动分配可用端口 | 默认 sidecar 启动方式 |

## 当前目录结构

```text
server/
├── main.py                 # 统一入口，负责拉起 3 个服务
├── requirements.txt        # Python 依赖
├── main.spec               # PyInstaller 配置
├── gateway/                # 对外 API 网关
├── backend/
│   ├── ai/                 # AI 服务与任务实现
│   ├── auth/               # 认证模型与 FastAPI-Users 配置
│   ├── common/             # 配置、Redis、端口发现、通用工具
│   ├── database/           # SQLAlchemy 模型与仓储层
│   ├── deep-research/      # 内部 research/chat 代码树，当前不由 main.py 独立启动
│   ├── preprocessing/      # WSI 图像服务与辅助缓存逻辑
│   └── storage/            # 存储统计、迁移、清理
├── build/                  # 打包产物目录
└── dist/                   # 打包产物目录
```

## 三个服务的职责

| 服务 | 当前职责 |
|------|----------|
| Gateway | 认证、用户管理、WSI / 任务 / 结果 / 聊天 / 存储 / 设置等对外 API |
| Preprocessing | WSI 基本信息、图像、缩略图、DZI、瓦片、热图辅助、ROI 提取与部分 COCO 标注导出逻辑 |
| AI | 训练、推理、特征提取、聚合器 / 分类器注册与模型内部接口 |

## 运行依赖

- PostgreSQL：元数据与业务状态
- Redis：任务队列、日志、进度与部分缓存
- `uploads/`：WSI、特征缓存、模型、日志、标注及衍生文件

默认配置可在 `backend/common/config.py` 中看到，包括：

- `DATABASE_URL_DEFAULT=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab`
- `REDIS_URL_DEFAULT=redis://localhost:6379/0`

## 当前实现重点

- `main.py` 中 Preprocessing 允许多 worker，并支持 `PREPROCESSING_MAX_REQUESTS`
- `main.py` 通过 `multiprocessing.Process` 拉起 3 个 uvicorn 服务并统一清理子进程
- Gateway 会在自身生命周期中初始化数据库、Redis、任务队列和若干启动期清理逻辑
- AI 与 Preprocessing 的内部服务地址通过环境变量注入给 Gateway
- `main.spec` 用于将 sidecar 打包为独立可执行文件
- 代码树中虽然存在 `backend/deep-research/`，但当前 sidecar 默认只启动 Gateway / Preprocessing / AI 三个服务

## 相关文档

- [Gateway README](gateway/README.md)
- [Backend Services README](backend/README.md)
- [Database README](backend/database/README.md)
- [Storage README](backend/storage/README.md)