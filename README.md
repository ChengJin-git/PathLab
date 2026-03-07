# PathLab

PathLab 是一个面向数字病理研究的桌面 / Web 一体化代码库，当前主应用位于 `pathlab/pathlab-client/`，采用 **Electron + React 渲染层 + Python FastAPI sidecar** 的组合架构。

## 运行形态

| 场景 | 入口 | 端口策略 |
|------|------|----------|
| Electron 开发 | `npm run dev` | Python sidecar 默认自动分配可用端口，并把 Gateway 端口通过 IPC 通知前端 |
| Electron 打包 / 预览 | `npm run build:*` / `npm run start` | 与桌面运行一致，默认使用 sidecar 动态端口 |
| 固定端口调试 | `PATHLAB_DEBUG=1 python server/main.py` | 固定 `5100 / 5101 / 5102` |
| Web / 运维部署脚本 | `deploy/start.sh` / `deploy/hot-reload.sh` | 固定 `6100 / 6101 / 6102` |

## 当前能力概览

- 本地认证、角色控制、JWT 会话与用户 `nonce` 单设备控制
- WSI / patch 文件管理、缩略图、DZI、瓦片阅片与热图/分割结果查看
- AI Chat、会话持久化、PDF 辅助阅读与引用上下文
- Deep Research 多步研究工作流与研究作业持久化
- 训练系统：19 个特征提取器、8 个 MIL 聚合器，覆盖 WSI 分类 / WSI 生存 / Patch 分类 / Patch 分割
- WSI 分类推理、结果查看、报告导出
- 存储统计、迁移、批量导入、派生数据重置、孤立文件 / 孤立记录清理
- 浏览器构建（PWA）与 Electron 桌面模式双运行方式

## 仓库结构

```text
pathlab/
├── pathlab-client/
│   ├── src/
│   │   ├── main/            # Electron 主进程
│   │   ├── preload/         # Electron preload / IPC 桥接
│   │   └── renderer/        # React + Vite 前端
│   ├── server/
│   │   ├── main.py          # Python sidecar 统一入口
│   │   ├── gateway/         # 对外 API 网关
│   │   └── backend/         # AI / 预处理 / 数据库 / 存储 / 认证 / Deep Research 共享模块
│   └── deploy/              # 固定端口部署脚本与 Nginx / systemd 模板
└── pathlab-server/          # 当前仓库中为空目录
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
- [Deep Research Snapshot](pathlab/pathlab-client/server/backend/deep-research/README.md)
- [Deployment](pathlab/pathlab-client/deploy/README.md)