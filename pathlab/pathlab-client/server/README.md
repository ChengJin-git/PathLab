# PathLab Python Backend

PathLab 的 Python 后端服务，提供 WSI 处理、AI 推理和 API 网关功能。

## 核心特性

- **零配置**: SQLite 数据库，无需安装 PostgreSQL
- **动态端口**: 自动寻找可用端口，避免端口冲突
- **单进程架构**: 统一入口 `main.py`，简化部署

## 架构概览

```
server/
├── main.py               # 统一入口 (动态端口发现)
├── requirements.txt      # Python 依赖
├── gateway/              # API 网关服务
│   ├── main.py           # Gateway FastAPI 应用
│   ├── task_queue.py     # GPU 任务队列管理器
│   ├── models.py         # Pydantic 请求/响应模型
│   ├── pipeline.py       # 任务流水线
│   ├── utils.py          # 工具函数
│   ├── routes/           # 模块化路由
│   │   ├── auth.py           # OAuth 认证
│   │   ├── wsi.py            # WSI CRUD
│   │   ├── wsi_upload.py     # WSI 上传/注册
│   │   ├── ai_tasks.py       # AI 推理任务
│   │   ├── training.py       # 训练任务
│   │   ├── models.py         # 模型管理
│   │   ├── chat.py           # AI Chat
│   │   ├── results.py        # 结果查询
│   │   ├── stats.py          # 统计信息
│   │   ├── queue.py          # 任务队列管理
│   │   └── storage.py        # 存储管理
│   └── dependencies.py   # 依赖注入
│
└── backend/              # 核心后端服务
    ├── ai/               # AI 服务
    │   ├── main.py           # AI FastAPI 应用
    │   ├── routes/           # 训练/推理路由
    │   ├── tasks/            # 任务类型
    │   │   ├── wsi_classification/   # WSI 分类
    │   │   ├── patch_classification/ # Patch 分类
    │   │   └── patch_segmentation/   # Patch 分割 (nnUNet)
    │   ├── extractors/       # 17+ 特征提取器
    │   ├── aggregators/      # 聚合器 (ABMIL, MeanMIL, MaxMIL)
    │   ├── classifiers/      # 分类器
    │   ├── segmentors/       # 分割器 (nnUNet, DINOv3)
    │   ├── schemas/          # 数据模式
    │   └── utils/            # AI 工具函数
    ├── preprocessing/    # 预处理服务
    │   ├── main.py           # 预处理 FastAPI 应用
    │   └── tiling.py         # WSI 切片、坐标提取
    ├── database/         # SQLite ORM (零配置)
    │   ├── database.py       # 异步连接管理
    │   ├── models.py         # 数据模型 (10 个表)
    │   ├── repositories.py   # 数据访问层
    │   └── init_db.py        # 数据库初始化
    ├── storage/          # 文件存储管理
    │   └── manager.py        # 存储管理器
    ├── analysis/         # 分析模块
    ├── paper/            # 论文相关功能
    └── common/           # 公共模块
        ├── port_utils.py     # 端口发现工具
        ├── auth.py           # 认证工具
        ├── config.py         # 配置管理
        └── logger.py         # 日志工具
```

## 数据库模型 (10 个表)

| 表名 | 用途 |
|------|------|
| `wsi_slides` | WSI 切片元数据（含患者信息、生存分析字段） |
| `ai_tasks` | AI 推理任务记录 |
| `ai_results` | AI 分析结果 |
| `training_tasks` | 训练任务配置和状态 (支持 classification/segmentation) |
| `training_task_wsi` | 训练任务与 WSI 多对多关联 |
| `trained_models` | 训练生成的模型信息 |
| `training_logs` | 训练日志（实时流式） |
| `chat_conversations` | 聊天会话 |
| `chat_messages` | 聊天消息历史 |
| `user_profiles` | 用户配置文件（OAuth 登录缓存） |

## GPU 任务队列

支持 GPU 任务的并发控制和故障恢复：

- **最大并发控制**: 默认 1 个 GPU 任务同时运行
- **FIFO 调度**: 先进先出任务调度
- **断电恢复**: 服务重启后自动恢复未完成任务
- **统一管理**: 同时支持训练任务 (TrainingTask) 和推理任务 (AITask)

## 开发运行

```bash
# 方式一：直接运行 (推荐)
cd server && python main.py

# 输出示例:
# PORT=48427              ← Electron 通过此解析端口
# [Gateway] Starting on port 48427
# [Services] Gateway: 48427, Preprocessing: 47001, AI: 53633
# [Database] Using SQLite: sqlite+aiosqlite:///~/.local/share/PathLab/pathlab.db

# 方式二：Electron 开发模式自动启动
npm run dev  # 在父目录执行
```

**注意**: 无需启动 PostgreSQL！数据自动存储在平台特定目录。

## 数据库存储位置

| 平台 | 数据库路径 |
|------|-----------|
| Linux | `~/.local/share/PathLab/pathlab.db` |
| macOS | `~/Library/Application Support/PathLab/pathlab.db` |
| Windows | `%APPDATA%/PathLab/pathlab.db` |

## 动态端口发现

Python 后端启动时自动寻找可用端口：

```python
# backend/common/port_utils.py
def find_free_port() -> int:
    """查找可用端口"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def announce_port(port: int):
    """通知 Electron 端口号"""
    print(f"PORT={port}", flush=True)
```

Electron 主进程解析 `PORT=xxxxx` 输出配置 API 地址。

## 打包

```bash
../build-python.sh
```

生成独立可执行文件到 `dist/` 目录。

## API 文档

启动服务后访问（端口动态分配）：

```bash
python main.py
# PORT=48427
# 访问: http://127.0.0.1:48427/docs
```

## 相关文档

- [Gateway 服务](gateway/README.md)
- [Backend 服务](backend/README.md)
- [数据库层](backend/database/README.md)
- [存储管理](backend/storage/README.md)
