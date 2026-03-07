# PathLab Frontend Source

`src/renderer/src` 是当前 React 应用的真实源码目录。

## 当前源码结构

```text
src/
├── App.tsx                 # 路由入口
├── main.tsx                # BrowserRouter / HashRouter 选择、Provider 装配、PWA 处理
├── config.ts               # Gateway / Preprocessing / AI 地址解析
├── api/                    # 按业务拆分的 API 客户端
├── components/             # 可复用 UI、聊天、阅片、结果、设置等组件
├── contexts/               # Auth / BackgroundTask / Toast 状态
├── constants/              # 文件类型、指标、训练等常量
├── lib/                    # hooks、Deep Research 运行时与辅助工具
├── locales/                # `en-US` / `zh-CN` / `zh-HK`
├── pages/                  # 页面级组件
└── types/                  # 类型声明
```

## 当前路由

`App.tsx` 当前包含以下路径：

- 公开页：`/`、`/login`
- AI Chat：`/dashboard`、`/dashboard/:conversationId`、`/ai-chat`、`/ai-chat/:conversationId`
- Deep Research：`/deep-research`、`/deep-research/:conversationId`
- 设置与工具：`/settings`
- 任务：`/task-setup`、`/task-list`、`/task/:task_id`
- 数据：`/wsi-list`、`/register`、`/wsi/:wsi_id`
- 结果：`/results`、`/reports`
- 兜底：`*`

说明：`pages/StorageManagementPage.tsx` 目前不是独立路由，而是作为设置页内部视图使用。

## 运行时事实

- Electron 环境下使用 `HashRouter`
- 浏览器环境下使用 `BrowserRouter`
- `main.tsx` 会先调用 `initializeApiConfig()`，从 preload / Electron IPC 获取 Gateway 端口
- 浏览器构建会注册 Service Worker；Electron 模式不会注册

## API 客户端现状

当前 API 客户端已拆分为模块化目录，主要包括：

- `api/auth.ts`
- `api/chat.ts`
- `api/wsi.ts`
- `api/training.ts`
- `api/results.ts`
- `api/storage.ts`
- `api/settings.ts`
- `api/stats.ts`
- `api/queue.ts`
- `api/heatmap.ts`
- `api/export.ts`
- `api/feedback.ts`
- `api/permissions.ts`
- `api/annotation.ts`
- `api/analysis.ts`
- 以及 `client.ts` / `index.ts` 等公共封装

Deep Research 相关前端运行时则主要位于：

- `lib/deep-research/api/`
- `lib/deep-research/store/`
- `lib/deep-research/sse/`
- `lib/deep-research/messages/`

## 主要页面文件

- `AIChatPage.tsx`：AI 对话与 PDF 辅助阅读
- `DeepResearchPage.tsx` 与 `pages/DeepResearch/`：Deep Research 主界面
- `ListPage.tsx`：WSI 列表与数据浏览
- `WSIViewerPage.tsx`：全屏阅片器
- `NewTaskPage.tsx` / `TaskDetailPage.tsx` / `TaskListPage.tsx`：任务配置与追踪
- `ResultsViewerPage.tsx` / `ReportGeneratorPage.tsx`：结果查看与报告导出
- `SettingsPage.tsx`：系统设置、存储管理入口

## 相关文档

- [Frontend README](../README.md)
- [Project README](../../../../../README.md)
- [Backend README](../../../../server/README.md)
