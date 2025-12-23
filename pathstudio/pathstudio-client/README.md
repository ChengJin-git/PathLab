# PathStudio Client (Electron + Python)

数字病理学本地工作站，基于 Electron + Python 双进程架构，实现"数据不动，模型动"的隐私计算理念。

## 功能特性

- **WSI 阅片器**: 基于 OpenSeadragon 的多层级全切片图像可视化
- **AI Chat 智能助手**: 流式 LLM 对话，自动提取任务参数
- **训练系统**: ResNet50 特征提取 + ABMIL 多实例学习训练
- **推理分析**: WSI 分类预测、注意力热图可视化
- **模型管理**: 训练模型保存、加载、默认模型切换
- **报告生成**: AI 分析报告自动生成
- **存储管理**: 文件生命周期管理、级联删除

## 技术架构

```
pathstudio-client/
├── src/                      # Electron 前端
│   ├── main/                 # 主进程 (窗口管理、Sidecar 管理)
│   │   ├── index.ts          # 入口点
│   │   └── sidecar-manager.ts # Python 进程管理
│   └── renderer/             # 渲染进程 (React + TypeScript)
│       ├── components/       # 可复用组件
│       └── pages/            # 页面组件
│
└── server/                   # Python 后端
    ├── main.py               # FastAPI 入口
    ├── gateway/              # API 网关 (Port 6100)
    │   ├── main.py           # Gateway 服务入口
    │   ├── routes/           # 模块化路由
    │   └── dependencies.py   # 依赖注入
    └── backend/              # 核心服务
        ├── ai/               # AI 服务 (Port 6102)
        │   ├── routes/       # 训练/推理路由
        │   └── tasks/        # 任务实现 (WSI分类等)
        ├── preprocessing/    # 预处理服务 (Port 6101)
        │   └── tiling.py     # WSI 切片逻辑
        ├── database/         # PostgreSQL ORM
        │   ├── models.py     # 数据模型
        │   └── repositories.py # 数据访问层
        └── storage/          # 文件存储管理
```

## 快速开始

### 1. 安装依赖

```bash
# 安装 Node 依赖
npm install

# 安装 Python 依赖
pip install -r server/requirements.txt
```

### 2. 启动 PostgreSQL

```bash
docker compose up -d postgres
```

### 3. 开发模式运行

```bash
# 方式一：同时启动 Electron + Python 服务
npm run dev

# 方式二：分别启动后端服务 (推荐开发时使用)
./start_all.sh    # 启动 Gateway + Preprocessing + AI 服务
npm run dev:electron  # 单独启动 Electron 前端
```

### 4. 停止服务

```bash
./stop_all.sh
```

## 服务端口

| 服务 | 端口 | 职责 |
|------|------|------|
| Gateway | 6100 | API 网关、业务编排、Chat、WSI 管理 |
| Preprocessing | 6101 | WSI 切片、DZI 生成、缩略图、坐标提取 |
| AI | 6102 | 特征提取、模型训练、推理分析 |
| PostgreSQL | 5432 | 数据持久化 |

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

启动服务后访问交互式文档：
- Gateway: http://127.0.0.1:6100/docs
- Preprocessing: http://127.0.0.1:6101/docs
- AI: http://127.0.0.1:6102/docs

## 相关文档

- [Python Backend 文档](server/README.md)
- [Gateway 服务文档](server/gateway/README.md)
- [Backend 服务文档](server/backend/README.md)
- [数据库文档](server/backend/database/README.md)
- [存储管理文档](server/backend/storage/README.md)
- [前端文档](src/renderer/README.md)
