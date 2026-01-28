# PathLab

> **项目名称:** PathLab
> **版本:** v1.0
> **日期:** 2026-01
> **状态:** 已完成原型
> **核心愿景:** 构建病理 AI 研究平台，实现"数据不动，模型动"的隐私计算理念。

---

## 运行模式

PathLab 采用统一代码库，支持两种运行模式：

| 模式 | 启动方式 | 适用场景 | 说明 |
|------|---------|---------|------|
| **网页端** (调试模式) | `xvfb-run npm run dev` | 开发调试 | Vite 热更新，浏览器访问，固定端口 |
| **本地端** (打包模式) | `npm run build:linux/win/mac` | 生产部署 | Electron 桌面应用，动态端口，离线可用 |

**端口分配:**
- 调试模式: Gateway: 6100, Preprocessing: 6101, AI: 6102 (固定)
- 打包模式: 动态分配，通过 `PORT=xxxxx` 通知 Electron

---

## 功能特性

| 功能模块 | 状态 | 说明 |
|---------|------|------|
| 登录认证系统 | ✅ | 本地认证（FastAPI-Users + JWT），客户端 SHA256 哈希 |
| Electron + Python 双进程架构 | ✅ | 主进程管理 Python Sidecar 生命周期 |
| WSI 阅片器 | ✅ | 基于 OpenSeadragon 的多层级 WSI 可视化 |
| AI Chat 智能助手 | ✅ | 流式 LLM 对话，自动提取任务参数 (PathLab Agent) |
| WSI 上传与管理 | ✅ | 支持批量 CSV 导入、元数据管理（患者信息、生存分析字段）|
| 训练任务系统 | ✅ | 17 种特征提取器 + 8 种 MIL 聚合器，特征缓存复用 |
| 推理分析系统 | ✅ | WSI 分类、注意力热图可视化、外部验证 |
| 模型管理 | ✅ | 训练模型保存、加载、默认模型切换 |
| SQLite 数据库 | ✅ | 15 个表，Repository 模式 |
| 存储管理系统 | ✅ | 文件生命周期管理、级联删除、孤立文件检测 |
| 生存分析 | ✅ | WSI-level survival analysis (lifelines) |
| 消息反馈系统 | ✅ | 用户对 AI 消息的反馈收集 |
| 数据导出任务 | ✅ | 异步大数据导出任务追踪 |

### TODO
- [x] 支持 wsi-level survival analysis
- [x] External Validation & 复用目前的模型重新推理 - 待测试
- [ ] 模型分析 1000 bootstrap CI
- [ ] Agent Planing（包括 agent 选择流程优化）
- [ ] Report Generator
- [ ] 公共数据集下载/整理 csv/xlsx
- [ ] i18n
- [ ] 网页端打包，域名配置
- [x] 服务端用户管理，安全性打包 - 待测试

恒常性任务：重构代码库，提高可读性

---

## 项目结构

