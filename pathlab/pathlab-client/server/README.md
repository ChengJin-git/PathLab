# PathLab Python Backend

PathLab 的 Python 后端服务，提供 WSI 处理、AI 推理和 API 网关功能。

## 🚀 运行模式

| 模式 | 端口策略 | 启动方式 | 说明 |
|------|---------|---------|------|
| **网页端** (调试模式) | 固定端口 | `python main.py` 或 `npm run dev` | Gateway: 6100, Preprocessing: 6101, AI: 6102 |
| **本地端** (打包模式) | 动态端口 | Electron 启动 | 自动寻找可用端口，通过 `PORT=xxxxx` 通知 Electron |

## 核心特性

- **零配置**: PostgreSQL 数据库 (18 表)，asyncpg 异步驱动
- **Redis 缓存**: 训练日志 (Streams)、任务进度 (KV)、分析状态 (Hash)，异步非阻塞
- **动态端口**: 自动寻找可用端口，避免端口冲突
- **单进程架构**: 统一入口 `main.py`，简化部署
- **特征缓存**: 全局特征缓存，跨任务复用

## 架构概览

```
server/
├── main.py               # 统一入口 (动态端口发现)
├── requirements.txt      # Python 依赖
├── gateway/              # API 网关服务 (对外唯一入口)
│   ├── main.py           # Gateway FastAPI 应用
│   ├── task_queue.py     # GPU 任务队列管理器
│   ├── models.py         # Pydantic 请求/响应模型
│   ├── routes/           # 模块化路由 (30 个模块)
│   │   ├── auth.py           # 认证 (FastAPI-Users)
│   │   ├── wsi.py            # WSI CRUD + 数据集
│   │   ├── wsi_upload.py     # WSI 上传 (文件/路径/CSV)
│   │   ├── ai_tasks.py       # AI 推理任务 + 提取器列表
│   │   ├── training.py       # 训练任务 (SSE 日志流)
    │   │   ├── results.py        # 结果查询 + 外部验证 + 分割分析
│   │   ├── models.py         # 模型管理
│   │   ├── chat.py           # AI Chat (SSE 流式)
│   │   ├── chat_pdf.py       # PDF 文档对话 (RAG)
│   │   ├── chat_pdf_vectorstore.py # PDF 向量存储管理
│   │   ├── queue.py          # GPU 队列管理
│   │   ├── storage.py        # 存储管理 + 迁移
│   │   ├── heatmap.py        # 热图数据 + Patch 图像
│   │   ├── asr.py            # 语音识别 (DashScope)
│   │   ├── stats.py          # 系统统计
│   │   ├── settings.py       # 全局设置
    │   │   ├── annotation.py     # 标注管理
│   └── dependencies.py   # 依赖注入
│
└── backend/              # 核心后端服务
    ├── ai/               # AI 服务 (内部端口)
    │   ├── main.py           # AI FastAPI 应用
    │   ├── routes/           # 训练/推理路由
    │   ├── tasks/            # 任务类型
    │   │   ├── wsi_classification/   # WSI 分类 (MIL)
    │   │   ├── patch_classification/ # Patch 分类
    │   │   ├── patch_segmentation/  # Patch 分割
    │   │   └── wsi_survival/        # 生存分析
    │   ├── extractors/       # 19 种特征提取器
    │   │   ├── aggregators/      # 8 种聚合器 (ABMIL, MeanMIL, MaxMIL, DSMIL, DTFDMIL, CLAM-SB, CLAM-MB, TransMIL)
    │   ├── classifiers/      # 分类器
    ├── preprocessing/    # 预处理服务 (内部端口)
    │   ├── main.py           # 预处理 FastAPI 应用
    │   └── tiling.py         # WSI 切片、坐标提取
    ├── database/         # PostgreSQL ORM
    │   ├── database.py       # 异步连接管理 (asyncpg)
    │   ├── models.py         # 数据模型 (18 个表)
    │   └── repositories/     # 数据访问层 (Repository 模式，模块化目录)
    ├── storage/          # 文件存储管理
    │   └── manager.py        # 存储管理器 (级联删除)
    └── common/           # 公共模块
        ├── redis_client.py   # Redis 异步连接池
        ├── progress_store.py # 任务进度存储 (Redis)
        ├── port_utils.py     # 端口发现工具
        ├── auth.py           # 认证工具
        ├── config.py         # 配置管理
        └── logger.py         # 日志工具
```

