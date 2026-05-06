# Paper Generation Frontend Interface Contract

> 创建日期：2026-05-04  
> 目标：给 PathLab 前端预留 paper generation 的 API client、页面入口、状态轮询和下载接口。

## 1. 前端入口

建议先做最小 UI，不追求完整编辑器：

```text
src/renderer/src/api/papers.ts
src/renderer/src/pages/PaperGenerationPage.tsx
src/renderer/src/pages/PaperRunDetailPage.tsx
```

路由建议：

```text
/papers                 # paper run 列表 + 创建入口
/papers/:paper_id        # paper run 详情、阶段状态、artifact、section、export
```

`App.tsx` 里预留：

```tsx
<Route path="/papers" element={<ProtectedRoute><Layout><PaperGenerationPage /></Layout></ProtectedRoute>} />
<Route path="/papers/:paper_id" element={<ProtectedRoute><Layout><PaperRunDetailPage /></Layout></ProtectedRoute>} />
```

`ToolsPage` 里增加一个入口卡片：

```text
Paper Generator
Generate MICCAI / Nature Scientific Reports drafts from completed PathLab experiments.
```

## 2. 前端 API client

新增：

```text
pathlab/pathlab-client/src/renderer/src/api/papers.ts
```

并在：

```text
pathlab/pathlab-client/src/renderer/src/api/index.ts
```

导出：

```ts
export * from './papers'
```

## 3. TypeScript 类型

```ts
export type PaperRunStatus =
  | 'created'
  | 'collecting'
  | 'building_evidence'
  | 'outlining'
  | 'plotting'
  | 'literature_review'
  | 'section_writing'
  | 'validating'
  | 'refining'
  | 'rendering'
  | 'exporting'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type PaperTemplateId = 'miccai' | 'nature_scientific_reports'

export interface CreatePaperRunRequest {
  title?: string
  paper_type?: 'research_paper'
  language?: 'en' | 'zh'
  source_task_ids: string[]
  source_analysis_ids?: string[] | 'latest'
  // UI should expose this as a single-select target venue; backend accepts exactly one id.
  templates?: [PaperTemplateId]
  include_external_validation?: boolean
  include_qualitative_examples?: boolean
  target_venue?: PaperTemplateId
  user_idea?: string
  sections?: string[]
}

export interface PaperRunArtifact {
  path: string
  kind: 'input' | 'evidence' | 'table' | 'figure' | 'citation' | 'draft' | 'validation' | 'final' | 'export'
  visibility: 'public' | 'private_backend_only'
  size_bytes?: number
  updated_at?: string
  downloadable: boolean
}

export interface PaperRunSummary {
  paper_id: string
  title?: string
  status: PaperRunStatus
  current_stage: PaperRunStatus
  progress?: number
  templates: PaperTemplateId[]
  source_task_ids: string[]
  created_at: string
  updated_at?: string
  finished_at?: string
  error_message?: string
}

export interface PaperRunDetail extends PaperRunSummary {
  config: CreatePaperRunRequest
  artifacts: PaperRunArtifact[]
  warnings?: string[]
  validation_summary?: {
    metric: 'pass' | 'fail' | 'warning' | 'pending'
    claim: 'pass' | 'fail' | 'warning' | 'pending'
    citation: 'pass' | 'fail' | 'warning' | 'pending'
    latex: 'pass' | 'fail' | 'warning' | 'pending'
    figure_table: 'pass' | 'fail' | 'warning' | 'pending'
  }
}

export interface PaperSectionSummary {
  name: string
  path: string
  template?: PaperTemplateId
  editable: boolean
  last_modified?: string
  validation_status?: 'pass' | 'fail' | 'warning' | 'pending'
}
```

## 4. API 函数

