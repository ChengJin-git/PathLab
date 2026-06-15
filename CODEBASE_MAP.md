# PathLab 中文模块地图
> 最后更新：2026-06-05  
> 适用版本：V 1.0.5
---

## 项目概览

**项目用途：** PathLab 是面向数字病理研究的桌面 / Web 一体化应用。主应用位于 `pathlab/pathlab-client/`，同时支持 Electron 桌面运行、浏览器调试和固定端口 Web 部署。

**技术栈：**

- 桌面宿主：Electron、electron-vite、embedded PostgreSQL、嵌入式 Redis / Garnet。
- 前端：React 18、TypeScript、Vite 7、Tailwind CSS 4、React Query、Vitest。
- 后端：Python FastAPI、uvicorn、SQLAlchemy async、PostgreSQL、Redis、pytest。
- AI / 图像：PyTorch、WSI 图像读取、特征提取器、MIL aggregator、分类 / 生存 / 分割训练与推理。

**主要入口：**

| 场景 | 入口 | 说明 |
|---|---|---|
| Electron 主进程 | `pathlab/pathlab-client/src/main/index.ts` | 创建窗口、深链登录、IPC、启动嵌入式服务与 Python sidecar。 |
| Electron preload | `pathlab/pathlab-client/src/preload/index.ts` | 暴露端口发现、认证回调、文件 / 目录选择 API。 |
| 前端应用 | `pathlab/pathlab-client/src/renderer/src/main.tsx`、`App.tsx` | 装配 Router、Context、PWA 与页面路由。 |
| Python sidecar | `pathlab/pathlab-client/server/main.py` | 统一拉起 Gateway、Preprocessing、AI 和 TaskWorker。 |
| Gateway | `pathlab/pathlab-client/server/gateway/main.py` | 对外 API、认证、业务聚合、静态资源挂载。 |
| Preprocessing | `pathlab/pathlab-client/server/backend/preprocessing/main.py` | WSI 信息、缩略图、DZI、tile、ROI / COCO 辅助。 |
| AI 服务 | `pathlab/pathlab-client/server/backend/ai/main.py` | 训练、推理、模型与特征提取内部接口。 |
| TaskWorker | `pathlab/pathlab-client/server/task_worker/main.py` | Redis 描述符队列消费者，长任务与 GPU 队列执行边界。 |
| 固定端口部署 | `pathlab/pathlab-client/deploy/start.sh` | 构建前端，固定 `6100 / 6101 / 6102` 启动后端。 |

**架构摘要：** Electron 主进程启动 PostgreSQL / Redis 与 Python sidecar；sidecar 再启动 3 个 HTTP 服务和 1 个无端口后台 worker。Gateway 对外提供 API，长任务只写 Redis 任务描述符；TaskWorker 负责 claim、执行、ack、重试和 DLQ；Preprocessing 提供底层图像服务；AI 服务提供训练 / 推理内部能力；React 前端通过模块化 API client 消费 Gateway / Preprocessing / AI。

---

## 目录结构

```text
.
├── README.md                                      # 仓库总览、运行形态和文档入口
├── CODEBASE_MAP.md                               # 本中文模块地图
├── .agents/skills/codebase-explorer/             # 本次使用的模块地图生成 skill
└── pathlab/pathlab-client/
    ├── README.md                                 # 主应用说明
    ├── package.json                              # npm 脚本、Electron Builder、前端依赖
    ├── electron.vite.config.ts                   # Electron main / preload / renderer 联合构建
    ├── vitest.config.ts                          # 前端单元测试配置
    ├── deploy/                                   # 固定端口 Web 部署、Nginx、systemd 模板
    ├── scripts/                                  # Python sidecar 打包、Redis 准备、patch 应用
    ├── server/
    │   ├── main.py                               # Python sidecar 统一入口
    │   ├── gateway/                              # 对外 FastAPI Gateway
    │   ├── task_worker/                          # Redis 任务描述符消费者
    │   ├── backend/                              # 后端共享模块与内部服务
    │   │   ├── ai/                               # 训练、推理、模型注册、任务实现
    │   │   ├── annotation/                       # 标注协作、presence、COCO / summary 辅助
    │   │   ├── auth/                             # 用户模型与 FastAPI-Users 配置
    │   │   ├── common/                           # 配置、Redis、端口、GPU、进度、文件类型
    │   │   ├── database/                         # ORM、session、Repository
    │   │   ├── preprocessing/                    # WSI 图像 / tile / DZI / ROI 服务
    │   │   └── storage/                          # 存储统计、迁移、孤立项清理
    │   └── tests/                                # 后端 pytest 单元测试
    ├── src/
    │   ├── main/                                 # Electron 主进程
    │   ├── preload/                              # Electron preload 桥接
    │   └── renderer/
    │       └── src/                              # React 应用真实源码
    │           ├── api/                          # 模块化 API client
    │           ├── components/                   # 业务组件与基础 UI
    │           ├── contexts/                     # Auth / BackgroundTask / Toast
    │           ├── constants/                    # 训练、文件、展示常量
    │           ├── lib/                          # 工具函数、hooks、阅片辅助
    │           ├── locales/                      # `en-US` / `zh-CN` / `zh-HK`
    │           ├── pages/                        # 页面级组件
    │           └── types/                        # 前端类型声明
    └── test/                                     # 前端 Vitest 单元测试
```

已排除：`node_modules/`、`dist/`、`build/`、`__pycache__/`、`.vite/`、测试覆盖率和其他构建缓存。

---

## 功能数据流

新增功能时优先从这里判断数据流，再进入 `快速定位索引` 查具体文件和函数。表里的路径是首选入口，不表示唯一调用点。

