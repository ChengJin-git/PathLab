# PathLab Frontend Source

> **注意**: 完整的项目文档请参阅 [项目根目录 README](../../../../../README.md)

本目录包含 PathLab 前端 React 应用的源代码。

## 目录结构

```
src/
├── components/          # 可复用 UI 组件
│   ├── Layout.tsx           # 主布局（侧边栏导航）
│   ├── WSIViewer.tsx        # OpenSeadragon 封装
│   ├── PageHeader.tsx       # 页面头部组件
│   └── ...
├── pages/               # 页面组件
│   ├── LoginPage.tsx        # 登录欢迎页 (默认首页)
│   ├── DashboardPage.tsx    # 仪表盘概览
│   ├── AIChatPage.tsx       # AI 智能助手
│   ├── ToolsPage.tsx        # 实用工具集
│   ├── ListPage.tsx         # 切片浏览器 (/wsi-list)
│   ├── DetailPage.tsx       # WSI 阅片器 (/wsi/:wsi_id)
│   ├── UploadPage.tsx       # 注册切片 (/register)
│   ├── NewTaskPage.tsx      # 任务配置 (/task-setup)
│   ├── TaskListPage.tsx     # 任务列表 (/task-list)
│   ├── TaskDetailPage.tsx   # 任务详情 (/task/:task_id)
│   ├── ResultsViewerPage.tsx # 结果查看器 (/results)
│   ├── ReportGeneratorPage.tsx # 报告生成器 (/reports)
│   └── SettingsPage.tsx     # 系统设置 (/settings)
├── contexts/            # React Context
│   └── AuthContext.tsx      # 认证状态管理
├── api.ts               # 后端 API 客户端
├── config.ts            # 环境配置
├── App.tsx              # 根组件（路由配置）
├── main.tsx             # 应用入口
└── index.css            # 全局样式 + Tailwind
```

## 技术栈

- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite 5
- **Routing**: React Router v6
- **Styling**: Tailwind CSS
- **WSI Viewer**: OpenSeadragon
- **State Management**: React Hooks + Context

## 页面路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` `/login` | LoginPage | 登录欢迎页 |
| `/dashboard` | DashboardPage | 仪表盘 |
| `/ai-chat` | AIChatPage | AI 助手 |
| `/tools` | ToolsPage | 工具集 |
| `/task-setup` | NewTaskPage | 任务配置 |
| `/task-list` | TaskListPage | 任务列表 |
| `/task/:task_id` | TaskDetailPage | 任务详情 |
| `/wsi-list` | ListPage | 切片浏览器 |
| `/wsi/:wsi_id` | DetailPage | WSI 阅片器 |
| `/register` | UploadPage | 注册切片 |
| `/results` | ResultsViewerPage | 结果查看器 |
| `/reports` | ReportGeneratorPage | 报告生成器 |
| `/settings` | SettingsPage | 系统设置 |

## API 集成

前端通过 Electron preload 脚本获取动态端口，与 Python 后端通信：

```typescript
// 获取后端 API 地址
const backendUrl = await window.api.getBackendUrl()
// 返回: http://127.0.0.1:48427 (端口动态分配)
```

## 相关文档

- [前端 README](../README.md) - 详细的前端文档
- [项目 README](../../../../../README.md) - 完整项目文档
- [后端 README](../../../../server/README.md) - Python 后端文档
