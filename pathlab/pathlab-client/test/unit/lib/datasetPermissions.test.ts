import { describe, expect, it } from 'vitest'

import { canEditDatasetVisibility } from '@renderer/lib/datasetPermissions'

describe('dataset permission helpers', () => {
  it('allows non-admin dataset editors to change visibility when backend marks the dataset editable', () => {
    const dataset = { user_id: null, can_delete: true }
    const user = { id: 'pathologist-1', role: 'pathologist' as const }

    expect(canEditDatasetVisibility(dataset, user)).toBe(true)
  })

  it('allows admins to change visibility regardless of ownership fields', () => {
    const dataset = { user_id: 'other-user', can_delete: false }
    const user = { id: 'admin-1', role: 'admin' as const }

    expect(canEditDatasetVisibility(dataset, user)).toBe(true)
  })

  it('denies non-admin users when neither backend edit capability nor ownership matches', () => {
    const dataset = { user_id: 'owner-1', can_delete: false }
    const user = { id: 'pathologist-1', role: 'pathologist' as const }

    expect(canEditDatasetVisibility(dataset, user)).toBe(false)
  })
})
