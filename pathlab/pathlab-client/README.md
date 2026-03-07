# PathLab Client

`pathlab-client/` 是当前主应用目录，包含 Electron 主进程、React 渲染层、Python sidecar，以及固定端口 Web / 运维部署脚本。

## 当前入口文件

- `electron.vite.config.ts`：Electron `main` / `preload` / `renderer` 联合构建入口
- `src/main/index.ts`：Electron 主进程入口，负责窗口、深链、sidecar 生命周期与 IPC
- `src/preload/index.ts`：向渲染层暴露登录跳转、文件选择、Gateway 端口发现等能力
- `src/renderer/vite.config.ts`：独立 Web 构建配置
- `server/main.py`：Python sidecar 统一入口
- `deploy/start.sh` / `deploy/hot-reload.sh`：固定端口部署脚本

## 运行模式

| 模式 | 启动方式 | 适用场景 | 说明 |
|------|---------|---------|------|
| Electron 开发 | `npm run dev` | 本地联调 | `electron-vite dev`，主进程拉起 Python sidecar，默认动态端口发现 |
| Electron 打包 | `npm run build:linux` / `build:win` / `build:mac` | 桌面分发 | 生成 Electron 构建产物，运行时仍由主进程拉起 sidecar |
| 固定端口调试 | `PATHLAB_DEBUG=1 python server/main.py` | 后端/前端分离调试 | 固定 `5100 / 5101 / 5102` |
| Web / 运维部署 | `deploy/start.sh` / `deploy/hot-reload.sh` | 浏览器访问、Nginx 代理 | 固定 `6100 / 6101 / 6102`，并构建 `src/renderer/dist` |

## 功能特性

- **WSI 阅片器**：基于 OpenSeadragon 的全切片图像可视化
- **AI Chat**：流式对话、会话持久化、PDF 引用与辅助阅读
- **Deep Research**：研究计划、执行、报告与研究作业持久化
- **训练系统**：19 个特征提取器 + 8 个 MIL 聚合器
- **任务类型**：WSI 分类、WSI 生存预测、Patch 分类、Patch 分割
- **推理与结果**：当前公开推理接口以 WSI 分类为主，支持热图 / Patch CAM / 分割结果查看
- **模型管理**：训练模型保存、激活、默认模型切换与外部验证相关能力
- **存储管理**：统计、迁移、批量导入、派生数据重置、孤立项清理
- **GPU 队列**：并发控制、任务恢复、状态推送
- **语音识别**：Gateway 暴露 Qwen3-ASR 相关接口
- **本地认证**：FastAPI-Users + JWT + 用户 `nonce` 控制

## 当前目录结构

```text
pathlab-client/
├── deploy/                 # 启动、热更新、Nginx、systemd 模板
├── server/                 # Python sidecar 与共享后端模块
├── src/
│   ├── main/               # Electron 主进程
│   ├── preload/            # Electron preload / IPC 桥
│   └── renderer/           # React + Vite 前端
├── electron.vite.config.ts
├── package.json
└── README.md
```

## 当前代码层次

### 前端

- React 18 + TypeScript + Vite + Tailwind CSS
- Electron 下使用 `HashRouter`，Web 构建下使用 `BrowserRouter`
- 模块化 API 客户端位于 `src/renderer/src/api/`
- Deep Research 前端位于 `src/renderer/src/pages/DeepResearch/` 与 `src/renderer/src/lib/deep-research/`
- PWA 能力由 `vite-plugin-pwa` 提供；Electron 渲染进程也复用同一套 React 应用

### Electron 宿主层

- 主进程负责启动 / 停止 Python sidecar
- 通过 `pathlab://auth` 深链接收 OAuth 回调
- preload 当前暴露：外部 URL 打开、Gateway 端口获取、文件/目录选择、Deep Research 前端日志落盘

### 后端

- FastAPI Gateway 负责对外 API、认证、业务编排
- Preprocessing 负责 WSI 信息、缩略图、DZI、tile、patch 与热图底层接口
- AI 服务负责训练、推理与特征提取
- PostgreSQL + Redis + `uploads/` 文件系统共同组成运行时状态层

## 当前已确认的实现事实

- Gateway 当前无条件注册 15 个 router，并在 `research_chat.py` 可成功导入时额外注册 Deep Research 代理路由
- `server/backend/database/models.py` 当前定义 18 个业务 ORM 表；加上 `users` 共 19 个可见 ORM 表
- 标注表当前模型名为 `segmentation_annotations`
- `annotation.py` 路由模块仍存在，但当前 `gateway/main.py` 没有直接 `include_router(annotation_router)`

## 推荐阅读顺序

1. [server/README.md](server/README.md)
2. [server/gateway/README.md](server/gateway/README.md)
3. [server/backend/database/README.md](server/backend/database/README.md)
4. [src/renderer/README.md](src/renderer/README.md)
5. [deploy/README.md](deploy/README.md)