# PathLab Client

> 适用版本：`PathLab v1.0.5`

`pathlab-client/` 是当前主应用目录，包含 Electron 宿主、React 渲染层、Python sidecar，以及固定端口部署所需的运维脚本。

## 当前入口文件

- `electron.vite.config.ts`：Electron `main` / `preload` / `renderer` 联合构建入口
- `src/main/index.ts`：Electron 主进程入口
- `src/main/sidecar-manager.ts`：Python sidecar 启停与端口发现
- `src/preload/index.ts`：向渲染层暴露后端端口发现能力
- `src/renderer/vite.config.ts`：独立 Web 构建入口
- `server/main.py`：Python sidecar 统一入口
- `scripts/build-python.sh`：Python sidecar 打包脚本（PyInstaller onedir 模式）
- `scripts/prepare-redis.sh`：嵌入式 Redis 二进制准备脚本
- `server/main.spec`：PyInstaller spec（onedir 模式，含完整依赖配置）
- `deploy/start.sh` / `deploy/hot-reload.sh`：固定端口部署与热更新脚本
- `package.json`：Electron 开发 / 构建脚本定义（`dev`、`build`、`start` 等）

## 当前目录结构

```text
pathlab-client/
├── deploy/                 # 启动、热更新、Nginx、systemd 模板
├── logs/                   # 固定端口脚本输出日志
├── server/                 # Python sidecar
│   ├── tests/              # 后端单元测试（pytest，29 个测试文件）
│   │   ├── conftest.py     # fixtures（auth mock、app factory）
│   │   ├── helpers.py      # 测试工具函数
│   │   ├── test_config.py
│   │   ├── test_settings.py
│   │   ├── test_queue_config.py
│   │   ├── test_ai_models.py
│   │   ├── test_ai_extractors_pretrained.py
│   │   ├── test_chat_continuation_helpers.py
│   │   ├── test_chat_conversation_title_extraction.py
│   │   ├── test_feature_cache_nowait.py
│   │   ├── test_fm_segmentation_decoders.py
│   │   ├── test_gpu_control.py
│   │   ├── test_patching_stage.py
│   │   ├── test_resume_tasks.py
│   │   ├── test_task_queue_patching.py
│   │   ├── test_training_routing.py
│   │   ├── test_permission_logic.py
│   │   ├── test_permission_policy_updates.py
│   │   ├── test_permission_revocation_fixes.py
│   │   ├── test_permission_closure_regressions.py
│   │   └── test_dataset_repository_namespacing.py
│   ├── pytest.ini          # asyncio_mode = auto
│   └── requirements-test.txt
├── src/
│   ├── main/               # Electron 主进程
│   ├── preload/            # Electron preload
│   └── renderer/           # React + Vite 前端
├── test/                   # 前端单元测试（Vitest）
│   ├── setup.ts            # 全局 mock 初始化
│   ├── unit/api/           # API 客户端层测试（20 个文件）
│   ├── unit/lib/           # 工具函数 / Hook 测试（13 个文件）
│   ├── unit/contexts/      # React Context 测试（1 个文件）
│   └── unit/components/    # 组件测试（4 个文件）
├── scripts/                # 构建辅助脚本
│   ├── build-python.sh     # Python sidecar 打包（PyInstaller）
│   └── prepare-redis.sh    # 嵌入式 Redis 二进制准备
├── vitest.config.ts        # Vitest 配置
├── electron.vite.config.ts
├── package.json
└── README.md
```

## 运行方式说明

### 1. Electron / 动态端口模式

- 主进程启动 sidecar
- `server/main.py` 自动选择可用端口
- Gateway 端口通过 stdout / preload / IPC 传给渲染层
- 前端运行时据此更新 API 基址
- 主进程当前还处理 `pathlab://` 深链登录回调，并向渲染层暴露文件 / 目录选择 IPC

### 2. 固定端口调试 / 部署模式

- `PATHLAB_DEBUG=1` 时使用 `6100 / 6101 / 6102`
- `deploy/start.sh` 与 `deploy/hot-reload.sh` 也围绕这组端口工作
- 浏览器调试、Nginx 反向代理和本地运维脚本都按这组端口设计