| 功能链路 | 前端入口 | API client | 后端入口 | 数据模型 / 后台执行 |
|---|---|---|---|---|
| 实验记录 / 结果列表 | `src/renderer/src/pages/ResultsViewerPage.tsx`：`ResultsViewerPage()`、`filterTasksByQuery()` | `api/results.ts`：`fetchAllResults()`；`api/training.ts`：`getTrainingTasks()`；`api/analysis.ts`：analysis 查询函数 | `gateway/routes/results.py`：`get_all_results()`、`get_analysis_tasks()`；`gateway/routes/training.py`：`list_training_tasks()` | `TrainingTask`、`AIResult`、`AnalysisRun` |
| 实验记录筛选 / 搜索 | `ResultsViewerPage.tsx`：`filterTasksByQuery()` 和页面 state | `api/training.ts`：`TrainingTaskListQuery`、`getTrainingTasks()` | `gateway/routes/training.py`：`list_training_tasks()`；必要时扩展 `results.py` 的任务查询 | `TrainingTask` 字段、相关前端测试 `ResultsViewerPage.sse.test.tsx` |
| 实验记录展示字段 | `ResultsViewerPage.tsx`：任务卡片 / 分析卡片渲染 | `api/results.ts`、`api/training.ts`、`api/analysis.ts` 对应 interface | `gateway/routes/results.py`：`get_analysis_tasks()`、`get_task_analysis()`、`get_quick_analysis()`；`training.py`：`get_training_task()` | `TrainingTask`、`AIResult`、`AnalysisRun`；测试 `results.test.ts`、`analysis.test.ts`、`training.test.ts` |
| 训练日志展示 | `src/renderer/src/pages/TaskDetailPage.tsx`；后台任务 context | `api/training.ts`：`getTrainingTask()`、训练日志相关请求 | `gateway/routes/training.py`：`get_training_logs()`、`stream_training_logs()`、`get_recent_training_logs()` | `TrainingLog`；测试 `test_training_task_dispatch.py`、前端 `training.test.ts` |
| 分析与快速分析 | `ResultsViewerPage.tsx`：`runAnalysis`、quick analysis UI | `api/analysis.ts`：`runTaskAnalysis()`、`getTaskQuickAnalysis()`、`getAnalysisStatus()` | `gateway/routes/results.py`：`run_task_analysis()`、`get_quick_analysis()`、`get_analysis_status()`、`stream_analysis_tasks()` | `AnalysisRun`；TaskWorker `jobs/analysis.py`；测试 `test_task_worker_analysis.py` |
| 分析结果文件下载 | `ResultsViewerPage.tsx`：分析详情 / 文件链接 | `api/analysis.ts` 或 `api/export.ts` 相关下载函数 | `gateway/routes/results.py`：`get_analysis_file()` | `AnalysisRun` 输出目录、analysis artifacts |
| 报告 / 导出 | `src/renderer/src/pages/ReportGeneratorPage.tsx`：`ReportGeneratorPage()` | `api/export.ts`：`startAsyncExport()`、`startAnalysisFullExport()`、`getAnalysisFullExportStatus()`、`downloadAnalysisFullExportFile()` | `gateway/routes/results.py`：`start_segmentation_analysis_full_export()`、`get_segmentation_analysis_full_export_status()`、`download_segmentation_analysis_full_export()` | `ExportTask`；测试 `export.test.ts`、`test_segmentation_analysis_export.py` |
| 批量 / 独立推理记录 | `ResultsViewerPage.tsx` 的 batch / independent inference 视图 | `api/batchInference.ts`：`startBatchInference()`、`listBatchInferenceTasks()`、`startIndependentInference()` | `gateway/routes/results.py`：`start_batch_inference()`、`list_batch_inference_tasks()`、`start_independent_inference()`、`list_independent_inference_tasks()` | Redis descriptor -> `TaskWorker` -> `AIResult`；测试 `test_results_task_dispatch.py` |
| 任务取消状态 | `TaskListPage.tsx`、`TaskDetailPage.tsx`、`ResultsViewerPage.tsx` | `api/queue.ts`：`cancelQueueTask()`；`api/training.ts` delete / status 函数 | `gateway/routes/queue.py`：`cancel_queued_task()`；`gateway/routes/training.py`：task status endpoints | Redis cancellation key、`TaskWorkerRuntime.handle_cancel_message()` |
| AI 对话引用实验记录 | `AIChatPage.tsx`、chat cards | `api/chat.ts`：`chatWithAI()`、conversation / patch inference 函数 | `gateway/routes/chat.py`：`chat_with_ai()`、`stream_ai_response()`；必要时读取 `results.py` / `training.py` 数据 | `ChatConversation`、`ChatMessage`、`TrainingTask`、`AIResult` |

---

## 模块拆解

### `/pathlab/pathlab-client`

**Role:** 主应用包，聚合 Electron、React、Python sidecar、测试和部署配置。  
**Sub-README:** 有，说明 v1.0.5 的入口文件、运行方式、测试命令和阅读顺序。  
**Depends on:** Node.js、Python、PostgreSQL、Redis / Garnet、OpenSlide / 图像依赖。  
**Used by:** 开发者、桌面打包脚本、固定端口部署脚本。

#### Files

| File | Purpose |
|---|---|
| `package.json` | npm 脚本、Electron Builder 配置、前端和 Electron 依赖声明。 |
| `electron.vite.config.ts` | Electron main / preload / renderer 构建入口。 |
| `server/main.py` | Python sidecar 统一入口。 |
| `vitest.config.ts` | 前端测试运行范围和 jsdom 配置。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `npm run dev` | script | [ENTRY] | 启动 Electron 开发模式。 |
| `npm run build` | script | [ENTRY] | 执行 Electron Vite 构建。 |
| `npm run build:python` | script | [ENTRY] | 用 PyInstaller 打包 Python sidecar。 |
| `npm run test:run` | script | [TEST] | 单次运行前端 Vitest 测试。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改桌面打包资源 | `pathlab/pathlab-client/package.json` | `build.extraResources` |
| 新增 npm 脚本 | `pathlab/pathlab-client/package.json` | `scripts` |
| 调整前端测试匹配规则 | `pathlab/pathlab-client/vitest.config.ts` | `test.include` |

---

### `/pathlab/pathlab-client/src/main`

**Role:** Electron 主进程，负责窗口生命周期、深链登录、IPC、嵌入式 PostgreSQL / Redis 和 Python sidecar 启停。  
**Sub-README:** 无。  
**Depends on:** Electron、`sidecar-manager.ts`、`services-manager.ts`、preload bundle。  
**Used by:** Electron 桌面运行和打包产物。

#### Files

| File | Purpose |
|---|---|
| `index.ts` | 主进程入口，创建窗口、处理 `pathlab://`、注册 IPC、启动 sidecar。 |
| `sidecar-manager.ts` | 启动 Python sidecar，解析 Gateway / 服务端口并通知 renderer。 |
| `services-manager.ts` | 管理嵌入式 PostgreSQL 与 Redis / Garnet 的端口、数据目录和进程。 |
| `types/` | Electron / preload 相关类型声明。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `handleDeepLink(url)` | function | [CORE] | 解析 `pathlab://auth` 回调并把 auth code 发送给 renderer。 |
| `createWindow()` | function | [ENTRY] | 创建 BrowserWindow、权限处理和页面加载。 |
| `startPythonSidecar(extraEnv?)` | function | [CORE] | 启动 Python sidecar 并等待 Gateway 端口。 |
| `getServicePorts()` | function | [API] | 返回 Gateway / Preprocessing / AI 当前端口。 |
| `startEmbeddedServices()` | function | [CORE] | 打包环境下启动 PostgreSQL 和 Redis / Garnet。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改桌面窗口尺寸或加载逻辑 | `pathlab/pathlab-client/src/main/index.ts` | `createWindow()` |
| 新增 Electron IPC 能力 | `pathlab/pathlab-client/src/main/index.ts` | `ipcMain.handle(...)` |
| 调整 sidecar 启动或端口解析 | `pathlab/pathlab-client/src/main/sidecar-manager.ts` | `startPythonSidecar()` |
| 调整嵌入式数据库 / Redis 行为 | `pathlab/pathlab-client/src/main/services-manager.ts` | `startEmbeddedServices()` |

---

### `/pathlab/pathlab-client/src/preload`

**Role:** Electron preload 桥接层，向前端暴露安全的 Electron API。  
**Sub-README:** 无。  
**Depends on:** Electron `contextBridge` / `ipcRenderer`。  
**Used by:** `src/renderer/src/config.ts`、登录回调、上传 / 注册页面的文件选择能力。

#### Files

