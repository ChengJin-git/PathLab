# Paper Generation Gateway Bridge

`server/gateway/paper_generation/` 只是 `/papers` API 的兼容桥接层。真正的
Paper Agent 实现、`uv` 环境、文档、测试、模板和设计记录都位于：

```text
pathlab/pathlab-client/server/paper_agent/
```

Gateway 保留这个 package 是为了让既有导入路径
`gateway.paper_generation.routes` 和前端使用的 `/papers` 路由保持稳定。

职责边界：

- Gateway 负责挂载 router、复用认证、权限和数据库会话。
- TaskWorker 负责消费 `paper_generation.*` Redis 描述符。
- Paper Agent 负责论文生成、引用、校验、LaTeX 渲染和导出。

不要在这里新增 agent、模板、校验器或渲染器实现；新的论文生成代码应放到
`server/paper_agent/`。详细说明见 [Paper Agent README](../../paper_agent/README.md)。