## 数据库模型 (18 个表)

| 表名 | 用途 |
|------|------|
| `users` | 用户账户（FastAPI-Users，含角色 RBAC）|
| `accesstoken` | 访问令牌（FastAPI-Users）|
| `data_groups` | 数据组定义（数据类型、聚合级别、任务类型组合）|
| `datasets` | 数据集元信息 (UUID 隐私保护) |
| `dataset_permissions` | 数据集临时提权（GPU 操作）|
| `wsi_slides` | WSI 切片元数据（含患者信息、标签、生存分析字段） |
| `ai_tasks` | AI 推理任务记录 |
| `ai_results` | AI 分析结果 |
| `chat_conversations` | 聊天会话 |
| `chat_messages` | 聊天消息历史 |
| `message_feedbacks` | 消息反馈（点赞/点踩/任务有用性）|
| `export_tasks` | 数据导出任务追踪 |
| `training_tasks` | 训练任务配置和状态 (classification/survival) |
| `training_task_wsi` | 训练任务与 WSI 多对多关联 |
| `trained_models` | 训练生成的模型信息 |
| `training_logs` | 训练日志（运行时通过 Redis Streams 读写，SSE 流式） |
| `storage_tasks` | 存储操作任务追踪（批量导入/删除）|
| `annotation_drafts` | 标注草稿 |

## GPU 任务队列

支持 GPU 任务的并发控制和故障恢复：

- **最大并发控制**: 默认 1 个 GPU 任务同时运行
- **FIFO 调度**: 先进先出任务调度
- **断电恢复**: 服务重启后自动恢复未完成任务
- **统一管理**: 同时支持训练任务 (TrainingTask) 和推理任务 (AITask)
- **实时状态**: SSE 流式推送任务状态更新

## 开发运行

```bash
# 方式一：直接运行 (推荐)
cd server && python main.py

# 输出示例:
# PORT=48427              ← Electron 通过此解析端口
# [Gateway] Starting on port 48427
# [Services] Gateway: 48427, Preprocessing: 47001, AI: 53633
# [Database] Using PostgreSQL: postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab

# 方式二：Electron 开发模式自动启动
npm run dev  # 在父目录执行
```

**注意**: 需确保 PostgreSQL 和 Redis 服务已运行，PostgreSQL 默认连接 `postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab`，Redis 默认连接 `redis://localhost:6379/0`。

## 数据库配置

通过 `DATABASE_URL` 环境变量配置：

```bash
# 默认 (本地开发)
DATABASE_URL=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab
```

## 动态端口发现

Python 后端启动时自动寻找可用端口：

```python
# backend/common/port_utils.py
def find_free_port() -> int:
    """查找可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def announce_port(port: int):
    """通知 Electron 端口号"""
    print(f"PORT={port}", flush=True)
```

Electron 主进程解析 `PORT=xxxxx` 输出配置 API 地址。

## 打包

```bash
../build-python.sh
```

生成独立可执行文件到 `dist/` 目录。

## API 文档

启动服务后访问（端口动态分配）：

```bash
python main.py
# PORT=48427
# 访问: http://127.0.0.1:48427/docs
```

## 相关文档

- [Gateway 服务](gateway/README.md)
- [Backend 服务](backend/README.md)
- [数据库层](backend/database/README.md)
- [存储管理](backend/storage/README.md)
