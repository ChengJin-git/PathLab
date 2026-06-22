import type { QueryClient } from '@tanstack/react-query'
import { invalidateWSIListCache } from '../api/wsi'

export const DATASET_REPOSITORY_QUERY_KEYS = {
  pages: 'page-datasets',
  sourceOptions: 'dataset-source-options',
} as const

export interface DatasetRepositoryPageFilters {
  page: number
  pageSize: number
  search: string
  taskType: string
  dataType: string
  level: string
  visibility: string
  source: string
}

export function buildDatasetRepositoryPageQueryKey(filters: DatasetRepositoryPageFilters) {
  return [DATASET_REPOSITORY_QUERY_KEYS.pages, filters] as const
}

export async function invalidateDatasetSourceOptions(queryClient: QueryClient): Promise<void> {
  await queryClient.invalidateQueries({ queryKey: [DATASET_REPOSITORY_QUERY_KEYS.sourceOptions] })
}

export async function invalidateDatasetRepositoryCache(queryClient: QueryClient): Promise<void> {
  invalidateWSIListCache()
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: [DATASET_REPOSITORY_QUERY_KEYS.pages] }),
    invalidateDatasetSourceOptions(queryClient),
  ])
}