| File | Purpose |
|---|---|
| `index.ts` | 暴露 auth callback、端口发现、文件选择、目录选择和外部链接打开能力。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `BackendServicePorts` | interface | [API] | Gateway / Preprocessing / AI 端口类型。 |
| `api` | const | [API] | 通过 `contextBridge` 暴露给 renderer 的桥接对象。 |
| `API` | type | [API] | preload 暴露 API 的 TypeScript 类型。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 给前端新增桌面原生能力 | `pathlab/pathlab-client/src/preload/index.ts` | `api` |
| 修改端口发现桥接 | `pathlab/pathlab-client/src/preload/index.ts` | `getServicePorts` / `onServicePorts` |

---

### `/pathlab/pathlab-client/src/renderer/src`

**Role:** React 应用真实源码，包含路由、页面、组件、API client、Context、工具和本地化。  
**Sub-README:** 有，记录路由、API client 拆分、运行时端口发现和组件分层。  
**Depends on:** React、React Router、React Query、preload API、Gateway / Preprocessing / AI HTTP API。  
**Used by:** Electron renderer、浏览器部署静态资源。

#### Files

| File | Purpose |
|---|---|
| `main.tsx` | 初始化 API 端口、选择 HashRouter / BrowserRouter、装配 Provider。 |
| `App.tsx` | 页面路由入口和受保护路由配置。 |
| `config.ts` | Gateway / Preprocessing / AI 地址解析与运行时端口更新。 |
| `api/client.ts` | 前端 API 请求公共封装。 |
| `contexts/AuthContext.tsx` | 登录态、用户信息、登出和认证上下文。 |
| `contexts/backgroundTask/` | 训练、分析、存储任务相关 SSE / 动作封装。 |
| `pages/` | 页面级组件，承载主要用户工作流。 |
| `components/` | 聊天、阅片、上传、训练、设置、结果和基础 UI 组件。 |
| `lib/` | 缓存、格式化、训练配置、阅片导航、聊天块解析等工具。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `App()` | function | [ENTRY] | 定义 `/dashboard`、`/settings`、`/task-setup`、`/wsi/:wsi_id` 等主路由。 |
| `initializeApiConfig()` | function | [CORE] | 前端启动时发现后端端口并初始化 API base。 |
| `updateApiBase()` | function | [CORE] | 收到端口变更时刷新 Gateway / Preprocessing / AI base URL。 |
| `AuthProvider` | function | [CORE] | 提供认证状态和用户操作。 |
| `ProtectedRoute` | function | [API] | 封装登录、管理员和 GPU 权限路由保护。 |
| `createCache()` / `createKeyedCache()` | function | [UTIL] | API 层缓存原语。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 新增或调整页面路由 | `pathlab/pathlab-client/src/renderer/src/App.tsx` | `App()` |
| 修改应用启动 Provider | `pathlab/pathlab-client/src/renderer/src/main.tsx` | React root render |
| 修改后端地址解析 | `pathlab/pathlab-client/src/renderer/src/config.ts` | `initializeApiConfig()` / `updateApiBase()` |
| 修改认证状态逻辑 | `pathlab/pathlab-client/src/renderer/src/contexts/AuthContext.tsx` | `AuthProvider` |
| 修改任务配置页面 | `pathlab/pathlab-client/src/renderer/src/pages/NewTaskPage.tsx` | `NewTaskPage()` |
| 修改阅片器页面 | `pathlab/pathlab-client/src/renderer/src/pages/WSIViewerPage.tsx` | `WSIViewerPage()` |
| 修改结果查看 / 分析页面 | `pathlab/pathlab-client/src/renderer/src/pages/ResultsViewerPage.tsx` | `ResultsViewerPage()` |
| 修改存储管理界面 | `pathlab/pathlab-client/src/renderer/src/pages/StorageManagementPage.tsx` | `StorageManagementPage()` |

---

### `/pathlab/pathlab-client/src/renderer/src/api`

**Role:** 前端模块化 API client，按业务域封装 Gateway / Preprocessing / AI 请求。  
**Sub-README:** 无，概览记录在 `src/renderer/src/README.md`。  
**Depends on:** `api/client.ts`、`config.ts`、浏览器 `fetch`。  
**Used by:** 页面、Context、组件和前端测试。

#### Files

| File | Purpose |
|---|---|
| `auth.ts` / `users.ts` | 登录、注册、用户资料、管理员用户管理、维护模式。 |
| `wsi.ts` | WSI / dataset 列表、详情、上传、CSV / COCO 模板、元数据。 |
| `training.ts` / `trainingOptions.ts` | 训练任务、模型列表、训练选项。 |
| `queue.ts` | GPU 队列状态、并发配置、取消任务。 |
| `results.ts` / `analysis.ts` / `batchInference.ts` | 结果、分析、外部验证、批量 / 独立推理。 |
| `annotation.ts` / `grants.ts` | 标注、协作、presence、权限授权。 |
| `chat.ts` / `feedback.ts` | AI 对话、会话、patch inference、消息反馈。 |
| `storage.ts` | 存储统计、迁移、扫描、孤立项清理、后台存储任务。 |
| `settings.ts` / `stats.ts` / `heatmap.ts` | 全局设置、首页统计、热图与缩略图 URL。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `loginWithCredentials()` | function | [API] | 调用 `/auth/secure-login` 完成登录。 |
| `fetchWSIList()` / `fetchDatasets()` | function | [API] | 读取 WSI 与 dataset 列表。 |
| `createTrainingTask()` | function | [API] | 提交训练任务配置。 |
| `getQueueStatus()` / `cancelQueueTask()` | function | [API] | 查询 TaskWorker 队列状态和取消任务。 |
| `chatWithAI()` | function | [API] | 流式 AI 对话请求。 |
| `getStorageStats()` / `scanDirectory()` | function | [API] | 存储统计和外部目录扫描。 |
| `saveAnnotation()` / `finalizeSharedAnnotation()` | function | [API] | 保存个人 / 协作标注。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 新增前端对 Gateway 的 API 调用 | `pathlab/pathlab-client/src/renderer/src/api/` | 对应业务文件 |
| 修改统一请求错误处理 | `pathlab/pathlab-client/src/renderer/src/api/client.ts` | 请求封装函数 |
| 修改训练任务提交 payload | `pathlab/pathlab-client/src/renderer/src/api/training.ts` | `TrainingTaskConfig` / `createTrainingTask()` |
| 修改标注协作接口 | `pathlab/pathlab-client/src/renderer/src/api/annotation.ts` | shared / presence / audit 函数 |
| 修改存储管理接口 | `pathlab/pathlab-client/src/renderer/src/api/storage.ts` | storage functions |

---

### `/pathlab/pathlab-client/server`

**Role:** Python sidecar 目录，不是单一 FastAPI 应用；`main.py` 统一拉起 Gateway / Preprocessing / AI / TaskWorker。  
**Sub-README:** 有，说明端口模式、服务职责、任务调度边界和测试方式。  
**Depends on:** `backend.common.config`、`backend.common.port_utils`、uvicorn、multiprocessing。  
**Used by:** Electron 主进程、`deploy/start.sh`、systemd 模板。

#### Files

