# PathLab Client

> 适用版本：`PathLab v1.0.1`

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
├── src/
│   ├── main/               # Electron 主进程
│   ├── preload/            # Electron preload
│   └── renderer/           # React + Vite 前端
├── test/                   # 前端单元测试（Vitest）
│   ├── setup.ts            # 全局 mock 初始化
│   ├── unit/api/           # API 客户端层测试（10 个文件）
│   ├── unit/lib/           # 工具函数测试（3 个文件）
│   └── unit/contexts/      # React Context 测试（1 个文件）
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

- `src/main/index.ts` 负责窗口生命周期、深链回调、权限请求与 sidecar 启停
- `src/preload/index.ts` 暴露认证回调、后端端口发现、文件 / 目录选择 IPC
- `src/main/sidecar-manager.ts` 将 `Gateway / Preprocessing / AI` 端口变化推送给渲染层

### 前端

- React 18 + TypeScript + Vite + Tailwind CSS
- BrowserRouter / HashRouter 双运行时
- 模块化 API 客户端位于 `src/renderer/src/api/`
- 浏览器模式支持 PWA；Electron 模式不注册 Service Worker

### 后端

- Gateway 负责认证、公开 API、任务编排与静态资源挂载
- Preprocessing 负责 WSI 信息、图像、缩略图、DZI、瓦片与部分热图辅助逻辑
- AI 服务负责训练、推理与模型相关内部能力
- PostgreSQL + Redis + `uploads/` 共同组成运行时状态层

## 当前已确认的实现事实

- Gateway 当前直接注册 16 个顶层 router；`server/gateway/routes/` 目录里实际共有 32 个路由模块文件，其中一部分作为分析 / 聊天 / 存储辅助模块被复用
- 数据库当前可见 ORM 表为 17 个，其中标注表为 `segmentation_annotations`
- 前端构建更应以 `vite.config.ts`、`electron.vite.config.ts` 与 `deploy/` 脚本为准，而不是沿用旧版 README 的脚本描述
- 仓库中虽有 `server/backend/deep-research/` 目录，但当前 README 不再把它当作独立运行模块或单独文档入口

## 单元测试

前端测试基于 **Vitest** + **@testing-library/react**，覆盖全部 API 客户端模块、工具函数库和 AuthContext。

```bash
npm run test:run      # 单次全量运行
npm run test          # 交互式监听模式
npm run test:coverage # 生成覆盖率报告
```

当前共 **345 个测试**，分布在 **14 个测试文件**：

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
| 工具函数 | `unit/lib/cache.test.ts` | TTL 缓存、键值缓存、持久化缓存、并发去重 |
| 工具函数 | `unit/lib/utils.test.ts` | cn()、formatBytes()、formatFileSize() |
| 工具函数 | `unit/lib/chatMessageParser.test.ts` | AI 消息净化、PDF 上下文检测 |
| React Context | `unit/contexts/AuthContext.test.tsx` | 认证状态机、角色判断、协议签署、维护公告 |

详细说明见 [test/README.md](test/README.md)。

## 推荐阅读顺序

1. [server/README.md](server/README.md)
2. [server/gateway/README.md](server/gateway/README.md)
3. [server/backend/database/README.md](server/backend/database/README.md)
4. [src/renderer/README.md](src/renderer/README.md)
5. [deploy/README.md](deploy/README.md)
6. [test/README.md](test/README.md)
