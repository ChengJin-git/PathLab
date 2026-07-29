import {
  ApiError,
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
export type GuardIssueSummary = components['schemas']['GuardIssueSummary']
export type GuardResultSummary = components['schemas']['GuardResultSummary']
export type OutlineDocument = components['schemas']['OutlineDocument']
// Hand-typed: FigureManifest / FigureManifestItem are not exposed via any
// `response_model` route (they live behind /files?path=figures/manifest.json
// which returns binary JSON), so the regen'd codegen drops them. Keep these
// in sync manually with backend `FigureManifest` Pydantic models.
export interface FigureManifestItem {
  figure_id: string
  status: string
  path?: string | null
  caption?: string | null
  source?: string | null
  kind?: string | null
  width?: number | null
  height?: number | null
}

export interface FigureManifest {
  figures: FigureManifestItem[]
}
export type PaperSection = components['schemas']['PaperSection']
export type PaperSectionListResponse = components['schemas']['PaperSectionListResponse']
export type RegenerateMode = components['schemas']['RegenerateSectionRequest']['mode']
export type RegenerateJobEntry = components['schemas']['RegenerateJobEntry']
export type DiffSummary = components['schemas']['DiffSummary']
export type SelectionLocatorResult = components['schemas']['SelectionLocatorResult']
export type RegenerateProgress = components['schemas']['RegenerateProgress']
export type RegenerateRejectResponse = components['schemas']['RegenerateRejectResponse']
export type CitationReference = components['schemas']['CitationReference']
export type CitationsView = components['schemas']['CitationsView']
export type VerifiedPoolSummary = components['schemas']['VerifiedPoolSummary']
export type AddCitationMode = components['schemas']['AddCitationRequest']['mode']
export type AddCitationRequest = components['schemas']['AddCitationRequest']
export type ManualCitationFields = components['schemas']['ManualCitationFields']
export type AddCitationPreview = components['schemas']['AddCitationPreview']
export type AddCitationResponse = components['schemas']['AddCitationResponse']
export type CitationDeleteResponse = components['schemas']['CitationDeleteResponse']

export const MAX_PAPERS_PER_SOURCE_TASK = 20

export interface PutPaperSectionBody {
  text: string
  source_hash?: string
}

export interface PutPaperSectionResponse {
  section: PaperSection
  downstream_stale: boolean
  stale_artifacts: string[]
}

export interface PostSectionRegenerateBody {
  mode: RegenerateMode
  target_section?: string
  target_paragraph?: number
  target_sentence?: number
  selected_text?: string
  source_hash?: string
  char_start?: number
  char_end?: number
  user_note?: string
  template_id?: TemplateId
}

export interface PostSectionRegenerateResponse {
  paper_id: string
  regen_id: string
  enqueued_at: string
}

export interface PutPaperOutlineBody {
  outline: OutlineDocument
  approve: boolean
}

export interface PutPaperOutlineResponse {
  paper_id: string
  approved: boolean
  current_stage: PaperRunStage
}

export interface PostPaperRenderExportResponse {
  paper_id: string
  status: PaperRunStatus
  current_stage: PaperRunStage
  message?: string
}

export interface PostPaperStageRerunBody {
  continue_downstream?: boolean
  include_previous_successful_output?: boolean
  confirm_overwrite_sections?: boolean
  confirm_overwrite_citations?: boolean
  confirm_regenerate_outline?: boolean
}

export interface PostPaperStageRerunResponse {
  paper_id: string
  status: PaperRunStatus
  current_stage: PaperRunStage
  message?: string
}

export type PostPaperPauseResponse = components['schemas']['PaperPauseResponse']

type BackendErrorDetail = {
  code?: string
  message?: string
  [key: string]: unknown
}

function paperFileEndpoint(paperId: string, path: string): string {
  const query = buildSearchParams({ path })
  return `${API_BASE}/papers/${encodeURIComponent(paperId)}/files?${query}`
}

function parseBackendErrorDetail(error: ApiError): BackendErrorDetail | null {
  const details = (error as ApiError & { details?: unknown }).details
  if (!details) return null
  if (typeof details === 'object') return details as BackendErrorDetail
  if (typeof details !== 'string') return null

  try {
    const parsed = JSON.parse(details)
    return parsed && typeof parsed === 'object' ? (parsed as BackendErrorDetail) : null
  } catch {
    return null
  }
}

async function preserveBackendErrorCode<T>(operation: () => Promise<T>): Promise<T> {
  try {
    return await operation()
  } catch (error) {
    if (error instanceof ApiError) {
      const detail = parseBackendErrorDetail(error)
      if (detail?.code) {
        throw new ApiError(detail.message || error.message, error.status, detail.code, JSON.stringify(detail))
      }
    }
    throw error
  }
}

export function createPaperRun(request: CreatePaperRunRequest): Promise<PaperRunCreateResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PaperRunCreateResponse>(
      `${API_BASE}/papers`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      },
      'Create paper run',
    ),
  )
}

export function listPaperRuns(params?: { limit?: number; offset?: number; source_task_id?: string }): Promise<PaperRunListResponse> {
  const query = buildSearchParams(params)
  const suffix = query.toString() ? `?${query}` : ''
  return apiFetch<PaperRunListResponse>(`${API_BASE}/papers${suffix}`, undefined, 'List paper runs')
}

export function getPaperRun(paperId: string): Promise<PaperRunDetail> {
  return apiFetch<PaperRunDetail>(`${API_BASE}/papers/${encodeURIComponent(paperId)}`, undefined, 'Get paper run')
}