| File | Purpose |
|---|---|
| `main.py` | 统一入口，动态或固定分配端口，启动 4 个子进程并清理。 |
| `requirements.txt` | Python 运行依赖。 |
| `requirements-test.txt` | pytest、pytest-asyncio、httpx 等测试依赖。 |
| `main.spec` | PyInstaller onedir 打包配置。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `main()` | function | [ENTRY] | 选择端口、设置服务发现环境变量、启动服务进程。 |
| `run_service(app_module, port, name, ...)` | function | [CORE] | 在子进程内运行 uvicorn 服务。 |
| `run_task_worker()` | function | [CORE] | 启动无端口 TaskWorker。 |
| `_detect_and_exclude_bad_gpus()` | function | [UTIL] | 尊重或自动设置 `CUDA_VISIBLE_DEVICES`，排除坏卡。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 调整固定端口 / 动态端口策略 | `pathlab/pathlab-client/server/main.py` | `main()` |
| 调整 Preprocessing worker 数或回收策略 | `pathlab/pathlab-client/server/main.py` | `PREPROCESSING_WORKERS` / `PREPROCESSING_MAX_REQUESTS` |
| 修改坏 GPU 自动探测逻辑 | `pathlab/pathlab-client/server/main.py` | `_detect_and_exclude_bad_gpus()` |
| 修改 PyInstaller 打包内容 | `pathlab/pathlab-client/server/main.spec` | spec 配置 |

---

### `/pathlab/pathlab-client/server/gateway`

**Role:** 对外 API Gateway，负责认证、业务聚合、静态资源挂载、任务描述符入队和内部服务协作。  
**Sub-README:** 有，详细记录直接注册的 router、任务边界、静态资源和模块职责。  
**Depends on:** `backend/` 共享模块、Preprocessing / AI 内部服务、Redis、PostgreSQL。  
**Used by:** React API client、Nginx 反向代理、Electron renderer。

#### Files

| File | Purpose |
|---|---|
| `main.py` | Gateway FastAPI 应用入口和生命周期装配。 |
| `app_setup.py` | 注册顶层 router，挂载 `/avatars`、`/assets`、`/images`。 |
| `startup.py` | 数据库、Redis、启动期清理和预热逻辑。 |
| `task_dispatch.py` | 构造并写入 Redis 任务描述符。 |
| `task_queue.py` | GPU 队列运行时类型和共享调度实现，实际运行时由 TaskWorker 初始化。 |
| `routes/` | 公开 API router 和支持模块。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `include_api_routers(app)` | function | [ENTRY] | 直接注册 auth、stats、wsi、training、results、storage、queue、annotation 等 router。 |
| `mount_static_routes(app, renderer_dist?)` | function | [CORE] | 挂载头像和前端构建产物静态目录。 |
| `enqueue_task_descriptor(...)` | function | [CORE] | Gateway 侧把长任务提交给 Redis 描述符队列。 |
| `auth_router` | router | [API] | 登录、注册、用户管理、维护模式和头像。 |
| `training_router` | router | [API] | 训练任务创建、列表、日志、模型关联。 |
| `results_router` | router | [API] | 结果、分析、外部验证、批量 / 独立推理。 |
| `storage_router` | router | [API] | 存储统计、迁移、孤立项、扫描和存储任务。 |
| `annotation_router` | router | [API] | 标注草稿、labels、协作、presence、审计。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 新增公开 API router | `pathlab/pathlab-client/server/gateway/app_setup.py` | `include_api_routers()` |
| 修改认证 / 用户管理 | `pathlab/pathlab-client/server/gateway/routes/auth.py` | `secure_login()` / user endpoints |
| 修改 WSI 列表 / 数据集接口 | `pathlab/pathlab-client/server/gateway/routes/wsi.py` | `router = APIRouter(prefix="/wsi")` |
| 修改上传 / 注册数据 | `pathlab/pathlab-client/server/gateway/routes/wsi_upload.py` | upload endpoints |
| 修改训练任务入队 | `pathlab/pathlab-client/server/gateway/routes/training.py` | `create_training_task()` |
| 修改结果 / 分析 / 推理流程 | `pathlab/pathlab-client/server/gateway/routes/results.py` | analysis / inference endpoints |
| 修改队列状态和取消 | `pathlab/pathlab-client/server/gateway/routes/queue.py` | `get_queue_status()` / `cancel_queued_task()` |
| 修改存储管理接口 | `pathlab/pathlab-client/server/gateway/routes/storage.py` | storage endpoints |
| 修改存储后台任务 | `pathlab/pathlab-client/server/gateway/routes/storage_tasks.py` | task start / stream endpoints |
| 修改标注协作 | `pathlab/pathlab-client/server/gateway/routes/annotation.py` | shared / collaborators / presence endpoints |
| 修改 AI 对话 | `pathlab/pathlab-client/server/gateway/routes/chat.py` | `chat_with_ai()` / `stream_ai_response()` |

---

### `/pathlab/pathlab-client/server/task_worker`

**Role:** 后台任务执行边界，消费 Redis 描述符队列，初始化 GPU 队列运行时，执行训练、推理、分析和聊天 patch inference。  
**Sub-README:** 无，职责记录在 `server/README.md` 和 `gateway/README.md`。  
**Depends on:** `gateway.task_dispatch`、`gateway.task_queue`、`backend.common.gpu_utils`、AI / Gateway job wrapper。  
**Used by:** `server/main.py`、Gateway `/queue` 状态、长任务执行流程。

#### Files

| File | Purpose |
|---|---|
| `main.py` | worker runtime、heartbeat、取消订阅、恢复和主循环。 |
| `handlers.py` | 根据 descriptor handler 分发到训练、推理、分析等任务。 |
| `recovery.py` | 启动时恢复遗留 processing descriptor 和 interrupted tasks。 |
| `runtime_status.py` | 构造并发布 TaskWorker 运行时快照。 |
| `jobs/` | 按任务类型封装 training、inference、analysis、chat_patch 等执行函数。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `TaskWorkerRuntime` | class | [CORE] | 封装 dequeue、dispatch、heartbeat、cancel loop 和 shutdown。 |
| `dispatch_descriptor(descriptor)` | function | [CORE] | 根据任务描述符选择具体 handler。 |
| `resume_interrupted_tasks()` | function | [CORE] | 启动恢复训练 / 推理相关遗留任务。 |
| `publish_runtime_status(queue)` | function | [API] | 发布给 Gateway `/queue` 使用的运行时快照。 |
| `handle_training_run()` | function | [CORE] | 运行训练任务 descriptor。 |
| `handle_inference_batch()` | function | [CORE] | 运行批量推理 descriptor。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 新增一种长任务 descriptor | `pathlab/pathlab-client/server/task_worker/handlers.py` | `_register()` / `dispatch_descriptor()` |
| 修改 worker 心跳和状态快照 | `pathlab/pathlab-client/server/task_worker/main.py` | `heartbeat_once()` |
| 修改启动恢复策略 | `pathlab/pathlab-client/server/task_worker/recovery.py` | `resume_interrupted_tasks()` |
| 修改训练任务执行包装 | `pathlab/pathlab-client/server/task_worker/jobs/training.py` | `run_training_pipeline()` |
| 修改推理任务执行包装 | `pathlab/pathlab-client/server/task_worker/jobs/inference.py` | inference job functions |

---

### `/pathlab/pathlab-client/server/backend/common`

