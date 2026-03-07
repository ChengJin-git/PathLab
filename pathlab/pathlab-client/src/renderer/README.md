# PathLab Frontend

`src/renderer/` 是当前前端打包与浏览器构建目录，既服务 Electron 渲染进程，也支持独立 Web 构建。

## 当前实现概览

| 模式 | 典型入口 | API 地址策略 | 说明 |
|------|---------|-------------|------|
| Electron 开发 / 运行 | `npm run dev` 或打包后的 Electron | 通过 preload / IPC 获取 Gateway 动态端口 | 桌面应用主路径 |
| 独立 Web 构建 | `src/renderer/vite.config.ts` | 默认指向 `5100 / 5101 / 5102`，也可用 `VITE_*` 覆盖 | 用于部署脚本和浏览器模式 |

- 技术栈：React 18 + TypeScript + Vite + Tailwind CSS
- 路由：Web 构建使用 `BrowserRouter`，Electron 模式使用 `HashRouter`
- 国际化：`en-US`、`zh-CN`、`zh-HK`
- PWA：`vite-plugin-pwa` 已启用；独立 Web 构建会注册 Service Worker
- WSI 阅片：OpenSeadragon 资源随项目一起打包

## 关键入口文件

- `vite.config.ts`：独立 Web 构建配置
- `../electron.vite.config.ts`：Electron `main` / `preload` / `renderer` 联合构建配置
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
│   ├── lib/                # hooks、Deep Research 运行时与工具函数
│   ├── locales/            # i18n 文案
│   ├── pages/              # 页面组件
│   ├── types/              # 类型声明
│   ├── App.tsx
│   ├── config.ts
│   └── main.tsx
└── vite.config.ts
```

## 当前路由与页面

`src/App.tsx` 当前覆盖：

- 公开页：`/`、`/login`
- AI Chat：`/dashboard`、`/dashboard/:conversationId`、`/ai-chat`、`/ai-chat/:conversationId`
- Deep Research：`/deep-research`、`/deep-research/:conversationId`
- 任务相关：`/task-setup`、`/task-list`、`/task/:task_id`
- 数据相关：`/wsi-list`、`/register`、`/wsi/:wsi_id`
- 结果相关：`/results`、`/reports`
- 系统页：`/settings`
- 以及 1 个 `*` 兜底路由

另外，`pages/StorageManagementPage.tsx` 目前作为设置页内部功能页使用，并非独立路由。

## 与后端的连接方式

- Electron 模式：通过 preload 暴露的 IPC 获取 Gateway 动态端口
- Web / 浏览器模式：默认回退到 `5100 / 5101 / 5102`，也可由 `VITE_API_BASE`、`VITE_PREPROCESSING_BASE`、`VITE_AI_BASE` 覆盖
- `src/config.ts` 统一导出：
  - `API_BASE`
  - `PREPROCESSING_BASE`
  - `AI_BASE`

## 当前和旧文档的差异

- `npm run dev` 当前是 **Electron 开发流**，不是独立浏览器 dev server 脚本
- API 客户端已从单文件拆成 `src/api/` 目录
- 运行时存在 `ToastProvider`、`AuthProvider`、`BackgroundTaskProvider`
- 新增了 Deep Research 页面与 `src/lib/deep-research/` 运行时模块
- OpenSeadragon 资源使用本地打包资产，而不是运行时远程加载

## 相关文档

- [Source README](src/README.md)
- [PathLab Client README](../../README.md)
- [Python Backend README](../../server/README.md)