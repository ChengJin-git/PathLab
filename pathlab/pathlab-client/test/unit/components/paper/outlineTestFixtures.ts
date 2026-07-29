import { ApiError } from '@renderer/api/client'
import type { OutlineDocument, PaperRunDetail } from '@renderer/api/papers'

export const PAPER_ID_FIXTURE = 'paper-outline-auto-refresh'

export const outlineDocumentFixture = {
  plotting_plan: [],
  macro_lit_search: [],
  micro_lit_clusters: [],
  section_plan: [
    {
      section: 'introduction',
      goal: 'Explain the auto-refresh regression fixture.',
      evidence_inputs: ['evidence/evidence_public.json'],
      citation_hints: [],
      locked_block_inputs: [],
    },
  ],
  pathlab_extensions: {
    templates: ['miccai'],
    guard_requirements: [],
  },
} satisfies OutlineDocument

export function makePaperRunDetailFixture(
  overrides: Partial<PaperRunDetail> = {},
): PaperRunDetail {
  return {
    paper_id: PAPER_ID_FIXTURE,
    status: 'running',
    current_stage: 'outlining',
    title: 'Outline auto-refresh fixture',
    selected_templates: ['miccai'],
    source_task_ids: [],
    created_at: '2026-07-29T00:00:00Z',
    finished_at: null,
    error_message: null,
    source_tasks: [],
    artifacts: [],
    stage_log: [],
    ...overrides,
  }
}

export const runningOutliningRunFixture = makePaperRunDetailFixture()

export const awaitingOutlineApprovalRunFixture = makePaperRunDetailFixture({
  status: 'awaiting_outline_approval',
})

export function makeOutlineUnavailableErrorFixture(): ApiError {
  return new ApiError('Paper file not found: drafts/outline.json', 404, 'NOT_FOUND')
}