**Role:** 后端共享基础设施，包含配置、Redis、端口、GPU、文件类型、进度、日志和 split 生成。  
**Sub-README:** 无，概览记录在 `backend/README.md`。  
**Depends on:** OS 环境变量、Redis、PyTorch / pynvml、文件系统。  
**Used by:** Gateway、AI、Preprocessing、TaskWorker、Storage。

#### Files

| File | Purpose |
|---|---|
| `config.py` | 全局配置、端口默认值、uploads 目录解析、持久设置。 |
| `redis_client.py` | Redis connection pool、初始化和 key helper。 |
| `port_utils.py` | 空闲端口发现和 stdout 端口公告。 |
| `gpu_utils.py` | GPU 健康、VRAM、可用设备选择和任务 GPU 选择。 |
| `progress_store.py` | Redis progress / task owner 存取。 |
| `slide_utils.py` / `file_types.py` | WSI / patch 文件识别与 slide 加载辅助。 |
| `split_generation.py` | 分类、生存、分割数据划分辅助。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `Config` | class | [CONFIG] | 统一配置入口，含默认端口、数据库、Redis、uploads 目录和全局设置。 |
| `get_redis()` | function | [CORE] | 获取当前事件循环的 Redis client。 |
| `find_free_port()` | function | [UTIL] | 为动态端口模式查找可用端口。 |
| `announce_port(port, service_name)` | function | [API] | 输出 Electron 可解析的端口公告。 |
| `get_gpu_count()` / `probe_all_gpu_health()` | function | [UTIL] | GPU 数量和健康检查。 |
| `select_optimal_gpu_for_task()` | function | [CORE] | 按 VRAM 选择任务 GPU。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改 uploads 目录优先级 | `pathlab/pathlab-client/server/backend/common/config.py` | `Config.get_uploads_dir()` |
| 修改默认端口 / DB / Redis | `pathlab/pathlab-client/server/backend/common/config.py` | `Config` constants |
| 修改 Redis key 或连接管理 | `pathlab/pathlab-client/server/backend/common/redis_client.py` | `get_redis()` / `make_key()` |
| 修改 GPU 选择策略 | `pathlab/pathlab-client/server/backend/common/gpu_utils.py` | `select_optimal_gpu_for_task()` |
| 修改文件类型识别 | `pathlab/pathlab-client/server/backend/common/file_types.py` | `is_patch_file()` |

---

### `/pathlab/pathlab-client/server/backend/database`

**Role:** SQLAlchemy 数据访问层，负责 ORM 模型、异步 session、初始化和 Repository。  
**Sub-README:** 有，记录 22 个 ORM 表、annotation 命名规范、Repository 现状和旧文档差异。  
**Depends on:** SQLAlchemy async、PostgreSQL、`backend.auth.models.User`。  
**Used by:** Gateway、Preprocessing、AI、Storage、TaskWorker。

#### Files

| File | Purpose |
|---|---|
| `database.py` | async engine 和 session 工厂。 |
| `models.py` | 业务 ORM 模型。 |
| `init_db.py` | 初始化和建表逻辑。 |
| `repositories/` | 按业务拆分的数据访问对象。 |
| `migrate_task_taxonomy.py` | 任务 taxonomy / data group 迁移脚本。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `Dataset` / `WSISlide` | class | [CORE] | 数据集和 WSI 元数据核心模型。 |
| `TrainingTask` / `TrainedModel` | class | [CORE] | 训练任务和模型记录。 |
| `AIResult` / `AnalysisRun` | class | [CORE] | 推理结果和分析运行记录。 |
| `SegmentationAnnotation` | class | [CORE] | 分割标注、草稿、共享草稿和 GT 记录。 |
| `DatasetGrant` / `PermissionAuditLog` | class | [CORE] | 数据集授权和权限审计。 |
| `BaseRepository` | class | [UTIL] | Repository 通用基类。 |
| `TrainingTaskRepository` | class | [CORE] | 训练任务数据访问和 WSI 关联。 |
| `SegmentationAnnotationRepository` | class | [CORE] | 标注版本、所有权和读写逻辑。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 新增数据库表或字段 | `pathlab/pathlab-client/server/backend/database/models.py` | 对应 ORM class |
| 修改用户字段 | `pathlab/pathlab-client/server/backend/auth/models.py` | `User` |
| 新增仓储方法 | `pathlab/pathlab-client/server/backend/database/repositories/` | 对应 Repository |
| 修改标注数据一致性 | `pathlab/pathlab-client/server/backend/database/repositories/annotation.py` | `SegmentationAnnotationRepository` |
| 修改权限授权读写 | `pathlab/pathlab-client/server/backend/database/repositories/dataset_grant.py` | `DatasetGrantRepository` |

---

### `/pathlab/pathlab-client/server/backend/auth`

**Role:** 用户模型、JWT / FastAPI-Users 配置和认证 schema。  
**Sub-README:** 无，认证现状记录在 Gateway 和 Database README。  
**Depends on:** FastAPI-Users、SQLAlchemy、JWT strategy。  
**Used by:** Gateway route dependency、用户管理、权限系统。

#### Files

| File | Purpose |
|---|---|
| `models.py` | `users` ORM 表和业务字段。 |
| `users.py` | FastAPI-Users 配置、用户数据库、认证后端。 |
| `schemas.py` | 用户读写 schema。 |
| `dependencies.py` | 当前用户、管理员、活跃用户等依赖。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `User` | class | [CORE] | 认证用户表，包含 role、avatar、session_nonces、agreement、notice 等业务字段。 |
| `current_active_user` | dependency | [API] | Gateway 路由常用登录用户依赖。 |
| `require_admin` | dependency | [API] | 管理员接口权限依赖。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改用户 ORM 字段 | `pathlab/pathlab-client/server/backend/auth/models.py` | `User` |
| 修改认证 backend / JWT 策略 | `pathlab/pathlab-client/server/backend/auth/users.py` | auth backend setup |
| 修改用户 schema | `pathlab/pathlab-client/server/backend/auth/schemas.py` | schema classes |
| 修改权限依赖 | `pathlab/pathlab-client/server/backend/auth/dependencies.py` | dependency functions |

---

### `/pathlab/pathlab-client/server/backend/preprocessing`

**Role:** 内部 Preprocessing FastAPI 服务，提供 WSI 图像读取、缩略图、DZI、tile、patch、ROI 提取和部分 COCO 缓存生成。  
**Sub-README:** 无，职责记录在 `backend/README.md`。  
**Depends on:** OpenSlide / slide SDK、PIL、数据库、uploads 目录、annotation helper。  
**Used by:** Gateway、前端阅片器、AI / 训练数据准备。

#### Files

