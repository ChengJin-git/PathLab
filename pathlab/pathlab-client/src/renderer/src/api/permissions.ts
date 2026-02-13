import { API_BASE } from '../config'
import { apiFetch } from './client'

// ============================================================================
// Dataset Permission APIs (Temporary Elevated Access Management)
// ============================================================================

/**
 * Dataset permission info
 */
export interface DatasetPermission {
  id: number
  dataset_id: string
  user_id: string
  granted_by: string
  permission_level: string
  expires_at: string | null
  created_at: string
  is_expired: boolean
  is_valid: boolean
}

/**
 * Get current user's dataset permissions
 * Returns list of datasets where user has temporary elevated access
 */
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
/**
 * Grant temporary elevated permission to a user for a dataset (admin only)
 * @param datasetId - Dataset ID
 * @param userId - User ID to grant permission to
 * @param expiresInHours - Optional expiration time in hours (null = no expiration)
 */
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

/**
 * Revoke a user's permission for a dataset (admin only)
 * @param datasetId - Dataset ID
 * @param userId - User ID to revoke permission from
 */
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

/**
 * Get all dataset permissions for a specific user (admin only)
 * @param userId - User ID to get permissions for
 */
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

