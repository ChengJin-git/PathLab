# PathLab

> 正式版本号：`v1.0.0`

发布日期：2026 年 3 月 12 日

PathLab 是一个面向数字病理研究的桌面 / Web 一体化代码库。当前主应用位于 `pathlab/pathlab-client/`，由 **Electron 主进程 / preload、React 渲染层、Python FastAPI sidecar** 共同组成。

## 当前仓库重点

- Electron 主进程、preload 与 sidecar 管理位于 `pathlab/pathlab-client/src/main`、`src/preload`
- React 前端源码位于 `pathlab/pathlab-client/src/renderer/src`
- Python 统一入口位于 `pathlab/pathlab-client/server/main.py`
- `server/main.py` 当前会拉起 3 个内部服务：`Gateway`、`Preprocessing`、`AI`
- 固定端口部署、Nginx 与 systemd 模板位于 `pathlab/pathlab-client/deploy/`
- `server/backend/deep-research/` 当前仍在代码树中，但不属于默认 sidecar 启动的独立服务

## 运行形态

| 场景 | 入口 | 端口策略 |
|------|------|----------|
| 浏览器调试 / 固定端口运维 | `PATHLAB_DEBUG=1` 下的 sidecar + 前端构建产物 | 固定 `6100 / 6101 / 6102` |
| Electron 桌面运行 | `server/main.py` 由主进程拉起 | 自动分配可用端口，并把 Gateway 端口传给前端 |
| Web 部署脚本 | `deploy/start.sh` / `deploy/hot-reload.sh` | 固定 `6100 / 6101 / 6102` |

## 当前能力概览

- 用户认证、JWT 会话控制、管理员用户管理
- WSI 上传、列表、详情、缩略图 / DZI / 瓦片阅片
- 训练任务、推理任务、结果查看、热图与分割标注相关能力
- AI 对话、会话持久化、PDF 缓存与语义检索辅助阅读
- 存储统计、目录扫描、迁移、孤立文件 / 孤立记录清理
- 浏览器模式 PWA 与 Electron 桌面模式双运行方式
- 桌面端 `pathlab://` 深链登录回调与本地文件 / 目录选择能力

## 仓库结构

```text
pathlab/
└── pathlab-client/
    ├── src/
    │   ├── main/            # Electron 主进程
    │   ├── preload/         # Electron preload
    │   └── renderer/        # React + Vite 前端
    ├── server/
    │   ├── main.py          # Python sidecar 统一入口
    │   ├── gateway/         # 对外 API 网关
    │   └── backend/         # AI / preprocessing / database / storage / auth
    └── deploy/              # 固定端口启动、热更新、Nginx、systemd 模板
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

说明：仓库当前没有单独维护的 `deep-research` README；该目录未纳入 `server/main.py` 默认启动链，因此只在总览文档中顺带说明。