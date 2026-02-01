/**
 * useDataSelection Hook
 *
 * Manages dataset and file selection state for Step 2.
 */

import { useState, useEffect, useMemo, useCallback } from 'react'
import { fetchDatasets, fetchWSIList, DatasetSummary } from '../api'
import { WSIItem, DataLevel, TaskType } from '../types/training'

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
  getFileType: (wsiPath: string | null, fileSize: number | null) => 'WSI' | 'Patch'

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
  // Dataset state
  const [datasets, setDatasets] = useState<DatasetSummary[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null)
  const [selectedDatasetName, setSelectedDatasetName] = useState('')

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

  // Pre-defined splits
  const [hasPreDefinedSplits, setHasPreDefinedSplits] = useState(false)
  const [predefinedSplitCounts, setPredefinedSplitCounts] = useState({ train: 0, val: 0, test: 0 })

  // Load datasets
  const loadDatasets = useCallback(async () => {
    setDatasetsLoading(true)
    try {
      const data = await fetchDatasets(dataLevel)
      setDatasets(data.items || [])
    } catch (e) {
      console.error('Failed to load datasets:', e)
    } finally {
      setDatasetsLoading(false)
    }
  }, [dataLevel])

  // Load files for selected dataset
  const loadWSIList = useCallback(async (datasetId: string) => {
    setLoading(true)
    try {
      const data = await fetchWSIList(datasetId, dataLevel)
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

  // Select dataset - also update split info from dataset summary immediately
  const selectDataset = useCallback((id: string | null, name: string) => {
    setSelectedDatasetId(id)
    setSelectedDatasetName(name)
    if (!id) {
      setItems([])
      setHasPreDefinedSplits(false)
      setPredefinedSplitCounts({ train: 0, val: 0, test: 0 })
    } else {
      // Get split info immediately from dataset summary (no need to wait for WSI list)
      const selectedDataset = datasets.find(d => d.dataset_id === id)
      if (selectedDataset) {
        const hasSplits = selectedDataset.has_predefined_splits ?? false
        const counts = selectedDataset.predefined_split_counts ?? { train: 0, val: 0, test: 0 }
        setHasPreDefinedSplits(hasSplits)
        setPredefinedSplitCounts(counts)
      }
    }
  }, [datasets])

  // Load files when dataset changes
  useEffect(() => {
    if (selectedDatasetId) {
      loadWSIList(selectedDatasetId)
    } else {
      setItems([])
    }
  }, [selectedDatasetId, loadWSIList])

  // Reset selection when dataLevel or taskType changes
  useEffect(() => {
    setSelectedDatasetId(null)
    setSelectedDatasetName('')
    setItems([])
    setSelectedIds(new Set())
  }, [dataLevel, taskType])

  // Filter datasets by task type
  const filteredDatasets = useMemo(() => {
    if (!datasets || datasets.length === 0) return []
    const compatibleType = taskType === 'survival_prediction' ? 'survival' : 'classification'
    return datasets.filter((d) => d.dataset_type === compatibleType)
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

  // Helper to determine file type
  const getFileType = (wsiPath: string | null, fileSize: number | null): 'WSI' | 'Patch' => {
    if (!wsiPath) return 'WSI'
    const path = wsiPath.toLowerCase()
    const patchExtensions = ['.png', '.jpg', '.jpeg', '.bmp']
    if (patchExtensions.some((ext) => path.endsWith(ext))) return 'Patch'
    if (path.endsWith('.tif') || path.endsWith('.tiff')) {
      const SIZE_THRESHOLD = 100 * 1024 * 1024
      return (fileSize || 0) >= SIZE_THRESHOLD ? 'WSI' : 'Patch'
    }
    return 'WSI'
  }

  // Check if this is a patch dataset
  const isPatchDataset = useMemo(() => {
    if (filteredItems.length === 0) return false
    const patchCount = filteredItems.filter(
      (item) => getFileType(item.wsi_path || null, item.file_size || null) === 'Patch'
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
        pageSlides.forEach((s) => next.delete(s.wsi_id))
      } else {
        pageSlides.forEach((s) => next.add(s.wsi_id))
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

  // Check for pre-defined splits
  useEffect(() => {
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
  }, [selectedIds, items])

  return {
    datasets,
    datasetsLoading,
    filteredDatasets,
    selectedDatasetId,
    selectedDatasetName,
    selectDataset,
    loadDatasets,
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

