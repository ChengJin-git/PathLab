/**
 * useDataSelection Hook
 *
 * Manages dataset and file selection state for Step 2.
 */

import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import { fetchAllDatasets, fetchAllWSIList } from '../../api/wsi'
import type { DatasetSummary } from '../../api/wsi'
import { getFileType } from '../../constants/fileTypes'
import { DataLevel, TaskType, getTaskFamily, getTaskMetadata } from '../../constants/training'
import { WSIItem } from '../../types/training'
import { useDraftState } from './useDraftState'

const D = 'draft:wizard:'

export interface UseDataSelectionProps {
  dataLevel: DataLevel
  taskType: TaskType
}

export interface UseDataSelectionReturn {
  // Dataset selection
  datasets: DatasetSummary[]
  datasetsLoading: boolean
  filteredDatasets: DatasetSummary[]
  selectedDatasetId: string | null
  selectedDatasetName: string
  selectDataset: (id: string | null, name: string) => void
  loadDatasets: () => Promise<void>

  // Dataset-level selection (without loading files)
  filesExpanded: boolean
  expandFiles: () => void
  collapseFiles: () => void
  isWholeDatasetSelected: boolean
  selectedDatasetFileCount: number

  // File selection
  items: WSIItem[]
  loading: boolean
  selectedIds: Set<string>
  setSelectedIds: (ids: Set<string>) => void
  toggleSelection: (wsiId: string) => void
  clearSelection: () => void

  // Filtering and pagination
  searchQuery: string
  setSearchQuery: (query: string) => void
  filteredItems: WSIItem[]
  currentPage: number
  setCurrentPage: (page: number) => void
  pageSize: number
  setPageSize: (size: number) => void
  totalPages: number

  // Case grouping
  groupedByCaseId: [string, WSIItem[]][]
  hasMultiSlideCases: boolean
  expandedCases: Set<string>
  toggleCaseExpansion: (caseId: string) => void

  // Pagination helpers
  paginatedCases: [string, WSIItem[]][] | null
  paginatedItems: WSIItem[]
  pageSlides: WSIItem[]
  allPageSelected: boolean
  allFilteredSelected: boolean
  handleSelectPage: () => void
  handleSelectAllFiltered: () => void

  // Additional computed values
  isPatchDataset: boolean
  totalCases: number
  getFileType: (fileExtension: string | null, fileSize: number | null, authoritativeDataType?: 'wsi' | 'patch' | null) => 'WSI' | 'Patch'

  // Pre-defined splits
  hasPreDefinedSplits: boolean
  predefinedSplitCounts: { train: number; val: number; test: number }

  // Reload
  reloadItems: () => Promise<void>
}

