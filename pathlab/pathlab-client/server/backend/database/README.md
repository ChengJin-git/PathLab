# PathLab Database Layer

> 适用版本：`PathLab v1.0.3`

`server/backend/database/` 是当前 SQLAlchemy 数据访问层，负责模型声明、异步 Session 管理、数据库初始化以及 Repository 封装。

## 当前组成

- `database.py`：异步 engine / session 工厂（启动时自动调用 `migrate_rename_annot_to_label.py` 幂等迁移）
- `models.py`：业务 ORM 模型
- `init_db.py`：初始化与建表逻辑
- `repositories/`：按业务拆分的数据访问对象
- `migrate_unify_annotations.py`：标注相关迁移脚本
- `migrate_rename_annot_to_label.py`：将 `annotation_id` 中 `annot_` 前缀统一重命名为 `label_` 的幂等迁移脚本

## 当前 ORM 表现状

当前代码里可直接看到 **21 个 ORM 表**：

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
14. `storage_tasks`
15. `segmentation_annotations`
16. `annotation_audit_logs`（标注操作审计日志表）
17. `analysis_runs`（分析运行记录表，追踪训练任务结果的内部统计分析）
18. `dataset_stats`
19. `dataset_grants`
20. `permission_audit_logs`

### 认证表（`backend/auth/models.py`）

21. `users`

`users` 当前除 FastAPI-Users 的基础字段外，还直接扩展了这些与业务强相关的字段：

- `role` / `nickname`
- `avatar_path`
- `password_sha256`
- `session_nonce`
- `agreement_accepted_at` / `agreement_ip`
- `notice_acknowledged_at`

## annotation_id 命名规范

`segmentation_annotations.annotation_id` 字段当前遵循以下命名规范：

| 类型 | 格式 | 说明 |
|------|------|------|
| 数据集级别标注（GT/labels） | `label_{dataset_id}` | 由 finalize 或 GT 导入写入 |
| 个人/共享草稿 | UUID | 由草稿写入逻辑生成 |

`migrate_rename_annot_to_label.py` 负责将旧格式 `annot_{dataset_id}` 批量迁移为 `label_{dataset_id}`，在 Gateway 启动时通过 `init_db()` 自动调用（幂等）。

## annotation_source 派生字段

`annotation_source` 不是数据库列，而是**在查询时计算的派生字段**：

- 取值 `"imported_gt"`：标注来源于外部导入的 mask GT
- 取值 `"user_label"`：标注来源于用户手绘或共享标注 finalize
- 计算逻辑：`GET /datasets/{dataset_id}/labels` 端点（annotation.py）读取 effective annotation 记录并根据 `source` 字段判断
- `SegmentationAnnotation.to_dict()` 也会在单条记录序列化时输出此字段（供 WSI viewer GT overlay 使用）

## 与旧文档相比的关键变化

- 标注表当前是 `segmentation_annotations`，不是旧文档里的 `annotation_drafts`
- `annotation_id` 中的 `annot_` 前缀已全部迁移为 `label_` 前缀（由幂等迁移脚本保障）
- 当前 README 不再把 `accesstoken` 记作项目里明确可见的独立 ORM 模型
- 认证更贴近"JWT + users + nonce 控制"的实现方式
- 当前权限体系已统一到 `dataset_grants` / `permission_audit_logs`，旧表 `dataset_permissions` 与 `annotation_collaborators` 不再作为 ORM 模型存在

## Repository 现状

`repositories/` 当前包含 18 个业务仓储模块，并由 `repositories/__init__.py` 统一导出：

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
- `DatasetStatsRepository`
- `DatasetGrantRepository`
- `PermissionAuditLogRepository`
- `StorageTaskRepository`
- `OrphanedRecordsRepository`
- `SegmentationAnnotationRepository`（同时导出 `VersionConflictError`）
- `AnnotationAuditLogRepository`

这意味着当前仓储层已经覆盖数据集、WSI、AI 任务、聊天、反馈、导出、训练、权限、存储任务、孤立记录、标注及协作审计等核心实体。`analysis_runs` 表当前通过直接 ORM 查询访问，暂无独立 Repository 封装。

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
