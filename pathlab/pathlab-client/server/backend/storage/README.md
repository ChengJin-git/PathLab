# PathLab Storage Management

`server/backend/storage/` 负责文件系统层面的统计、迁移、配置与清理工作，是数据库状态与 `uploads/` 目录之间的一层维护工具。

## 当前模块结构

- `manager.py`：统一入口 `StorageManager`
- `stats_mixin.py`：目录体积、文件数、分类统计
- `orphan_mixin.py`：孤立文件与孤立数据库记录检测
- `migration.py`：存储目录迁移工具

## 当前 `StorageManager` 能力

`StorageManager` 当前主要提供：

- `delete_wsi_files()`
- `delete_wsi_ai_results()`
- `delete_training_task_files()`
- `get_wsi_storage_info()`
- `get_training_task_storage_info()`
- `reset_derived_data()`
- `cleanup_dangling_feature_symlinks()`
- `save_wsi_metadata()`
- `get_wsi_metadata()`
- 以及统计 / 迁移 / 孤立项清理相关方法

这些能力通过 Gateway 的 `/storage` 路由族对外暴露；对应代码分散在：

- `gateway/routes/storage.py`
- `gateway/routes/storage_tasks.py`
- `gateway/routes/storage_scan.py`

## 当前 uploads 目录现状

`uploads` 根目录默认位于 `pathlab-client/uploads`，但也可以通过：

- 环境变量 `PATHLAB_UPLOADS_DIR`
- 持久化配置文件（应用数据目录下的 `storage.json`）

进行覆盖。

根据 `backend/common/config.py`、统计与清理逻辑，当前项目会管理以下主要目录：

- `uploads/wsi_files/`
- `uploads/features/`
- `uploads/coordinates/`
- `uploads/masks/`
- `uploads/ai_results/`
- `uploads/training/`
- `uploads/models/`
- `uploads/logs/`
- `uploads/avatars/`
- `uploads/metadata/`
- `uploads/progress/`
- `uploads/pdf_cache/`（按需生成，用于聊天 / PDF 相关缓存）

这已经超出“只存切片文件”的阶段，当前实现同时管理模型、训练结果、日志、缓存和用户上传衍生物。

## 统计与清理现状

### 存储统计

`stats_mixin.py` 会统计：

- 总体积与文件数量
- 各子目录占用
- WSI / 训练任务相关数据的聚合视图

### 孤立项检测

`orphan_mixin.py` 当前会关注：

- `wsi_files`
- `features`
- `coordinates`
- `masks`
- `ai_results`
- `training`
- `models`
- `logs`
- `metadata`
- `progress`
- `pdf_cache`
- `avatars`

并将它们与数据库中的 WSI、任务、模型、用户等记录对照，以发现多余文件或失配记录。

### 批处理任务

当前 `/storage` 路由除了常规查询外，还包含后台任务型操作，例如：

- `POST /storage/reset-derived-data`
- `POST /storage/tasks/batch-import`
- `POST /storage/tasks/delete-external`
- `POST /storage/tasks/batch-update-metadata`
- `GET /storage/tasks/stream`

这些操作会把执行状态落在 `storage_tasks` 表中，并通过 SSE / 轮询供前端查看。

## 迁移现状

`migration.py` 中的 `StorageMigrator` 支持：

- 校验新路径
- 预估迁移规模
- 执行目录迁移
- 更新数据库中的存储根路径配置

适用于把 `uploads/` 迁移到新磁盘或新挂载点的场景。

## 与业务层的关系

- Gateway：提供 `/storage`、扫描、清理、配置更新等接口
- Database：提供 WSI、训练任务、模型、用户等实体用于一致性校验
- Frontend：设置页中的存储管理视图会消费这些接口

## 相关文档

- [Backend README](../README.md)
- [Database README](../database/README.md)
- [Gateway README](../../gateway/README.md)