# PathLab Gateway Service

API 网关服务，PathLab 数字病理平台的统一入口。

## 🚀 运行模式

| 模式 | Gateway 端口 | 说明 |
|------|-------------|------|
| **网页端** (调试模式) | 6100 (固定) | `npm run dev` 启动，浏览器访问 |
| **本地端** (打包模式) | 动态分配 | Electron 启动，通过 `PORT=xxxxx` 通知前端 |

## 功能概述

- **请求路由**: 转发请求到 Preprocessing/AI 服务
- **数据聚合**: 合并多服务响应
- **元数据管理**: WSI/Dataset CRUD（PostgreSQL，17 表）
- **用户认证**: FastAPI-Users + JWT，本地邮箱密码登录，客户端 SHA256 哈希
- **AI 聊天**: OpenRouter LLM 集成，对话持久化
- **训练管理**: 训练任务生命周期，SSE 实时日志
- **GPU 队列**: 最大并发控制，FIFO 调度，断电恢复

---

## 完整 API 端点列表

### 1. 认证 API (`/auth/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| POST | `/auth/jwt/login` | ⛔ 已禁用（防止绕过 reCAPTCHA） | — |
| POST | `/auth/jwt/logout` | 登出 | 已登录 |
| POST | `/auth/secure-login` | 安全登录（客户端哈希） | 公开 |
| POST | `/auth/register` | 注册新用户 | 公开 |
| POST | `/auth/migrate-password` | 迁移旧密码格式 | 已登录 |
| GET | `/auth/me` | 获取当前用户信息 | 已登录 |
| PATCH | `/auth/me` | 更新当前用户信息 | 已登录 |
| GET | `/auth/users` | 列出所有用户 | 管理员 |
| GET | `/auth/users/{id}` | 获取指定用户 | 管理员 |
| PATCH | `/auth/users/{id}` | 更新指定用户 | 管理员 |
| DELETE | `/auth/users/{id}` | 删除用户 | 管理员 |
| POST | `/auth/accept-agreement` | 接受服务条款 | 已登录 |
| POST | `/auth/users/{id}/revoke-agreement` | 撤销用户协议 | 管理员 |

---

### 2. WSI 管理 API (`/wsi/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/wsi` | 列出所有 WSI（支持分页、筛选） | 已登录 |
| GET | `/wsi/{wsi_id}` | 获取 WSI 详情 | 已登录 |
| POST | `/wsi/upload/path` | 通过路径注册 WSI | 已登录 |
| POST | `/wsi/upload/file` | 上传 WSI 文件 | 已登录 |
| POST | `/wsi/batch` | 批量注册 WSI | 已登录 |
| PATCH | `/wsi/{wsi_id}` | 更新 WSI 元数据 | 已登录 |
| DELETE | `/wsi/{wsi_id}` | 删除 WSI | 已登录 |

---

### 3. Dataset 管理 API (`/datasets/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/datasets` | 列出所有数据集 | 已登录 |
| GET | `/datasets/{dataset_id}` | 获取数据集详情 | 已登录 |
| POST | `/datasets` | 创建数据集 | 已登录 |
| PATCH | `/datasets/{dataset_id}` | 更新数据集 | 已登录 |
| DELETE | `/datasets/{dataset_id}` | 删除数据集 | 已登录 |
| POST | `/datasets/{dataset_id}/wsi` | 添加 WSI 到数据集 | 已登录 |
| DELETE | `/datasets/{dataset_id}/wsi/{wsi_id}` | 从数据集移除 WSI | 已登录 |

---

### 4. AI 任务 API (`/tasks/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/tasks/extractors` | 列出可用特征提取器（17种） | 已登录 |
| POST | `/tasks/wsi_classification` | 创建 WSI 分类任务 | 已登录 |
| GET | `/tasks/{task_id}` | 获取任务状态 | 已登录 |

---

### 5. 训练 API (`/training/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/training/tasks` | 列出训练任务 | 已登录 |
| GET | `/training/tasks/{task_id}` | 获取训练任务详情 | 已登录 |
| POST | `/training/tasks` | 创建训练任务 | 已登录 |
| DELETE | `/training/tasks/{task_id}` | 删除训练任务 | 已登录 |
| POST | `/training/tasks/{task_id}/start` | 启动训练 | 已登录 |
| POST | `/training/tasks/{task_id}/stop` | 停止训练 | 已登录 |
| GET | `/training/tasks/{task_id}/logs` | 获取训练日志（SSE 流式） | 已登录 |
| GET | `/training/models` | 列出已训练模型 | 已登录 |
| GET | `/training/models/{model_id}` | 获取模型详情 | 已登录 |
| DELETE | `/training/models/{model_id}` | 删除模型 | 已登录 |

---

### 6. 结果 API (`/results/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/results` | 获取所有 AI 结果 | 已登录 |
| GET | `/results/analysis/stats` | 获取分析统计 | 已登录 |
| GET | `/results/tasks` | 获取可分析任务列表 | 已登录 |
| POST | `/results/tasks/{task_id}/regenerate` | 重新生成 AI 结果 | 已登录 |
| POST | `/results/external-validation` | 开始外部验证 | 已登录 |
| GET | `/results/external-validation/{task_id}` | 获取验证进度 | 已登录 |
| GET | `/results/tasks/{task_id}/analysis` | 获取任务分析结果 | 已登录 |
| POST | `/results/tasks/{task_id}/analysis` | 运行任务分析 | 已登录 |
| GET | `/results/tasks/{task_id}/analysis/{analysis_id}/file/{filename}` | 获取分析文件 | 已登录 |
| DELETE | `/results/tasks/{task_id}/analysis/{analysis_id}` | 删除分析 | 已登录 |

