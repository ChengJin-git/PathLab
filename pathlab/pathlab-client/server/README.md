# PathLab Python Backend

> 适用版本：`PathLab v1.0.5`

`server/` 是当前 Python sidecar 目录。它不是单一 FastAPI 应用，而是由 `main.py` 统一拉起 **Gateway / Preprocessing / AI / TaskWorker** 四个进程，并复用 `backend/` 下的共享模块。`2026-06-23` 起，AutoResearch（实现 codename：AutoResearch）也接入这一套 Gateway + backend package + 数据库/文件系统运行边界。

## 当前启动方式

### 统一入口

- 文件：`server/main.py`
- 作用：
  - 选择固定端口或动态端口
  - 设置服务发现环境变量
  - 启动 Gateway / Preprocessing / AI 三个 uvicorn 进程，以及独立 TaskWorker 进程
  - 在退出时统一清理子进程

### 两种端口模式

| 模式 | 端口 | 触发方式 |
|------|------|----------|
| 调试 / 固定端口 | Gateway `6100`、Preprocessing `6101`、AI `6102`；TaskWorker 无 HTTP 端口 | `PATHLAB_DEBUG=1` |
| Electron / 动态端口 | 3 个 HTTP 服务自动分配可用端口，TaskWorker 作为无端口后台进程运行 | 默认 sidecar 启动方式 |

## 当前目录结构

```text
server/
├── main.py                 # 统一入口，负责拉起 3 个 HTTP 服务和 TaskWorker
├── requirements.txt        # Python 依赖
├── requirements-test.txt   # 测试依赖（pytest、pytest-asyncio、httpx）
├── pytest.ini              # asyncio_mode = auto
├── main.spec               # PyInstaller 配置
├── tests/                  # 后端单元测试（pytest）
│   ├── conftest.py         # fixtures：auth mock、app factory、load_dotenv
│   ├── helpers.py          # 测试工具函数
│   └── test_*.py           # 路由 / 权限 / 任务 / 存储 / 结果 / AI 回归，完整清单以文件系统为准
├── gateway/                # 对外 API 网关
├── task_worker/            # Redis 描述符队列消费者、GPU 队列运行时与任务恢复
├── backend/
│   ├── ai/                 # AI 服务与任务实现
│   ├── auth/               # 认证模型与 FastAPI-Users 配置
│   ├── common/             # 配置、Redis、端口发现、通用工具
│   ├── database/           # SQLAlchemy 模型与仓储层
│   ├── autoresearch/      # AutoResearch / AutoResearch runtime、编排、持久化与 sandbox
│   ├── annotation/         # 协作标注 pubsub、presence、COCO/summary 辅助
│   ├── preprocessing/      # WSI 图像服务与辅助缓存逻辑
│   └── storage/            # 存储统计、迁移、清理
├── build/                  # 打包产物目录
└── dist/                   # 打包产物目录
```

## 服务职责

| 服务 | 当前职责 |
|------|----------|
| Gateway | 认证、用户管理、WSI / 任务 / 结果 / 聊天 / 存储 / 设置 / AutoResearch 等对外 API |
| Preprocessing | WSI 基本信息、图像、缩略图、DZI、瓦片、热图辅助、ROI 提取与部分 COCO 标注导出逻辑 |
| AI | 训练、推理、特征提取、聚合器 / 分类器注册与模型内部接口 |
| TaskWorker | 独立消费 Redis 任务描述符，拥有 GPU 任务队列、取消订阅、运行时快照发布与训练恢复 |

AutoResearch 不是单独的 HTTP sidecar。它的用户入口由 Gateway 的 `autoresearch_router` 暴露，实际运行时与 AutoResearch 编排代码在 `backend/autoresearch/` 中，历史索引写入 `auto_research_*` ORM 表，完整 OpenHands/AutoResearch workspace 与 artifact 保留在磁盘。

## 任务调度边界

Gateway 负责把训练、推理、分析和补丁类长任务序列化为 Redis 任务描述符，并通过 `/queue` 等接口读取 TaskWorker 发布的运行时状态。Gateway 不在自身生命周期中初始化队列运行时或执行训练恢复；GPU 队列运行时由 TaskWorker 初始化并消费描述符。聊天 PDF 的 Marker GPU 升级路径仍通过共享 `TaskQueueManager` 提交，但队列所有权属于 TaskWorker 运行时。

TaskWorker 是任务执行边界。它从 Redis 描述符队列中 claim 任务，放入 processing 列表，执行完成后 ack；失败时按重试上限重新入队，达到上限后进入 DLQ。取消请求会先写入短 TTL 的 durable cancellation key，再发布 pub/sub 消息；TaskWorker 同时用 job lock 防止同一 job descriptor 被重复执行。启动恢复时，TaskWorker 会先把遗留在 processing 列表中的描述符救回 pending 队列，再执行持久化训练恢复。

