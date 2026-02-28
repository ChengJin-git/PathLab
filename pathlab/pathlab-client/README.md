# PathLab Client

数字病理学研究平台，基于 Electron + Python 双进程架构，实现"数据不动，模型动"的隐私计算理念。

## 🚀 运行模式

PathLab 采用统一代码库，支持两种运行模式：

| 模式 | 启动方式 | 适用场景 | 说明 |
|------|---------|---------|------|
| **网页端** (调试模式) | `npm run dev` | 开发调试 | Vite 热更新，浏览器访问，固定端口 (5100, 5101, 5102) |
| **本地端** (打包模式) | `npm run build:linux/win/mac` | 生产部署 | Electron 桌面应用，动态端口发现，离线可用 |

## 功能特性

- **WSI 阅片器**: 基于 OpenSeadragon 的多层级全切片图像可视化
- **AI Chat 智能助手**: 流式 LLM 对话 (OpenRouter API)，支持会话持久化
- **训练系统**: 19 种特征提取器 + 8 种 MIL 聚合器，全局特征缓存复用
- **任务类型**: WSI 分类、Patch 分类、Patch 分割、生存预测 (Survival Prediction)
- **推理分析**: WSI 分类预测、注意力热图可视化、Patch CAM 可视化、分割分析
- **模型管理**: 训练模型保存、加载、默认模型切换、激活/停用
- **外部验证**: 支持使用训练好的模型对新数据集进行外部验证
- **存储管理**: 文件生命周期管理、级联删除、孤立文件检测、存储迁移
- **GPU 任务队列**: 并发控制、断电恢复、任务状态实时更新 (SSE)
- **语音识别**: 集成 DashScope Qwen3-ASR 语音转文字
- **本地认证**: FastAPI-Users + JWT，客户端 SHA256 密码哈希
- **零配置**: PostgreSQL 数据库 (18 个表)、动态端口发现，开箱即用

## 技术架构

```
pathlab-client/
├── src/                      # Electron 前端
│   ├── main/                 # 主进程 (窗口管理、Sidecar 管理)
│   │   ├── index.ts          # 入口点
│   │   └── sidecar-manager.ts # Python 进程管理 + 端口发现
│   ├── preload/              # Preload 脚本
│   │   └── index.ts          # Backend API 暴露
│   └── renderer/             # 渲染进程 (React + TypeScript)
│       └── src/
│           ├── api.ts            # 统一 API 客户端 (2000+ 行)
│           ├── components/       # 可复用组件
│           │   ├── Layout.tsx        # 主布局 + 侧边栏
│           │   ├── WSIViewer.tsx     # OpenSeadragon 封装
│           │   └── HeatmapOverlay.tsx # 注意力热图叠加层
│           ├── pages/            # 页面组件 (14 页)
│           └── contexts/         # React Context
│               ├── AuthContext.tsx       # 认证状态
│               └── BackgroundTaskContext.tsx  # 后台任务追踪
│
└── server/                   # Python 后端 (单进程统一服务)
    ├── main.py               # 统一入口 (自动端口发现)
    ├── gateway/              # API 网关 (动态端口，对外唯一入口)
    │   ├── main.py           # Gateway FastAPI 应用
    │   ├── task_queue.py     # GPU 任务队列管理器
    │   ├── models.py         # Pydantic 请求/响应模型
    │   │   ├── routes/           # 模块化路由 (30 个模块)
    │   │   ├── auth.py           # 认证 (FastAPI-Users)
    │   │   ├── wsi.py            # WSI CRUD + 数据集管理
    │   │   ├── wsi_upload.py     # WSI 上传 (文件/路径/CSV)
    │   │   ├── chat.py           # AI Chat (SSE 流式)
    │   │   ├── training.py       # 训练任务 (SSE 日志)
    │   │   ├── ai_tasks.py       # AI 推理任务
    │   │   │   ├── results.py        # 结果查询 + 外部验证 + 分割分析
    │   │   ├── models.py         # 模型管理
    │   │   ├── queue.py          # GPU 队列管理
    │   │   ├── storage.py        # 存储管理 + 迁移
    │   │   ├── heatmap.py        # 热图数据 + 图像
    │   │   ├── asr.py            # 语音识别 (DashScope)
    │   │   ├── stats.py          # 系统统计
    │   │   ├── settings.py       # 全局设置
    │   │   │   ├── annotation.py     # 标注管理
    │   │   │   └── gpu.py            # GPU 信息
    └── backend/              # 核心服务
        ├── ai/               # AI 服务 (内部端口)
        ├── tasks/            # 任务类型
        │   │   ├── wsi_classification/   # WSI 分类 (MIL)
        │   │   ├── patch_classification/ # Patch 分类
        │   │   ├── patch_segmentation/  # Patch 分割
        │   │   │   └── wsi_survival/        # 生存分析
        ├── extractors/       # 19 种特征提取器
        │   │   ├── wsi_classification/   # WSI 分类 (MIL)
        │   │   └── patch_classification/ # Patch 分类
        │   ├── extractors/       # 19 种特征提取器
        │   ├── aggregators/      # 8 种聚合器 (ABMIL, MeanMIL, MaxMIL, DSMIL, DTFDMIL, CLAM, TransMIL)
        │   └── utils/            # CAM 工具 (Grad-CAM, Attention)
        ├── preprocessing/    # 预处理服务 (内部端口)
        │   ├── main.py           # 预处理 FastAPI 应用
        │   └── tiling.py         # WSI 切片 + 坐标提取
        ├── database/         # PostgreSQL ORM
        │   ├── database.py       # 异步 PostgreSQL 连接 (asyncpg)
        │   ├── models.py         # 数据模型 (18 个表)
        │   └── repositories/     # 数据访问层 (Repository 模式，模块化目录)
        ├── storage/          # 文件存储管理
        │   └── manager.py        # 存储管理器 (级联删除)
        └── common/           # 公共模块
            ├── redis_client.py   # Redis 异步连接池
            ├── progress_store.py # 任务进度存储 (Redis)
            ├── port_utils.py     # 端口发现工具
            ├── config.py         # 配置管理
            └── auth.py           # 认证模块
```

