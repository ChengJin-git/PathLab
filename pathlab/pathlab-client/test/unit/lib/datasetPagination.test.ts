import { describe, expect, it } from 'vitest'
import { clampDatasetPage } from '@renderer/lib/datasetPagination'

describe('clampDatasetPage', () => {
  it('does not reset page during transient refetch without data', () => {
    const next = clampDatasetPage(4, 1, {
      isError: false,
      isFetching: true,
      hasQueryData: false,
    })

    expect(next).toBe(4)
  })

  it('does not reset page when query is in error', () => {
    const next = clampDatasetPage(3, 1, {
      isError: true,
      isFetching: false,
      hasQueryData: false,
    })

    expect(next).toBe(3)
  })

  it('clamps page once stable data is available', () => {
    const next = clampDatasetPage(5, 2, {
      isError: false,
      isFetching: false,
      hasQueryData: true,
    })

    expect(next).toBe(2)
  })
})
