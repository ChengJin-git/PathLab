import {
  apiFetch,
  apiFetchBlob,
  buildSearchParams,
  downloadApiFile,
  withAuthTokenQuery,
  type DownloadApiFileResult,
} from './client'
import { API_BASE } from '../config'
import type { components } from './papers.types'

export type PaperRunStatus = components['schemas']['PaperRunStatus']
export type PaperRunStage = components['schemas']['PaperRunStage']
export type TemplateId = components['schemas']['TemplateId']
export type TaskRole = components['schemas']['TaskRole']
export type SourceTaskRef = components['schemas']['SourceTaskRef']
export type CreatePaperRunRequest = components['schemas']['CreatePaperRequest']
export type PaperRunCreateResponse = components['schemas']['PaperRunCreateResponse']
export type PaperRunArtifact = components['schemas']['PaperRunArtifact']
export type PaperRunSummary = components['schemas']['PaperRunSummary']
export type PaperRunDetail = components['schemas']['PaperRunDetail']
export type PaperRunListResponse = components['schemas']['PaperRunListResponse']
export type PaperStageLogEntry = components['schemas']['PaperStageLogEntry']
export type ValidationSummary = components['schemas']['ValidationSummary']
export type GuardResultSummary = components['schemas']['GuardResultSummary']
export type OutlineDocument = components['schemas']['OutlineDocument']
export type FigureManifest = components['schemas']['FigureManifest']
export type FigureManifestItem = components['schemas']['FigureManifestItem']
export type PaperSection = components['schemas']['PaperSection']
export type PaperSectionListResponse = components['schemas']['PaperSectionListResponse']

function paperFileEndpoint(paperId: string, path: string): string {
  const query = buildSearchParams({ path })
  return `${API_BASE}/papers/${encodeURIComponent(paperId)}/files?${query}`
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

export function getPaperSections(paperId: string): Promise<PaperSectionListResponse> {
  return apiFetch<PaperSectionListResponse>(
    `${API_BASE}/papers/${encodeURIComponent(paperId)}/sections`,
    undefined,
    'Get paper sections'
  )
}

export function deletePaperRun(paperId: string): Promise<{ paper_id?: string; deleted?: boolean; [key: string]: unknown }> {
  return apiFetch<{ paper_id?: string; deleted?: boolean; [key: string]: unknown }>(
    `${API_BASE}/papers/${encodeURIComponent(paperId)}`,
    { method: 'DELETE' },
    'Delete paper run'
  )
}

export function getPaperFileBlob(paperId: string, path: string): Promise<Blob> {
  return apiFetchBlob(paperFileEndpoint(paperId, path), undefined, 'Get paper artifact')
}

export async function getPaperFileText(paperId: string, path: string): Promise<string> {
  const blob = await getPaperFileBlob(paperId, path)
  return blob.text()
}

export async function getPaperFileJson<T>(paperId: string, path: string): Promise<T> {
  const text = await getPaperFileText(paperId, path)
  return JSON.parse(text) as T
}

export function getPaperFileUrl(paperId: string, path: string): string {
  return withAuthTokenQuery(paperFileEndpoint(paperId, path))
}

export function downloadPaperFile(
  paperId: string,
  path: string,
  fallbackFilename?: string
): Promise<DownloadApiFileResult> {
  const filename = fallbackFilename || path.split('/').pop() || 'paper-artifact'
  return downloadApiFile(paperFileEndpoint(paperId, path), filename, undefined, 'Download paper artifact')
}

export function downloadPaperExport(paperId: string, template: string = 'miccai'): Promise<DownloadApiFileResult> {
  return downloadPaperFile(paperId, `exports/${template}_bundle.zip`, `${template}_bundle.zip`)
}
