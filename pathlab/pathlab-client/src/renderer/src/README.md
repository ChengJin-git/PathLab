# PathLab Frontend Source

`src/renderer/src` 是当前 React 应用的真实源码目录。

## 当前源码结构

```text
src/
├── App.tsx                 # 路由入口
├── main.tsx                # BrowserRouter / HashRouter 选择、Context 装配、PWA 注册
├── config.ts               # Gateway / Preprocessing / AI 地址解析
├── api/                    # 按业务拆分的 API 客户端
├── components/             # 可复用 UI、聊天、阅片、结果、设置等组件
├── contexts/               # Auth / BackgroundTask / Toast 状态
├── constants/              # 文件类型、指标、训练等常量
├── lib/                    # hooks 与辅助工具
├── locales/                # `en-US` / `zh-CN` / `zh-HK`
├── pages/                  # 页面级组件
└── types/                  # 类型声明
```

## 当前路由

`App.tsx` 中当前有 14 个主路由入口，外加 1 个兜底 `*` 路由：

- 公开页：`/`、`/login`
- 受保护页面：
  - `/dashboard`
  - `/dashboard/:conversationId`
  - `/tools`
  - `/settings`
  - `/task-setup`
  - `/task-list`
  - `/task/:task_id`
  - `/wsi-list`
  - `/register`
  - `/results`
  - `/reports`
  - `/wsi/:wsi_id`

说明：`pages/StorageManagementPage.tsx` 当前不是独立路由，而是作为设置页内部视图使用。

## 运行时事实

- Electron 环境下使用 `HashRouter`
- 浏览器环境下使用 `BrowserRouter`
- `main.tsx` 会先调用 `initializeApiConfig()`，从 preload / Electron IPC 获取 Gateway 端口
- 运行时组合 `ToastProvider`、`AuthProvider`、`BackgroundTaskProvider`
- 浏览器模式会注册 Service Worker；Electron 模式不会注册

## API 客户端现状

旧文档里提到的单体 `api.ts` 已经拆分为模块化目录。当前可见模块包括：

- `api/analysis.ts`
- `api/annotation.ts`
- `api/auth.ts`
- `api/chat.ts`
- `api/export.ts`
- `api/feedback.ts`
- `api/heatmap.ts`
- `api/permissions.ts`
- `api/queue.ts`
- `api/results.ts`
- `api/settings.ts`
- `api/stats.ts`
- `api/storage.ts`
- `api/training.ts`
- `api/users.ts`
- `api/wsi.ts`
- 以及 `client.ts` / `crypto.ts` / `index.ts` 等公共封装

## 主要页面与状态模块

- `AIChatPage.tsx`：AI 对话与 PDF 辅助阅读
- `ListPage.tsx`：WSI 列表与数据浏览
- `UploadPage.tsx`：数据注册 / 上传入口（路由为 `/register`）
- `WSIViewerPage.tsx`：全屏阅片器
- `NewTaskPage.tsx` / `TaskDetailPage.tsx` / `TaskListPage.tsx`：任务配置与追踪
- `ResultsViewerPage.tsx` / `ReportGeneratorPage.tsx`：结果查看与报告导出
- `SettingsPage.tsx` / `StorageManagementPage.tsx`：系统设置与存储管理相关界面
- `contexts/backgroundTask/`：训练、分析、存储相关 SSE / 动作封装

## 组件分层补充

`components/` 当前除了基础 UI 外，还拆出了这些主要分组：

- `chat/`
- `list/`
- `results/`
- `settings/`
- `taskDetail/`
- `training/`
- `upload/`
- `workflow/`
- `wsiViewer/`

## 相关文档

- [Frontend README](../README.md)
- [Project README](../../../../../README.md)
- [Backend README](../../../../server/README.md)
