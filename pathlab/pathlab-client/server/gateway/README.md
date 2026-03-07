# PathLab Gateway

Gateway 是当前 PathLab 对外 API 的统一入口，负责认证、业务聚合、任务编排，以及与 Preprocessing / AI / Deep Research 内部服务的协作。

## 当前应用行为

| 模式 | Gateway 端口 | 说明 |
|------|-------------|------|
| 固定端口调试 | 5100 | `PATHLAB_DEBUG=1 python server/main.py` |
| Electron sidecar | 动态分配 | 由 `server/main.py` 自动分配，并把 Gateway 端口通知前端 |
| Web / 运维部署 | 6100 | `deploy/start.sh` / Nginx / systemd 固定使用 |

- 启动文件：`server/gateway/main.py`
- Web 框架：FastAPI
- 启动时会：
  - 初始化数据库
  - 初始化任务队列
  - 等待 Preprocessing / AI 服务可用
  - 清理过期任务并恢复部分中断状态
  - 注册路由
  - 挂载 `/avatars`

## 当前在 `main.py` 中注册的 router

`main.py` 当前**无条件**注册以下 15 个 router：

1. `auth`
2. `stats`
3. `wsi`
4. `wsi_upload`
5. `training`
6. `ai_tasks`
7. `results`
8. `models`
9. `chat`
10. `storage`
11. `queue`
12. `asr`
13. `heatmap`
14. `settings`
15. `gpu`

另外：

- `research_chat` 会在 `gateway.routes.research_chat` 成功导入时**条件注册**
- `annotation.py` 路由模块虽然仍在 `routes/` 包中导出，但当前 `gateway/main.py` **没有直接 `include_router(annotation_router)`**

## 公开能力概览

- 登录 / 用户管理 / 维护模式 / 头像上传
- WSI 上传、列表、详情、权限检查
- 训练任务、AI 任务与 GPU 队列观察
- 模型管理、结果查看、报告导出
- AI Chat、会话历史、PDF 缓存与反馈
- Deep Research 代理与研究作业持久化
- 存储统计、扫描、清理与配置
- GPU 信息、热图、系统设置

## 路由目录现状

`server/gateway/routes/` 中除了顶层 router，还包含大量被组合复用的支持模块，例如：

- 分析相关：`classification_analysis.py`、`segmentation_analysis.py`、`survival_analysis.py`、`external_validation_analysis.py`
- 聊天辅助：`chat_pdf.py`、`chat_pdf_vectorstore.py`、`chat_feedback.py`
- 存储辅助：`storage_tasks.py`、`storage_scan.py`
- Deep Research 代理：`research_chat.py`
- WSI 权限与工具模块：`wsi_permissions.py`、`analysis_helpers.py` 等

这些文件多数通过顶层 router `include_router(...)` 或普通导入方式组合，不一定单独在 `main.py` 注册。

## 认证现状

认证相关代码集中在 `routes/auth.py` 与 `backend/auth/`：

- 使用 FastAPI-Users + JWT strategy
- 维护用户 `nonce`，用于单设备会话控制
- 支持 `secure-login`、登出、资料更新、头像上传
- 包含管理员批量启用 / 禁用 / 删除用户接口

## 静态资源挂载

Gateway 当前明确挂载的静态路径是：

- `/avatars` → `Config.get_uploads_dir() / "avatars"`

前端静态资源的正式 Web 部署入口主要由 `deploy/nginx/` 提供，而不是由 Gateway 在代码里直接托管整套 SPA 构建产物。

## 与内部服务的关系

- Preprocessing：提供 WSI 信息、缩略图、DZI、tile、patch、热图等底层接口
- AI：提供训练、特征提取、推理等内部能力
- Deep Research：通过 `research_chat.py` 代理其 HTTP/SSE 能力，并把研究作业落库
- Database / Storage：通过 `backend/` 共享 ORM、仓储与文件系统能力

## 阅读建议

- 如果要看公开 API 面：先看 `main.py` 和 `routes/`
- 如果要看训练/推理底层：继续看 `../backend/README.md`
- 如果要看数据落库：继续看 `../backend/database/README.md`
- 如果要看文件与目录占用：继续看 `../backend/storage/README.md`

## 相关文档

- [Server README](../README.md)
- [Backend README](../backend/README.md)
- [Database README](../backend/database/README.md)
- [Storage README](../backend/storage/README.md)