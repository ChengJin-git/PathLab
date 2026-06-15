# PathLab Database Layer

> 适用版本：`PathLab v1.0.4`

`server/backend/database/` 是当前 SQLAlchemy 数据访问层，负责模型声明、异步 Session 管理、数据库初始化以及 Repository 封装。

## 当前组成

- `database.py`：异步 engine / session 工厂
- `models.py`：业务 ORM 模型
- `init_db.py`：初始化与建表逻辑
- `repositories/`：按业务拆分的数据访问对象
- `migrate_unify_annotations.py`：标注相关迁移脚本

## 当前 ORM 表现状

当前代码里可直接看到 **24 个 ORM 表**：

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
21. `auto_research_sessions`（PathScientist 自动化实验会话汇总）
22. `auto_research_experiments`（PathScientist 每次实验 run 的 metrics 和摘要）
23. `auto_research_events`（PathScientist 运行事件流，用于回放/审计）

### 认证表（`backend/auth/models.py`）

24. `users`

`users` 当前除 FastAPI-Users 的基础字段外，还直接扩展了这些与业务强相关的字段：

- `role` / `nickname`
- `avatar_path`
- `password_sha256`
- `session_nonce`
- `agreement_accepted_at` / `agreement_ip`
- `notice_acknowledged_at`
- `registration_email`：用户通过 `POST /auth/request-access` 申请访问时填写的教育邮箱，用于发送申请受理与账号激活通知邮件；直接注册（`/auth/register`）的用户此字段为 `null`

## annotation_id 命名规范

`segmentation_annotations.annotation_id` 字段当前遵循以下命名规范：

| 类型 | 格式 | 说明 |
|------|------|------|
| 数据集级别标注（GT/labels） | `label_{dataset_id}` | 由 finalize 或 GT 导入写入 |
| 个人/共享草稿 | UUID | 由草稿写入逻辑生成 |

## annotation_source 派生字段

`annotation_source` 不是数据库列，而是**在查询时计算的派生字段**：

- 取值 `"imported_gt"`：标注来源于外部导入的 mask GT
- 取值 `"user_label"`：标注来源于用户手绘或共享标注 finalize
- 计算逻辑：`GET /datasets/{dataset_id}/labels` 端点（annotation.py）读取 effective annotation 记录并根据 `source` 字段判断
- `SegmentationAnnotation.to_dict()` 也会在单条记录序列化时输出此字段（供 WSI viewer GT overlay 使用）

## 与旧文档相比的关键变化

- 标注表当前是 `segmentation_annotations`，不是旧文档里的 `annotation_drafts`
- `annotation_id` 中的数据集级别记录统一使用 `label_{dataset_id}` 格式（旧 `annot_` 前缀已迁移完毕）
- 当前 README 不再把 `accesstoken` 记作项目里明确可见的独立 ORM 模型
- 认证更贴近"JWT + users + nonce 控制"的实现方式
- 当前权限体系已统一到 `dataset_grants` / `permission_audit_logs`，旧表 `dataset_permissions` 与 `annotation_collaborators` 不再作为 ORM 模型存在

## Repository 现状

`repositories/` 当前包含 19 个业务仓储模块，并由 `repositories/__init__.py` 统一导出：

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
- `AutoResearchRepository`

这意味着当前仓储层已经覆盖数据集、WSI、AI 任务、聊天、反馈、导出、训练、权限、存储任务、孤立记录、标注及协作审计等核心实体。`analysis_runs` 表当前通过直接 ORM 查询访问，暂无独立 Repository 封装。

## PathScientist 自动化实验存储

Web PathScientist 流程会 best-effort 写入现有 `auto_research_*` 表。当前目标是
**DB 索引 + 磁盘权威**：

- DB 负责历史列表、用户过滤、摘要、metrics、可回放的 Gateway 投影事件、恢复定位信息。
- 磁盘负责完整 OpenHands/PathScientist 状态、原始 OpenHands 事件、workspace、模型文件、实验 artifact、`base_state.json`。

### 表内容