| File | Purpose |
|---|---|
| `main.py` | Preprocessing FastAPI app 和主要图像接口。 |
| `heatmap_routes.py` | 热图相关辅助接口。 |
| `slide_cache.py` / cache helpers | slide handle 缓存与释放。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `health()` | function | [API] | 服务健康检查。 |
| `get_wsi_info(wsi_id)` | function | [API] | 读取 WSI 尺寸、倍率等基础信息。 |
| `get_thumbnail(...)` | function | [API] | 生成 / 返回缩略图。 |
| `get_dzi(wsi_id, ...)` | function | [API] | 返回 Deep Zoom Image 描述。 |
| `get_tile(...)` | function | [API] | 返回 OpenSeadragon tile。 |
| `extract_regions(...)` | function | [API] | 异步提取标注 ROI 到新数据集。 |
| `_extract_segmentation_dataset(...)` | function | [CORE] | 生成分割数据集和 COCO 标注缓存。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改 tile / DZI 行为 | `pathlab/pathlab-client/server/backend/preprocessing/main.py` | `get_dzi()` / `get_tile()` |
| 修改缩略图或 patch 图像 | `pathlab/pathlab-client/server/backend/preprocessing/main.py` | `get_thumbnail()` / `get_patch_image()` |
| 修改 ROI 提取 | `pathlab/pathlab-client/server/backend/preprocessing/main.py` | `extract_regions()` |
| 修改热图辅助接口 | `pathlab/pathlab-client/server/backend/preprocessing/heatmap_routes.py` | route functions |

---

### `/pathlab/pathlab-client/server/backend/ai`

**Role:** 内部 AI 服务和训练 / 推理实现，包含特征提取器、aggregator、classifier、task trainer、schema 和 route。  
**Sub-README:** 无，概览记录在 `backend/README.md`。  
**Depends on:** PyTorch、模型 checkpoint、uploads、数据库、GPU 工具。  
**Used by:** Gateway、TaskWorker、Preprocessing 生成的数据。

#### Files

| File | Purpose |
|---|---|
| `main.py` | AI FastAPI app，挂载 training / inference router。 |
| `routes/training.py` | 特征提取、WSI 分类、生存、patch 分类、patch 分割训练入口。 |
| `routes/inference.py` | WSI 分析和推理 pipeline。 |
| `extractors/registry.py` | 特征提取器注册、解析和可用列表。 |
| `aggregators/` | ABMIL、CLAM、DSMIL、DTFD、MeanMIL、MaxMIL、TransMIL 等 MIL aggregator。 |
| `classifiers/` | Linear、MLP、Attention classifier 和 registry。 |
| `tasks/` | 分类、生存、patch 分类、patch 分割 trainer。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `train_wsi_classification()` | function | [API] | WSI 分类训练入口。 |
| `train_wsi_survival()` | function | [API] | WSI 生存训练入口。 |
| `train_patch_classification()` | function | [API] | patch 分类训练入口。 |
| `train_patch_segmentation()` | function | [API] | patch 分割训练入口。 |
| `run_inference_pipeline()` | function | [CORE] | 异步推理 pipeline。 |
| `get_extractor()` / `list_extractors()` | function | [CORE] | 特征提取器 registry 查询。 |
| `WSIClassificationTrainer` | class | [CORE] | WSI 分类 trainer。 |
| `WSISurvivalTrainer` | class | [CORE] | 生存分析 trainer。 |
| `PatchClassificationTrainer` | class | [CORE] | patch 分类 trainer。 |
| `SegmentationTrainer` | class | [CORE] | patch 分割 trainer。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 新增特征提取器 | `pathlab/pathlab-client/server/backend/ai/extractors/registry.py` | `register_extractor()` |
| 新增 MIL aggregator | `pathlab/pathlab-client/server/backend/ai/aggregators/` | `BaseAggregator` 子类和 registry |
| 新增 classifier | `pathlab/pathlab-client/server/backend/ai/classifiers/` | `BaseClassifier` 子类和 registry |
| 修改 WSI 分类训练 | `pathlab/pathlab-client/server/backend/ai/tasks/wsi_classification/trainer.py` | `WSIClassificationTrainer` |
| 修改 WSI 生存训练 | `pathlab/pathlab-client/server/backend/ai/tasks/wsi_survival/trainer.py` | `WSISurvivalTrainer` |
| 修改 patch 分割训练 | `pathlab/pathlab-client/server/backend/ai/tasks/patch_segmentation/trainer.py` | `SegmentationTrainer` |
| 修改推理 pipeline | `pathlab/pathlab-client/server/backend/ai/routes/inference.py` | `run_inference_pipeline()` |

---

### `/pathlab/pathlab-client/server/backend/annotation`

**Role:** 标注共享辅助模块，不是独立服务；提供 COCO 导出、summary 缓存、协作 pub/sub 和 presence。  
**Sub-README:** 无，概览记录在 `backend/README.md`。  
**Depends on:** Redis、uploads、database annotation model。  
**Used by:** Gateway annotation route、Preprocessing ROI / COCO 流程。

#### Files

| File | Purpose |
|---|---|
| `coco_utils.py` | COCO 标注导出辅助。 |
| `summary_cache.py` | 数据集 / 草稿标注摘要缓存。 |
| `pubsub.py` | 协作标注事件广播。 |
| `presence_pubsub.py` | 在线协作 presence 广播。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `build_dataset_annotation_summary_cache()` | function | [CORE] | 从标注和 WSI 构造数据集摘要缓存。 |
| `rebuild_dataset_annotation_summary_cache()` | function | [CORE] | 异步重建数据集标注摘要。 |
| `build_effective_summary_from_cache()` | function | [UTIL] | 基于缓存构造有效 summary。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改 COCO 导出结构 | `pathlab/pathlab-client/server/backend/annotation/coco_utils.py` | COCO helper |
| 修改标注 summary 缓存 | `pathlab/pathlab-client/server/backend/annotation/summary_cache.py` | cache build / rebuild functions |
| 修改协作广播 | `pathlab/pathlab-client/server/backend/annotation/pubsub.py` | pubsub helpers |
| 修改 presence 逻辑 | `pathlab/pathlab-client/server/backend/annotation/presence_pubsub.py` | presence helpers |

---

### `/pathlab/pathlab-client/server/backend/storage`

**Role:** 文件系统存储管理层，负责统计、迁移、孤立文件 / 记录检测和清理。  
**Sub-README:** 有，记录 uploads 目录优先级、统计类别、孤立项检测和 Gateway 暴露接口。  
**Depends on:** `Config.get_uploads_dir()`、database repositories、文件系统。  
**Used by:** Gateway `/storage` route、设置页存储管理视图、部署运维。

#### Files

| File | Purpose |
|---|---|
| `manager.py` | 统一入口 `StorageManager`，组合 stats / orphan mixin。 |
| `stats_mixin.py` | 分目录统计、WSI / training 存储信息。 |
| `orphan_mixin.py` | 孤立文件和孤立数据库记录检测。 |
| `migration.py` | uploads 根目录迁移。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `StorageManager` | class | [CORE] | 存储管理统一入口。 |
| `StorageStatsMixin` | class | [CORE] | 统计目录体积、文件数和分类占用。 |
| `StorageOrphanMixin` | class | [CORE] | 检测和清理孤立文件 / 记录。 |
| `MigrationManager` | class | [CORE] | 迁移 uploads 根目录。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改统计类别 | `pathlab/pathlab-client/server/backend/storage/stats_mixin.py` | `StorageStatsMixin` |
| 修改孤立文件检测 | `pathlab/pathlab-client/server/backend/storage/orphan_mixin.py` | `StorageOrphanMixin` |
| 修改迁移逻辑 | `pathlab/pathlab-client/server/backend/storage/migration.py` | `MigrationManager` |
| 新增统一存储能力 | `pathlab/pathlab-client/server/backend/storage/manager.py` | `StorageManager` |

