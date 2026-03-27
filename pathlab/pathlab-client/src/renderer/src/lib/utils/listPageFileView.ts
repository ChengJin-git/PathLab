export interface ListPageFileViewInput {
  selectedDatasetId: string | null
  showInitialFilesLoading: boolean
  hasFilesError: boolean
  itemCount: number
  searchQuery: string
  debouncedSearch: string
}

export interface ListPageFileViewState {
  hasActiveSearch: boolean
  showSearchActions: boolean
  showDatasetEmptyState: boolean
  showFileTableArea: boolean
  showNoMatchingFilesState: boolean
}

export function getListPageFileViewState(input: ListPageFileViewInput): ListPageFileViewState {
  const hasDataset = Boolean(input.selectedDatasetId)
  const hasActiveSearch = input.searchQuery.trim() !== '' || input.debouncedSearch.trim() !== ''
  const hasItems = input.itemCount > 0
  const canRenderContent = hasDataset && !input.showInitialFilesLoading && !input.hasFilesError

  const showSearchActions = canRenderContent && (hasItems || hasActiveSearch)
  const showDatasetEmptyState = canRenderContent && !hasItems && !hasActiveSearch
  const showFileTableArea = canRenderContent && (hasItems || hasActiveSearch)
  const showNoMatchingFilesState = showFileTableArea && !hasItems && hasActiveSearch

  return {
    hasActiveSearch,
    showSearchActions,
    showDatasetEmptyState,
    showFileTableArea,
    showNoMatchingFilesState,
  }
}
