# PathLab Client

> 适用版本：`PathLab v1.0.5`

`pathlab-client/` 是当前主应用目录，包含 Electron 宿主、React 渲染层、Python sidecar（Gateway / Preprocessing / AI / TaskWorker），以及固定端口部署所需的运维脚本。`2026-06-23` 起，本目录还包含 AutoResearch 用户能力；其实现 codename 为 **PathScientist**。

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
- `package.json`：Electron 开发 / 构建脚本定义；当前 npm 脚本包括 `dev`、`build`、`build:python`、`prepare-redis`、`build:linux`、`build:mac`、`build:win`、`test`、`test:run`、`test:coverage` 等

## 当前目录结构

```text
pathlab-client/
├── deploy/                 # 启动、热更新、Nginx、systemd 模板
├── logs/                   # 固定端口脚本输出日志
├── server/                 # Python sidecar
│   ├── backend/            # 共享后端模块与内部服务实现
│   │   └── pathscientist/  # AutoResearch / PathScientist 运行时、编排、持久化与部署文档
│   ├── tests/              # 后端单元测试（pytest，路由 / 权限 / 任务 / 存储 / AI 回归）
│   │   ├── conftest.py     # fixtures（auth mock、app factory、load_dotenv）
│   │   ├── helpers.py      # 测试工具函数
│   │   └── test_*.py       # 以当前文件系统为准，不在 README 固定完整清单
│   ├── task_worker/        # Redis 描述符队列消费者与后台任务执行边界
│   ├── pytest.ini          # asyncio_mode = auto
│   └── requirements-test.txt
├── src/
│   ├── main/               # Electron 主进程
│   ├── preload/            # Electron preload
│   └── renderer/           # React + Vite 前端
├── test/                   # 前端单元测试（Vitest 2）
│   ├── setup.ts            # 全局 mock 初始化
│   ├── unit/api/           # API 客户端层测试
│   ├── unit/lib/           # 工具函数 / Hook 测试
│   ├── unit/contexts/      # React Context 测试
│   ├── unit/constants/     # 常量测试
│   ├── unit/pages/         # 页面级测试
│   └── unit/components/    # 组件测试
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
- `server/main.py` 自动选择 Gateway / Preprocessing / AI 端口，并拉起无 HTTP 端口的 TaskWorker
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
- `src/main/sidecar-manager.ts` 将 `Gateway / Preprocessing / AI` 端口变化推送给渲染层，并在 Gateway `/health` 就绪后再向渲染层放行；TaskWorker 作为 sidecar 后台进程运行但不暴露端口

### 前端

- React 18 + TypeScript + Vite 7 + Tailwind CSS 4
- BrowserRouter / HashRouter 双运行时
- 模块化 API 客户端位于 `src/renderer/src/api/`
- AutoResearch / PathScientist 前端入口位于 `/pathscientist`、`/pathscientist/new`、`/pathscientist/sessions/:id`，API 客户端为 `src/renderer/src/api/pathscientist.ts`
- React Query、TooltipProvider 与多层 Context 在 `src/renderer/src/main.tsx` 中统一装配
- 浏览器模式支持 PWA；Electron 模式不注册 Service Worker

### 后端

- Gateway 负责认证、公开 API、任务描述符入队 / 状态查询与静态资源挂载
- Preprocessing 负责 WSI 信息、图像、缩略图、DZI、瓦片与部分热图辅助逻辑
- AI 服务负责训练、推理与模型相关内部能力
- TaskWorker 负责消费 Redis 任务描述符、持有 GPU 队列、执行长任务并发布运行时快照
- PathScientist 是 AutoResearch 的实现 codename；Gateway 暴露 `/pathscientist` 与 `/api/pathscientist` 会话 API，`server/backend/pathscientist/` 提供 CLI/headless runtime、实验编排、数据集获取、文献/RAG、综合报告、持久化、sandbox/runtime 和 domain templates/skills
- PostgreSQL + Redis + `uploads/` 共同组成运行时状态层；`uploads/` 优先由 `PATHLAB_UPLOADS_DIR` 指定，其次读取 `storage.json`，否则落到系统 app data 目录

## 当前已确认的实现事实

- Gateway 顶层 router 由 `server/gateway/app_setup.py` 统一注册；`server/gateway/routes/` 下的部分模块作为分析 / 聊天 / 存储 / 训练辅助模块被复用，不一定单独挂载
- AutoResearch（codename PathScientist）于 `2026-06-23` 加入；前端、Gateway router、数据库 repository、artifact workspace 和部署脚本均已接入当前代码树
- 数据库当前可见 ORM 表为 26 个，其中标注表为 `segmentation_annotations`，权限相关表统一为 `dataset_grants` 与 `permission_audit_logs`，用户级 WSI split 覆盖表为 `wsi_slide_user_splits`，AutoResearch 历史使用 `auto_research_sessions` / `auto_research_experiments` / `auto_research_events` 与 `knowhow_entries`
- 前端构建更应以 `vite.config.ts`、`electron.vite.config.ts` 与 `deploy/` 脚本为准，而不是沿用旧版 README 的脚本描述
- `server/backend/` 当前已收敛为 `ai / annotation / auth / common / database / pathscientist / preprocessing / storage` 八组共享模块

## 测试

### 前端测试（Vitest）

基于 **Vitest** + **@testing-library/react**，覆盖全部 API 客户端模块、工具函数库和 AuthContext。

```bash
npm run test:run      # 单次全量运行
npm run test          # 交互式监听模式
npm run test:coverage # 生成覆盖率报告
```

当前测试入口由 `vitest.config.ts` 的 `include: ['test/**/*.test.{ts,tsx}']` 决定；不要在 README 固定完整文件数量，实际清单以 `test/unit/**` 为准。全部 API 测试文件均使用 `test/helpers/apiHelpers.ts` 中的工具函数（`ok` / `errResp` / `noContent` / `blobResp` / `createSSEStream`）构造 Response mock，详细说明见 [test/README.md](test/README.md)。测试运行器为 **Vitest 2**（`^2.1.9`）。

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

后端测试覆盖配置、认证、权限闭包、任务 taxonomy、Gateway 装配、存储迁移 / 扫描、结果读取、分析、GPU 队列、AI 模型路径与 PathScientist Gateway / 进程注册边界。PathScientist backend package 自身还带 `server/backend/pathscientist/tests/`。当前测试文件以 `server/tests/test_*.py` 与实际 package tests 为准；预训练模型测试单独运行，避免默认 CI 拉取大模型。详细说明见 [server/README.md](server/README.md)。

## 推荐阅读顺序

1. [server/README.md](server/README.md)
2. [server/backend/pathscientist/README.md](server/backend/pathscientist/README.md)
3. [server/permissions/README.md](server/permissions/README.md)
4. [server/gateway/README.md](server/gateway/README.md)
5. [server/backend/database/README.md](server/backend/database/README.md)
6. [src/renderer/README.md](src/renderer/README.md)
7. [deploy/README.md](deploy/README.md)
8. [test/README.md](test/README.md)
