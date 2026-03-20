import { API_BASE } from '../config'
import { apiFetch } from './client'


export interface DatasetPermission {
  id: number
  dataset_id: string
  dataset_name?: string | null
  user_id: string
  user_email?: string | null
  user_nickname?: string | null
  user_role?: string | null
  user_is_active?: boolean | null
  granted_by: string
  can_collaborate: boolean
  can_use_gpu: boolean
  expires_at: string | null
  created_at: string
  is_expired: boolean
  is_valid: boolean
}

export async function getMyDatasetPermissions(): Promise<{
  user_id: string
  permissions: DatasetPermission[]
  elevated_dataset_ids: string[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/my-permissions`,
    undefined,
    'Failed to get dataset permissions'
  )
}
export async function grantDatasetPermission(
  datasetId: string,
  userId: string,
  expiresInHours?: number
): Promise<{ message: string; permission: DatasetPermission }> {
  const formData = new FormData()
  formData.append('user_id', userId)
  if (expiresInHours !== undefined && expiresInHours > 0) {
    formData.append('expires_in_hours', expiresInHours.toString())
  }

  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions`,
    {
      method: 'POST',
      body: formData
    },
    'Failed to grant dataset permission'
  )
}

export async function revokeDatasetPermission(
  datasetId: string,
  userId: string
): Promise<{ message: string }> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions/${userId}`,
    { method: 'DELETE' },
    'Failed to revoke dataset permission'
  )
}

export async function getUserDatasetPermissions(userId: string): Promise<{
  user_id: string
  permissions: DatasetPermission[]
  valid_permissions: DatasetPermission[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/user-permissions/${userId}`,
    undefined,
    'Failed to get user dataset permissions'
  )
}

export async function listDatasetPermissions(datasetId: string): Promise<{
  dataset_id: string
  permissions: DatasetPermission[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions`,
    undefined,
    'Failed to list dataset permissions'
  )
}

export interface BatchDatasetPermissionResult {
  user_id: string
  success: boolean
  message?: string
  error?: string
  permission?: DatasetPermission
  affected_tasks?: string[]
}

export interface BatchDatasetPermissionResponse {
  dataset_id: string
  granted?: number
  revoked?: number
  failed: number
  results: BatchDatasetPermissionResult[]
}

export async function batchGrantDatasetPermissions(
  datasetId: string,
  userIds: string[],
  expiresInHours?: number
): Promise<BatchDatasetPermissionResponse> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions/batch-grant`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_ids: userIds, expires_in_hours: expiresInHours })
    },
    'Failed to batch grant dataset permissions'
  )
}

export async function batchRevokeDatasetPermissions(
  datasetId: string,
  userIds: string[]
): Promise<BatchDatasetPermissionResponse> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/permissions/batch-revoke`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_ids: userIds })
    },
    'Failed to batch revoke dataset permissions'
  )
}


export async function updateDatasetVisibility(
  datasetId: string,
  isPublic: boolean,
  isOpenCollaboration?: boolean
): Promise<{ dataset_id: string; is_public: boolean; is_open_collaboration: boolean }> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/visibility`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_public: isPublic, is_open_collaboration: isOpenCollaboration })
    },
    'Failed to update dataset visibility'
  )
}

