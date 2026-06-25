# PathLab Frontend Source

> 适用版本：`PathLab v1.0.5`

`src/renderer/src` 是当前 React 应用的真实源码目录。`2026-06-23` 起，AutoResearch（实现 codename：AutoResearch）的前端页面、API、类型和组件也位于此目录内。

## 当前源码结构

```text
src/
├── App.tsx                 # 路由入口
├── main.tsx                # BrowserRouter / HashRouter 选择、Context 装配、PWA 注册
├── config.ts               # Gateway / Preprocessing / AI 地址解析
├── i18n.ts                 # i18next 初始化
├── api/                    # 按业务拆分的 API 客户端
├── components/             # 可复用 UI、聊天、阅片、结果、设置、AutoResearch 等组件
├── contexts/               # Auth / BackgroundTask / Toast 状态
├── constants/              # 文件类型、指标、训练等常量
├── hooks/                  # 独立 React Hook 模块
├── lib/                    # 工具函数与辅助逻辑
├── locales/                # `en-US` / `zh-CN` / `zh-HK`
├── pages/                  # 页面级组件
└── types/                  # 类型声明
```

## 当前路由

`App.tsx` 中当前定义这些主路由入口，外加 1 个兜底 `*` 路由：

- 公开页：`/`、`/login`
- 受保护页面：
  - `/dashboard`
  - `/dashboard/:conversationId`
  - `/tools`
  - `/settings`（requireAdmin）
  - `/task-setup`（requireGpu）
  - `/task-list`
  - `/task/:task_id`
  - `/wsi-list`
  - `/register`
  - `/results`（requireGpu）
  - `/reports`
  - `/wsi/:wsi_id`
  - `/autoresearch`
  - `/autoresearch/new`
  - `/autoresearch/sessions/:id`

说明：`pages/StorageManagementPage.tsx` 当前不是独立路由，而是作为设置页内部视图使用。Standalone AutoResearch 模式下，`/` 与 `/login` 会重定向到 `/autoresearch/new`。

## 运行时事实

- Electron 环境下使用 `HashRouter`
- 浏览器环境下使用 `BrowserRouter`
- `main.tsx` 会先调用 `initializeApiConfig()`，优先从 preload / Electron IPC 获取全部后端端口
- `config.ts` 优先走 `getServicePorts()` / `onServicePorts()`，同时兼容只暴露 `gateway-port` 的旧桥接
- 收到端口更新时会调用 `updateApiBase()`，刷新 `API_BASE` / `PREPROCESSING_BASE` / `AI_BASE`
- 运行时组合 `QueryClientProvider`、`TooltipProvider`、`ToastProvider`、`AuthProvider`、`BackgroundTaskProvider`
- 浏览器模式会注册 Service Worker；Electron 模式不会注册

## API 客户端现状

旧文档里提到的单体 `api.ts` 已经拆分为模块化目录。当前 API 模块以 `api/*.ts` 为准，核心业务模块包括：

- `api/analysis.ts`
- `api/annotation.ts`
- `api/auth.ts`
- `api/batchInference.ts`（无标签数据集批量推理）
- `api/chat.ts`
- `api/export.ts`
- `api/feedback.ts`
- `api/heatmap.ts`
- `api/grants.ts`
- `api/queue.ts`
- `api/autoresearch.ts`（AutoResearch / AutoResearch session API，base 为 `${API_BASE}/autoresearch`，默认模型 `gpt-5.5`）
- `api/results.ts`
- `api/settings.ts`
- `api/stats.ts`
- `api/storage.ts`
- `api/training.ts`
- `api/trainingOptions.ts`
- `api/users.ts`
- `api/wsi.ts`
- 以及 `client.ts` / `crypto.ts` / `index.ts` 等公共封装

## 主要页面与状态模块

- `IntroductionPage.tsx` / `LoginPage.tsx`：公开入口与认证页面
- `AIChatPage.tsx` / `ToolsPage.tsx`：AI 对话、工具页与 PDF 辅助阅读
- `ListPage.tsx`：WSI 列表与数据浏览
- `UploadPage.tsx`：数据注册 / 上传入口（路由为 `/register`）
- `WSIViewerPage.tsx`：全屏阅片器
- `NewTaskPage.tsx` / `TaskDetailPage.tsx` / `TaskListPage.tsx`：任务配置与追踪
- `ResultsViewerPage.tsx` / `ReportGeneratorPage.tsx`：结果查看与报告导出
- `SettingsPage.tsx` / `StorageManagementPage.tsx`：系统设置与存储管理相关界面
- `AutoResearchSessionsPage.tsx` / `AutoResearchNewSessionPage.tsx` / `AutoResearchSessionPage.tsx`：AutoResearch / AutoResearch 会话列表、新建与运行详情
- `contexts/backgroundTask/`：训练、分析、存储相关 SSE / 动作封装
- `types/autoresearch.ts` 与 `lib/autoresearch*.ts`：AutoResearch API types、事件/session 辅助、国际化与 artifact 下载相关工具

## 组件分层补充

`components/` 当前除了基础 UI 外，还拆出了这些主要分组：

- `charts/`（分析图表组件）
- `chat/`
- `common/`（语言切换、音频可视化等公共 UI 组件）
- `landing/`
- `legal/`（隐私政策、免责声明等法律文本内联链接）
- `list/`
- `autoresearch/`
- `results/`
- `settings/`
- `taskDetail/`
- `training/`
- `ui/`
- `upload/`
- `wsiViewer/`

## 相关文档

- [Frontend README](../README.md)
- [Project README](../../../../../README.md)
- [Backend README](../../../server/README.md)