## 快速开始

### 1. 安装依赖

```bash
# 安装 Node 依赖
npm install

# 安装 Python 依赖
pip install -r server/requirements.txt
```

### 2. 开发模式运行

```bash
# 方式一：同时启动 Electron + Python 服务 (推荐)
npm run dev

# 方式二：单独启动 Python 后端 (调试用)
cd server && python main.py
# 输出: PORT=xxxxx  ← Electron 通过此解析端口
```

**注意**: 需确保 PostgreSQL 和 Redis 服务已运行：
- PostgreSQL 默认连接：`postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab`
- Redis 默认连接：`redis://localhost:6379/0`
- 可通过 `DATABASE_URL` 环境变量配置 PostgreSQL

## 服务架构

| 组件 | 端口 | 说明 |
|------|------|------|
| **Gateway** | 动态 | API 网关、业务编排、Chat、WSI/训练/结果管理 |
| **Preprocessing** | 内部 | WSI 切片、DZI 生成、组织掩膜、坐标提取 |
**AI** | 内部 | 特征提取 (19种)、模型训练、推理分析、热图生成、分割分析 |
**PostgreSQL** | - | PostgreSQL 数据库（18 表，asyncpg 异步驱动） |
| **Redis** | 6379 | 缓存层（训练日志 Streams、任务进度 KV、分析状态 Hash） |

### 数据库表 (18 个)

| 表名 | 用途 |
|------|------|
| `users` | 用户账户（FastAPI-Users，含角色 RBAC）|
| `accesstoken` | 访问令牌（FastAPI-Users）|
| `data_groups` | 数据组定义（数据类型、聚合级别、任务类型组合）|
| `datasets` | 数据集元信息 (UUID 隐私保护) |
| `dataset_permissions` | 数据集临时提权（GPU 操作）|
| `wsi_slides` | WSI 切片元数据 (含患者信息、生存分析字段) |
| `ai_tasks` | AI 推理任务记录 |
| `ai_results` | AI 分析结果 |
| `chat_conversations` | 聊天会话 |
| `chat_messages` | 聊天消息历史 |
| `message_feedbacks` | 消息反馈（点赞/点踩/任务有用性）|
| `export_tasks` | 数据导出任务追踪 |
| `training_tasks` | 训练任务配置和状态 (分类/生存) |
| `training_task_wsi` | 训练任务与 WSI 多对多关联 |
| `trained_models` | 训练生成的模型信息 |
| `training_logs` | 训练日志（运行时通过 Redis Streams 读写，SSE 流式） |
| `storage_tasks` | 存储操作任务追踪（批量导入/删除）|
| `annotation_drafts` | 标注草稿 |

### 特征提取器 (19 种)

