# PathLab

PathLab 是一个面向数字病理研究的桌面 / Web 一体化代码库，当前实现采用 **Electron + React 前端** 与 **Python FastAPI sidecar** 的组合架构。

## 当前代码现状

- 前端代码位于 `pathlab/pathlab-client/src/renderer/src`
- Electron 主进程与 preload 位于 `pathlab/pathlab-client/src/main`、`src/preload`
- Python 统一入口位于 `pathlab/pathlab-client/server/main.py`
- 该入口会拉起 3 个 FastAPI 服务：
  - Gateway
  - Preprocessing
  - AI
- Gateway 当前目录下有 **29 个路由文件**，其中 `main.py` 直接注册 **16 个顶层 router`
- 数据库当前可见的 ORM 表为 **17 个**：`models.py` 中 16 个业务表 + `backend/auth/models.py` 中的 `users`

## 运行形态

| 场景 | 入口 | 端口策略 |
|------|------|----------|
| 浏览器 / 调试 | `PATHLAB_DEBUG=1` 下的 Python 服务 + Vite / Electron 开发流 | 固定 `6100 / 6101 / 6102` |
| Electron 打包运行 | `server/main.py` 被主进程拉起 | 自动发现可用端口，并把 Gateway 端口通知前端 |
| 部署脚本 | `deploy/start.sh` / `deploy/hot-reload.sh` | 固定 `6100 / 6101 / 6102` |

## 当前能力概览

- 用户认证、角色控制、单设备 JWT 会话控制
- WSI 切片管理、缩略图 / DZI / 瓦片阅片
- AI 对话、会话持久化、PDF 辅助阅读与引用上下文
- 训练任务、推理任务、结果分析、热图与分割相关结果查看
- 存储统计、迁移、孤立文件 / 孤立记录清理
- 浏览器模式 PWA 与 Electron 桌面模式双运行方式

## 仓库结构

```text
pathlab/
└── pathlab-client/
    ├── src/
    │   ├── main/            # Electron 主进程
    │   ├── preload/         # Electron preload
    │   └── renderer/        # React 前端构建目录
    ├── server/
    │   ├── main.py          # Python sidecar 统一入口
    │   ├── gateway/         # 对外网关
    │   └── backend/         # AI / 预处理 / 数据库 / 存储 / 认证等内部模块
    └── deploy/              # 固定端口部署脚本与 Nginx / systemd 模板
```

## 文档入口

- [PathLab Client](pathlab/pathlab-client/README.md)
- [Python Backend](pathlab/pathlab-client/server/README.md)
- [Gateway](pathlab/pathlab-client/server/gateway/README.md)
- [Backend Services](pathlab/pathlab-client/server/backend/README.md)
- [Database Layer](pathlab/pathlab-client/server/backend/database/README.md)
- [Storage Management](pathlab/pathlab-client/server/backend/storage/README.md)
- [Frontend](pathlab/pathlab-client/src/renderer/README.md)
- [Frontend Source](pathlab/pathlab-client/src/renderer/src/README.md)
- [Deployment](pathlab/pathlab-client/deploy/README.md)