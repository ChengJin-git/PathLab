# Report TodoList (Action Items) Feature Plan

## Background

当前 deep-research 生成的报告是纯 Markdown 文本，没有结构化的 "行动建议" 部分。用户读完报告后，缺少一个可交互的 todolist 来跟踪后续行动。

**开源项目现状**：
- DeerFlow（ByteDance）：Plan 的 steps 充当研究阶段的 "todolist"，但最终报告没有专门的 action items 节（仅 `social_media` 报告风格有 "Action Steps"）
- GPT Researcher：完全没有 todolist 功能，聚焦分析综述
- **结论**：业界还没有标准做法，这是一个差异化功能

**PathLab 现有条件**：
- `remark-gfm` 已安装并在 `markdown.tsx` 中启用 → GFM task list (`- [ ]`) 语法已经能被解析渲染
- 但 checkbox 默认是 `disabled` 只读的，需要加交互
- 报告内容存在 zustand store 的 message.content 中

---

## 方案

### Phase 1: 让 Reporter 生成 Action Items（Backend Prompt）

**修改文件**：
- `server/backend/deep-research/src/prompts/reporter.md`
- `server/backend/deep-research/src/prompts/reporter.zh_CN.md`
- `server/backend/deep-research/src/prompts/reporter.zh_HK.md`

**改动**：在 reporter prompt 末尾增加一个必选章节的说明：

```markdown
## Report Structure Requirements

Your report MUST end with a "Recommended Next Steps" section using GFM task list syntax:

## Recommended Next Steps

- [ ] [High Priority] Specific, actionable recommendation derived from finding X
- [ ] [Medium Priority] Another recommendation with concrete details
- [ ] [Low Priority] Nice-to-have improvement

Rules for action items:
- Each item must be specific and actionable (not vague platitudes)
- Each item must directly trace back to a research finding in the report
- Items should be ordered by priority (high → low)
- Include 3-7 items (not too many, not too few)
- For PathLab pathology context: include specific model names, datasets, or techniques where applicable
```

中文版对应翻译。

**为什么放在 prompt 里而不是后处理**：
- LLM 能根据研究内容生成有针对性的建议，后处理做不到
- 无需改动 graph 节点逻辑或 SSE 事件流
- 与现有 citation 引用系统天然兼容（action items 可以引用 `[[n]](url)`）

### Phase 2: 前端交互式 Checkbox（Frontend）

#### 2a. 让 checkbox 可点击

**修改文件**：`src/renderer/src/components/deep-research/markdown.tsx`

在 `Markdown` 组件的 `components` prop 中添加 `input` 覆盖：

```tsx
input: ({ node, checked, disabled, ...props }) => {
  if (props.type === 'checkbox') {
    return (
      <input
        {...props}
        type="checkbox"
        checked={checked}
        className="mr-2 h-4 w-4 rounded border-gray-300 cursor-pointer"
        onChange={() => {
          // Phase 2b handles state management
          onCheckboxToggle?.(node?.position?.start?.line, !checked);
        }}
      />
    );
  }
  return <input {...props} />;
},
```

同时给 `Markdown` 组件加 `sourcePos={true}` prop，这样每个 checkbox 都能通过 `node.position.start.line` 定位到源 markdown 的行号。

#### 2b. Checkbox 状态管理

**方案选择**：修改 markdown 源文本（Approach A）

理由：
- 报告内容已经存在 zustand store 的 `message.content` 中
- 直接在 markdown 文本上做 `- [ ]` ↔ `- [x]` 替换，最简单
- 状态随 message 自动持久化到后端（已有的对话保存机制）
- 无需新建数据表或 API

**修改文件**：
- `src/renderer/src/lib/deep-research/store/store.ts` — 添加 `toggleReportTodo(messageId, lineNumber)` action
- `src/renderer/src/pages/DeepResearch/components/blocks/report-layout.tsx` — 传递 `onCheckboxToggle` 回调
- `src/renderer/src/pages/DeepResearch/components/research-report-block.tsx` — 连接 store action