---

### 7. 热力图 API (`/heatmap/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/heatmap/wsi/{wsi_id}/available` | 获取可用热力图列表 | 已登录 |
| GET | `/heatmap/wsi/{wsi_id}/data` | 获取热力图数据 | 已登录 |
| GET | `/heatmap/wsi/{wsi_id}/patch_image` | 获取 patch 图像 | 已登录 |
| GET | `/heatmap/wsi/{wsi_id}/patch_cam` | 获取 patch CAM | 已登录 |
| GET | `/heatmap/wsi/{wsi_id}/image` | 获取 patch 文件图像 | 已登录 |
| GET | `/heatmap/wsi/{wsi_id}/thumbnail` | 获取 WSI 缩略图 | 已登录 |

---

### 8. GPU 队列 API (`/queue/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/queue/config` | 获取队列配置 | 已登录 |
| GET | `/queue` | 获取队列状态 | 已登录 |
| POST | `/queue/config` | 更新队列配置 | 管理员 |
| DELETE | `/queue/{task_id}` | 取消排队任务 | 已登录 |
| GET | `/queue/{task_id}` | 检查任务是否在队列中 | 已登录 |

---

### 9. 聊天 API (`/chat`, `/conversations/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| POST | `/conversations` | 创建新对话 | 已登录 |
| GET | `/conversations` | 列出对话 | 已登录 |
| GET | `/conversations/{id}` | 获取对话详情（含消息） | 已登录 |
| DELETE | `/conversations/{id}` | 删除对话 | 已登录 |
| POST | `/conversations/{id}/messages` | 添加消息 | 已登录 |
| PATCH | `/conversations/{id}/messages/{message_id}` | 更新消息 | 已登录 |
| DELETE | `/conversations/{id}/messages/{message_id}` | 删除消息起点 | 已登录 |
| POST | `/chat` | AI 聊天（SSE 流式响应） | 已登录 |

---

### 10. 语音识别 API (`/asr/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| POST | `/asr/transcribe` | 语音转文字（DashScope Qwen3-ASR） | 已登录 |

---

### 11. GPU 信息 API (`/gpu/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/gpu/info` | 获取 GPU 信息（显存、利用率） | 已登录 |

---

### 12. 存储管理 API (`/storage/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/storage/stats` | 获取存储统计 | 已登录 |
| GET | `/storage/disk-space` | 获取磁盘空间信息 | 已登录 |
| GET | `/storage/check-upload-space` | 检查上传空间是否充足 | 已登录 |
| GET | `/storage/config` | 获取存储配置 | 已登录 |
| POST | `/storage/config` | 更新存储配置 | 管理员 |
| GET | `/storage/wsi/{wsi_id}` | 获取 WSI 存储信息 | 已登录 |
| GET | `/storage/training/{task_id}` | 获取训练任务存储信息 | 已登录 |
| POST | `/storage/migrate` | 开始存储迁移 | 管理员 |
| GET | `/storage/migration/status` | 获取迁移状态 | 已登录 |
| GET | `/storage/orphaned` | 检测孤立文件 | 管理员 |
| POST | `/storage/orphaned/cleanup` | 清理孤立文件 | 管理员 |

---

### 13. 系统设置 API (`/settings/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/settings` | 获取全局设置 | 已登录 |
| POST | `/settings` | 更新全局设置 | 管理员 |

---

### 14. 统计 API (`/stats/*`)

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/stats` | 获取系统统计 | 已登录 |
| GET | `/stats/recent-activity` | 获取最近活动 | 已登录 |

---

### 15. 健康检查

| 方法 | 端点 | 说明 | 权限 |
|------|------|------|------|
| GET | `/health` | 健康检查 | 公开 |

---

## 数据库架构

PostgreSQL 数据库包含 17 个表（自动创建）：

| 表名 | 用途 |
|------|------|
| `users` | 用户账户（FastAPI-Users） |
| `accesstoken` | 访问令牌（FastAPI-Users）|
| `data_groups` | 数据组定义（数据类型、聚合级别、任务类型组合）|
| `datasets` | 数据集元数据（UUID 隐私保护） |
| `dataset_permissions` | 数据集临时提权 |
| `wsi_slides` | WSI 元数据（含患者信息、标签、生存数据） |
| `ai_tasks` | AI 推理任务记录 |
| `ai_results` | AI 分析结果 |
| `chat_conversations` | 聊天会话 |
| `chat_messages` | 聊天消息历史 |
| `message_feedbacks` | 消息反馈（点赞/点踩/任务有用性）|
| `export_tasks` | 数据导出任务追踪 |
| `training_tasks` | 训练任务配置（分类/生存） |
| `training_task_wsi` | 训练任务与 WSI 多对多关联 |
| `trained_models` | 模型检查点元数据 |
| `training_logs` | 训练日志条目（运行时通过 Redis Streams 读写，SSE 流式） |
| `storage_tasks` | 存储操作任务追踪（批量导入/删除）|

---

## GPU 任务队列

任务队列管理器 (`task_queue.py`) 提供：

- **最大并发**: 默认 1 个 GPU 任务
- **FIFO 调度**: 先进先出
- **断电恢复**: 重启后自动恢复待处理任务
- **统一管理**: 支持 TrainingTask + AITask

---

## 技术栈

- **框架**: FastAPI (Python 3.12)
- **认证**: FastAPI-Users + JWT
- **数据库**: PostgreSQL + asyncpg (异步)
- **缓存**: Redis (训练日志 Streams、任务进度 KV、分析状态 Hash)
- **ORM**: SQLAlchemy 2.0+
- **LLM**: OpenRouter API
- **ASR**: DashScope Qwen3-ASR

---

## License

See root repository LICENSE file.
