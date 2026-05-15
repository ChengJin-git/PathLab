import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useDataSelection } from '@renderer/lib/hooks/useDataSelection'
import * as wsiApi from '@renderer/api/wsi'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))

describe('useDataSelection predefined splits', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
  })

  it('sets hasPreDefinedSplits and predefinedSplitCounts when selecting a dataset with predefined splits', async () => {
    vi.spyOn(wsiApi, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-1',
          dataset_name: 'All-IDB',
          user_id: 'u1',
          file_count: 260,
          total_size: 0,
          data_type: 'patch',
          task_type: 'patch_classification',
          aggregation_level: 'file',
          has_predefined_splits: true,
          predefined_split_counts: { train: 180, val: 40, test: 40 },
        },
      ],
      total: 1,
    })

    const { result } = renderHook(() =>
      useDataSelection({ dataLevel: 'patch', taskType: 'patch_classification' }),
    )

    await act(async () => {
      await result.current.loadDatasets()
    })

    act(() => {
      result.current.selectDataset('dataset-1', 'All-IDB')
    })

    await waitFor(() => {
      expect(result.current.hasPreDefinedSplits).toBe(true)
      expect(result.current.predefinedSplitCounts).toEqual({ train: 180, val: 40, test: 40 })
    })
  })

  it('clears split state when selecting null dataset', async () => {
    vi.spyOn(wsiApi, 'fetchDatasets').mockResolvedValue({
      items: [
        {
          dataset_id: 'dataset-1',
          dataset_name: 'All-IDB',
          user_id: 'u1',
          file_count: 260,
          total_size: 0,
          data_type: 'patch',
          task_type: 'patch_classification',
          aggregation_level: 'file',
          has_predefined_splits: true,
          predefined_split_counts: { train: 180, val: 40, test: 40 },
        },
      ],
      total: 1,
    })

    const { result } = renderHook(() =>
      useDataSelection({ dataLevel: 'patch', taskType: 'patch_classification' }),
    )

    await act(async () => {
      await result.current.loadDatasets()
    })

    act(() => {
      result.current.selectDataset('dataset-1', 'All-IDB')
    })

    await waitFor(() => {
      expect(result.current.hasPreDefinedSplits).toBe(true)
    })

    act(() => {
      result.current.selectDataset(null, '')
    })

    await waitFor(() => {
      expect(result.current.hasPreDefinedSplits).toBe(false)
      expect(result.current.predefinedSplitCounts).toEqual({ train: 0, val: 0, test: 0 })
    })
  })
})
