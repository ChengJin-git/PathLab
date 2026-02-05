# PathLab Backend Services

后端微服务，提供 WSI 处理和 AI 推理功能。

## 运行模式

| 模式 | 端口策略 | 说明 |
|------|---------|------|
| **网页端** (调试模式) | 固定端口 | Gateway: 6100, Preprocessing: 6101, AI: 6102 |
| **本地端** (打包模式) | 动态端口 | 自动寻找可用端口，避免冲突 |

## 服务架构

```
┌─────────────────────────────────────────────────────────────┐
│                   PathLab Backend                           │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │   Gateway    │  │  Preprocessing   │  │  AI Service  │   │
│  │    :6100     │  │     :6101        │  │    :6102     │   │
│  └──────────────┘  └──────────────────┘  └──────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         SQLite Database (zero-config, 16 tables)     │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         File System Storage (uploads/)               │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 技术栈

- **框架**: FastAPI (Python 3.12)
- **ASGI**: Uvicorn
- **数据库**: SQLite + aiosqlite (异步)
- **ORM**: SQLAlchemy 2.0+
- **WSI 处理**: ASlide, OpenSlide
- **AI 框架**: PyTorch 2.x
- **特征提取**: 17 种预训练模型
- **聚合器**: 8 种 MIL 聚合方法 (ABMIL, MeanMIL, MaxMIL, DSMIL, DTFDMIL, CLAM-SB, CLAM-MB, TransMIL)

---

## Preprocessing Service

**端口**: 6101 (调试模式) / 动态 (打包模式)

### API 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/wsi` | 列出 WSI |
| GET | `/api/wsi/{wsi_id}/dzi` | 获取 DZI 描述符 |
| GET | `/api/wsi/{wsi_id}/tiles/{z}/{x}_{y}.jpeg` | 获取图像瓦片 |
| GET | `/api/wsi/{wsi_id}/mask` | 获取组织掩膜 |
| GET | `/api/wsi/{wsi_id}/coordinates` | 获取组织坐标 |
| GET | `/api/wsi/{wsi_id}/thumbnail` | 获取缩略图 |

### 功能说明

- **WSI 文件处理**: 支持 .svs, .tif, .ndpi 等格式（通过 ASlide/OpenSlide）
- **DZI 生成**: Deep Zoom Image 描述符，支持前端瓦片浏览
- **组织分割**: Otsu 阈值自动检测组织区域
- **坐标提取**: 生成 AI 处理所需的瓦片坐标
- **LRU 缓存**: 滑片对象和 DeepZoom 生成器缓存

---

## AI Service

**端口**: 6102 (调试模式) / 动态 (打包模式)

### API 端点

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查 |
| GET | `/api/ai/gpu` | 获取 GPU 信息 |
| POST | `/api/ai/inference` | 运行推理任务 |
| GET | `/api/ai/inference/{task_id}` | 获取推理状态 |
| POST | `/api/ai/training` | 创建训练任务 |
| GET | `/api/ai/training/{task_id}` | 获取训练状态 |
| GET | `/api/ai/training/{task_id}/logs` | 获取训练日志（SSE） |
| POST | `/api/ai/training/{task_id}/stop` | 停止训练 |

### 支持的特征提取器（17 种）

| 模型 | ID | 输出维度 | 来源 |
|------|-----|---------|------|
| ResNet50 | `resnet50` | 2048 | ImageNet |
| ViT-Large | `vit_l_16` | 1024 | ImageNet |
| CONCH | `conch` | 512 | Mahmood Lab |
| CONCH 1.5 | `conch15` | 512 | Mahmood Lab |
| UNI | `uni` | 1024 | Mahmood Lab |
| UNI2 | `uni2` | 1536 | Mahmood Lab |
| Virchow | `virchow` | 1280 | Paige AI |
| Virchow2 | `virchow2` | 1280 | Paige AI |
| H-Optimus-0 | `H-Optimus-0` | 1536 | Bioptimus |
| H-Optimus-1 | `H-Optimus-1` | 1536 | Bioptimus |
| Phikon | `phikon` | 768 | Owkin |
| Phikon2 | `phikon2` | 1024 | Owkin |
| PLIP | `plip` | 512 | PathLAIA |
| OpenMidnight | `openmidnight` | 1536 | OpenMidnight |
| mSTAR | `mSTAR` | 1024 | Smartlab |
| GPFM | `GPFM` | 1024 | Smartlab |
| Prov-GigaPath | `gigapath` | 1536 | Microsoft |