---

### `/pathlab/pathlab-client/deploy`

**Role:** 固定端口 Web 部署与运维脚本，面向服务器部署、热更新、Nginx 和 systemd。  
**Sub-README:** 有，记录桌面打包、固定端口部署、GPU 控制、脚本行为和代理模板。  
**Depends on:** Node / npm、Python、Redis、PostgreSQL、Nginx、systemd。  
**Used by:** 浏览器调试和服务器部署。

#### Files

| File | Purpose |
|---|---|
| `start.sh` | 清理旧进程、安装依赖、构建前端、固定端口启动后端并健康检查。 |
| `hot-reload.sh` | 支持 frontend / backend / gateway / preprocessing / ai / all 热更新。 |
| `nginx/` | HTTPS 与 HTTP-only 反向代理模板。 |
| `systemd/pathlab.service` | systemd 服务模板。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `PATHLAB_DEBUG=1` | env | [CONFIG] | 固定端口模式开关。 |
| `GATEWAY_PORT=6100` | env | [CONFIG] | Gateway 固定端口。 |
| `PREPROCESSING_PORT=6101` | env | [CONFIG] | Preprocessing 固定端口。 |
| `AI_PORT=6102` | env | [CONFIG] | AI 固定端口。 |
| `CUDA_VISIBLE_DEVICES` | env | [CONFIG] | 运维侧 GPU 可见性控制。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 修改一键启动流程 | `pathlab/pathlab-client/deploy/start.sh` | script body |
| 修改热更新目标 | `pathlab/pathlab-client/deploy/hot-reload.sh` | target handlers |
| 修改 HTTPS 反代 | `pathlab/pathlab-client/deploy/nginx/pathlab.conf` | location blocks |
| 修改 HTTP-only 反代 | `pathlab/pathlab-client/deploy/nginx/pathlab-http-only.conf` | location blocks |
| 修改 systemd 环境 | `pathlab/pathlab-client/deploy/systemd/pathlab.service` | `Environment` / `EnvironmentFile` |

---

### `/pathlab/pathlab-client/test` 与 `/pathlab/pathlab-client/server/tests`

**Role:** 前端 Vitest 和后端 pytest 测试套件。  
**Sub-README:** 前端测试有 README；后端测试概览在 `server/README.md`。  
**Depends on:** Vitest、Testing Library、jsdom、pytest、pytest-asyncio、httpx。  
**Used by:** 开发回归、CI 和重构验证。

#### Files

| File | Purpose |
|---|---|
| `test/setup.ts` | 前端全局 mock：fetch、localStorage。 |
| `test/helpers/apiHelpers.ts` | 构造 Response mock 和 SSE stream。 |
| `test/unit/api/` | API client 单元测试。 |
| `test/unit/components/` | React 组件测试。 |
| `server/tests/conftest.py` | 后端 fixtures、auth mock、app factory、dotenv。 |
| `server/tests/test_*.py` | 路由、权限、任务、存储、分析、AI、GPU 回归测试。 |

#### Key Symbols

| Symbol | Kind | Tag | Description |
|---|---|---|---|
| `ok()` / `errResp()` / `createSSEStream()` | function | [TEST] | 前端 API 测试 Response mock 工具。 |
| `pytest.ini` | config | [TEST] | 后端 `asyncio_mode = auto`。 |
| `npm run test:run` | script | [TEST] | 前端全量单次测试。 |
| `python -m pytest server/tests/ -v` | command | [TEST] | 后端全量测试入口。 |

#### Where to Edit

| I want to... | File | Symbol / Line |
|---|---|---|
| 给新 API client 加测试 | `pathlab/pathlab-client/test/unit/api/` | 新增 `*.test.ts` |
| 修改前端测试全局 mock | `pathlab/pathlab-client/test/setup.ts` | setup hooks |
| 增加后端 route 测试 | `pathlab/pathlab-client/server/tests/` | 新增 `test_*.py` |
| 修改后端测试 fixtures | `pathlab/pathlab-client/server/tests/conftest.py` | fixtures |

---

## 快速定位索引

