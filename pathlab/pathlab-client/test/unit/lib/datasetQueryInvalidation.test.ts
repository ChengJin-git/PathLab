import { QueryClient } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@renderer/api/wsi', () => ({
  invalidateWSIListCache: vi.fn(),
}))

import {
  DATASET_REPOSITORY_QUERY_KEYS,
  buildDatasetRepositoryPageQueryKey,
  invalidateDatasetRepositoryCache,
  invalidateDatasetSourceOptions,
} from '@renderer/lib/datasetQueryInvalidation'
import { invalidateWSIListCache } from '@renderer/api/wsi'

const mockedInvalidateWSIListCache = vi.mocked(invalidateWSIListCache)

describe('dataset repository query invalidation', () => {
  beforeEach(() => {
    mockedInvalidateWSIListCache.mockClear()
  })

  it('builds stable query keys for dataset repository pages', () => {
    const filters = {
      page: 1,
      pageSize: 8,
      search: 'lung',
      taskType: 'classification',
      dataType: 'wsi',
      level: 'patient',
      visibility: 'public',
      source: 'lung',
    } as const

    expect(buildDatasetRepositoryPageQueryKey(filters)).toEqual([
      DATASET_REPOSITORY_QUERY_KEYS.pages,
      filters,
    ])
  })

  it('clears API dataset caches before invalidating React Query dataset repository data', async () => {
    const queryClient = new QueryClient()
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)

    await invalidateDatasetRepositoryCache(queryClient)

    expect(mockedInvalidateWSIListCache).toHaveBeenCalledOnce()
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: [DATASET_REPOSITORY_QUERY_KEYS.pages] })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: [DATASET_REPOSITORY_QUERY_KEYS.sourceOptions] })
  })

  it('can refresh only dataset source options when repository cards are unchanged', async () => {
    const queryClient = new QueryClient()
    const invalidateQueries = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue(undefined)

    await invalidateDatasetSourceOptions(queryClient)

    expect(mockedInvalidateWSIListCache).not.toHaveBeenCalled()
    expect(invalidateQueries).toHaveBeenCalledOnce()
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: [DATASET_REPOSITORY_QUERY_KEYS.sourceOptions] })
  })
})