## 当前代码层次

### Electron 宿主

- `src/main/index.ts` 负责窗口生命周期、深链回调、权限请求，以及嵌入式 PostgreSQL / Redis 与 Python sidecar 的协同启停
- `src/preload/index.ts` 暴露认证回调、后端端口发现、文件 / 目录选择 IPC
- `src/main/services-manager.ts` 负责嵌入式 PostgreSQL / Redis 的端口选择、数据目录和启动探测
- `src/main/sidecar-manager.ts` 将 `Gateway / Preprocessing / AI` 端口变化推送给渲染层，并在 Gateway `/health` 就绪后再向渲染层放行

### 前端

- React 18 + TypeScript + Vite + Tailwind CSS
- BrowserRouter / HashRouter 双运行时
- 模块化 API 客户端位于 `src/renderer/src/api/`
- React Query、TooltipProvider 与多层 Context 在 `src/renderer/src/main.tsx` 中统一装配
- 浏览器模式支持 PWA；Electron 模式不注册 Service Worker

### 后端

- Gateway 负责认证、公开 API、任务编排与静态资源挂载
- Preprocessing 负责 WSI 信息、图像、缩略图、DZI、瓦片与部分热图辅助逻辑
- AI 服务负责训练、推理与模型相关内部能力
- PostgreSQL + Redis + `uploads/` 共同组成运行时状态层

## 当前已确认的实现事实

- Gateway 当前直接注册 17 个顶层 router；`server/gateway/routes/` 目录里实际共有 49 个路由模块文件，其中一部分作为分析 / 聊天 / 存储 / 训练辅助模块被复用
- 数据库当前可见 ORM 表为 21 个，其中标注表为 `segmentation_annotations`，权限相关表统一为 `dataset_grants` 与 `permission_audit_logs`
- 前端构建更应以 `vite.config.ts`、`electron.vite.config.ts` 与 `deploy/` 脚本为准，而不是沿用旧版 README 的脚本描述
- `server/backend/` 当前已收敛为 `ai / annotation / auth / common / database / preprocessing / storage` 七组共享模块

## 测试

### 前端测试（Vitest）

基于 **Vitest** + **@testing-library/react**，覆盖全部 API 客户端模块、工具函数库和 AuthContext。

```bash
npm run test:run      # 单次全量运行
npm run test          # 交互式监听模式
npm run test:coverage # 生成覆盖率报告
```

当前共 **40 个测试文件**：

