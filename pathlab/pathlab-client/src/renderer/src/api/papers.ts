import { apiFetch, buildSearchParams, downloadApiFile, type DownloadApiFileResult } from './client'
import { API_BASE } from '../config'

export type PaperRunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export type PaperRunStage =
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

export type TemplateId = 'miccai' | 'nature_scientific_reports'
export type TaskRole = 'main' | 'ablation' | 'baseline' | 'external_validation'

export interface SourceTaskRef {
  task_id: string
  role?: TaskRole
  label?: string | null
}

export interface CreatePaperRunRequest {
  title?: string | null
  paper_type?: string
  language?: string
  source_tasks: SourceTaskRef[]
  selected_templates?: TemplateId[]
  include_external_validation?: boolean
  user_idea?: string | null
}

export interface PaperRunCreateResponse {
  paper_id: string
  status: PaperRunStatus
  message: string
}

export interface PaperRunArtifact {
  path: string
  status: string
  visibility: string
  downloadable: boolean
  label?: string | null
  content_type?: string | null
}

export interface PaperRunSummary {
  paper_id: string
  status: PaperRunStatus
  current_stage: PaperRunStage
  title?: string | null
  selected_templates: TemplateId[]
  source_task_ids: string[]
  created_at: string
  finished_at?: string | null
  error_message?: string | null
}

export interface PaperRunDetail extends PaperRunSummary {
  artifacts: PaperRunArtifact[]
  stage_log: Array<Record<string, unknown>>
  validation_summary?: Record<string, unknown> | null
}

export interface PaperRunListResponse {
  items: PaperRunSummary[]
  total: number
}

export function createPaperRun(request: CreatePaperRunRequest): Promise<PaperRunCreateResponse> {
  return apiFetch<PaperRunCreateResponse>(
    `${API_BASE}/papers`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    },
    'Create paper run'
  )
}

export function listPaperRuns(params?: { limit?: number; offset?: number }): Promise<PaperRunListResponse> {
  const query = buildSearchParams(params)
  const suffix = query.toString() ? `?${query}` : ''
  return apiFetch<PaperRunListResponse>(`${API_BASE}/papers${suffix}`, undefined, 'List paper runs')
}

export function getPaperRun(paperId: string): Promise<PaperRunDetail> {
  return apiFetch<PaperRunDetail>(`${API_BASE}/papers/${encodeURIComponent(paperId)}`, undefined, 'Get paper run')
}

export function deletePaperRun(paperId: string): Promise<{ paper_id: string; deleted: boolean }> {
  return apiFetch<{ paper_id: string; deleted: boolean }>(
    `${API_BASE}/papers/${encodeURIComponent(paperId)}`,
    { method: 'DELETE' },
    'Delete paper run'
  )
}

export function downloadPaperFile(
  paperId: string,
  path: string,
  fallbackFilename?: string
): Promise<DownloadApiFileResult> {
  const query = buildSearchParams({ path })
  const filename = fallbackFilename || path.split('/').pop() || 'paper-artifact'
  return downloadApiFile(
    `${API_BASE}/papers/${encodeURIComponent(paperId)}/files?${query}`,
    filename,
    undefined,
    'Download paper artifact'
  )
}

export function downloadPaperExport(paperId: string, template: string = 'miccai'): Promise<DownloadApiFileResult> {
  return downloadPaperFile(paperId, `exports/${template}_bundle.zip`, `${template}_bundle.zip`)
}
