# PathLab Client (Electron + Python)

数字病理学本地工作站，基于 Electron + Python 双进程架构，实现"数据不动，模型动"的隐私计算理念。

## 功能特性

- **WSI 阅片器**: 基于 OpenSeadragon 的多层级全切片图像可视化
- **AI Chat 智能助手**: 流式 LLM 对话，自动提取任务参数
- **训练系统**: 17+ 特征提取器 + MIL 聚合器 (ABMIL/MeanMIL/MaxMIL)，特征缓存复用
- **任务类型**: WSI 分类、Patch 分类、Patch 分割 (nnUNet)
- **推理分析**: WSI 分类预测、注意力热图可视化
- **模型管理**: 训练模型保存、加载、默认模型切换
- **报告生成**: AI 分析报告自动生成
- **存储管理**: 文件生命周期管理、级联删除、存储统计
- **GPU 任务队列**: 并发控制、断电恢复、任务优先级管理
- **工具集**: 实用工具（如论文信息提取）
- **零配置**: SQLite 数据库 (10 个表)、动态端口发现，开箱即用

## 技术架构

```
pathlab-client/
├── src/                      # Electron 前端
│   ├── main/                 # 主进程 (窗口管理、Sidecar 管理)
│   │   ├── index.ts          # 入口点
│   │   └── sidecar-manager.ts # Python 进程管理 + 端口发现
│   ├── preload/              # Preload 脚本
│   │   └── index.ts          # Backend API 暴露
│   └── renderer/             # 渲染进程 (React + TypeScript)
│       └── src/
│           ├── components/       # 可复用组件
│           │   ├── Layout.tsx        # 主布局
│           │   ├── WSIViewer.tsx     # OpenSeadragon 封装
│           │   └── PageHeader.tsx    # 页面头部
│           ├── pages/            # 页面组件
│           │   ├── LoginPage.tsx     # 登录页
│           │   ├── DashboardPage.tsx # 仪表盘
│           │   ├── AIChatPage.tsx    # AI 助手
│           │   ├── TaskListPage.tsx  # 任务列表
│           │   ├── TaskDetailPage.tsx # 任务详情
│           │   ├── ListPage.tsx      # 切片浏览器
│           │   ├── DetailPage.tsx    # WSI 阅片器
│           │   ├── ToolsPage.tsx     # 工具集
│           │   ├── StorageManagementPage.tsx  # 存储管理
│           │   └── ...
│           └── contexts/         # React Context
│               ├── AuthContext.tsx       # 认证状态管理
│               └── BackgroundTaskContext.tsx  # 后台任务管理
│
└── server/                   # Python 后端 (单进程统一服务)
    ├── main.py               # 统一入口 (自动端口发现)
    ├── gateway/              # API 网关 (动态端口)
    │   ├── main.py           # Gateway FastAPI 应用
    │   ├── task_queue.py     # GPU 任务队列管理器
    │   ├── routes/           # 模块化路由
    │   │   ├── auth.py           # OAuth 认证
    │   │   ├── wsi.py            # WSI CRUD
    │   │   ├── chat.py           # AI Chat
    │   │   ├── training.py       # 训练任务
    │   │   ├── ai_tasks.py       # AI 推理任务
    │   │   ├── models.py         # 模型管理
    │   │   ├── queue.py          # 任务队列管理
    │   │   └── storage.py        # 存储管理
    │   └── dependencies.py   # 依赖注入
    └── backend/              # 核心服务
        ├── ai/               # AI 服务 (内部端口)
        │   ├── tasks/            # 任务类型
        │   │   ├── wsi_classification/   # WSI 分类
        │   │   ├── patch_classification/ # Patch 分类
        │   │   └── patch_segmentation/   # Patch 分割
        │   ├── extractors/       # 17+ 特征提取器
        │   ├── aggregators/      # 聚合器 (ABMIL, MeanMIL, MaxMIL)
        │   └── segmentors/       # 分割模型 (nnUNet, DINOv3)
        ├── preprocessing/    # 预处理服务 (内部端口)
        │   ├── main.py           # 预处理 FastAPI 应用
        │   └── tiling.py         # WSI 切片
        ├── database/         # SQLite ORM (零配置)
        │   ├── database.py       # 异步 SQLite 连接
        │   ├── models.py         # 数据模型 (10 个表)
        │   └── repositories.py   # 数据访问层
        ├── storage/          # 文件存储管理
        │   └── manager.py        # 存储管理器
        └── common/           # 公共模块
            ├── port_utils.py     # 端口发现工具
            ├── config.py         # 配置管理
            └── auth.py           # 认证模块
```

## 快速开始

### 1. 安装依赖

```bash
# 安装 Node 依赖
npm install

# 安装 Python 依赖
pip install -r server/requirements.txt
```

### 2. 开发模式运行

```bash
# 方式一：同时启动 Electron + Python 服务 (推荐)
npm run dev

# 方式二：单独启动 Python 后端 (调试用)
cd server && python main.py
# 输出: PORT=xxxxx  ← Electron 通过此解析端口
```

**注意**: 无需启动 PostgreSQL！使用内嵌 SQLite 数据库，数据存储在：
- Linux: `~/.local/share/PathLab/pathlab.db`
- macOS: `~/Library/Application Support/PathLab/pathlab.db`
- Windows: `%APPDATA%/PathLab/pathlab.db`

## 服务架构

| 组件 | 说明 |
|------|------|
| **Gateway** | API 网关、业务编排、Chat、WSI 管理 |
| **Preprocessing** | WSI 切片、DZI 生成、缩略图、坐标提取 |
| **AI** | 特征提取、模型训练、推理分析 |
| **SQLite** | 零配置本地数据库（自动创建） |

### 动态端口发现

Python 后端启动时自动寻找可用端口，并通过标准输出通知 Electron：

```
PORT=48427
[Gateway] Starting on port 48427
```

Electron 主进程解析此输出并配置前端 API 地址。

## 打包发布

### 1. 打包 Python Sidecar

```bash
pip install pyinstaller
./build-python.sh
```

### 2. 打包 Electron 应用

```bash
npm run build:linux   # Linux (AppImage, deb)
npm run build:win     # Windows (nsis installer)
npm run build:mac     # macOS (dmg)
```

输出文件在 `dist/` 目录。

## API 文档

启动服务后访问交互式文档（端口动态分配）：

```bash
# 查看实际端口
cd server && python main.py
# PORT=48427

# 访问文档
open http://127.0.0.1:48427/docs
```

## 相关文档

- [Python Backend 文档](server/README.md)
- [Gateway 服务文档](server/gateway/README.md)
- [Backend 服务文档](server/backend/README.md)
- [数据库文档](server/backend/database/README.md)
- [存储管理文档](server/backend/storage/README.md)
- [前端文档](src/renderer/README.md)
