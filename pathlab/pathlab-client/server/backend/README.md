# PathLab Backend Services

`server/backend/` 存放 Gateway 共享的核心后端模块、两个内部 FastAPI 服务（Preprocessing / AI）的具体实现，以及一个当前未纳入默认 sidecar 启动链的 `deep-research/` 代码树。

## 当前模块划分

```text
backend/
├── ai/               # 训练、推理、模型相关服务
├── auth/             # 用户模型、JWT/FastAPI-Users 配置
├── common/           # 配置、Redis、端口与通用工具
├── database/         # SQLAlchemy 模型、Session、Repository
├── deep-research/    # 内部 research/chat 代码树（非默认启动服务）
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

## `deep-research/` 目录现状

`backend/deep-research/` 当前在仓库中保留了 `src/` 与 `tests/` 代码树，但默认 `server/main.py` 不会把它作为第四个服务拉起，因此这里不再为它单列 README 入口。

## Shared Infrastructure

### 认证

- 用户模型在 `auth/models.py`
- FastAPI Users 配置在 `auth/users.py`
- 当前会话控制依赖 JWT 与用户 `nonce`

### 数据库

- ORM 模型：`database/models.py`
- 仓储导出：`database/repositories/__init__.py`
- 初始化：`database/init_db.py`
- 当前已确认 ORM 表共 17 个

### Redis / 配置

- 统一配置：`common/config.py`
- Redis 客户端 / 连接管理位于 `common/` 下
- 端口与服务发现工具：`common/port_utils.py` 等

### 存储

- 统一入口：`storage/manager.py`
- 统计：`storage/stats_mixin.py`
- 孤立文件 / 记录检测：`storage/orphan_mixin.py`
- 迁移：`storage/migration.py`

## 当前代码状态提示

- 旧文档中的 `annotation_drafts` 已不再对应当前表名；当前模型为 `segmentation_annotations`
- 旧文档中的单体 API / 单体服务表述已经过时，当前实现明确拆成 Gateway / Preprocessing / AI 三层
- `backend/common/config.py` 会确保 `avatars`、`coordinates`、`masks`、`features`、`ai_results`、`training`、`models`、`logs`、`wsi_files`、`metadata`、`progress` 等目录存在
- `deep-research/` 当前是保留在代码树中的内部目录，而不是默认启动链中的独立服务

## 相关文档

- [Server README](../README.md)
- [Gateway README](../gateway/README.md)
- [Database README](database/README.md)
- [Storage README](storage/README.md)