### 支持的聚合器（8 种）

| 聚合器 | ID | 说明 |
|--------|-----|------|
| ABMIL | `abmil` | Attention-based MIL（推荐） |
| MeanMIL | `meanmil` | 均值池化 |
| MaxMIL | `maxmil` | 最大值池化 |
| DSMIL | `dsmil` | 双流 MIL |
| DTFDMIL | `dtfdmil` | DTF-MIL |
| CLAM-SB | `clam_sb` | CLAM 单分支 |
| CLAM-MB | `clam_mb` | CLAM 多分支 |
| TransMIL | `transmil` | Transformer MIL |

### 任务类型

- **WSI 分类**: 特征提取 → 聚合 → 滑片级预测
- **生存分析**: 特征提取 → 聚合 → 风险评分 + 生存曲线
- **外部验证**: 使用已训练模型对新数据集进行验证

---

## 数据库架构

SQLite 数据库包含 17 个表（零配置，自动创建）：

| 表名 | 用途 |
|------|------|
| `users` | 用户账户（FastAPI-Users） |
| `accesstoken` | 访问令牌（FastAPI-Users）|
| `data_groups` | 数据组定义（数据类型、聚合级别、任务类型组合）|
| `datasets` | 数据集元数据（UUID 隐私保护） |
| `dataset_permissions` | 数据集临时提权（GPU 操作） |
| `wsi_slides` | WSI 元数据（含患者信息、标签、生存数据） |
| `ai_tasks` | AI 推理任务记录 |
| `ai_results` | AI 分析结果 |
| `chat_conversations` | 聊天会话 |
| `chat_messages` | 聊天消息历史 |
| `message_feedbacks` | 消息反馈（点赞/点踩/任务有用性）|
| `export_tasks` | 数据导出任务追踪 |
| `training_tasks` | 训练任务配置（分类/生存） |
| `training_task_wsi` | 训练任务与 WSI 多对多关联 |
| `trained_models` | 模型检查点元数据 |
| `training_logs` | 训练日志条目（SSE 流式） |
| `storage_tasks` | 存储操作任务追踪（批量导入/删除）|

### 数据库路径

```bash
# Linux:   ~/.local/share/PathLab/pathlab.db
# macOS:   ~/Library/Application Support/PathLab/pathlab.db
# Windows: %APPDATA%/PathLab/pathlab.db
```

---

## 文件存储结构

```
uploads/
├── wsi_files/          # WSI 原始文件
│   └── {wsi_id}.svs
├── masks/              # 组织掩膜（也作为缩略图）
│   └── {wsi_id}_mask.png
├── coordinates/        # 瓦片坐标缓存 (H5)
│   └── {wsi_id}_coords.h5
├── features/           # 全局特征缓存（跨任务复用）
│   └── {extractor_name}/
│       └── {params_hash}/
│           └── {wsi_id}.pt
├── training/           # 训练任务数据
│   └── {task_id}/
│       ├── features/   # 特征文件（软链接）
│       └── checkpoints/
├── models/             # 用户训练的模型
│   └── {model_id}/
│       ├── checkpoint.pth
│       └── config.json
└── ai_results/         # AI 推理结果
    └── {wsi_id}/
        └── {task_id}_attention.npy

---

## 启动方式

### 调试模式（网页端）

```bash
cd pathlab/pathlab-client
npm run dev
# 自动启动 Gateway:6100, Preprocessing:6101, AI:6102
# 浏览器访问 http://localhost:5173
```

### 打包模式（本地端）

```bash
cd pathlab/pathlab-client
npm run build:linux  # 或 build:mac, build:win
# 生成 Electron 桌面应用，端口动态分配
```

---

## License

See root repository LICENSE file.
