import { API_BASE } from '../config'
import { apiFetch } from './client'
import { invalidateWSIListCache } from './wsi'


export interface DatasetGrant {
  id: number
  dataset_id: string
  dataset_name?: string | null
  user_id: string
  user_email?: string | null
  user_nickname?: string | null
  user_role?: string | null
  user_is_active?: boolean | null
  granted_by: string
  can_read: boolean
  can_collaborate: boolean
  can_use_gpu: boolean
  expires_at: string | null
  created_at: string
  is_expired: boolean
  is_valid: boolean
}

export async function getMyDatasetGrants(): Promise<{
  user_id: string
  grants: DatasetGrant[]
  elevated_dataset_ids: string[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/my-grants`,
    undefined,
    'Failed to get dataset grants'
  )
}
export async function grantDatasetGrant(
  datasetId: string,
  userId: string,
  expiresInHours?: number
): Promise<{ message: string; permission: DatasetGrant }> {
  const formData = new FormData()
  formData.append('user_id', userId)
  if (expiresInHours !== undefined && expiresInHours > 0) {
    formData.append('expires_in_hours', expiresInHours.toString())
  }

  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/grants`,
    {
      method: 'POST',
      body: formData
    },
    'Failed to grant dataset grant'
  )
}

export async function revokeDatasetGrant(
  datasetId: string,
  userId: string
): Promise<{ message: string }> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/grants/${userId}`,
    { method: 'DELETE' },
    'Failed to revoke dataset grant'
  )
}

export async function getUserDatasetGrants(userId: string): Promise<{
  user_id: string
  grants: DatasetGrant[]
  valid_grants: DatasetGrant[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/user-grants/${userId}`,
    undefined,
    'Failed to get user dataset grants'
  )
}

export async function listDatasetGrants(datasetId: string): Promise<{
  dataset_id: string
  grants: DatasetGrant[]
}> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/grants`,
    undefined,
    'Failed to list dataset grants'
  )
}

export interface BatchDatasetGrantResult {
  user_id: string
  success: boolean
  message?: string
  error?: string
  grant?: DatasetGrant
  affected_tasks?: string[]
}

export interface BatchDatasetGrantResponse {
  dataset_id: string
  granted?: number
  revoked?: number
  failed: number
  results: BatchDatasetGrantResult[]
}

export async function batchGrantDatasetGrants(
  datasetId: string,
  userIds: string[],
  expiresInHours?: number
): Promise<BatchDatasetGrantResponse> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/grants/batch-grant`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_ids: userIds,
        expires_in_hours: expiresInHours
      })
    },
    'Failed to batch grant dataset grants'
  )
}

export async function batchRevokeDatasetGrants(
  datasetId: string,
  userIds: string[]
): Promise<BatchDatasetGrantResponse> {
  return apiFetch(
    `${API_BASE}/wsi/datasets/${datasetId}/grants/batch-revoke`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_ids: userIds })
    },
    'Failed to batch revoke dataset grants'
  )
}


export async function updateDatasetVisibility(
  datasetId: string,
  isPublic: boolean
): Promise<{ dataset_id: string; is_public: boolean }> {
  const result = await apiFetch<{ dataset_id: string; is_public: boolean }>(
    `${API_BASE}/wsi/datasets/${datasetId}/visibility`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_public: isPublic })
    },
    'Failed to update dataset visibility'
  )
  invalidateWSIListCache()
  return result
}
