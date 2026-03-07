# PathLab Backend Services

`server/backend/` 存放 Gateway 共享的核心后端模块，以及两个内部 FastAPI 服务（Preprocessing / AI）的具体实现。

## 当前模块划分

```text
backend/
├── ai/               # 训练、推理、特征提取、模型注册
├── auth/             # 用户模型、JWT / FastAPI-Users 配置
├── common/           # 配置、Redis、端口、缓存与通用工具
├── database/         # SQLAlchemy 模型、Session、Repository
├── deep-research/    # Deep Research vendored snapshot 与 PathLab 适配层
├── preprocessing/    # WSI 信息 / DZI / Tile / Heatmap / ROI 提取服务
└── storage/          # 存储统计、迁移、清理、元数据读写
```

## Preprocessing 服务现状

入口文件：`backend/preprocessing/main.py`

当前主要暴露：

- `/health`
- `/wsi/{wsi_id}/info`
- `/wsi/{wsi_id}/image`
- `/wsi/{wsi_id}/thumbnail`
- `/wsi/{wsi_id}/dzi`
- `/wsi/{wsi_id}/tiles/{level}/{col}_{row}.{format}`
- `/wsi/{wsi_id}/compute_patches`
- `/wsi/{wsi_id}/patches`
- `/wsi/{wsi_id}/mask`
- `/wsi/{wsi_id}/patch_image`
- `/annotation/extract_regions`
- `heatmap_routes.py` 中的热图相关接口（如 `heatmap`、`heatmap_thumbnail`、`available_heatmaps`、`patch_cam`、`seg_mask`）

它更像是底层图像与派生数据服务，不直接承担业务权限和用户会话逻辑。

## AI 服务现状

入口文件：`backend/ai/main.py`

当前由两个 router 组成：

- `routes/training.py`
- `routes/inference.py`

公开路径统一挂在 `/api/ai` 下，当前主要包括：

### 训练相关

- `DELETE /api/ai/training/{task_id}`
- `POST /api/ai/training/{task_id}/revoke-permission`
- `GET /api/ai/training/extractors`
- `POST /api/ai/training/extract_features`
- `POST /api/ai/training/wsi_classification`
- `POST /api/ai/training/wsi_survival`
- `POST /api/ai/training/patch_classification`
- `POST /api/ai/training/patch_segmentation`

### 推理相关

- `POST /api/ai/analyze`
- `POST /api/ai/analyze/sync`
- `POST /api/ai/wsi_classification`

当前 patch classification / patch segmentation 的推理接口仍是预留注释状态，并未正式公开。

## Shared Infrastructure

### 认证

- 用户模型在 `auth/models.py`
- FastAPI-Users 配置在 `auth/users.py`
- 当前会话控制依赖 JWT 与用户 `nonce`

### 数据库

- ORM 模型：`database/models.py`
- 仓储导出：`database/repositories/__init__.py`
- 初始化：`database/init_db.py`
- 当前可见 ORM 表共 **19 个**

### Redis / 配置

- 统一配置：`common/config.py`
- Redis 封装：`common/redis_manager.py`
- 端口与服务发现：`common/port_utils.py`
- 上传根目录、任务超时、维护模式、全局 AI 设置也都在 `common/config.py` 中集中管理

### 存储

- 统一入口：`storage/manager.py`
- 统计：`storage/stats_mixin.py`
- 孤立文件 / 记录检测：`storage/orphan_mixin.py`
- 迁移：`storage/migration.py`

### Deep Research

- vendored snapshot 位于 `deep-research/src/`
- PathLab 适配层位于 `deep-research/src/pathlab/`
- Gateway 通过 `gateway/routes/research_chat.py` 代理 Deep Research HTTP / SSE 能力

## 当前代码状态提示

- 旧文档中的 `annotation_drafts` 已不再对应当前表名；当前模型为 `segmentation_annotations`
- 当前实现已经明确拆成 Gateway / Preprocessing / AI 三层
- 文件系统不只包含 WSI，还管理模型、训练日志、特征、遮罩、坐标、PDF 缓存、研究相关日志等目录

## 相关文档

- [Server README](../README.md)
- [Gateway README](../gateway/README.md)
- [Database README](database/README.md)
- [Storage README](storage/README.md)
- [Deep Research README](deep-research/README.md)