export function useDataSelection({
  dataLevel,
  taskType,
}: UseDataSelectionProps): UseDataSelectionReturn {
  const isFirstMountRef = useRef(true)

  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useDraftState<string | null>(`${D}datasetId`, null)
  const [selectedDatasetName, setSelectedDatasetName] = useDraftState(`${D}datasetName`, '')

  // File state
  const [items, setItems] = useState<WSIItem[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // Filtering and pagination
  const [searchQuery, setSearchQuery] = useState('')
  const [currentPage, setCurrentPage] = useState(1)
  const [pageSize, setPageSize] = useState(5)

  // Case grouping
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set())

  // Dataset-level selection (lazy file loading)
  const [filesExpanded, setFilesExpanded] = useState(false)

  // Pre-defined splits
  const [hasPreDefinedSplits, setHasPreDefinedSplits] = useState(false)
  const [predefinedSplitCounts, setPredefinedSplitCounts] = useState({ train: 0, val: 0, test: 0 })

  // Load datasets
  const loadDatasets = useCallback(async () => {
    setDatasetsLoading(true)
    try {
      const data = await fetchAllDatasets(dataLevel, { task_type: taskType })
      setDatasets(data.items || [])
    } catch (e) {
      console.error('Failed to load datasets:', e)
    } finally {
      setDatasetsLoading(false)
    }
  }, [dataLevel, taskType])

  // Load files for selected dataset
  const loadWSIList = useCallback(async (datasetId: string) => {
    setLoading(true)
    try {
      const data = await fetchAllWSIList(datasetId, dataLevel)
      setItems((data.items || []) as WSIItem[])
    } catch (e) {
      console.error('Failed to load WSI list:', e)
    } finally {
      setLoading(false)
    }
  }, [dataLevel])

  // Reload items
  const reloadItems = useCallback(async () => {
    if (selectedDatasetId) {
      await loadWSIList(selectedDatasetId)
    }
  }, [selectedDatasetId, loadWSIList])

  // Select dataset - does NOT load files (lazy loading)
  const selectDataset = useCallback((id: string | null, name: string) => {
    setSelectedDatasetId(id)
    setSelectedDatasetName(name)
    setFilesExpanded(false)
    setItems([])
    setSelectedIds(new Set())
    if (!id) {
      setHasPreDefinedSplits(false)
      setPredefinedSplitCounts({ train: 0, val: 0, test: 0 })
    } else {
      const selectedDataset = datasets.find(d => d.dataset_id === id)
      if (selectedDataset) {
        const hasSplits = selectedDataset.has_predefined_splits ?? false
        const counts = selectedDataset.predefined_split_counts ?? { train: 0, val: 0, test: 0 }
        setHasPreDefinedSplits(hasSplits)
        setPredefinedSplitCounts(counts)
      }
    }
  }, [datasets, setSelectedDatasetId, setSelectedDatasetName])

  // Expand files: load and show file list for the selected dataset
  const expandFiles = useCallback(() => {
    if (selectedDatasetId && !filesExpanded) {
      setFilesExpanded(true)
      loadWSIList(selectedDatasetId)
    }
  }, [selectedDatasetId, filesExpanded, loadWSIList])

  // Collapse files: hide file list, go back to dataset-level view
  const collapseFiles = useCallback(() => {
    setFilesExpanded(false)
    setItems([])
    setSelectedIds(new Set())
  }, [])

  // biome-ignore lint/correctness/useExhaustiveDependencies: dataLevel/taskType are change triggers; the callback only calls stable setters so biome incorrectly flags them as unused deps
  useEffect(() => {
    if (isFirstMountRef.current) {
      isFirstMountRef.current = false
      return
    }
    setSelectedDatasetId(null)
    setSelectedDatasetName('')
    setFilesExpanded(false)
    setItems([])
    setSelectedIds(new Set())
  }, [dataLevel, taskType, setSelectedDatasetId, setSelectedDatasetName])

  // Select the requested task's labels from multi-task image collections.
  const filteredDatasets = useMemo(() => {
    if (!datasets || datasets.length === 0) return []
    return datasets.filter((d) => d.task_types.includes(taskType))
  }, [datasets, taskType])

  // Filter items by search query
  const filteredItems = useMemo(() => {
    if (!items || items.length === 0) return []
    if (!searchQuery) return items
    const query = searchQuery.toLowerCase()
    return items.filter(
      (item) =>
        (item.original_filename || '').toLowerCase().includes(query) ||
        (item.wsi_id || '').toLowerCase().includes(query) ||
        (item.label || '').toLowerCase().includes(query)
    )
  }, [items, searchQuery])

  // Check if this is a patch dataset
  const isPatchDataset = useMemo(() => {
    if (filteredItems.length === 0) return false
    const patchCount = filteredItems.filter(
      (item) => getFileType(item.file_extension || null, item.file_size || null, item.data_type || null) === 'Patch'
    ).length
    return patchCount > filteredItems.length / 2
  }, [filteredItems])

  // Group items by case_id
  const groupedByCaseId = useMemo(() => {
    const groups = new Map<string, WSIItem[]>()
    const NO_CASE = '__no_case__'

    filteredItems.forEach((item) => {
      const caseId = item.case_id || NO_CASE
      if (!groups.has(caseId)) {
        groups.set(caseId, [])
      }
      groups.get(caseId)!.push(item)
    })

    return Array.from(groups.entries()).sort((a, b) => {
      if (a[0] === NO_CASE) return 1
      if (b[0] === NO_CASE) return -1
      if (b[1].length !== a[1].length) return b[1].length - a[1].length
      return a[0].localeCompare(b[0])
    })
  }, [filteredItems])

  // Check if we should use grouping UI
  const hasMultiSlideCases = useMemo(() => {
    const hasAnyCaseId = filteredItems.some((item) => item.case_id && item.case_id.trim() !== '')
    if (!hasAnyCaseId) return false
    if (isPatchDataset) return false
    return groupedByCaseId.some(([caseId, slides]) => caseId !== '__no_case__' && slides.length > 1)
  }, [filteredItems, groupedByCaseId, isPatchDataset])

  // Pagination
  const totalCases = groupedByCaseId.length
  const totalPages = hasMultiSlideCases
    ? Math.ceil(totalCases / pageSize)
    : Math.ceil(filteredItems.length / pageSize)

  useEffect(() => {
    if (currentPage > totalPages && totalPages > 0) {
      setCurrentPage(totalPages)
    } else if (totalPages === 0 && currentPage !== 1) {
      setCurrentPage(1)
    }
  }, [totalPages, currentPage])

  const startIndex = (currentPage - 1) * pageSize

  const paginatedCases = hasMultiSlideCases
    ? groupedByCaseId.slice(startIndex, startIndex + pageSize)
    : null

  const paginatedItems = hasMultiSlideCases
    ? []
    : filteredItems.slice(startIndex, startIndex + pageSize)

  const pageSlides = useMemo(() => {
    if (hasMultiSlideCases && paginatedCases) {
      return paginatedCases.flatMap(([, slides]) => slides)
    }
    return paginatedItems || []
  }, [hasMultiSlideCases, paginatedCases, paginatedItems])

  const allPageSelected = pageSlides.length > 0 && pageSlides.every((s) => selectedIds.has(s.wsi_id))
  const allFilteredSelected = filteredItems.length > 0 && filteredItems.every((s) => selectedIds.has(s.wsi_id))

  // Toggle selection
  const toggleSelection = useCallback((wsiId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(wsiId)) {
        next.delete(wsiId)
      } else {
        next.add(wsiId)
      }
      return next
    })
  }, [])

  // Toggle case expansion
  const toggleCaseExpansion = useCallback((caseId: string) => {
    setExpandedCases((prev) => {
      const next = new Set(prev)
      if (next.has(caseId)) {
        next.delete(caseId)
      } else {
        next.add(caseId)
      }
      return next
    })
  }, [])

  // Select page
  const handleSelectPage = useCallback(() => {
    if (allFilteredSelected) {
      setSelectedIds(new Set())
      return
    }
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allPageSelected) {
        for (const s of pageSlides) next.delete(s.wsi_id)
      } else {
        for (const s of pageSlides) next.add(s.wsi_id)
      }
      return next
    })
  }, [allFilteredSelected, allPageSelected, pageSlides])

  // Select all filtered
  const handleSelectAllFiltered = useCallback(() => {
    setSelectedIds(new Set(filteredItems.map((i) => i.wsi_id)))
  }, [filteredItems])

  // Clear selection
  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
  }, [])

  // Check for pre-defined splits (only when files are expanded and individual items are selected)
  useEffect(() => {
    // When using whole-dataset selection (files not expanded), the split info
    // comes from the dataset summary (set in selectDataset), so skip this effect.
    if (!filesExpanded && selectedDatasetId) {
      return
    }

    if (selectedIds.size === 0) {
      setHasPreDefinedSplits(false)
      setPredefinedSplitCounts({ train: 0, val: 0, test: 0 })
      return
    }

    const selectedItems = items.filter((item) => selectedIds.has(item.wsi_id))
    const counts = { train: 0, val: 0, test: 0 }
    let hasMissing = false

    selectedItems.forEach((item) => {
      if (!item.split) {
        hasMissing = true
      } else {
        const s = item.split.toLowerCase()
        if (s === 'train') counts.train++
        else if (s === 'val' || s === 'validation') counts.val++
        else if (s === 'test') counts.test++
      }
    })

    setPredefinedSplitCounts(counts)
    setHasPreDefinedSplits(!hasMissing && counts.train > 0)
  }, [selectedIds, items, filesExpanded, selectedDatasetId])

  // Whether user selected a dataset without expanding individual files
  const isWholeDatasetSelected = !!selectedDatasetId && !filesExpanded

  // Get file count from dataset summary for the selected dataset
  const selectedDatasetFileCount = useMemo(() => {
    if (!selectedDatasetId) return 0
    const ds = datasets.find(d => d.dataset_id === selectedDatasetId)
    return ds?.file_count ?? 0
  }, [selectedDatasetId, datasets])

  return {
    datasets,
    datasetsLoading,
    filteredDatasets,
    selectedDatasetId,
    selectedDatasetName,
    selectDataset,
    loadDatasets,
    filesExpanded,
    expandFiles,
    collapseFiles,
    isWholeDatasetSelected,
    selectedDatasetFileCount,
    items,
    loading,
    selectedIds,
    setSelectedIds,
    toggleSelection,
    clearSelection,
    searchQuery,
    setSearchQuery,
    filteredItems,
    currentPage,
    setCurrentPage,
    pageSize,
    setPageSize,
    totalPages,
    groupedByCaseId,
    hasMultiSlideCases,
    expandedCases,
    toggleCaseExpansion,
    paginatedCases,
    paginatedItems,
    pageSlides,
    allPageSelected,
    allFilteredSelected,
    handleSelectPage,
    handleSelectAllFiltered,
    isPatchDataset,
    totalCases,
    getFileType,
    hasPreDefinedSplits,
    predefinedSplitCounts,
    reloadItems,
  }
}
