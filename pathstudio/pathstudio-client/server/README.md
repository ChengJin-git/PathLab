# PathStudio Python Backend

PathStudio 的 Python 后端服务，提供 WSI 处理、AI 推理和 API 网关功能。

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
│   ├── routes/           # 模块化路由
│   │   ├── wsi.py        # WSI CRUD
│   │   ├── ai_tasks.py   # AI 任务管理
│   │   ├── training.py   # 训练任务
│   │   ├── chat.py       # AI Chat
│   │   ├── auth.py       # 认证路由
│   │   └── storage.py    # 存储管理
│   └── dependencies.py   # 依赖注入
│
└── backend/              # 核心后端服务
    ├── ai/               # AI 服务
    │   ├── routes/       # 训练/推理路由
    │   └── tasks/        # 任务实现
    ├── preprocessing/    # 预处理服务
    │   └── tiling.py     # WSI 切片
    ├── database/         # SQLite ORM (零配置)
    │   ├── database.py   # 异步连接管理
    │   ├── models.py     # 数据模型
    │   └── repositories.py # 数据访问层
    ├── storage/          # 文件存储管理
    │   └── manager.py    # 存储管理器
    └── common/           # 公共模块
        ├── port_utils.py # 端口发现工具
        ├── auth.py       # 认证工具
        └── config.py     # 配置管理
```

## 开发运行

```bash
# 方式一：直接运行 (推荐)
cd server && python main.py

# 输出示例:
# PORT=48427              ← Electron 通过此解析端口
# [Gateway] Starting on port 48427
# [Services] Gateway: 48427, Preprocessing: 47001, AI: 53633
# [Database] Using SQLite: sqlite+aiosqlite:///~/.local/share/PathStudio/pathstudio.db

# 方式二：Electron 开发模式自动启动
npm run dev  # 在父目录执行
```

**注意**: 无需启动 PostgreSQL！数据自动存储在平台特定目录。

## 数据库存储位置

| 平台 | 数据库路径 |
|------|-----------|
| Linux | `~/.local/share/PathStudio/pathstudio.db` |
| macOS | `~/Library/Application Support/PathStudio/pathstudio.db` |
| Windows | `%APPDATA%/PathStudio/pathstudio.db` |

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
