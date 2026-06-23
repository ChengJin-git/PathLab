# PathLab Backend Services

> 适用版本：`PathLab v1.0.5`

`server/backend/` 存放 Gateway 共享的核心后端模块、两个内部 FastAPI 服务（Preprocessing / AI）的具体实现，以及 AutoResearch（实现 codename：PathScientist）的后端运行时。PathScientist 于 `2026-06-23` 加入当前代码库。

## 当前模块划分

```text
backend/
├── ai/               # 训练、推理、模型相关服务
├── auth/             # 用户模型、JWT/FastAPI-Users 配置
├── common/           # 配置、Redis、端口与通用工具
├── database/         # SQLAlchemy 模型、Session、Repository
├── annotation/       # 协作标注 pubsub、presence、COCO/summary 辅助
├── pathscientist/    # AutoResearch runtime、实验编排、持久化、sandbox 与技能模板
├── preprocessing/    # WSI 信息 / 图像 / DZI / Tile / Heatmap 服务
└── storage/          # 存储统计、迁移、孤立文件处理
```

## Preprocessing 服务现状

入口文件：`backend/preprocessing/main.py`

当前代码可以确认它承担的主要职责包括：

- WSI 健康检查与基础信息读取
- WSI 原图 / 缩略图 / DZI / Tile 提供
- `heatmap_routes.py` 中的热图相关辅助接口
- 热图预览缓存与相关工具函数
- 标注 ROI 提取，以及为数据集生成 COCO 标注缓存时在 `uploads/annotations/` 下写入 `*_coco.json`

它本质上是底层图像与预处理服务，不直接承担用户认证与业务权限逻辑。

## AI 服务现状

入口文件：`backend/ai/main.py`

当前由两个子 router 组成：

- `routes/training.py`
- `routes/inference.py`

当前职责可概括为：

- 训练任务启动、状态追踪、结果读取
- 推理与分析相关内部能力
- 模型、特征提取器、聚合器 / 分类器注册与训练流水线复用逻辑

## Annotation 辅助模块现状

`backend/annotation/` 当前提供：

- `coco_utils.py`：COCO 标注导出辅助
- `summary_cache.py`：数据集标注摘要缓存
- `pubsub.py` / `presence_pubsub.py`：协作标注事件与在线状态广播

它本身不是独立服务，而是由 Gateway 标注路由与 Preprocessing 的 ROI / COCO 相关流程复用。

## PathScientist / AutoResearch 现状

入口目录：`backend/pathscientist/`

PathScientist 是 AutoResearch 的实现 codename。它不是独立 HTTP 服务，而是由 Gateway 的 `pathscientist_router` 调用后端 package 来创建、恢复、停止和导出自动研究会话。

当前目录承担的主要职责包括：

- CLI/headless runtime 与 OpenHands/PathScientist 会话编排
- 基于 PathLab dataset 的数据集获取、workspace 准备与 artifact 归档
- 文献检索、RAG、domain skills/templates、实验综合报告与 know-how 记录
- session/run 生命周期、事件投影、resume metadata 与 DB best-effort persistence
- Apptainer / sandbox runtime recipes 与部署 quickstart 文档

完整架构、运行命令、部署 quickstart 与 Apptainer sandbox 说明见 [PathScientist README](pathscientist/README.md)。

## Shared Infrastructure

### 认证

- 用户模型在 `auth/models.py`
- FastAPI Users 配置在 `auth/users.py`
- 当前会话控制依赖 JWT 与用户 `session_nonces`；旧 `session_nonce` 字段仅为 schema 兼容保留

### 数据库

- ORM 模型：`database/models.py`
- 仓储导出：`database/repositories/__init__.py`
- 初始化：`database/init_db.py`
- 当前 ORM 表以 `database/models.py` 与 `auth/models.py` 的 `__tablename__` 声明为准，权限相关模型统一为 `dataset_grants` 与 `permission_audit_logs`；AutoResearch 历史索引使用 `auto_research_sessions`、`auto_research_experiments`、`auto_research_events` 与 `knowhow_entries`

### Redis / 配置

- 统一配置：`common/config.py`
- Redis 客户端 / 连接管理位于 `common/` 下
- 端口与服务发现工具：`common/port_utils.py` 等
- GPU / slide / split 等通用辅助位于 `common/gpu_utils.py`、`slide_utils.py`、`split_generation.py`
- 持久化全局设置当前覆盖 `openrouter`、`huggingface`、`dashscope`、`exa`、`local_vllm`、`local_asr`、`turnstile`、`admin_notify_email`、`email_templates` 等键
- 存储根目录解析由 `Config.get_uploads_dir()` 负责，优先级为 `PATHLAB_UPLOADS_DIR`、`storage.json`、系统 app data 目录

### 存储

- 统一入口：`storage/manager.py`
- 统计：`storage/stats_mixin.py`
- 孤立文件 / 记录检测：`storage/orphan_mixin.py`
- 迁移：`storage/migration.py`

## 当前代码状态提示

- 旧文档中的 `annotation_drafts` 已不再对应当前表名；当前模型为 `segmentation_annotations`
- 旧文档中的单体 API / 单体服务表述已经过时，当前实现明确拆成 Gateway / Preprocessing / AI 三层
- `backend/common/config.py` 会确保 `avatars`、`coordinates`、`masks`、`features`、`ai_results_bundles`、`training`、`models`、`extractor_checkpoints`、`logs`、`wsi_files`、`metadata`、`progress` 等目录存在
- `backend/annotation/` 当前已成为标注协作与 COCO/summary 辅助逻辑的独立共享模块
- 长任务执行边界当前在 `server/task_worker/`，`backend/ai/` 提供任务实现、模型注册和训练 / 推理内部能力
- AutoResearch/PathScientist 的用户态会话由 Gateway 暴露，后端 package 保留完整 workspace/artifact 于磁盘，同时将 compact 历史与事件投影写入数据库便于列表、恢复和回放

## 相关文档

- [Server README](../README.md)
- [Gateway README](../gateway/README.md)
- [PathScientist README](pathscientist/README.md)
- [Database README](database/README.md)
- [Storage README](storage/README.md)
