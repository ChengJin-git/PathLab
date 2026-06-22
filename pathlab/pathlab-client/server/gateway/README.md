# PathLab Gateway

> 适用版本：`PathLab v1.0.5`

Gateway 是当前 PathLab 对外 API 的统一入口，负责认证、业务聚合、静态资源挂载以及与 Preprocessing / AI 内部服务的协作。

## 当前应用行为

- 启动文件：`server/gateway/main.py`
- Web 框架：FastAPI
- 启动时当前会执行：
  - 初始化数据库
  - 初始化 Redis
  - 清理旧的 progress 文件
  - 清理过期完成任务
  - 清理过期 PDF 缓存
  - 异步预热训练推荐所需的 embedding 模型与内置知识源
  - 异步预热所有非管理员用户的聊天上下文缓存（`_startup_prewarm_chat_context_cache`）
  - 注册所有顶层 router
  - 在存在前端构建产物时挂载静态资源
  - 始终挂载 `/avatars`

> 注：GPU 探测、任务队列运行时初始化与训练恢复当前由独立的 `TaskWorker` 进程负责；Gateway 通过 Redis 读取其发布的运行时快照与心跳，不再在 Gateway 生命周期内初始化队列运行时。

## 任务边界与队列状态

Gateway 对长任务只做描述符入队、取消请求发布和状态查询。`gateway.task_dispatch` 负责构造 Redis 任务描述符并写入 pending 队列；TaskWorker 负责 claim、执行、ack、失败重试和 DLQ 归档。这样 Gateway 进程重启不会拥有未完成 GPU 工作，也不会因本地队列状态丢失而影响已入队任务。

可靠描述符队列使用三组 Redis list：pending、processing 和 DLQ。TaskWorker claim 时把描述符从 pending 移到 processing，成功后 ack 删除，失败后按上限重试，超过上限进入 DLQ。取消路径同时写 durable cancellation key 和 pub/sub 消息，TaskWorker 在执行前检查 cancellation key，并用 job lock 跳过重复 descriptor。

`GET /queue` 优先读取 TaskWorker 发布的运行时快照。响应中 `running_count` / `pending_count` / `queue_size` 描述 TaskWorker 内部 GPU 队列，`descriptor_pending_count` / `descriptor_processing_count` / `descriptor_dlq_count` 描述 Redis 描述符队列健康状态。

## 当前直接注册的 router

`app_setup.py` 里当前直接注册这些顶层 router：

1. `auth`
2. `stats`
3. `wsi`
4. `wsi_upload`
5. `training`
6. `ai_tasks`
7. `results`
8. `models`
9. `chat`
10. `storage`
11. `queue`
12. `asr`
13. `heatmap`
14. `settings`
15. `gpu`
16. `annotation`
17. `training_options`

这些 router 覆盖了当前主要公开能力：

- 登录 / 用户管理 / 维护通知 / 头像上传
- WSI 上传、列表、详情、权限检查
- 训练任务、AI 任务与 GPU 队列观察
- 模型管理、结果查看、报告导出
- AI 对话、会话历史、网页检索、PDF 缓存 / 向量检索与反馈
- 存储统计、扫描、清理与配置
- GPU 信息、热图、标注、系统设置

## 路由目录现状

`server/gateway/routes/` 下包含顶层 router 与被其他 router 复用的支持模块。模块数量会随功能增长变化，实际清单以文件系统为准。

除了上面顶层 router 外，目录里还有若干**被其他 router 复用的支持模块**，例如：

- 推理实现：`inference_external_validation.py`、`inference_wsi_survival.py`、`inference_patch_segmentation.py`、`inference_patch_classification.py`、`inference_wsi_classification.py`（各推理路径的实现逻辑，由 `results` router 调用）、`inference_batch.py`（无标签数据集批量推理，由 GPU 任务队列以 `BATCH_INFERENCE` 类型调度）
- 推理基础：`inference_base.py`（推理路径共享的基础逻辑）
- 分析相关：`classification_analysis.py`、`segmentation_analysis.py`、`survival_analysis.py`、`external_validation_analysis.py`
- 分析辅助：`analysis_utils.py`、`analysis_metrics.py`、`analysis_state.py`
- 聊天辅助：`chat_pdf.py`、`chat_pdf_vectorstore.py`、`chat_pdf_document.py`、`chat_pdf_sources.py`、`chat_pdf_shared.py`、`chat_pdf_marker_shared.py`、`chat_feedback.py`、`chat_patch_inference.py`、`chat_training_recommendation.py`、`chat_intent_policy.py`、`chat_conversation.py`、`chat_llm_client.py`、`chat_model_selector.py`
- 访问控制：`access_control.py`
- 训练辅助：`training_options.py`（为 `training_options_router` 提供 `/training/options` 接口）
- 运行时辅助：`transformers_runtime.py`
- 存储辅助：`storage_scan.py`、`storage_tasks.py`
- WSI 权限辅助：`wsi_grants.py`

