# Deep Research UI 优化方案

## 当前实现分析

### 组件架构

```
MessagesBlock (左 42%)              ResearchBlock (右 58%)
├── MessageListView                  ├── Tabs: Report | Activities
│   └── MessageListItem[]           ├── ResearchReportBlock
│       ├── ResearchCard             │   └── ReportLayout
│       ├── PlanCard                 │       └── Markdown (react-markdown + remark-gfm + rehype-katex)
│       └── MessageBubble            └── ResearchActivitiesBlock
│                                        ├── ActivityMessage[] (agent 输出)
│                                        └── ActivityListItem[] (tool call 卡片)
```

### 当前技术栈

| 模块 | 技术 |
|------|------|
| Markdown 渲染 | react-markdown + remark-gfm + remark-math + rehype-katex |
| 动画 | rehypeSplitWordsIntoSpans (逐词 span, animate-fadeIn) |
| 状态管理 | Zustand (useStore) |
| Citation | 预计算 citationMap (URL -> index), inline `[n]` 链接 + scroll-to + hover popover |

### 关键文件

| 文件 | 职责 |
|------|------|
| `report-layout.tsx` | Heading 提取, heading ID 分配 (sequential cursor), PATHLAB_RESEARCH_META 剥离 |
| `markdown.tsx` | Markdown 渲染, citation 处理 (CitationLink hover popover), 自定义组件 |
| `research-activities-block.tsx` | Activity 列表, agent message, tool call 过滤, 空项过滤 |
| `message-list-view.tsx` | 主消息列表, 滚动容器, thinking 指示器 |
| `message-list-item.tsx` | 消息过滤, research/plan/podcast card 决策, TRAINING_CHAT_LINK 剥离 |
| `research-report-block.tsx` | ReportLayout 包装, skeleton loading 状态 |
| `research-block.tsx` | Tabs (report/activities), 编辑模式, 下载按钮 |
| `research-card.tsx` | Research 状态卡片, open/restart 按钮, Training Card (Go/disabled) |
| `main.tsx` | 布局: 单列 vs 双列 (基于 openResearchId) |
| `store.ts` | Zustand 状态, researchPlanIds Map (O(1) planner 检测), 所有 store getters |

---

## 已完成的优化

| 项目 | 状态 | 说明 |
|------|------|------|
| **P0-3 Planner 检测预计算** | 已完成 | store 维护 `researchPlanIds` Map, MessageListItem O(1) 读取 |
| **P1-5 Report 骨架屏** | 已完成 | ReportSkeleton 在 content 为空时显示 |
| **P1-6 TOC 逻辑统一** | 已完成 | 一次解析 headings[], sequential cursor 分配 ID, 消除 slug 不一致 |
| **TOC 移除** | 已完成 | TOC 侧栏/移动端折叠/阅读进度条/scroll-spy 全部移除 (浪费空间) |
| **P2-8 Citation popover** | 已完成 | CitationLink hover 显示来源标题/URL/摘要, 已在 markdown.tsx 中实现 |
| **Report 文字换行** | 已完成 | 修复 Radix ScrollArea display:table 问题, 移除 prose max-width:65ch, 修复 table td nowrap |
| **Animated spans 修复** | 已完成 | animate-fade-in → animate-fadeIn 匹配 Tailwind config |
| **PATHLAB_RESEARCH_META 剥离** | 已完成 | stripMetaBlocks() 在渲染前清除 |
| **Activity 空内容修复** | 已完成 | 放宽 agent 字段检查, ActivityItem 空项返回 null |
| **Training Card UI** | 已完成 | Go 按钮移至 CardFooter, 匹配 Research Card 样式, 删除态 disabled |
| **TRAINING_CHAT_LINK 隐藏** | 已完成 | 从 content check 剥离, 空内容返回 null |

---

## 剩余优化方案

### P0 — 性能问题

#### 1. Activity 列表折叠分组

**当前**: 全部 activity 平铺渲染，50+ 条时明显卡顿。

**方案**:
- 按 agent 阶段分组 (搜索阶段 / 分析阶段 / 报告阶段)，每组默认折叠只显示摘要
- 组内用 `@tanstack/react-virtual` 虚拟滚动
- 参考 Deep Research Web UI 的节点点击展开模式

**改动文件**:
- `research-activities-block.tsx` — 重构为分组 + 折叠
- `store.ts` — 可选: 预计算 activity 分组

#### 2. MessageListView 虚拟化

**当前**: 对话超过 100 条时 DOM 节点过多。

**方案**:
- 用 `@tanstack/react-virtual` 替换当前的 `.map()` 全量渲染
- 保留 auto-scroll-to-bottom 行为 (streaming 时)

**改动文件**:
- `message-list-view.tsx` — 引入 `useVirtualizer`

---

### P1 — UX 改进

#### 3. Activity 树状可视化 (参考 Deep Research Web UI)

**当前**: 线性列表，不直观。

**方案**:
- 用 [reactflow](https://github.com/xyflow/xyflow) 渲染研究过程的树状图
- 节点类型: 搜索查询 -> 来源页面 -> 分析结论 -> 报告
- 点击节点在右侧展示详情 (来源内容、搜索结果)
- 作为 Activities tab 的切换视图 (列表视图 / 树视图)

**改动文件**:
- 新增 `research-tree-view.tsx`
- `research-block.tsx` — 添加视图切换
- `package.json` — 新增 `@xyflow/react` 依赖

---

### P2 — 功能增强

#### 4. Report 导出增强 (参考 GPT Researcher)

**当前**: 有 Markdown/HTML/PDF/Word/Image 导出。

**可补充**:
- 带引用的 PDF 导出: footnote 格式的引用列表
- PPT 导出: 已有 PPT 模块 (`src/ppt/`)，但 UI 上没有入口

**改动文件**:
- `research-block.tsx` — 新增 PPT 导出按钮
- 导出逻辑文件

---

## 实施顺序

```
Phase 1 (性能):  P0-1 activity 折叠分组
Phase 2 (UX):    P1-3 activity 树状视图
Phase 3 (可选):  P0-2 message 虚拟化 + P2-4 导出增强
```

---

## 跨项目通用 UI 模式总结

### Report 渲染
- Markdown 是通用格式，所有项目都用 markdown 作为核心输出
- Citation 存储为 JSON (URL -> index mapping)，inline `[n]` 标记 + hover popover
- 导出支持: PDF (浏览器 print 或 PDFKit), Word, Markdown

### Activity 可视化
| 模式 | 项目 | 技术 |
|------|------|------|
| 树状图 + 可点击节点 | Deep Research Web UI | VueFlow |
| 实时步骤显示 | STORM | Streamlit |
| Chat 对话线程 | DeerFlow, GPT Researcher v2 | Next.js |
| LangGraph Studio 追踪 | LangChain Open Deep Research | 内置 tracing |
