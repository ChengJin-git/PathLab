# PathLab Python Backend

> 适用版本：`PathLab v1.0.5`

`server/` 是当前 Python sidecar 目录。它不是单一 FastAPI 应用，而是由 `main.py` 统一拉起 **Gateway / Preprocessing / AI** 三个服务进程，并复用 `backend/` 下的共享模块。

## 当前启动方式

### 统一入口

- 文件：`server/main.py`
- 作用：
  - 选择固定端口或动态端口
  - 设置服务发现环境变量
  - 启动 3 个 uvicorn 进程
  - 在退出时统一清理子进程

### 两种端口模式

| 模式 | 端口 | 触发方式 |
|------|------|----------|
| 调试 / 固定端口 | Gateway `6100`、Preprocessing `6101`、AI `6102` | `PATHLAB_DEBUG=1` |
| Electron / 动态端口 | 3 个服务自动分配可用端口 | 默认 sidecar 启动方式 |

## 当前目录结构

```text
server/
├── main.py                 # 统一入口，负责拉起 3 个服务
├── requirements.txt        # Python 依赖
├── requirements-test.txt   # 测试依赖（pytest、pytest-asyncio、httpx）
├── pytest.ini              # asyncio_mode = auto
├── main.spec               # PyInstaller 配置
├── tests/                  # 后端单元测试（pytest）
│   ├── conftest.py         # fixtures：auth mock、app factory、load_dotenv
│   ├── helpers.py          # 测试工具函数
│   └── test_*.py           # 路由 / 权限 / 任务 / 存储 / 结果 / AI 回归，完整清单以文件系统为准
├── gateway/                # 对外 API 网关
├── backend/
│   ├── ai/                 # AI 服务与任务实现
│   ├── auth/               # 认证模型与 FastAPI-Users 配置
│   ├── common/             # 配置、Redis、端口发现、通用工具
│   ├── database/           # SQLAlchemy 模型与仓储层
│   ├── annotation/         # 协作标注 pubsub、presence、COCO/summary 辅助
│   ├── preprocessing/      # WSI 图像服务与辅助缓存逻辑
│   └── storage/            # 存储统计、迁移、清理
├── build/                  # 打包产物目录
└── dist/                   # 打包产物目录
```

## 三个服务的职责

| 服务 | 当前职责 |
|------|----------|
| Gateway | 认证、用户管理、WSI / 任务 / 结果 / 聊天 / 存储 / 设置等对外 API |
| Preprocessing | WSI 基本信息、图像、缩略图、DZI、瓦片、热图辅助、ROI 提取与部分 COCO 标注导出逻辑 |
| AI | 训练、推理、特征提取、聚合器 / 分类器注册与模型内部接口 |

## 运行依赖

- PostgreSQL：元数据与业务状态
- Redis：任务队列、日志、进度与部分缓存
- `uploads/`：WSI、特征缓存、模型、日志、标注及衍生文件

默认配置可在 `backend/common/config.py` 中看到，包括：

- `DATABASE_URL_DEFAULT=postgresql+asyncpg://pathlab:pathlab@localhost:5432/pathlab`
- `REDIS_URL_DEFAULT=redis://localhost:6379/0`

## 当前实现重点

- `main.py` 中 Preprocessing 允许多 worker，并支持 `PREPROCESSING_MAX_REQUESTS`
- `main.py` 通过 `multiprocessing.Process` 拉起 3 个 uvicorn 服务并统一清理子进程
- Gateway 会在自身生命周期中初始化数据库、Redis、任务队列和若干启动期清理逻辑
- AI 与 Preprocessing 的内部服务地址通过环境变量注入给 Gateway
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
- [Database README](backend/database/README.md)
- [Storage README](backend/storage/README.md)
