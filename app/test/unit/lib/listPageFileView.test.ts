import { describe, expect, it } from 'vitest'
import { getListPageFileViewState } from '../../../src/renderer/src/lib/utils/listPageFileView'

describe('getListPageFileViewState', () => {
  it('shows only loading state during initial files load', () => {
    const state = getListPageFileViewState({
      selectedDatasetId: 'ds-1',
      showInitialFilesLoading: true,
      hasFilesError: false,
      itemCount: 0,
      searchQuery: '',
      debouncedSearch: '',
    })

    expect(state.showSearchActions).toBe(false)
    expect(state.showDatasetEmptyState).toBe(false)
    expect(state.showNoMatchingFilesState).toBe(false)
    expect(state.showFileTableArea).toBe(false)
  })

  it('shows dataset-empty state when no files and no active search', () => {
    const state = getListPageFileViewState({
      selectedDatasetId: 'ds-1',
      showInitialFilesLoading: false,
      hasFilesError: false,
      itemCount: 0,
      searchQuery: '',
      debouncedSearch: '',
    })

    expect(state.showSearchActions).toBe(false)
    expect(state.showDatasetEmptyState).toBe(true)
    expect(state.showNoMatchingFilesState).toBe(false)
    expect(state.showFileTableArea).toBe(false)
  })

  it('shows search + no-match state when search yields zero files', () => {
    const state = getListPageFileViewState({
      selectedDatasetId: 'ds-1',
      showInitialFilesLoading: false,
      hasFilesError: false,
      itemCount: 0,
      searchQuery: 'abc',
      debouncedSearch: 'abc',
    })

    expect(state.showSearchActions).toBe(true)
    expect(state.showDatasetEmptyState).toBe(false)
    expect(state.showNoMatchingFilesState).toBe(true)
    expect(state.showFileTableArea).toBe(true)
  })

  it('shows table and search actions when data exists', () => {
    const state = getListPageFileViewState({
      selectedDatasetId: 'ds-1',
      showInitialFilesLoading: false,
      hasFilesError: false,
      itemCount: 10,
      searchQuery: '',
      debouncedSearch: '',
    })

    expect(state.showSearchActions).toBe(true)
    expect(state.showDatasetEmptyState).toBe(false)
    expect(state.showNoMatchingFilesState).toBe(false)
    expect(state.showFileTableArea).toBe(true)
  })
})