```ts
import { apiFetch, downloadApiFile, buildSearchParams } from './client'

const API_PREFIX = '/papers'

export async function createPaperRun(payload: CreatePaperRunRequest): Promise<PaperRunSummary> {
  return apiFetch<PaperRunSummary>(API_PREFIX, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  }, 'Create paper run')
}

export async function listPaperRuns(params?: {
  page?: number
  page_size?: number
  status?: PaperRunStatus
}): Promise<{ items: PaperRunSummary[]; total: number }> {
  const qs = buildSearchParams(params as Record<string, string | number | undefined>)
  return apiFetch(`${API_PREFIX}?${qs.toString()}`, undefined, 'List paper runs')
}

export async function getPaperRun(paperId: string): Promise<PaperRunDetail> {
  return apiFetch<PaperRunDetail>(`${API_PREFIX}/${encodeURIComponent(paperId)}`, undefined, 'Get paper run')
}

export async function deletePaperRun(paperId: string): Promise<void> {
  await apiFetch(`${API_PREFIX}/${encodeURIComponent(paperId)}`, { method: 'DELETE' }, 'Delete paper run')
}

export async function listPaperSections(paperId: string): Promise<PaperSectionSummary[]> {
  return apiFetch<PaperSectionSummary[]>(`${API_PREFIX}/${encodeURIComponent(paperId)}/sections`, undefined, 'List paper sections')
}

export async function regeneratePaperSection(
  paperId: string,
  sectionName: string,
  instruction?: string
): Promise<PaperRunDetail> {
  return apiFetch<PaperRunDetail>(
    `${API_PREFIX}/${encodeURIComponent(paperId)}/sections/${encodeURIComponent(sectionName)}/regenerate`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ instruction })
    },
    'Regenerate paper section'
  )
}

export async function downloadPaperFile(
  paperId: string,
  path: string,
  fallbackFilename: string
): Promise<void> {
  await downloadApiFile(
    `${API_PREFIX}/${encodeURIComponent(paperId)}/files/${encodeURIComponent(path)}`,
    fallbackFilename,
    undefined,
    'Download paper file'
  )
}

export async function downloadPaperExport(
  paperId: string,
  template: PaperTemplateId): Promise<void> {
  const qs = buildSearchParams({ template })
  await downloadApiFile(
    `${API_PREFIX}/${encodeURIComponent(paperId)}/export?${qs.toString()}`,
    `${paperId}_${template}_bundle.zip`,
    undefined,
    'Download paper export'
  )
}
```

注意：如果后端路由用 FastAPI path 参数接收 `{path:path}`，前端不要手写拼接未编码路径。可以后续改成 query 参数更安全：

```text
GET /papers/{paper_id}/files?path=final/miccai/main.pdf
```

这个形式更适合前端和 allowlist。

## 5. React Query keys

```ts
export const paperQueryKeys = {
  all: ['papers'] as const,
  lists: () => [...paperQueryKeys.all, 'list'] as const,
  list: (params: unknown) => [...paperQueryKeys.lists(), params] as const,
  detail: (paperId: string) => [...paperQueryKeys.all, 'detail', paperId] as const,
  sections: (paperId: string) => [...paperQueryKeys.detail(paperId), 'sections'] as const
}
```

建议状态轮询：

- `created` 到 `exporting`：每 2 秒 poll `GET /papers/{id}`。
- `completed` / `failed` / `cancelled`：停止 poll。
- 后续可加 SSE，但 v1 先 poll 更简单。

## 6. 最小页面功能

### `/papers`

- 列表：paper_id、title、status、current_stage、templates、created_at。
- 创建按钮：打开 Create Paper Run dialog。
- 创建输入：
  - source tasks multi-select
  - idea textarea
  - templates checkbox：MICCAI / Nature SR
  - include external validation
  - include qualitative examples
- 点击 run 进入 `/papers/:paper_id`。

### `/papers/:paper_id`

- 顶部状态：status、current stage、progress、error。
- 阶段 timeline：collector / evidence / outline / plotting / literature / writing / guards / export。
- Validation summary：metric、claim、citation、latex、figure-table。
- Artifacts：只展示 `visibility=public` 且 `downloadable=true` 的文件。
- Sections：显示 section 列表和 regenerate 按钮。
- Export：MICCAI / Nature SR ZIP 下载按钮。

## 7. 前端安全约束

- 前端不要尝试下载 `private_backend_only` artifact。
- 前端 artifact 列表以 `manifest.json` 返回的 `downloadable` 为准。
- 前端不要展示 raw prompt / raw response。
- 前端不要把 `source_tasks.json`、`evidence_lock.private.json` 暴露为链接。
- 如果 API 返回 403，应显示“该文件仅后端验证使用，不能下载”，不要当成错误崩溃。

## 8. 和 Phase 的对应关系

- Phase 01：实现 `papers.ts` API shell、`/papers` 列表、`/papers/:id` 状态页。
- Phase 03：前端开始显示 public evidence 和 warnings。
- Phase 08：前端显示 sections。
- Phase 09：前端显示 validation summary。
- Phase 11：前端开放 regenerate 和 ZIP export。

## 9. 验收标准

- `POST /papers` 后前端能跳转到详情页并轮询状态。
- private artifact 不显示下载按钮。
- public artifact 能正常下载。
- completed run 能下载 ZIP。
- failed run 能展示 warnings 和 error_message。
- section regenerate 后详情页刷新，validation 状态更新。