| 分类 | 文件 | 覆盖内容 |
|------|------|---------|
| API 基础 | `unit/api/client.test.ts` | ApiError、apiFetch、token 管理、session 过期事件 |
| API 基础 | `unit/api/crypto.test.ts` | SHA-256（Web Crypto + JS Fallback）、APP_SALT |
| 业务 API | `unit/api/auth.test.ts` | 登录（哈希密码）、登出、获取当前用户、头像管理 |
| 业务 API | `unit/api/wsi.test.ts` | WSI / 数据集 CRUD、上传、CSV 导入、模板下载 |
| 业务 API | `unit/api/training.test.ts` | 训练任务、模型、特征提取器 |
| 业务 API | `unit/api/results.test.ts` | 推理结果查询与删除 |
| 业务 API | `unit/api/stats.test.ts` | 存储统计、近期活动、用户用量 |
| 业务 API | `unit/api/chat.test.ts` | AI 对话会话 CRUD、SSE 流式请求、PDF 管理 |
| 业务 API | `unit/api/heatmap.test.ts` | 热图列表、数据获取、URL 构建、缓存失效 |
| 业务 API | `unit/api/users.test.ts` | 管理员用户 CRUD、权限、维护公告 |
| 业务 API | `unit/api/analysis.test.ts` | 外部验证提交、分析触发、分析状态轮询 |
| 业务 API | `unit/api/batchInference.test.ts` | 无标签数据集批量推理任务创建、列表、结果查询、CSV 导出 |
| 业务 API | `unit/api/annotation.test.ts` | 标注草稿 CRUD、标签读取（/labels）、协作标注全流程、协作者管理、审计日志、WebSocket 协作 URL |
| 业务 API | `unit/api/export.test.ts` | 异步导出任务创建、状态轮询、文件下载 |
| 业务 API | `unit/api/feedback.test.ts` | 消息反馈提交 / 删除、管理员查看、统计导出 |
| 业务 API | `unit/api/grants.test.ts` | 数据集临时提权授权 / 撤销、批量操作 |
| 业务 API | `unit/api/queue.test.ts` | GPU 队列状态、配置读写、任务取消 |
| 业务 API | `unit/api/settings.test.ts` | 公开设置读取、全局设置读写 |
| 业务 API | `unit/api/storage.test.ts` | 存储配置、统计、孤立项、迁移、扫描、批量任务 |
| 业务 API | `unit/api/trainingOptions.test.ts` | 训练选项读取（提取器、聚合器、分割架构等）|
| 工具函数 | `unit/lib/cache.test.ts` | TTL 缓存、键值缓存、持久化缓存、并发去重 |
| 工具函数 | `unit/lib/avatarUrl.test.ts` | 头像 URL 绝对路径保留、根路径拼接与空值处理 |
| 工具函数 | `unit/lib/utils.test.ts` | cn()、formatBytes()、formatFileSize() |
| 工具函数 | `unit/lib/chatMessageParser.test.ts` | AI 消息净化、PDF 上下文检测 |
| 工具函数 | `unit/lib/datasetPagination.test.ts` | clampDatasetPage() 翻页边界逻辑 |
| 工具函数 | `unit/lib/segmentationUploadUtils.test.ts` | stem 提取、JSON 文件合并、图像 / JSON 匹配摘要 |
| 工具函数 | `unit/lib/externalValidationUtils.test.ts` | 任务类型判断、提取器维度表、数据集兼容性过滤 |
| 工具函数 | `unit/lib/trainingSubmissionTracker.test.ts` | localStorage 训练提交状态机（pending / created / failed / cancelled / 过期清理）|
| 工具函数 | `unit/lib/useAsyncAction.test.tsx` | `useAsyncAction` Hook：isPending 状态、并发引用计数、onError 回调、默认 console.error 降级 |
| 工具函数 | `unit/lib/useConfirmDialog.test.tsx` | `useConfirmDialog` Hook |
| 工具函数 | `unit/lib/useDebounce.test.tsx` | `useDebounce` Hook |
| 工具函数 | `unit/lib/listPageFileView.test.ts` | `getListPageFileViewState()` 列表页文件视图状态机逻辑 |
| React Context | `unit/contexts/AuthContext.test.tsx` | 认证状态机、角色判断、协议签署、维护公告 |
| 组件 | `unit/components/settings/PermissionCenterModal.test.tsx` | 权限中心弹窗数据集选择与展示逻辑 |
| 组件 | `unit/components/settings/UsersTab.test.tsx` | 管理员创建用户流程 |
| 组件 | `unit/components/settings/CreateUserModal.test.tsx` | 创建用户弹窗字段文案 |
| 组件 | `unit/components/settings/EditUserModal.test.tsx` | 编辑用户弹窗字段文案 |
| 组件 | `unit/components/settings/storage/BatchScanResults.test.tsx` | 存储批量扫描结果展示组件 |
| 组件 | `unit/components/ui/modal-shell.test.tsx` | ModalShell 基础弹窗组件 |
| 组件 | `unit/components/ui/pagination-footer.test.tsx` | PaginationFooter 分页组件 |

全部 API 测试文件均使用 `test/helpers/apiHelpers.ts` 中的工具函数（`ok` / `errResp` / `noContent` / `blobResp` / `createSSEStream`）构造 Response mock，详细说明见 [test/README.md](test/README.md)。

### 后端测试（pytest）

基于 **pytest** + **pytest-asyncio** + **httpx**，覆盖配置层、Gateway 路由以及 AI 模型推理（含 GPU smoke test）。