`/queue` 返回的运行时状态区分两类计数：GPU 队列内部的 `running_count` / `pending_count` / `queue_size`，以及 Redis 描述符队列的 `descriptor_pending_count` / `descriptor_processing_count` / `descriptor_dlq_count`。

## 运行依赖

- PostgreSQL：元数据与业务状态
- Redis：任务队列、日志、进度与部分缓存
- `uploads/`：WSI、特征缓存、模型、日志、标注、AutoResearch workspace / artifact 及衍生文件
- 上传目录解析顺序：`PATHLAB_UPLOADS_DIR` 环境变量 > `storage.json` 中的 `uploads_dir` > 系统 app data 目录下的 `uploads/`

默认配置可在 `backend/common/config.py` 中看到，包括：

- `DATABASE_URL_DEFAULT=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab`
- `REDIS_URL_DEFAULT=redis://localhost:6379/0`

## 当前实现重点

- `main.py` 中 Preprocessing 默认以 **4 个 worker** 启动（`PREPROCESSING_WORKERS` 环境变量可覆盖），并默认设置 `PREPROCESSING_MAX_REQUESTS=500`（每个 worker 处理满 500 个请求后自动回收，释放 C 库内存；`PREPROCESSING_MAX_REQUESTS` 可覆盖）
- `main.py` 通过 `multiprocessing.Process` 拉起 3 个 uvicorn 服务和 1 个 TaskWorker，并统一清理子进程
- Gateway 会在自身生命周期中初始化数据库、Redis 和若干启动期清理逻辑
- 任务队列初始化、GPU 探测与训练恢复由独立的 `TaskWorker` 进程负责，Gateway 通过 Redis 消费其发布的运行时快照与心跳
- AI 与 Preprocessing 的内部服务地址通过环境变量注入给 Gateway
- Gateway 同时直接注册 AutoResearch router，并以 `/api` prefix 再注册一份；因此 AutoResearch API 同时可通过 `/autoresearch/...` 与 `/api/autoresearch/...` 访问
- `main.spec` 用于将 sidecar 打包为独立可执行文件
- `main.py` 会尊重预先设置的 `CUDA_VISIBLE_DEVICES`，否则在启动时自动探测坏卡并收缩可见 GPU 集合

## 单元测试

后端测试基于 **pytest** + **pytest-asyncio** + **httpx**，覆盖配置层、Gateway 路由以及 AI 模型推理。

```bash
# 在 pathlab-client/ 目录下运行
python -m pytest server/tests/ -v

# 跳过需要 GPU 的预训练模型测试
python -m pytest server/tests/ -v -k "not pretrained"

# 单独运行预训练模型测试（需 GPU，耗时较长）
python -m pytest server/tests/test_ai_extractors_pretrained.py -v
```

安装测试依赖：

```bash
pip install -r server/requirements-test.txt
```

当前后端测试按行为域组织，完整清单以 `server/tests/test_*.py` 为准，主要覆盖：

- 配置与运行时：`test_config.py`、`test_settings.py`、`test_queue_config.py`、`test_gateway_*`、`test_gpu_*`
- 认证与权限：`test_auth_*`、`test_user_activation_backfill.py`、`test_permission_*`
- 任务 taxonomy 与调度：`test_task_taxonomy.py`、`test_*_task_taxonomy.py`、`test_training_*`、`test_resume_tasks.py`
- 存储与数据一致性：`test_storage_*`、`test_uploads_boundary.py`、`test_dataset_repository_namespacing.py`
- AutoResearch / AutoResearch：`test_autoresearch_routes.py`、`test_autoresearch_process_registry.py`，以及 `backend/autoresearch/tests/`
- 结果、分析与推理：`test_ai_result_store*.py`、`test_*analysis*.py`、`test_batch_inference.py`、`test_patching_stage.py`
- AI 模型 smoke：`test_ai_models.py`、`test_fm_segmentation_decoders.py`；`test_ai_extractors_pretrained.py` 需 GPU / HuggingFace token，单独运行

**测试设计要点**

- **路由测试**：创建只挂载单个 router 的裸 FastAPI app，`app.dependency_overrides` 替换 auth 依赖，`httpx.AsyncClient(transport=ASGITransport(...))` 发请求，不依赖真实 DB / Redis / GPU
- **Config 测试**：每个测试的 setup / teardown 两端均重置 `Config._global_settings_cache`、`_global_settings_dirty`、`_task_timeout`，防止缓存跨测试污染
- **预训练模型测试**：用模块级 `_MODEL_CACHE` dict 跨 parametrize 用例复用同一模型实例，避免重复加载大模型
- **HF Token**：通过 `.env`（已 gitignored）传入，`conftest.py` 顶部 `load_dotenv` 加载；`.env.example` 含 `HF_TOKEN` 占位说明

## 相关文档

- [Permissions README](permissions/README.md)
- [Gateway README](gateway/README.md)
- [Backend Services README](backend/README.md)
- [AutoResearch README](backend/autoresearch/README.md)
- [Database README](backend/database/README.md)
- [Storage README](backend/storage/README.md)
