import { API_BASE } from '../config'
import { apiFetch, apiFetchBlob, downloadApiFile } from './client'
import type { SupportedLanguage } from '../i18n'

export type ReportTemplate = 'conference' | 'journal'
export interface ReportSource {
  source_type: 'experiment' | 'research'
  source_id: string
  title: string
}
export interface ReportRecommendation {
  template: ReportTemplate
  completed_runs: number
  dataset_count: number
}
export interface ArticleGeneration {
  status: 'queued' | 'running' | 'completed' | 'paused' | 'failed'
  stage: string
  error_code?: string
  completed_sections: string[]
  total_sections: number
  current_section: string
  reference_count: number
  language: SupportedLanguage
  autonomous?: boolean
}
export interface ArticleReference {
  number: number
  title: string
  authors: string[]
  year: string | number
  venue: string
  url: string
  doi?: string
  pmid?: string
  source: string
  source_url: string
  verified_at: string
}
export interface Manuscript extends ReportSource {
  report_id: string
  user_id: string
  template: ReportTemplate
  content: string
  revision: number
  status: 'draft' | 'ready'
  created_at: string
  updated_at: string
  evidence: {
    runs: { run_id: string; status: string; metrics: Record<string, unknown> }[]
  }
  recommendation: ReportRecommendation
  generation?: ArticleGeneration
  references?: ArticleReference[]
  figures?: {
    number: number
    filename: string
    caption: string
    source: string
    width_mm?: number
  }[]
}
export interface ReportSummary extends Pick<
  Manuscript,
  | 'report_id'
  | 'user_id'
  | 'source_type'
  | 'source_id'
  | 'title'
  | 'template'
  | 'status'
  | 'created_at'
  | 'updated_at'
> {
  owner_name: string
  excerpt: string
  generation?: Pick<
    ArticleGeneration,
    'status' | 'stage' | 'current_section'
  > | null
}
export interface ReportPage {
  items: ReportSummary[]
  next_cursor: string | null
  page_size: number
}
export type SourceKey = Pick<ReportSource, 'source_type' | 'source_id'>
const base = () => `${API_BASE}/reports`
export const deleteReport = (
  id: string,
): Promise<{ deleted: boolean; report_id: string }> =>
  apiFetch(`${base()}/documents/${encodeURIComponent(id)}`, { method: 'DELETE' })
const json = (body: unknown) => ({
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
export const listReportSources = (
  query: string,
  signal?: AbortSignal,
): Promise<{ items: ReportSource[] }> =>
  apiFetch(`${base()}/sources?query=${encodeURIComponent(query)}`, { signal })
export const getReportSource = (
  source: SourceKey,
  signal?: AbortSignal,
): Promise<{ title: string; recommendation: ReportRecommendation }> =>
  apiFetch(`${base()}/source?${new URLSearchParams(source)}`, { signal })
export const listReports = (
  filters: { query?: string; cursor?: string } & Partial<SourceKey> = {},
  signal?: AbortSignal,
): Promise<ReportPage> =>
  apiFetch(
    `${base()}/documents?${new URLSearchParams(Object.entries(filters).map(([k, v]) => [k, String(v)]))}`,
    { signal },
  )
export const getReport = (
  id: string,
  signal?: AbortSignal,
): Promise<Manuscript> =>
  apiFetch(`${base()}/documents/${encodeURIComponent(id)}`, { signal })
export const getReportFigure = (
  id: string,
  filename: string,
  signal?: AbortSignal,
): Promise<Blob> =>
  apiFetchBlob(
    `${base()}/documents/${encodeURIComponent(id)}/figures/${encodeURIComponent(filename)}`,
    { signal },
  )
export const createReport = (
  source: SourceKey,
  template: ReportTemplate | 'auto',
  language: SupportedLanguage,
  instruction: string,
): Promise<Manuscript> =>
  apiFetch(`${base()}/documents`, {
    method: 'POST',
    ...json({ ...source, template, language, instruction }),
  })
export const resumeReport = (id: string): Promise<Manuscript> =>
  apiFetch(`${base()}/documents/${encodeURIComponent(id)}/resume`, {
    method: 'POST',
  })
export const saveReport = (report: Manuscript): Promise<Manuscript> =>
  apiFetch(`${base()}/documents/${report.report_id}`, {
    method: 'PUT',
    ...json({
      title: report.title,
      content: report.content,
      template: report.template,
      revision: report.revision,
      status: report.status,
    }),
  })
export const downloadReport = (report: Manuscript, format: 'docx' | 'latex') =>
  downloadApiFile(
    `${base()}/documents/${report.report_id}/download/${format}`,
    `${report.template}-${report.report_id.slice(0, 8)}.${format === 'docx' ? 'docx' : 'zip'}`,
  )
export const polishReport = (
  report: Manuscript,
  instruction: string,
  selection: [number, number],
  signal?: AbortSignal,
): Promise<{ suggestion: string; revision: number }> =>
  apiFetch(`${base()}/documents/${report.report_id}/polish`, {
    method: 'POST',
    signal,
    ...json({
      revision: report.revision,
      instruction,
      selection_start: selection[0],
      selection_end: selection[1],
    }),
  })