- `auto_research_sessions`：按 `session_id` 唯一保存一次自动化实验会话，包含 `user_id`、`research_question`、`status`、`phase`、`best_metric`、`best_experiment`、`comparison_results`、`final_report`。
  - 为历史恢复新增的字段：
    - `conversation_id`：PathScientist/OpenHands conversation id，用于定位磁盘会话。
    - `persistence_dir`：conversation 持久化目录，通常包含 `base_state.json` 与 OpenHands events。
    - `workspace_path`：session workspace 路径，用于 artifact 下载和调试。
    - `resume_available`：是否检测到可恢复 checkpoint。当前判断标准是 `persistence_dir/base_state.json` 存在。
    - `event_source_version`：Gateway 事件投影版本，当前默认 `gateway-v1`。
    - `recovery_metadata`：恢复相关 compact JSON，包含路径、artifact policy，以及 external test / review / integrity 等辅助摘要。
- `auto_research_experiments`：按 `(session_id, training_task_id)` 逻辑幂等保存每次 run，其中 `training_task_id` 使用 PathScientist `run_id`，`metrics` 保存 `metrics.json` 的结构化内容，`hyperparams` 保存 compact config/path metadata。
- `auto_research_events`：按 `(session_id, sequence)` 逻辑幂等保存 Gateway SSE/event payload，供审计和回放使用。
  - ORM 和启动初始化都确保 `(session_id, sequence)` 唯一，重复写入不会产生重复历史事件。
  - `AutoResearchRepository.append_event_once()` 先查重，再通过数据库唯一约束兜底；真实 `AsyncSession` 下使用 nested transaction 捕获 `IntegrityError`。
  - `AutoResearchRepository.get_session_events()` 按 `sequence` 顺序读取事件，供历史 session detail/events replay 使用。

### JSON 摘要策略

`comparison_results` 和 `recovery_metadata` 只保存 compact JSON：

- `comparison_results.run_history`：run 级别摘要。
- `comparison_results.external_test_history`：external test 历史的 compact list。
- `comparison_results.review_history`：review 阶段历史的 compact list。
- `comparison_results.integrity_report`：数据完整性/执行完整性摘要。
- `recovery_metadata.artifact_policy`：明确说明数据库只保存 metadata/path，较大的原始产物仍在磁盘。

不把完整 OpenHands 原始会话塞进数据库。也就是说，原始交互消息、完整工具调用参数、完整工具输出、terminal output、workspace 文件和模型 artifact 仍主要在磁盘的 conversation/workspace 目录里。

### 初始化与迁移

`database.py:init_db()` 会在启动时幂等确保以下结构：

- 给 `auto_research_sessions` 补齐 `conversation_id`、`persistence_dir`、`workspace_path`、`resume_available`、`event_source_version`、`recovery_metadata`。
- 创建 `idx_auto_research_sessions_conversation_id`，加速通过 conversation id 定位历史。
- 清理 `auto_research_events` 中已有的 `(session_id, sequence)` 重复行，只保留较早记录。
- 创建 `uq_auto_research_events_session_seq` 唯一索引。

历史 Gateway 文件态 session 可以通过 `server/scripts/migrate_pathscientist_file_sessions_to_db.py` 导入数据库。脚本现在会：

- 读取 Gateway registry：`gateway_sessions.json`。
- 读取 Gateway JSONL events：`gateway_events/*.jsonl`。
- 根据 `conversation_id` 定位 PathScientist/OpenHands conversation 目录。
- 合并 conversation summary，补齐 `persistence_dir`、`workspace_path`、`resume_available`。
- 当 Gateway JSONL 缺失时，尝试用 OpenHands `events/event-*.json` 投影生成 DB replay events。
- 复用 `AutoResearchRepository` 的幂等 upsert / append 逻辑，重复迁移不会重复显示同一 sequence 的事件。

数据库只保存可查询索引、状态、metrics、摘要和路径。大型产物仍保存在文件系统：

- session workspace：`PATHSCIENTIST_BASE_DIR/session_<id>/...`
- dataset cache：`PATHSCIENTIST_DATASET_CACHE_DIR`
- feature outputs：`<dataset_root>/patches/*.h5` 和 `<dataset_root>/pt_files/<extractor>/*.pt`
- model/checkpoint/run artifacts：以路径或 compact summary 进入 JSON 字段，不复制二进制内容进库

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
