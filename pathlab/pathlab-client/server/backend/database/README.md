# PathLab Database Layer

> 适用版本：`PathLab v1.0.0`

`server/backend/database/` 是当前 SQLAlchemy 数据访问层，负责模型声明、异步 Session 管理、数据库初始化以及 Repository 封装。

## 当前组成

- `database.py`：异步 engine / session 工厂
- `models.py`：业务 ORM 模型
- `init_db.py`：初始化与建表逻辑
- `repositories/`：按业务拆分的数据访问对象
- `migrate_unify_annotations.py`：标注相关迁移脚本

## 当前 ORM 表现状

当前代码里可直接看到 **17 个 ORM 表**：

### 业务表（`models.py`）

1. `data_groups`
2. `datasets`
3. `wsi_slides`
4. `ai_tasks`
5. `ai_results`
6. `chat_conversations`
7. `chat_messages`
8. `message_feedbacks`
9. `export_tasks`
10. `training_tasks`
11. `training_task_wsi`（训练任务与 WSI 的关联表）
12. `trained_models`
13. `training_logs`
14. `dataset_permissions`
15. `storage_tasks`
16. `segmentation_annotations`

### 认证表（`backend/auth/models.py`）

17. `users`

`users` 当前除 FastAPI-Users 的基础字段外，还直接扩展了这些与业务强相关的字段：

- `role` / `nickname`
- `avatar_path`
- `password_sha256`
- `session_nonce`
- `agreement_accepted_at` / `agreement_ip`
- `notice_acknowledged_at`

## 与旧文档相比的关键变化

- 标注表当前是 `segmentation_annotations`，不是旧文档里的 `annotation_drafts`
- 当前 README 不再把 `accesstoken` 记作项目里明确可见的独立 ORM 模型
- 认证更贴近“JWT + users + nonce 控制”的实现方式

## Repository 现状

`repositories/` 当前包含 15 个业务仓储模块，并由 `repositories/__init__.py` 统一导出：

- `DataGroupRepository`
- `DatasetRepository`
- `WSIRepository`
- `AITaskRepository`
- `AIResultRepository`
- `ChatRepository`
- `FeedbackRepository`
- `ExportTaskRepository`
- `TrainingTaskRepository`
- `TrainedModelRepository`
- `TrainingLogRepository`
- `DatasetPermissionRepository`
- `StorageTaskRepository`
- `OrphanedRecordsRepository`
- `SegmentationAnnotationRepository`

这意味着当前仓储层已经覆盖数据集、WSI、AI 任务、聊天、反馈、导出、训练、权限、存储任务、孤立记录与标注等核心实体。

## 初始化与使用方式

- Gateway 启动时会调用数据库初始化逻辑
- 业务代码通过异步 session 进入 Repository
- `backend/database/__init__.py` 统一导出常用模型、session 与仓储类

## 你可以从这里继续看什么

- 如果关心认证表与用户字段：看 `../auth/`
- 如果关心文件系统与数据库的一致性：看 `../storage/README.md`
- 如果关心业务 API 如何写入这些表：看 `../../gateway/README.md`

## 相关文档

- [Backend README](../README.md)
- [Gateway README](../../gateway/README.md)
- [Storage README](../storage/README.md)