```bash
# 安装测试依赖
pip install -r server/requirements-test.txt

# 运行全部后端测试（跳过预训练模型）
python -m pytest server/tests/ -v -k "not pretrained"

# 运行预训练模型测试（需 GPU，耗时较长）
python -m pytest server/tests/test_ai_extractors_pretrained.py -v
```

当前共 **29 个测试文件**（含 5 个权限专项、4 个 AI 模型测试，以及 8 个 Gateway / 预处理 / 运行时辅助测试）：

| 文件 | 测试数 | 覆盖内容 |
|------|--------|---------|
| `server/tests/test_config.py` | 28 | Config 全局设置、任务超时、并发数、维护模式 |
| `server/tests/test_settings.py` | 19 | GET/POST /settings 路由、check-vllm |
| `server/tests/test_queue_config.py` | 15 | GET/POST /queue/config、GET /queue/{id} |
| `server/tests/test_ai_models.py` | 54 | GPU 环境、extractor/aggregator/classifier 注册与 forward pass |
| `server/tests/test_ai_extractors_pretrained.py` | ~216 | 18 个 HuggingFace 预训练模型加载与推理验证 |
| `server/tests/test_fm_segmentation_decoders.py` | — | 分割模型 decoder 结构与输出维度 |
| `server/tests/test_feature_cache_nowait.py` | — | 特征缓存非阻塞写入逻辑 |
| `server/tests/test_gpu_control.py` | — | GPU 坏卡探测与 CUDA_VISIBLE_DEVICES 控制 |
| `server/tests/test_patching_stage.py` | — | 推理流水线 patching 阶段逻辑 |
| `server/tests/test_task_queue_patching.py` | — | 任务队列 patching 操作 |
| `server/tests/test_resume_tasks.py` | — | 中断任务恢复逻辑 |
| `server/tests/test_training_routing.py` | — | 训练任务路由与调度 |
| `server/tests/test_chat_continuation_helpers.py` | — | AI 对话续接辅助函数 |
| `server/tests/test_chat_conversation_title_extraction.py` | — | 会话标题提取逻辑 |
| `server/tests/test_auth_dependencies.py` | — | token 参数 / header 鉴权依赖与 scoped session 使用 |
| `server/tests/test_coords_utils.py` | — | H5 坐标属性加载异常兜底 |
| `server/tests/test_permission_logic.py` | — | 权限判断核心逻辑 |
| `server/tests/test_permission_policy_updates.py` | — | 权限策略变更后的行为回归 |
| `server/tests/test_permission_revocation_fixes.py` | — | 权限撤销边界修复验证 |
| `server/tests/test_permission_closure_regressions.py` | — | 权限闭包回归测试 |
| `server/tests/test_dataset_repository_namespacing.py` | — | 数据集仓储命名空间隔离 |
| `server/tests/test_batch_inference.py` | — | 批量推理任务类型、请求模型校验与完整推理流程回归 |
| `server/tests/test_gateway_app_setup.py` | — | router 注册与静态资源挂载 |
| `server/tests/test_gateway_cleanup.py` | — | 旧任务 / 过期权限清理提交逻辑 |
| `server/tests/test_gateway_runtime_orchestration.py` | — | Gateway 启停序列、预热任务与 HTTP client 装配 |
| `server/tests/test_gateway_startup.py` | — | 内部服务健康探测等待逻辑 |
| `server/tests/test_gpu_utils.py` | — | NVML 回退路径下的 GPU 数量与显存信息 |
| `server/tests/test_preprocessing_slide_access.py` | — | slide cache 命中与驱逐 |
| `server/tests/test_training_recommendation_paths.py` | — | 训练推荐知识运行时目录布局 |

详细说明见 [server/README.md](server/README.md)。

## 推荐阅读顺序

1. [server/README.md](server/README.md)
2. [server/permissions/README.md](server/permissions/README.md)
3. [server/gateway/README.md](server/gateway/README.md)
4. [server/backend/database/README.md](server/backend/database/README.md)
5. [src/renderer/README.md](src/renderer/README.md)
6. [deploy/README.md](deploy/README.md)
7. [test/README.md](test/README.md)
