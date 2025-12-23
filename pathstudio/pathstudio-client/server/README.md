# PathStudio Python Backend

PathStudio 的 Python 后端服务，提供 WSI 处理、AI 推理和 API 网关功能。

## 架构概览

```
server/
├── main.py               # FastAPI 入口 (可选：统一启动)
├── gateway/              # API 网关服务 (Port 6100)
│   ├── main.py           # Gateway 入口
│   ├── routes/           # 模块化路由
│   │   ├── wsi.py        # WSI CRUD
│   │   ├── ai_tasks.py   # AI 任务管理
│   │   ├── training.py   # 训练任务
│   │   ├── chat.py       # AI Chat
│   │   └── storage.py    # 存储管理
│   └── dependencies.py   # 依赖注入
│
└── backend/              # 核心后端服务
    ├── ai/               # AI 服务 (Port 6102)
    │   ├── main.py       # AI 服务入口
    │   ├── routes/       # 训练/推理路由
    │   └── tasks/        # 任务实现
    ├── preprocessing/    # 预处理服务 (Port 6101)
    │   ├── main.py       # 预处理服务入口
    │   └── tiling.py     # WSI 切片
    ├── database/         # PostgreSQL ORM
    │   ├── models.py     # 数据模型
    │   └── repositories.py
    └── storage/          # 文件存储管理
        └── manager.py    # 存储管理器
```

## 服务说明

| 服务 | 端口 | 职责 |
|------|------|------|
| Gateway | 6100 | API 网关、业务编排、Chat、WSI 管理 |
| Preprocessing | 6101 | WSI 切片、DZI 生成、缩略图、坐标提取 |
| AI | 6102 | 特征提取、模型训练、推理分析 |

## 开发运行

```bash
# 方式一：使用启动脚本 (推荐)
./start_all.sh

# 方式二：单独启动各服务
python -m uvicorn pathstudio.services.gateway.main:app --port 6100 --reload
python -m uvicorn pathstudio.services.backend.preprocessing.main:app --port 6101 --reload
python -m uvicorn pathstudio.services.backend.ai.main:app --port 6102 --reload

# 方式三：Electron 开发模式自动启动
npm run dev  # 在父目录执行
```

## 打包

```bash
../build-python.sh
```

生成独立可执行文件到 `dist/` 目录。

## 相关文档

- [Gateway 服务](gateway/README.md)
- [Backend 服务](backend/README.md)
- [数据库层](backend/database/README.md)
- [存储管理](backend/storage/README.md)