export function putPaperOutline(
  paperId: string,
  body: PutPaperOutlineBody,
): Promise<PutPaperOutlineResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PutPaperOutlineResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/outline`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      'Update paper outline',
    ),
  )
}

export function postPaperRenderExport(paperId: string): Promise<PostPaperRenderExportResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PostPaperRenderExportResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/render-export`,
      { method: 'POST' },
      'Render/export paper',
    ),
  )
}

export function postPaperRetry(
  paperId: string,
  body?: PostPaperStageRerunBody,
): Promise<PostPaperStageRerunResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PostPaperStageRerunResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/retry`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body ?? {}),
      },
      'Retry paper run',
    ),
  )
}

export function postPaperPause(paperId: string): Promise<PostPaperPauseResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PostPaperPauseResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/pause`,
      { method: 'POST' },
      'Pause paper run',
    ),
  )
}

export function postPaperStageRerun(
  paperId: string,
  stage: PaperRunStage | string,
  body?: PostPaperStageRerunBody,
): Promise<PostPaperStageRerunResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PostPaperStageRerunResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/stages/${encodeURIComponent(stage)}:rerun`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body ?? {}),
      },
      'Rerun paper stage',
    ),
  )
}

export function getPaperSections(paperId: string): Promise<PaperSectionListResponse> {
  return apiFetch<PaperSectionListResponse>(
    `${API_BASE}/papers/${encodeURIComponent(paperId)}/sections`,
    undefined,
    'Get paper sections',
  )
}

export function putPaperSection(
  paperId: string,
  sectionName: string,
  body: PutPaperSectionBody,
): Promise<PutPaperSectionResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PutPaperSectionResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/sections/${encodeURIComponent(sectionName)}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      'Update paper section',
    ),
  )
}

export function getCitations(paperId: string): Promise<CitationsView> {
  return apiFetch<CitationsView>(
    `${API_BASE}/papers/${encodeURIComponent(paperId)}/citations`,
    undefined,
    'Get paper citations',
  )
}

export function postCitation(
  paperId: string,
  body: AddCitationRequest,
): Promise<AddCitationResponse | AddCitationPreview> {
  return preserveBackendErrorCode(() =>
    apiFetch<AddCitationResponse | AddCitationPreview>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/citations`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      'Add paper citation',
    ),
  )
}

export function deleteCitation(paperId: string, key: string): Promise<CitationDeleteResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<CitationDeleteResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/citations/${encodeURIComponent(key)}`,
      { method: 'DELETE' },
      'Delete paper citation',
    ),
  )
}

export function postSectionRegenerate(
  paperId: string,
  sectionName: string,
  body: PostSectionRegenerateBody,
): Promise<PostSectionRegenerateResponse> {
  return preserveBackendErrorCode(() =>
    apiFetch<PostSectionRegenerateResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/sections/${encodeURIComponent(sectionName)}/regenerate`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      'Regenerate paper section',
    ),
  )
}

export function getRegenerateJob(paperId: string, regenId: string): Promise<RegenerateJobEntry> {
  return apiFetch<RegenerateJobEntry>(
    `${API_BASE}/papers/${encodeURIComponent(paperId)}/regen/${encodeURIComponent(regenId)}`,
    undefined,
    'Get regenerate job',
  )
}

export function postRegenerateReject(
  paperId: string,
  regenId: string,
  reason?: string,
  templateId?: TemplateId,
): Promise<RegenerateRejectResponse> {
  const body = {
    reason: reason || undefined,
    template_id: templateId,
  }

  return preserveBackendErrorCode(() =>
    apiFetch<RegenerateRejectResponse>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/regen/${encodeURIComponent(regenId)}:reject`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      },
      'Reject regenerate job',
    ),
  )
}

export function postRegenerateCancel(paperId: string, regenId: string): Promise<{ [key: string]: string }> {
  return preserveBackendErrorCode(() =>
    apiFetch<{ [key: string]: string }>(
      `${API_BASE}/papers/${encodeURIComponent(paperId)}/regen/${encodeURIComponent(regenId)}:cancel`,
      { method: 'POST' },
      'Cancel regenerate job',
    ),
  )
}

export function deletePaperRun(
  paperId: string,
): Promise<{ paper_id?: string; deleted?: boolean; [key: string]: unknown }> {
  return apiFetch<{
    paper_id?: string
    deleted?: boolean
    [key: string]: unknown
  }>(`${API_BASE}/papers/${encodeURIComponent(paperId)}`, { method: 'DELETE' }, 'Delete paper run')
}

export function getPaperFileBlob(paperId: string, path: string, options?: RequestInit): Promise<Blob> {
  return apiFetchBlob(paperFileEndpoint(paperId, path), options, 'Get paper artifact')
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
  fallbackFilename?: string,
): Promise<DownloadApiFileResult> {
  const filename = fallbackFilename || path.split('/').pop() || 'paper-artifact'
  return downloadApiFile(paperFileEndpoint(paperId, path), filename, undefined, 'Download paper artifact')
}

export function downloadPaperExport(
  paperId: string,
  template: string = 'miccai',
  fallbackFilename?: string,
): Promise<DownloadApiFileResult> {
  return downloadPaperFile(
    paperId,
    `exports/${template}_bundle.zip`,
    fallbackFilename ?? `${template}_bundle.zip`,
  )
}