| 我想做什么 | 前端入口 | API client | 后端入口 | 数据模型 / 测试 |
|---|---|---|---|---|
| 新增实验记录筛选字段 | `ResultsViewerPage.tsx`：`filterTasksByQuery()`、筛选 state | `api/training.ts`：`TrainingTaskListQuery`、`getTrainingTasks()` | `gateway/routes/training.py`：`list_training_tasks()`；必要时 `results.py`：`get_analysis_tasks()` | `TrainingTask`；`test/unit/api/training.test.ts`、`ResultsViewerPage.sse.test.tsx` |
| 新增实验记录展示字段 | `ResultsViewerPage.tsx`：任务 / 分析卡片渲染 | `api/results.ts`、`api/analysis.ts`、`api/training.ts` 的 interface | `results.py`：`get_all_results()`、`get_analysis_tasks()`；`training.py`：`get_training_task()` | `TrainingTask`、`AIResult`、`AnalysisRun`；`results.test.ts`、`analysis.test.ts` |
| 优化实验记录列表加载 | `ResultsViewerPage.tsx`：React Query / SSE 合并逻辑 | `api/results.ts`：`fetchAllResults()`；`api/training.ts`：`getTrainingTasks()` | `results.py`：`get_all_results()`；`training.py`：`list_training_tasks()` | `AIResultRepository`、`TrainingTaskRepository`；`test_ai_result_store*.py` |
| 新增训练日志展示 | `TaskDetailPage.tsx`、background task context | `api/training.ts`：训练日志请求 | `training.py`：`get_training_logs()`、`stream_training_logs()`、`get_recent_training_logs()` | `TrainingLog`；`test_training_task_dispatch.py` |
| 修改分析任务创建 | `ResultsViewerPage.tsx`：`runAnalysis` | `api/analysis.ts`：`runTaskAnalysis()` | `results.py`：`run_task_analysis()`；TaskWorker `jobs/analysis.py` | `AnalysisRun`；`test_task_worker_analysis.py` |
| 修改快速分析结果 | `ResultsViewerPage.tsx`：quick analysis UI | `api/analysis.ts`：`getTaskQuickAnalysis()` | `results.py`：`get_quick_analysis()` | analysis artifacts；`test_external_validation_analysis.py` |
| 新增分析结果文件下载 | `ResultsViewerPage.tsx`：分析详情动作 | `api/analysis.ts` 或 `api/export.ts` | `results.py`：`get_analysis_file()` | `AnalysisRun` 输出目录 |
| 新增报告 / 导出项 | `ReportGeneratorPage.tsx` | `api/export.ts`：`startAsyncExport()`、`startAnalysisFullExport()` | `results.py`：`start_segmentation_analysis_full_export()`、`download_segmentation_analysis_full_export()` | `ExportTask`；`export.test.ts`、`test_segmentation_analysis_export.py` |
| 修改批量推理记录 | `ResultsViewerPage.tsx` batch inference 视图 | `api/batchInference.ts`：`startBatchInference()`、`listBatchInferenceTasks()` | `results.py`：`start_batch_inference()`、`list_batch_inference_tasks()` | `TrainingTask`、`AIResult`；`test_results_task_dispatch.py` |
| 修改独立推理记录 | `ResultsViewerPage.tsx` independent inference 视图 | `api/batchInference.ts`：`startIndependentInference()`、`listIndependentInferenceTasks()` | `results.py`：`start_independent_inference()`、`list_independent_inference_tasks()` | `TrainingTask`、`AIResult` |
| 修改训练任务提交 | `NewTaskPage.tsx`、训练 wizard hooks | `api/training.ts`：`TrainingTaskConfig`、`createTrainingTask()` | `training.py`：`create_training_task()` | `TrainingTask`、`TrainingTaskWSI`；`training.test.ts`、`test_training_preflight.py` |
| 修改训练实现 | 训练配置页面只负责提交 | 无直接前端实现 | `backend/ai/routes/training.py`、`backend/ai/tasks/` 对应 trainer | `WSIClassificationTrainer`、`WSISurvivalTrainer`、`SegmentationTrainer` |
| 修改任务取消状态 | `TaskListPage.tsx`、`TaskDetailPage.tsx`、`ResultsViewerPage.tsx` | `api/queue.ts`：`cancelQueueTask()` | `queue.py`：`cancel_queued_task()`；`task_worker/main.py`：`handle_cancel_message()` | Redis cancellation key；`test_task_worker_analysis.py` |
| 新增 TaskWorker 任务类型 | 无固定前端入口，通常由某个 API 提交 descriptor | 由对应业务 API client 调用 | `task_worker/handlers.py`：`_register()`、`dispatch_descriptor()`；`gateway/task_dispatch.py` | descriptor payload；`server/tests/test_*task_dispatch.py` |
| 修改 AI 对话引用实验记录 | `AIChatPage.tsx`、chat cards | `api/chat.ts`：`chatWithAI()` | `chat.py`：`chat_with_ai()`、`stream_ai_response()` | `ChatConversation`、`ChatMessage`、`TrainingTask`、`AIResult` |
| 修改权限控制 | `ProtectedRoute`、页面级按钮显示 | `api/grants.ts`、`api/auth.ts`、`api/users.ts` | `auth.py`、`access_control.py`、`wsi_grants.py` | `User`、`DatasetGrant`、`PermissionAuditLog` |
| 修改标注记录 / 审计 | `WSIViewerPage.tsx`、标注组件 | `api/annotation.ts`：audit / shared / labels 函数 | `annotation.py`：`list_annotation_audit()`、`export_annotation_audit_csv()`、shared endpoints | `SegmentationAnnotation`、`AnnotationAuditLog` |
| 修改存储统计 / 清理 | `StorageManagementPage.tsx`、settings storage components | `api/storage.ts`：`getStorageStats()`、`detectOrphanedFiles()`、`scanDirectory()` | `storage.py`、`storage_tasks.py`、`storage_scan.py` | `StorageManager`、`StorageTask`；`storage.test.ts` |
| 修改 WSI 列表 / dataset 行为 | `ListPage.tsx` | `api/wsi.ts`：`fetchWSIList()`、`fetchDatasets()` | `wsi.py`、`wsi_upload.py` | `Dataset`、`WSISlide`、`DatasetStats` |
| 修改上传 / 注册数据 | `UploadPage.tsx` | `api/wsi.ts`：`uploadWSIFile()`、`uploadWSIByPath()`、`uploadWSIByCSV()` | `wsi_upload.py`：file / path / csv endpoints | `Dataset`、`WSISlide`、`SegmentationAnnotation` |
| 修改阅片器 tile / DZI | `WSIViewerPage.tsx`、`components/wsiViewer/` | `api/heatmap.ts` URL helper、`api/annotation.ts` | `backend/preprocessing/main.py`：`get_dzi()`、`get_tile()`、`get_thumbnail()` | Preprocessing slide cache |
| 新增公开 Gateway API | 对应页面或组件 | `src/renderer/src/api/` 新增 / 扩展业务文件 | `gateway/routes/` 新增 router，并在 `app_setup.py`：`include_api_routers()` 注册 | 新增 API 测试：`test/unit/api/*.test.ts`、`server/tests/test_*.py` |
| 新增页面路由 | `App.tsx`：`App()` | 新页面需要的 API client | 对应 Gateway route | 前端页面 / 组件测试 |
| 新增桌面 IPC | 需要桌面能力的页面 / hook | preload exposed API type | `src/main/index.ts`：`ipcMain.handle()`；`src/preload/index.ts`：`api` | Electron 类型声明 |
| 修改 Electron sidecar 启动 | 无前端页面 | `config.ts` 消费端口 | `src/main/sidecar-manager.ts`：`startPythonSidecar()` | preload `BackendServicePorts` |
| 修改部署启动 | 无前端页面 | 无 | `deploy/start.sh`、`deploy/hot-reload.sh` | 部署 README / systemd / nginx |
| 给前端功能加测试 | 对应页面 / 组件 | `test/unit/api/` 对应 API 测试 | 不适用 | `test/helpers/apiHelpers.ts`、`test/setup.ts` |
| 给后端 route 加测试 | 不适用 | 用 httpx ASGITransport 发请求 | `server/tests/test_*.py` | `server/tests/conftest.py` fixtures |

---

## 统计

- **文档语言：** 中文；代码路径、文件名、类名、函数名和命令保留英文原文。
- **扫描范围：** `pathlab/pathlab-client/`，排除依赖、构建产物和缓存目录。
- **相关文件数：** 746。
- **源码文件数：** 706。
- **Python 源码文件：** 340。
- **TypeScript / TSX 源码文件：** 366。
- **估算关键符号数：** 4066 个类、函数、接口、类型或导出常量。
- **本地图谱 MCP 状态：** 当前项目图谱只有 35 个节点，覆盖偏浅；本文件以 README、源码和目录扫描为主，MCP 结果作辅助。
- **导航建议：** 新增功能时先查 `功能数据流` 确认前后端链路，再查 `快速定位索引` 定位文件和函数，最后进入对应 `模块拆解` 段落理解边界。
- **热点文件：**
  - `pathlab/pathlab-client/server/gateway/routes/results.py`：结果、分析、外部验证、批量 / 独立推理聚合点。
  - `pathlab/pathlab-client/server/gateway/routes/training.py`：训练任务创建、日志、模型和 GPU stage 聚合点。
  - `pathlab/pathlab-client/server/backend/common/config.py`：端口、数据库、Redis、uploads、全局设置的核心配置入口。
  - `pathlab/pathlab-client/src/renderer/src/config.ts`：前端运行时服务地址和端口发现入口。
  - `pathlab/pathlab-client/server/gateway/routes/chat.py`：AI 对话、训练推荐、PDF / patch inference 聚合点。

---

## 备注

- 旧文档如果提到单体 API / 单体后端服务，应以当前 Gateway / Preprocessing / AI / TaskWorker 四进程边界为准。
- 旧标注表名 `annotation_drafts` 已过时，当前 ORM 模型是 `SegmentationAnnotation`，表名是 `segmentation_annotations`。
- 长任务执行边界在 `server/task_worker/`；Gateway 负责描述符入队、状态查询和取消请求发布。
- 固定端口部署和 `PATHLAB_DEBUG=1` 共享 `6100 / 6101 / 6102` 端口约定。