```
pathlab/
└── pathlab-client/           # 主项目目录
    ├── src/                  # Electron 前端 (React + TypeScript)
    │   ├── main/             # 主进程 (窗口管理、Sidecar 管理)
    │   ├── preload/          # Preload 脚本
    │   └── renderer/         # 渲染进程 (React 应用)
    │
    └── server/               # Python 后端 (FastAPI)
        ├── main.py           # 统一入口
        ├── gateway/          # API 网关 (15 个路由模块)
        └── backend/          # 核心服务
            ├── ai/           # AI 推理与训练
            ├── preprocessing/# WSI 预处理
            ├── database/     # SQLite ORM (15 个表)
            └── storage/      # 文件存储管理
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Electron + React + TypeScript + Vite |
| 后端 | Python + FastAPI + SQLAlchemy |
| 数据库 | SQLite (零配置) |
| AI | PyTorch + timm + transformers |
| WSI | ASlide (OpenSlide wrapper) + OpenSeadragon |

---

## 支持的 AI 模型

### 特征提取器 (17 种)

| 模型 | ID | 维度 | 来源 |
|------|-----|------|------|
| ResNet50 | resnet50 | 2048 | ImageNet |
| ViT-Large | vit_l_16 | 1024 | ImageNet |
| UNI | uni | 1024 | Mahmood Lab |
| UNI2 | uni2 | 1536 | Mahmood Lab |
| CONCH | conch | 512 | Mahmood Lab |
| CONCH 1.5 | conch15 | 512 | Mahmood Lab |
| Virchow | virchow | 1280 | Paige AI |
| Virchow2 | virchow2 | 1280 | Paige AI |
| H-Optimus-0 | H-Optimus-0 | 1536 | Bioptimus |
| H-Optimus-1 | H-Optimus-1 | 1536 | Bioptimus |
| Phikon | phikon | 768 | Owkin |
| Phikon2 | phikon2 | 1024 | Owkin |
| PLIP | plip | 512 | PathLAIA |
| PathoCLIP | patho_clip | 512 | PathLAIA |
| OpenMidnight | openmidnight | 1536 | SophontAI |
| mSTAR | mSTAR | 1024 | Smartlab |
| GPFM | GPFM | 1024 | Smartlab |

### 聚合器 (8 种)

| 聚合器 | ID | 说明 |
|--------|-----|------|
| ABMIL | abmil | Attention-based MIL |
| MeanMIL | meanmil | 简单平均池化 |
| MaxMIL | maxmil | 最大池化 |
| DSMIL | dsmil | Dual-stream MIL |
| DTFD-MIL | dtfdmil | Double-Tier Feature Distillation MIL |
| CLAM-SB | clam_sb | CLAM Single Branch |
| CLAM-MB | clam_mb | CLAM Multi Branch |
| TransMIL | transmil | Transformer-based MIL |

---

## 页面路由 (14 页)

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` `/login` | LoginPage | 登录欢迎页 |
| `/dashboard` | DashboardPage | 仪表盘概览 |
| `/ai-chat` | AIChatPage | PathLab Agent 智能助手 |
| `/task-setup` | NewTaskPage | 任务配置 |
| `/task-list` | TaskListPage | 任务列表 |
| `/task/:task_id` | TaskDetailPage | 任务详情 |
| `/wsi-list` | ListPage | 切片浏览器 |
| `/wsi/:wsi_id` | DetailPage | WSI 阅片器 |
| `/register` | UploadPage | 注册切片 |
| `/results` | ResultsViewerPage | 结果查看器 |
| `/reports` | ReportGeneratorPage | 报告生成器 |
| `/tools` | ToolsPage | 实用工具集 |
| `/storage` | StorageManagementPage | 存储管理 |
| `/settings` | SettingsPage | 系统设置 |

---

## Gateway 路由模块 (15 个)

| 模块 | 路由前缀 | 功能 |
|------|---------|------|
| auth | `/auth` | 用户认证 (FastAPI-Users + JWT) |
| wsi | `/wsi` | WSI CRUD、数据集管理 |
| wsi_upload | `/wsi/upload` | 文件/路径/CSV 批量上传 |
| training | `/training` | 训练任务 CRUD、SSE 日志流 |
| ai_tasks | `/tasks` | AI 推理任务、提取器列表 |
| results | `/results` | 结果查询、外部验证 |
| models | `/models` | 训练模型管理 |
| chat | `/chat`, `/conversations` | AI 对话、会话管理 |
| queue | `/queue` | GPU 队列状态、配置 |
| storage | `/storage` | 存储统计、迁移、清理 |
| heatmap | `/heatmap` | 热图数据、Patch 图像 |
| asr | `/asr` | 语音转文字 (DashScope Qwen3-ASR) |
| stats | `/stats` | 系统统计 |
| settings | `/settings` | 全局设置 |
| gpu | `/gpu` | GPU 信息和状态 |

---

## 数据库表 (15 个)

| 表名 | 用途 |
|------|------|
| `users` | 用户账户（FastAPI-Users，含角色 RBAC）|
| `datasets` | 数据集元信息（UUID 隐私保护）|
| `dataset_permissions` | 数据集临时提权（GPU 操作）|
| `wsi_slides` | WSI 切片元数据（含患者信息、生存分析字段）|
| `ai_tasks` | AI 推理任务记录 |
| `ai_results` | AI 分析结果 |
| `training_tasks` | 训练任务配置（分类/生存）|
| `training_task_wsi` | 训练任务与 WSI 多对多关联 |
| `trained_models` | 训练生成的模型检查点 |
| `training_logs` | 训练日志（SSE 流式）|
| `chat_conversations` | 聊天会话 |
| `chat_messages` | 聊天消息历史 |
| `message_feedback` | 消息反馈（点赞/点踩）|
| `export_tasks` | 数据导出任务追踪 |
| `accesstoken` | 访问令牌（FastAPI-Users）|

---

## 相关文档

- [PathLab Client 文档](pathlab/pathlab-client/README.md)
- [Python Backend 文档](pathlab/pathlab-client/server/README.md)
- [Gateway 服务文档](pathlab/pathlab-client/server/gateway/README.md)
- [Backend 服务文档](pathlab/pathlab-client/server/backend/README.md)
- [数据库文档](pathlab/pathlab-client/server/backend/database/README.md)
- [存储管理文档](pathlab/pathlab-client/server/backend/storage/README.md)
- [前端文档](pathlab/pathlab-client/src/renderer/src/README.md)