**Store action 实现**：

```typescript
toggleReportTodo: (messageId: string, lineNumber: number) => {
  const state = get();
  const message = state.messages[messageId];
  if (!message) return;

  const lines = message.content.split('\n');
  const idx = lineNumber - 1; // sourcePos is 1-indexed
  if (idx < 0 || idx >= lines.length) return;

  const line = lines[idx];
  if (line.match(/- \[ \]/)) {
    lines[idx] = line.replace('- [ ]', '- [x]');
  } else if (line.match(/- \[x\]/i)) {
    lines[idx] = line.replace(/- \[x\]/i, '- [ ]');
  } else {
    return; // not a checkbox line
  }

  set({
    messages: {
      ...state.messages,
      [messageId]: { ...message, content: lines.join('\n') },
    },
  });
},
```

#### 2c. 样式美化

**修改文件**：`src/renderer/src/index.css` 或 markdown.tsx 内联样式

```css
/* Task list styling in reports */
.contains-task-list {
  list-style: none;
  padding-left: 0;
}
.task-list-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.375rem 0;
}
.task-list-item input[type="checkbox"] {
  margin-top: 0.25rem;
  cursor: pointer;
  accent-color: var(--color-primary-600);
}
.task-list-item input[type="checkbox"]:checked + * {
  text-decoration: line-through;
  opacity: 0.6;
}
```

### Phase 3: 持久化（可选，后续迭代）

当前 Phase 2 的 checkbox 状态存在 zustand store 中，对话保存时会一起写入后端。但如果需要更细粒度的持久化：

**方案**：利用已有的对话 update API 保存修改后的 message content

调用 `updateMessage(conversationId, messageId, newContent)` 将 checkbox 状态同步到后端数据库。在 `toggleReportTodo` action 中 debounce 调用此 API。

---

## 文件清单

| 文件 | 操作 | Phase |
|------|------|-------|
| `server/backend/deep-research/src/prompts/reporter.md` | 修改 - 添加 action items 章节指令 | 1 |
| `server/backend/deep-research/src/prompts/reporter.zh_CN.md` | 修改 - 同上中文版 | 1 |
| `server/backend/deep-research/src/prompts/reporter.zh_HK.md` | 修改 - 同上粤语版 | 1 |
| `src/renderer/src/components/deep-research/markdown.tsx` | 修改 - 添加 input 组件覆盖 + sourcePos | 2a |
| `src/renderer/src/lib/deep-research/store/store.ts` | 修改 - 添加 toggleReportTodo action | 2b |
| `src/renderer/src/pages/DeepResearch/components/blocks/report-layout.tsx` | 修改 - 传递 onCheckboxToggle | 2b |
| `src/renderer/src/pages/DeepResearch/components/research-report-block.tsx` | 修改 - 连接 store action | 2b |
| `src/renderer/src/index.css` | 修改 - task list 样式 | 2c |

## 风险与注意事项

1. **LLM 不一定总是生成 task list** — prompt 只是引导，不是保证。可以在前端做降级：如果报告中没有 `- [ ]` 语法，就不显示任何 todolist 相关 UI
2. **Streaming 期间的 checkbox** — 报告流式输出时，checkbox 应该是 disabled 的（`message.isStreaming === true`），等完整输出后再启用交互
3. **行号漂移** — 如果 markdown 内容被其他逻辑修改（如 citation 后处理），sourcePos 的行号可能不准确。需要验证 remark-gfm 解析后的 sourcePos 是否对应原始 content 的行号

## 验证

1. 启动一个 deep research → 报告末尾包含 "Recommended Next Steps" 章节，带有 `- [ ]` 格式的 action items
2. 点击 checkbox → 勾选/取消勾选，文字出现/消失删除线
3. 刷新页面/重新打开对话 → checkbox 状态保持（已勾选的仍然勾选）
4. 流式输出期间 → checkbox 不可点击
5. 中文报告 → 同样有"建议后续步骤"章节
