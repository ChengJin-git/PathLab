# PathLab Storage Management

`server/backend/storage/` 负责文件系统层面的统计、迁移、配置与清理工作，是数据库状态与 `uploads/` 目录之间的一层维护工具。

## 当前模块结构

- `manager.py`：统一入口 `StorageManager`
- `stats_mixin.py`：目录体积、文件数、分类统计
- `orphan_mixin.py`：孤立文件与孤立数据库记录检测
- `migration.py`：存储目录迁移工具

## 当前 StorageManager 能力

`StorageManager` 结合 `stats_mixin.py` / `orphan_mixin.py` 当前主要承担：

- 总存储统计与分目录统计
- WSI 级别存储信息读取
- 训练任务级别存储信息读取
- 删除 WSI 相关衍生文件
- 删除训练任务相关衍生文件
- 重置部分派生数据与悬挂符号链接清理辅助逻辑

这些能力通过 Gateway 的 `/storage` 相关接口暴露给前端或运维流程。

## 当前 uploads 目录现状

根据 `backend/common/config.py`，当前启动时会确保这些目录存在：

- `uploads/avatars/`
- `uploads/coordinates/`
- `uploads/masks/`
- `uploads/features/`
- `uploads/ai_results/`
- `uploads/training/`
- `uploads/models/`
- `uploads/logs/`
- `uploads/wsi_files/`
- `uploads/metadata/`
- `uploads/progress/`

此外，当前代码里还有两类按需生成目录：

- `uploads/annotations/`：Preprocessing 为数据集写出 `*_coco.json` 缓存时创建
- `uploads/pdf_cache/`：聊天 / PDF 相关逻辑按需使用

这已经超出“只存切片文件”的阶段，当前实现同时管理模型、训练结果、日志、缓存和用户上传衍生物。

## 统计与清理现状

### 存储统计

`stats_mixin.py` 当前重点统计这些类别：

- `coordinates`
- `masks`
- `ai_results`
- `features_cache`
- `training`
- `models`
- `logs`
- `wsi_files`

### 孤立项检测

`orphan_mixin.py` 当前重点扫描这些类别：

- `wsi_files`
- `coordinates`
- `masks`
- `features_cache`
- `ai_results`
- `training`
- `models`
- `logs`

并将它们与数据库中已有的 WSI、任务、模型记录对照，以发现多余文件或失配记录。

因此要注意：`metadata`、`progress`、`avatars`、`annotations`、`pdf_cache` 虽然是当前运行时会使用的目录，但并不是都被纳入同一套统计 / 孤立扫描逻辑。

## Gateway 暴露方式

`server/gateway/routes/storage.py` 当前直接提供或组合这些入口：

- `/storage/stats`
- `/storage/config`
- `/storage/migrate`
- `/storage/orphaned`
- `/storage/orphaned/cleanup`
- `/storage/orphaned-records`
- `/storage/orphaned-records/cleanup`
- 以及 `storage_tasks.py`、`storage_scan.py` 中的批量任务与目录扫描接口

## 迁移现状

`migration.py` 中的 `StorageMigrator` 负责存储根目录迁移相关逻辑，适用于把 `uploads/` 迁移到新磁盘或新挂载点的场景。

## 与业务层的关系

- Gateway：提供统计、扫描、清理、配置更新等接口
- Database：提供 WSI、训练任务、模型等实体用于一致性校验
- Frontend：设置页中的存储管理视图会消费这些接口

## 相关文档

- [Backend README](../README.md)
- [Database README](../database/README.md)
- [Gateway README](../../gateway/README.md)