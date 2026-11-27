import type { AuthUser, DatasetSummary } from '../api'

export function canEditDatasetVisibility(
  dataset: Pick<DatasetSummary, 'user_id' | 'can_delete'> | null | undefined,
  user: Pick<AuthUser, 'id' | 'role'> | null | undefined,
): boolean {
  if (!dataset || !user) return false
  if (user.role === 'admin') return true
  return Boolean(dataset.can_delete) || dataset.user_id === user.id
}
