# PathLab Gateway

> 适用版本：`PathLab v1.0.4`

Gateway 是当前 PathLab 对外 API 的统一入口，负责认证、业务聚合、静态资源挂载以及与 Preprocessing / AI 内部服务的协作。

## 当前应用行为

- 启动文件：`server/gateway/main.py`
- Web 框架：FastAPI
- 启动时当前会执行：
  - 初始化数据库
  - 初始化 Redis
  - 探测 GPU 数量并决定 `max_concurrent`
  - 初始化任务队列
  - 清理旧的 progress 文件
  - 恢复中断的训练任务
  - 清理过期完成任务
  - 清理过期 PDF 缓存
  - 异步预热训练推荐所需的 embedding 模型与 bundled knowledge 源
  - 异步预热所有非管理员用户的聊天上下文缓存（`_startup_prewarm_chat_context_cache`）
  - 注册所有顶层 router
  - 在存在前端构建产物时挂载静态资源
  - 始终挂载 `/avatars`

## 当前直接注册的 router

`main.py` 里当前直接注册了 **17 个顶层 router**：

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

`server/gateway/routes/` 当前包含 **34 个路由模块文件**（不含 `__init__.py`）。

除了上面 17 个顶层 router 外，目录里还有若干**被其他 router 复用的支持模块**，例如：

- 分析相关：`classification_analysis.py`、`segmentation_analysis.py`、`survival_analysis.py`、`external_validation_analysis.py`
- 分析辅助：`analysis_helpers.py`、`analysis_metrics.py`、`analysis_state.py`
- 聊天辅助：`chat_pdf.py`、`chat_pdf_vectorstore.py`、`chat_feedback.py`、`chat_patch_inference.py`、`chat_training_recommendation.py`、`chat_intent_policy.py`
- 训练辅助：`training_options.py`（为 `training_options_router` 提供 `/training/options` 接口）
- 运行时辅助：`transformers_runtime.py`
- 存储辅助：`storage_scan.py`、`storage_tasks.py`
- WSI 权限辅助：`wsi_grants.py`

这些文件通常通过导入被组合到顶层 router，而不是单独挂载；当前也没有额外单列的 `deep-research` router 入口。

## 认证现状

认证相关代码集中在 `routes/auth.py` 与 `backend/auth/`：

- 使用 FastAPI Users + JWT strategy
- `/auth/jwt/login` 当前被禁用，实际登录入口为 `/auth/secure-login`
- 维护用户 `nonce`，用于单设备会话控制
- 支持 `secure-login`、登出、资料更新、头像上传
- 支持维护模式、维护公告确认、分页用户列表与批量用户启停删
- 包含管理员批量启用 / 禁用 / 删除用户接口
- 当前代码里没有单独暴露的 `AccessToken` ORM 模型 README 记录，认证主要依赖 JWT

## 标注路由（annotation router）

`routes/annotation.py` 当前提供的核心公开端点包括：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/datasets/{dataset_id}/labels` | 获取数据集的有效标注（GT + 个人覆盖层合并），含 `label_annotation_source` 派生字段 |
| `GET` | `/wsi/{wsi_id}/labels` | 获取单张 WSI 的个人标注草稿 |
| `GET` | `/datasets/{dataset_id}/labels/summary` | 获取标注汇总统计，含 `label_annotation_source` 字段 |
| `DELETE` | `/datasets/{dataset_id}/labels` | 删除数据集标注（活跃训练任务时拦截） |
| `POST` | `/datasets/{dataset_id}/delete-by-labels` | 按 label 类别删除标注 |
| `POST` | `/annotation/extract` | 提取标注 ROI 到新数据集（触发 `promoted_to_training_reference` 审计） |

注意：`/ground-truth` 路径已在 v1.0.4 之前的重构中改名为 `/labels`，旧路径不再有效。

## 存储路由补充说明

`routes/storage.py` 自身提供 `/storage/stats`、`/storage/disk-space`、`/storage/check-upload-space`、`/storage/config`、`/storage/migrate`、`/storage/migration/status`、`/storage/orphaned` 等入口，并进一步组合：

- `storage_tasks.py`
- `storage_scan.py`

因此 `/storage` 不是单一文件，而是一组聚合后的存储管理路由。

## 静态资源挂载

- `/avatars` → `uploads/avatars`
- `/images`、`/assets` → 当前前端构建产物目录（如果存在）

这意味着浏览器部署模式下，Gateway 既提供 API，也可以直接为前端构建产物提供静态资源入口。

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
