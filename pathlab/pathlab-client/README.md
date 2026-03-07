# PathLab Client

`pathlab-client/` 是当前主应用目录，包含 Electron 前端、React 渲染层、Python sidecar，以及用于固定端口部署的运维脚本。

## 当前入口文件

- `electron.vite.config.ts`：Electron `main` / `preload` / `renderer` 联合构建入口
- `src/main/index.ts`：Electron 主进程入口
- `src/preload/index.ts`：向渲染层暴露后端端口发现能力
- `src/renderer/vite.config.ts`：独立 Web 构建入口
- `server/main.py`：Python sidecar 统一入口
- `deploy/start.sh` / `deploy/hot-reload.sh`：固定端口部署脚本

## 运行模式

| 模式 | 启动方式 | 适用场景 | 说明 |
|------|---------|---------|------|
| **网页端** (调试模式) | `npm run dev` | 开发调试 | Vite 热更新，浏览器访问，固定端口 (5100, 5101, 5102) |
| **本地端** (打包模式) | `npm run build:linux/win/mac` | 生产部署 | Electron 桌面应用，动态端口发现，离线可用 |

## 功能特性

- **WSI 阅片器**: 基于 OpenSeadragon 的多层级全切片图像可视化
- **AI Chat 智能助手**: 流式 LLM 对话 (OpenRouter API)，支持会话持久化
- **🆕 DeepResearch Agent**: 多智能体病理学研究助手 (agentv2 + LangGraph)，支持研究计划制定、执行、报告生成
- **训练系统**: 19 种特征提取器 + 8 种 MIL 聚合器，全局特征缓存复用
- **任务类型**: WSI 分类、Patch 分类、Patch 分割、生存预测 (Survival Prediction)
- **推理分析**: WSI 分类预测、注意力热图可视化、Patch CAM 可视化、分割分析
- **模型管理**: 训练模型保存、加载、默认模型切换、激活/停用
- **外部验证**: 支持使用训练好的模型对新数据集进行外部验证
- **存储管理**: 文件生命周期管理、级联删除、孤立文件检测、存储迁移
- **GPU 任务队列**: 并发控制、断电恢复、任务状态实时更新 (SSE)
- **语音识别**: 集成 DashScope Qwen3-ASR 语音转文字
- **本地认证**: FastAPI-Users + JWT，客户端 SHA256 密码哈希
- **零配置**: PostgreSQL 数据库 (18 个表)、动态端口发现，开箱即用

## 当前目录结构

```text
pathlab-client/
├── deploy/                 # 启动、热更新、Nginx、systemd 模板
├── server/                 # Python sidecar
├── src/
│   ├── main/               # Electron 主进程
│   ├── preload/            # Electron preload
│   └── renderer/           # React + Vite 前端
├── electron.vite.config.ts
└── README.md
```

## 运行方式说明

### 1. Electron / 动态端口模式

- 主进程启动 sidecar
- `server/main.py` 自动分配端口
- Gateway 端口通过标准输出通知主进程
- 渲染层通过 preload / IPC 获取端口并更新 API 基址

### 2. 固定端口调试 / 部署模式

- `PATHLAB_DEBUG=1` 时使用 `6100 / 6101 / 6102`
- `deploy/start.sh` 与 `deploy/hot-reload.sh` 也采用固定端口
- 浏览器调试、Nginx 反向代理和本地运维脚本都围绕这组端口设计

## 当前代码层次

### 前端

- React 18 + TypeScript + Tailwind CSS
- BrowserRouter / HashRouter 双运行时
- 模块化 API 客户端（`src/renderer/src/api/`）
- PWA 支持与本地 OpenSeadragon 资源打包

### 后端

- FastAPI 网关负责对外 API、认证、会话、任务编排
- Preprocessing 负责 WSI 信息、缩略图、DZI、瓦片、热图辅助接口
- AI 服务负责训练、推理与部分模型内部接口
- PostgreSQL + Redis + 文件系统 `uploads/` 共同组成运行时状态层

## 当前已确认的实现事实

- Gateway 目录下共有 29 个路由文件，但只有 16 个 router 在 `gateway/main.py` 中直接注册
- 数据库当前可见 ORM 表为 17 个，不再把 `accesstoken` 作为当前代码里的独立 ORM 模型记录
- 标注数据当前模型名为 `segmentation_annotations`，不再是旧文档里的 `annotation_drafts`

## 推荐阅读顺序

1. [server/README.md](server/README.md)
2. [server/gateway/README.md](server/gateway/README.md)
3. [server/backend/database/README.md](server/backend/database/README.md)
4. [src/renderer/README.md](src/renderer/README.md)
5. [deploy/README.md](deploy/README.md)