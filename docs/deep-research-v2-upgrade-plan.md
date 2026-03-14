# Deep Research v2 升级计划

基于 DeerFlow v1→v2 对比分析 + 2026-03-11 main 分支合并内容更新。

---

## 已完成（本次 merge 带入）

| 功能 | 说明 |
|---|---|
| ✅ 研究证据门控 | `research_validation.py`：researcher 必须拿到足够有效证据才能继续，否则自动重试（最多 `max_research_retry_rounds` 次） |
| ✅ 语音输入 | `useVoiceSession` + `VoiceSessionOverlay` + `AudioVisualizer`，已接入 `input-box.tsx` |
| ✅ Exa 搜索引擎 | 后端 `exa_search/`，前端 Settings 页面已有 `search_provider` 切换和 API Key 配置 |
| ✅ 工具结果标准化 | `result_utils.py`：统一 tool 返回格式，带 `valid_for_research` 标记供证据门控使用 |
| ✅ Observation 过滤 | Reporter 不再把 `[ERROR]`/`[WARNING]` 等内部调试信息写进最终报告 |
| ✅ 前端 store 大重构 | 持久化恢复、streaming 消息修复、agent 事件归一化等 |

---

## 待完成

### P1 — 并行步骤执行（价值最高，难度中）

**现状**：`research_team → researcher → research_team → researcher...` 串行循环，每个步骤等前一个完成才开始

**目标**：用 LangGraph 的 `Send` API，把同类型步骤同时 dispatch

```
Before: step1 → step2 → step3（耗时 N×T）

After:  step1 ↗
        step2 → merge → reporter（耗时 ~T）
        step3 ↘
```

**实现思路**：
- `research_team_node` 找出所有未执行步骤，按类型分组，用 `Send` 并发 dispatch
- 新增 `merge_results_node`：等所有并发步骤完成后汇总，再进 planner/reporter
- 并发数建议可配置（默认 3，受 vLLM 并发限制）
- 注意：已有的 `research_validation` 门控逻辑需要在每个并发分支中独立运行

**预期收益**：3 个研究步骤从 3×T → ~T，速度提升最明显

---

### P2 — PPT 生成前端接入（价值高，难度低）

**现状**：`/api/ppt/generate` 后端已有，前端 store/UI 完全未接

**目标**：报告完成后，像 Podcast 一样出现"生成 PPT"按钮

**实现思路**：
- 参考 `podcast-card.tsx` + store 里 `generatePodcast` 的实现模式
- 新增 `ppt-card.tsx`，提供 `.pptx` 文件下载
- store 增加 `generatePPT` action 调用 `/api/ppt/generate`
- i18n 补充 PPT 相关文案（`en.json` / `zh-CN.json` / `zh-HK.json`）

**预期收益**：后端已有，前端工作量极小，直接暴露现有能力

---

### P3 — Prose 编辑器前端接入（价值中，难度中）

**现状**：`/api/prose/generate` 后端已有（improve/fix/longer/shorter/zap 五种操作），前端未接

**目标**：报告区提供 inline 文本编辑操作

**实现思路**：
- 报告块工具栏或右键菜单：改进 / 缩短 / 扩写 / 修复语法 / 清理
- 选中文本 → 选操作 → 调用对应 prose endpoint → 流式替换
- 需要前端富文本选区支持

**预期收益**：让用户对报告做精细调整

---

### P4 — 持久化记忆（价值中，难度中）

**现状**：`InMemoryStore`，应用重启即清空，无跨会话记忆

**目标**：跨会话记住用户偏好和研究历史

**实现思路**：
- 将 `InMemoryStore` 替换为 SQLite 存储（已有 SQLite 基础设施）
- 后台异步提取每次对话关键 facts（DeerFlow v2 做法）
- PathLab 场景优先记忆：
  - 用户常用的 dataset/model/extractor 偏好
  - 过去研究的关键结论（避免重复搜索）
  - 语言和报告风格偏好

**预期收益**：连续使用体验提升，agent 有上下文感知

---

### P5 — Prompt 同步（价值低，难度低）

**现状**：`researcher.md` 已在本次 merge 中更新；其他 agent prompt 仍为 v1 版本

**目标**：对照 DeerFlow v2 更新剩余 prompt 质量

**实现思路**：
- 重点检查 `planner.md`、`coordinator.md`
- 保留 PathLab 特有的 `PATHLAB_*` 变量注入部分

**预期收益**：规划和协调质量小幅提升

---

## 优先级总表

| 优先级 | 功能 | 前端 | 后端 | 预期收益 |
|---|---|---|---|---|
| **P1** | 并行步骤执行 | 无 | 大（改图结构） | 速度 2-3x |
| **P2** | PPT 前端接入 | 小（复用 podcast） | 无（已有） | 新功能 |
| **P3** | Prose 编辑器 | 中 | 无（已有） | 新功能 |
| **P4** | 持久化记忆 | 小 | 中 | 体验提升 |
| **P5** | Prompt 同步 | 无 | 小 | 质量提升 |
