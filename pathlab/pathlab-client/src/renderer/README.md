# PathLab Frontend

> 适用版本：`PathLab v1.0.5`

`src/renderer/` 是当前前端打包与浏览器构建目录，既服务 Electron 渲染进程，也支持独立 Web 构建。

## 当前实现概览

- 技术栈：React 18 + TypeScript + Vite 7 + Tailwind CSS 4
- 路由：浏览器模式使用 `BrowserRouter`，Electron 模式使用 `HashRouter`
- 国际化：`en-US`、`zh-CN`、`zh-HK`
- PWA：浏览器模式会注册 Service Worker，Electron 模式不会
- WSI 阅片：OpenSeadragon 资源随项目一起打包

## 关键入口文件

- `vite.config.ts`：独立 Web 构建配置
- `../../electron.vite.config.ts`：Electron `main` / `preload` / `renderer` 联合构建配置
- `../main/index.ts`：桌面模式主进程入口
- `../main/services-manager.ts`：桌面模式嵌入式 PostgreSQL / Redis 生命周期管理
- `../main/sidecar-manager.ts`：桌面模式 sidecar 启停与端口发现
- `../preload/index.ts`：渲染层可见的 IPC 桥接
- `src/main.tsx`：前端运行时入口
- `src/App.tsx`：页面路由定义
- `src/config.ts`：Gateway / Preprocessing / AI 地址解析

## 目录结构

```text
src/renderer/
├── public/                 # 静态资源（images、OpenSeadragon 资源等）
├── src/
│   ├── api/                # 模块化 API 客户端
│   ├── components/         # UI、聊天、阅片、结果、设置等组件
│   ├── constants/          # 常量定义
│   ├── contexts/           # Auth / BackgroundTask / Toast
│   ├── hooks/              # 独立 React Hook 模块
│   ├── lib/                # 工具函数与辅助逻辑
│   ├── locales/            # i18n 文案
│   ├── pages/              # 页面组件
│   ├── types/              # 类型声明
│   ├── App.tsx
│   ├── config.ts
│   ├── i18n.ts
│   └── main.tsx
└── vite.config.ts
```

## 当前运行时事实

`src/main.tsx` 当前会：

- 根据 Electron / 浏览器环境选择 `HashRouter` 或 `BrowserRouter`
- 启动时调用 `initializeApiConfig()`，从 preload / Electron IPC 读取后端端口
- 在端口更新时调用 `updateApiBase()` 刷新 `API_BASE` / `PREPROCESSING_BASE` / `AI_BASE`
- 组合 `QueryClientProvider`、`TooltipProvider`、`ToastProvider`、`AuthProvider`、`BackgroundTaskProvider`
- 在浏览器模式注册 Service Worker

## 当前路由与页面

`src/App.tsx` 当前定义了：

- 公开页：`/`、`/login`
- 受保护页：`/dashboard`、`/dashboard/:conversationId`、`/tools`、`/settings`（requireAdmin）
- 任务相关：`/task-setup`（requireGpu）、`/task-list`、`/task/:task_id`
- 数据相关：`/wsi-list`、`/register`、`/wsi/:wsi_id`
- 结果相关：`/results`（requireGpu）、`/reports`
- 以及 1 个 `*` 兜底路由

另外，`pages/StorageManagementPage.tsx` 当前仍是设置页内部功能页，并非独立路由。

## API 客户端现状

`src/api/` 当前按业务拆分为模块化 TypeScript 文件，实际清单以 `src/renderer/src/api/*.ts` 为准，核心业务模块包括：

- `analysis`
- `annotation`
- `auth`
- `batchInference`（无标签数据集批量推理）
- `chat`
- `export`
- `feedback`
- `heatmap`
- `grants`
- `queue`
- `results`
- `settings`
- `stats`
- `storage`
- `training`
- `trainingOptions`
- `users`
- `wsi`
- 以及 `client` / `crypto` / `index` 等公共封装

## 与后端的连接方式

- Electron 模式：通过 preload 暴露的 `getServicePorts()` / `onServicePorts()` 获取动态端口
- 浏览器模式：优先读取 `VITE_API_BASE` / `VITE_PREPROCESSING_BASE` / `VITE_AI_BASE`，否则回退到 `6100 / 6101 / 6102`
- `src/config.ts` 会统一导出 `API_BASE`、`PREPROCESSING_BASE`、`AI_BASE`

## 相关文档

- [Source README](src/README.md)
- [PathLab Client README](../../README.md)
- [Python Backend README](../../server/README.md)