| 模型 | ID | 维度 | 来源 |
|------|-----|------|------|
| ResNet50 | resnet50 | 2048 | ImageNet |
| ViT-Large | vit_l_16 | 1024 | ImageNet |
| CONCH | conch | 512 | Mahmood Lab |
| CONCH 1.5 | conch15 | 512 | Mahmood Lab |
| UNI | uni | 1024 | Mahmood Lab |
| UNI2 | uni2 | 1536 | Mahmood Lab |
| Virchow | virchow | 1280 | Paige AI |
| Virchow2 | virchow2 | 1280 | Paige AI |
| H-Optimus-0 | H-Optimus-0 | 1536 | Bioptimus |
| H-Optimus-1 | H-Optimus-1 | 1536 | Bioptimus |
| Phikon | phikon | 768 | Owkin |
| Phikon2 | phikon2 | 1024 | Owkin |
| PLIP | plip | 512 | James Zou Lab |
| PathoCLIP | patho_clip | 512 | Hong Bu Lab |
| OpenMidnight | openmidnight | 1536 | SophontAI |
| mSTAR | mSTAR | 1024 | Smartlab |
| GPFM | GPFM | 1024 | Smartlab |
| SmartCCS | smartccs | 1024 | Smartlab |
| SmartCyto | smartcyto | 768 | Smartlab |

### Gateway 路由模块 (30 个)

| 模块 | 路由前缀 | 功能 |
|------|---------|------|
| auth | `/auth` | 用户认证 (FastAPI-Users + JWT) |
| wsi | `/wsi` | WSI CRUD、数据集管理 |
| wsi_upload | `/wsi/upload` | 文件/路径/CSV 批量上传 |
| wsi_permissions | `/wsi/permissions` | WSI 权限管理 |
| training | `/training` | 训练任务 CRUD、SSE 日志流 |
| ai_tasks | `/tasks` | AI 推理任务、提取器列表 |
| results | `/results` | 结果查询、外部验证 |
| models | `/models` | 训练模型管理 |
| chat | `/chat`, `/conversations` | AI 对话、会话管理 |
| chat_pdf | `/chat/pdf` | PDF 文档对话 (RAG) |
| chat_pdf_vectorstore | `/chat/pdf/vectorstore` | PDF 向量存储管理 |
| chat_feedback | `/feedback` | 消息反馈管理 |
| queue | `/queue` | GPU 队列状态、配置 |
| storage | `/storage` | 存储统计、迁移、清理 |
| storage_tasks | `/storage/tasks` | 存储任务管理 |
| storage_scan | `/storage/scan` | 存储扫描 |
| heatmap | `/heatmap` | 热图数据、Patch 图像 |
| asr | `/asr` | 语音转文字 (DashScope Qwen3-ASR) |
| stats | `/stats` | 系统统计 |
| settings | `/settings` | 全局设置 |
| gpu | `/gpu` | GPU 信息和状态 |
| classification_analysis | `/analysis/classification` | 分类分析 |
| survival_analysis | `/analysis/survival` | 生存分析 |
| external_validation_analysis | `/analysis/external-validation` | 外部验证分析 |
| analysis_metrics | `/analysis/metrics` | 分析指标 |
| analysis_state | `/analysis/state` | 分析状态 |
| analysis_helpers | (内部) | 分析辅助函数 |
| annotation | `/annotation` | 标注管理 |
| segmentation_analysis | `/analysis/segmentation` | 分割分析 |

### 动态端口发现

Python 后端启动时自动寻找可用端口，并通过标准输出通知 Electron：

```
PORT=48427
[Gateway] Starting on port 48427
```

Electron 主进程解析此输出并配置前端 API 地址。

## 打包发布

### 1. 打包 Python Sidecar

```bash
pip install pyinstaller
./build-python.sh
```

### 2. 打包 Electron 应用

```bash
npm run build:linux   # Linux (AppImage, deb)
npm run build:win     # Windows (nsis installer)
npm run build:mac     # macOS (dmg)
```

输出文件在 `dist/` 目录。

## API 文档

启动服务后访问交互式文档（端口动态分配）：

```bash
# 查看实际端口
cd server && python main.py
# PORT=48427

# 访问文档
open http://127.0.0.1:48427/docs
```

## 相关文档

- [Python Backend 文档](server/README.md)
- [Gateway 服务文档](server/gateway/README.md)
- [Backend 服务文档](server/backend/README.md)
- [数据库文档](server/backend/database/README.md)
- [存储管理文档](server/backend/storage/README.md)
- [前端文档](src/renderer/src/README.md)