这些文件通常通过导入被组合到顶层 router，而不是单独挂载；当前聊天 / PDF / 训练推荐相关能力都在 Gateway 路由层内部聚合。

## 认证现状

认证相关代码集中在 `routes/auth.py` 与 `backend/auth/`：

- 使用 FastAPI Users + JWT strategy
- `/auth/jwt/login` 当前被禁用，实际登录入口为 `/auth/secure-login`
- 维护用户 `session_nonces`，用于会话失效控制；旧 `session_nonce` 仅为 schema 兼容保留
- 支持 `secure-login`、登出、资料更新、头像上传
- 支持维护模式、维护公告确认、分页用户列表与批量用户启停删
- 包含管理员批量启用 / 禁用 / 删除用户接口
- 当前代码里没有单独暴露的 `AccessToken` ORM 模型 README 记录，认证主要依赖 JWT

## 标注路由（annotation router）

`routes/annotation.py` 当前提供的核心公开端点包括：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/annotation/datasets/{dataset_id}/labels` | 获取数据集的有效标注（GT + 个人覆盖层合并），含 `annotation_source` 派生字段 |
| `GET` | `/annotation/wsi/{wsi_id}/labels` | 获取单张 WSI 的个人标注草稿 |
| `GET` | `/annotation/datasets/{dataset_id}/summary` | 获取标注汇总统计，含 `label_annotation_source` 字段 |
| `DELETE` | `/annotation/datasets/{dataset_id}/labels` | 删除数据集标注（活跃训练任务时拦截） |
| `POST` | `/annotation/datasets/{dataset_id}/delete-by-labels` | 按 label 类别删除标注 |
| `POST` | `/annotation/extract` | 提取标注 ROI 到新数据集（触发 `promoted_to_training_reference` 审计） |

注意：annotation router 的公开路径都带 `/annotation` 前缀；旧 `/ground-truth` 路径已在 v1.0.5 之前的重构中改名为 `/labels`，旧路径不再有效。

## 存储路由补充说明

`routes/storage.py` 自身提供 `/storage/stats`、`/storage/disk-space`、`/storage/check-upload-space`、`/storage/config`、`/storage/migrate`、`/storage/migration/status`、`/storage/orphaned` 等入口，并进一步组合：

- `storage_tasks.py`
- `storage_scan.py`

因此 `/storage` 不是单一文件，而是一组聚合后的存储管理路由。

## 静态资源挂载

- `/avatars` → `uploads/avatars`
- `/images`、`/assets` → 当前前端构建产物目录（如果存在）

这意味着浏览器部署模式下，Gateway 既提供 API，也可以直接为前端构建产物提供静态资源入口。

## Gateway 顶层模块

`server/gateway/` 目录除 `routes/` 子目录外，当前还包含以下顶层 Python 模块 / 子目录：

| 模块 | 说明 |
|------|------|
| `main.py` | FastAPI 应用入口，负责生命周期管理与 router 注册 |
| `dependencies.py` | 公共 FastAPI 依赖（日志、工具函数等） |
| `models.py` | Gateway 层 Pydantic 请求 / 响应模型 |
| `utils.py` | 业务工具函数（segmentation contract 校验等） |
| `pipeline.py` | AI 推理流水线辅助逻辑 |
| `task_queue.py` | 共享 `TaskQueueManager` 实现（最大并发控制、FIFO 调度、VRAM 预检）；运行时由 TaskWorker 初始化，Gateway 路由只在需要时导入类型或提交任务 |
| `task_dispatch.py` | 构造并写入 Redis 任务描述符；Gateway 侧长任务入口通过它把工作交给 TaskWorker |
| `email_notifications.py` | 模板化邮件发送（用户激活通知、申请受理通知、管理员新用户提醒）|
| `scan_sessions.py` | 目录扫描会话状态管理（TTL 缓存，供 `storage_scan` 路由复用）|
| `bootstrap_builtin_training_knowledge.py` | 内置训练推荐知识源预热逻辑 |
| `app_setup.py` | 顶层 router 注册与静态资源挂载 |
| `startup.py` | Gateway 生命周期启动 / 关闭编排 |
| `chat/` | 上下文缓存、权限与训练推荐辅助逻辑 |
| `knowledge/` | 内置知识源与 training RAG 运行时目录 |
| `prompts/` | Gateway 侧 LLM prompt 模板 |

## 与内部服务的关系

- Preprocessing：提供 WSI 信息、图像、缩略图、DZI、瓦片等底层接口
- AI：提供训练、推理等内部能力
- Database / Storage：通过 `backend/` 共享模块提供 ORM、仓储、文件系统能力

## 阅读建议

- 如果你要看公开 API 面：先看 `main.py` 和 `routes/`
- 如果你要看数据落库：继续看 `../backend/database/README.md`
- 如果你要看文件与目录占用：继续看 `../backend/storage/README.md`

## 相关文档

- [Server README](../README.md)
- [Backend README](../backend/README.md)
- [Database README](../backend/database/README.md)
- [Storage README](../backend/storage/README.md)
