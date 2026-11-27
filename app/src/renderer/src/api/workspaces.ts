import { API_BASE } from '../config'
import { apiFetch, buildSearchParams } from './client'
import type { ExecutionMode } from '../lib/workspaceSelection'
import { createKeyedCache } from '../lib/utils/cache'
import { getAuthToken } from './client'

export interface WorkspaceInput {
  name: string
  dataset_ids: string[]
  root_paths: string[]
  enabled_skills: string[]
  enabled_connectors: string[]
  execution_mode: ExecutionMode
}
export interface Workspace extends WorkspaceInput {
  workspace_id: string
  user_id: string
  version: number
}
export interface CapabilityItem {
  id: string
  name: string
  name_en: string
  available?: boolean
}
export interface WorkspaceCapabilities {
  role: string
  can_use_gpu: boolean
  can_scan_server: boolean
  can_manage_users: boolean
  skills: CapabilityItem[]
  connectors: CapabilityItem[]
}
export interface WorkspaceDataset {
  dataset_id: string
  name: string
  task_types: string[]
  data_type: string
  file_count: number
}
export const listWorkspaces = () =>
  apiFetch<{ items: Workspace[] }>(`${API_BASE}/workspaces`)
export const getWorkspace = (id: string) =>
  apiFetch<Workspace>(`${API_BASE}/workspaces/${encodeURIComponent(id)}`)
const capabilityCache = createKeyedCache<WorkspaceCapabilities>(15_000)
export const getWorkspaceCapabilities = () =>
  capabilityCache.get(getAuthToken() ?? '', () =>
    apiFetch<WorkspaceCapabilities>(`${API_BASE}/workspaces/capabilities`),
  )
export const findWorkspaceDatasets = (search: string, page: number) =>
  apiFetch<{ items: WorkspaceDataset[]; total: number }>(
    `${API_BASE}/workspaces/datasets?${buildSearchParams({ search, page, page_size: 30 })}`,
  )
export const saveWorkspace = (value: WorkspaceInput, id?: string) =>
  apiFetch<Workspace>(
    `${API_BASE}/workspaces${id ? `/${encodeURIComponent(id)}` : ''}`,
    {
      method: id ? 'PUT' : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(value),
    },
  )
export const archiveWorkspace = (id: string) =>
  apiFetch(`${API_BASE}/workspaces/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
