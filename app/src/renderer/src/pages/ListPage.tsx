import React, { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import { Checkbox } from '../components/ui/checkbox'
import { useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { DatasetLoading } from '../components/common/PageLoading'
import { Link, useNavigate, useLocation } from 'react-router-dom'
import { useToast } from '../contexts/ToastContext'
import { fetchWSIList, fetchWSIIds, fetchDatasets, fetchDatasetSourceOptions, fetchDatasetSummary, updateDatasetProperties, type DatasetPropertiesUpdate, uploadWSIFile, updateWSIMetadata, getWSIStorageInfo, WSIStorageInfo, DatasetSummary, startBatchUpdateMetadataTask, startDeleteDatasetTask, invalidateWSIListCache, exportDatasetLabels, prefetchDatasets, prefetchWSIList } from '../api'
import { ApiError } from '../api/client'
import { Upload, Microscope, Edit, Trash2, CheckCircle, X, Loader2, ChevronLeft, ChevronRight, ChevronDown, Search, FolderOpen, ArrowLeft, Database, LayoutGrid, Pencil, Users, FileImage, User, Download, List, ArrowUp, ArrowDown, ChevronsUpDown, GitMerge, Globe, Lock } from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import {useSidebarText} from '../components/chat/sidebarText'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Tooltip } from '../components/ui/tooltip'
import { Input } from '../components/ui/input'
import { Select } from '../components/ui/select'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { ALL_ACCEPT_STRING, getFileType } from '../constants/fileTypes'
import { formatFileSize } from '../lib/utils/utils'
import { clampDatasetPage, clampFilePage } from '../lib/utils/datasetPagination'
import { getListPageFileViewState } from '../lib/utils/listPageFileView'
import {
  DATASET_REPOSITORY_QUERY_KEYS,
  buildDatasetRepositoryPageQueryKey,
  invalidateDatasetRepositoryCache,
  invalidateDatasetSourceOptions,
} from '../lib/datasetQueryInvalidation'
import { canEditDatasetVisibility } from '../lib/datasetPermissions'
import { isExternalUnavailable } from '../lib/externalAvailability'
import { useAsyncAction } from '../lib/hooks/useAsyncAction'
import { useAuth } from '../contexts/AuthContext'
import { FileMetadataModal, DeleteConfirmModal, BatchDeleteModal, EditMetadataModal, BatchEditModal, ExportLabelsModal, DatasetCard, type ExportLabelsOptions } from '../components/list'
import { organSources, organSourceKeyMap } from '../constants/wsi'
import { getTaskFamily, type TaskType } from '../constants/training'
import DatasetEditor from '../components/datasets/DatasetEditor'
import DatasetOverview from '../components/datasets/DatasetOverview'
import { useWorkbenchText } from '../components/chat/workbenchText'


type ListWSIItem = import('../api/wsi').WSISummary

type DatasetTaskFilter = 'all' | 'classification' | 'survival' | 'segmentation' | 'detection'
type DatasetTaskFamily = Exclude<DatasetTaskFilter, 'all'>
type DatasetTypeFilter = 'all' | 'wsi' | 'patch'
type DatasetLevelFilter = 'all' | 'file' | 'patient'
type DatasetVisibilityFilter = 'all' | 'public' | 'private'
type DatasetViewMode = 'grid' | 'list'

const UNKNOWN_SOURCE_ORGAN_FILTER = '__unknown__'

const getNormalizedDatasetTaskType = (taskType: string): DatasetTaskFamily => {
  const family = getTaskFamily(taskType)
  if (family) return family
  return 'classification'
}

const getCanonicalDatasetTaskType = (taskType: DatasetTaskFamily): TaskType => {
  switch (taskType) {
    case 'classification':
      return 'wsi_classification'
    case 'survival':
      return 'wsi_survival'
    case 'segmentation':
      return 'patch_segmentation'
    case 'detection':
      return 'patch_detection'
  }
}

const getCanonicalDatasetTaskFilter = (taskType: DatasetTaskFilter): TaskType | undefined => {
  return taskType === 'all' ? undefined : getCanonicalDatasetTaskType(taskType)
}

const getDatasetVisualType = (dataset: DatasetSummary): 'slides' | 'images' => {
  if (dataset.data_type === 'wsi') return 'slides'
  if (dataset.data_type === 'patch') return 'images'
  if (dataset.file_count === 0) return 'images'

  const avgSize = dataset.total_size / dataset.file_count
  return avgSize > 20 * 1024 * 1024 ? 'slides' : 'images'
}

const getDatasetSourceOrganFilterValue = (sourceOrgan?: string | null): string => {
  const normalized = sourceOrgan?.trim()
  return normalized || UNKNOWN_SOURCE_ORGAN_FILTER
}

const getVisiblePaginationPages = (currentPage: number, totalPages: number): number[] => {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1)
  }

  return Array.from(new Set([1, currentPage - 1, currentPage, currentPage + 1, totalPages]))
    .filter((page) => page >= 1 && page <= totalPages)
    .sort((left, right) => left - right)
}

type SortColumn = 'filename' | 'label' | 'event_time' | 'event_status'

const SORT_FIELD_MAP: Record<SortColumn, string> = {
  filename: 'original_filename',
  label: 'label',
  event_time: 'event_time',
  event_status: 'event_status',
}

export default function ListPage() {
  const workbenchText = useWorkbenchText()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const sidebarText=useSidebarText()
  const location = useLocation()
  const fromAIChat = (location.state as { fromAIChat?: boolean } | null)?.fromAIChat === true
  const initialDatasetId = (location.state as { dataset_id?: string } | null)?.dataset_id
  const { error: toastError, success: toastSuccess } = useToast()
  const { addDeleteWSITask, tasks, subscribeStorageSSE, deletingDatasetNames, addDeletingDatasetName, removeDeletingDatasetByTaskId } = useBackgroundTask()
  const { isAdmin, user } = useAuth()
  const qc = useQueryClient()

  // Dataset view state - null means showing dataset list, otherwise showing files in that dataset
  // selectedDatasetId is used for API calls, selectedDatasetName is used for display
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(initialDatasetId || null)
  const [selectedDatasetName, setSelectedDatasetName] = useState<string>('')
  const [selectedDatasetType, setSelectedDatasetType] = useState<DatasetTaskFamily>('classification')
  const [selectedDatasetSummary, setSelectedDatasetSummary] = useState<DatasetSummary | null>(null)

  // Search and Filter state
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [datasetSearchQuery, setDatasetSearchQuery] = useState('')
  const [datasetDebouncedSearch, setDatasetDebouncedSearch] = useState('')
  const [datasetTaskFilter, setDatasetTaskFilter] = useState<DatasetTaskFilter>('all')
  const [datasetTypeFilter, setDatasetTypeFilter] = useState<DatasetTypeFilter>('all')
  const [datasetLevelFilter, setDatasetLevelFilter] = useState<DatasetLevelFilter>('all')
  const [datasetVisibilityFilter, setDatasetVisibilityFilter] = useState<DatasetVisibilityFilter>('all')
  const [datasetSourceFilter, setDatasetSourceFilter] = useState<string>('all')
  const [datasetViewMode, setDatasetViewMode] = useState<DatasetViewMode>('grid')
  const [datasetCurrentPage, setDatasetCurrentPage] = useState(1)
  const [datasetPageInput, setDatasetPageInput] = useState('1')
  const [datasetListItemsPerPage, setDatasetListItemsPerPage] = useState(5)

  // File list pagination state
  const [currentPage, setCurrentPage] = useState(1)
  const [filePageInput, setFilePageInput] = useState('1')
  const itemsPerPage = 10

  // Upload functionality
  const [uploading, runUpload] = useAsyncAction()
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, { progress: number; status: 'uploading' | 'success' | 'error'; error?: string }>>(new Map())
  const fileInputRef = useRef<HTMLInputElement>(null)



  // File upload with metadata modal
  const [showFileMetadataModal, setShowFileMetadataModal] = useState(false)
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [fileMetadata, setFileMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string }>>(new Map())
  const [uploadDatasetSourceSelection, setUploadDatasetSourceSelection] = useState('')
  const [uploadDatasetSourceCustom, setUploadDatasetSourceCustom] = useState('')

  // Delete confirmation modal
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [wsiToDelete, setWsiToDelete] = useState<{ wsi_id: string; label: string; original_filename?: string } | null>(null)
  const [wsiStorageInfo, setWsiStorageInfo] = useState<WSIStorageInfo | null>(null)
  const [loadingStorageInfo, runStorageInfo] = useAsyncAction()

  // Batch selection for deletion
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [showBatchDeleteModal, setShowBatchDeleteModal] = useState(false)

  // Edit metadata modal
  const [showEditModal, setShowEditModal] = useState(false)
  const [editingWSI, setEditingWSI] = useState<{
    wsi_id: string
    label?: string
    case_id: string
    age?: number
    gender?: string
    event_time?: number
    event_status?: number
  } | null>(null)
  const [editLabel, setEditLabel] = useState('')
  const [editCaseId, setEditCaseId] = useState('')
  const [editAge, setEditAge] = useState('')
  const [editGender, setEditGender] = useState('')
  const [editEventTime, setEditEventTime] = useState('')
  const [editEventStatus, setEditEventStatus] = useState('')
  const [updating, runUpdate] = useAsyncAction()

  // Batch edit metadata
  const [showBatchEditModal, setShowBatchEditModal] = useState(false)
  const [batchEditLabel, setBatchEditLabel] = useState('')
  const [batchEditCaseId, setBatchEditCaseId] = useState('')
  const [batchEditAge, setBatchEditAge] = useState('')
  const [batchEditGender, setBatchEditGender] = useState('')
  const [batchEditEventTime, setBatchEditEventTime] = useState('')
  const [batchEditEventStatus, setBatchEditEventStatus] = useState('')
  const [batchUpdating, runBatchUpdate] = useAsyncAction()

  // Case grouping - tracks which case_ids are expanded
  const [expandedCases, setExpandedCases] = useState<Set<string>>(new Set())

  const [sortColumn, setSortColumn] = useState<SortColumn | null>(null)
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')

  const handleSort = useCallback((col: SortColumn) => {
    if (sortColumn === col) {
      if (sortDirection === 'asc') {
        setSortDirection('desc')
      } else {
        setSortColumn(null)
        setSortDirection('asc')
      }
    } else {
      setSortColumn(col)
      setSortDirection('asc')
    }
    setCurrentPage(1)
  }, [sortColumn, sortDirection])

  const prefetchSort = useCallback((col: SortColumn) => {
    if (!selectedDatasetId) return
    const nextSortBy = SORT_FIELD_MAP[col]
    let nextOrder: 'asc' | 'desc'
    if (sortColumn === col) {
      if (sortDirection === 'asc') {
        nextOrder = 'desc'
      } else {
        return
      }
    } else {
      nextOrder = 'asc'
    }
    void qc.prefetchQuery({
      queryKey: ['wsi-list', selectedDatasetId, { page: 1, search: debouncedSearch, sort_by: nextSortBy, sort_order: nextOrder }],
      queryFn: () => fetchWSIList(selectedDatasetId!, undefined, {
        page: 1,
        page_size: itemsPerPage,
        search: debouncedSearch || undefined,
        sort_by: nextSortBy,
        sort_order: nextOrder,
      }),
      staleTime: 2 * 60 * 1000,
    })
  }, [qc, selectedDatasetId, sortColumn, sortDirection, debouncedSearch])

  // Edit dataset - stores dataset_id for the dataset being edited (rename + type + aggregation_level change)
  const [editingDatasetId, setEditingDatasetId] = useState<string | null>(null)
  const [datasetEditorTab, setDatasetEditorTab] = useState<'details' | 'labels'>('details')

  const resolveSourceValue = (selection: string, custom: string) => selection === 'Other' ? custom.trim() : selection.trim()

  const toSourceSelectionState = (value?: string | null) => {
    const normalized = value?.trim() || ''
    const knownSources = organSources.filter(source => source !== 'Other')
    if (!normalized) return { selection: '', custom: '' }
    return knownSources.includes(normalized)
      ? { selection: normalized, custom: '' }
      : { selection: 'Other', custom: normalized }
  }

  // Delete dataset - stores dataset_id and name for the dataset to delete
  const [datasetToDeleteId, setDatasetToDeleteId] = useState<string | null>(null)
  const [datasetToDeleteName, setDatasetToDeleteName] = useState<string>('')
  const [datasetToDeleteFileCount, setDatasetToDeleteFileCount] = useState<number>(0)
  const [deleting, runDelete] = useAsyncAction()

  const completedDeleteTaskIdsRef = useRef<Set<string>>(new Set())
  const completedUploadTaskIdsRef = useRef<Set<string>>(new Set())
  // Maps task_id → dataset_id for deletes that have been signaled as done by SSE but
  // not yet confirmed absent from the server response. Overlay stays until confirmed.
  const pendingDeleteRef = useRef<Map<string, string>>(new Map())

  // Export labels - stores dataset for export modal
  const [exportingDataset, setExportingDataset] = useState<DatasetSummary | null>(null)
  const [showExportModal, setShowExportModal] = useState(false)
  const [exporting, runExport] = useAsyncAction()

  const isSegmentationDataset = selectedDatasetType === 'segmentation' || selectedDatasetType === 'detection'
  const labelColumnTitle = isSegmentationDataset ? t('listPage.annotationStatus') : t('listPage.label')

  const renderSegmentationStatusBadge = (matched: boolean) => (
    matched ? (
      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-teal-100/80 text-teal-700 border border-teal-200/60 shadow-sm whitespace-nowrap">
        {t('listPage.maskMatched')}
      </span>
    ) : (
      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-amber-50 text-amber-700 border border-amber-200/80 shadow-sm whitespace-nowrap">
        {t('listPage.maskMissing')}
      </span>
    )
  )

  const renderLabelBadge = (item: { label?: string | null; has_segmentation_annotation?: boolean }) => {
    if (isSegmentationDataset) {
      return renderSegmentationStatusBadge(Boolean(item.has_segmentation_annotation))
    }

    if (item.label) {
      return <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 shadow-sm whitespace-nowrap">{item.label}</span>
    }

    return <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.noLabel')}</span>
  }

  const renderCaseLabelBadge = (slides: Array<{ label?: string | null; has_segmentation_annotation?: boolean }>) => {
    if (isSegmentationDataset) {
      const matchedCount = slides.filter(s => s.has_segmentation_annotation).length
      if (matchedCount === 0) return renderSegmentationStatusBadge(false)
      if (matchedCount === slides.length) return renderSegmentationStatusBadge(true)
      return (
        <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-slate-100 text-slate-700 border border-slate-200 shadow-sm whitespace-nowrap">
          {t('listPage.maskMatchedCount', { matched: matchedCount, total: slides.length })}
        </span>
      )
    }

    const labels = Array.from(new Set(slides.map(s => s.label).filter(Boolean)))
    if (labels.length === 0) return <span className="text-gray-300 text-xs italic">{t('listPage.noLabel')}</span>
    if (labels.length === 1) return <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-gray-100/80 text-gray-700 border border-gray-200/60 shadow-sm whitespace-nowrap">{labels[0]}</span>
    return (
      <div className="flex flex-wrap gap-1">
        {labels.slice(0, 2).map(l => (
          <span key={l} className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">{l}</span>
        ))}
        {labels.length > 2 && <span className="text-xs text-gray-500">+{labels.length - 2}</span>}
      </div>
    )
  }

  const datasetItemsPerPage = datasetViewMode === 'grid' ? 8 : datasetListItemsPerPage
  const datasetRepositoryPageFilters = {
    page: datasetCurrentPage,
    pageSize: datasetItemsPerPage,
    search: datasetDebouncedSearch,
    taskType: datasetTaskFilter,
    dataType: datasetTypeFilter,
    level: datasetLevelFilter,
    visibility: datasetVisibilityFilter,
    source: datasetSourceFilter,
  }

  const datasetsQuery = useQuery({
    queryKey: buildDatasetRepositoryPageQueryKey(datasetRepositoryPageFilters),
    queryFn: async () => {
      const d = await fetchDatasets(datasetTypeFilter === 'all' ? undefined : datasetTypeFilter, {
        page: datasetCurrentPage,
        page_size: datasetItemsPerPage,
        task_type: getCanonicalDatasetTaskFilter(datasetTaskFilter),
        aggregation_level:
          datasetLevelFilter === 'all'
            ? undefined
            : datasetLevelFilter === 'patient'
            ? 'case'
            : 'file',
        source_organ: datasetSourceFilter === 'all' ? undefined : datasetSourceFilter,
        is_public: datasetVisibilityFilter === 'all' ? undefined : datasetVisibilityFilter === 'public',
        search: datasetDebouncedSearch || undefined,
      })

      const totalPages = Math.max(1, Math.ceil((d.total || 0) / datasetItemsPerPage))
      const prefetchBase = {
        page_size: datasetItemsPerPage,
        task_type: getCanonicalDatasetTaskFilter(datasetTaskFilter),
        aggregation_level:
          datasetLevelFilter === 'all'
            ? undefined
            : datasetLevelFilter === 'patient'
            ? ('case' as const)
            : ('file' as const),
        source_organ: datasetSourceFilter === 'all' ? undefined : datasetSourceFilter,
        is_public: datasetVisibilityFilter === 'all' ? undefined : datasetVisibilityFilter === 'public',
        search: datasetDebouncedSearch || undefined,
      }
      if (datasetCurrentPage < totalPages) {
        void prefetchDatasets(datasetTypeFilter === 'all' ? undefined : datasetTypeFilter, {
          ...prefetchBase,
          page: datasetCurrentPage + 1,
        })
      }

      return d
    },
    enabled: !selectedDatasetId,
    staleTime: 2 * 60 * 1000,
    placeholderData: keepPreviousData,
  })

  const activeSortBy = sortColumn ? SORT_FIELD_MAP[sortColumn] : undefined
  const activeSortOrder = activeSortBy ? sortDirection : undefined

  const wsiListQuery = useQuery({
    queryKey: ['wsi-list', selectedDatasetId, { page: currentPage, search: debouncedSearch, sort_by: activeSortBy, sort_order: activeSortOrder }],
    queryFn: async () => {
      const d = await fetchWSIList(selectedDatasetId!, undefined, {
        page: currentPage,
        page_size: itemsPerPage,
        search: debouncedSearch || undefined,
        sort_by: activeSortBy,
        sort_order: activeSortOrder,
      })

      const totalUnits =
        (d.total_cases ?? 0) > 0 ? (d.total_cases ?? 0) : (d.total ?? d.items?.length ?? 0)
      const totalPages = Math.max(1, Math.ceil(totalUnits / itemsPerPage))

      if (currentPage < totalPages) {
        void prefetchWSIList(selectedDatasetId!, undefined, {
          page: currentPage + 1,
          page_size: itemsPerPage,
          search: debouncedSearch || undefined,
          sort_by: activeSortBy,
          sort_order: activeSortOrder,
        })
      }

      return d
    },
    enabled: !!selectedDatasetId,
    staleTime: 2 * 60 * 1000,
    placeholderData: keepPreviousData,
  })

  const sourceOptionsQuery = useQuery({
    queryKey: [DATASET_REPOSITORY_QUERY_KEYS.sourceOptions],
    queryFn: async () => {
      const items = await fetchDatasetSourceOptions()
      return items.map((sourceOrgan) => getDatasetSourceOrganFilterValue(sourceOrgan))
    },
    enabled: !selectedDatasetId,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  })

  const visibleDatasets = useMemo(() => {
    return datasetsQuery.data?.items ?? []
  }, [datasetsQuery.data?.items])

  const datasetSourceOptions = useMemo(() => {
    const sourceValues = [...(sourceOptionsQuery.data ?? [])].sort((left, right) => {
      if (left === UNKNOWN_SOURCE_ORGAN_FILTER) return 1
      if (right === UNKNOWN_SOURCE_ORGAN_FILTER) return -1
      return left.localeCompare(right)
    })

    return [
      { value: 'all', label: t('common.all') },
      ...sourceValues.map((value) => ({
        value,
        label: value === UNKNOWN_SOURCE_ORGAN_FILTER
          ? t('listPage.filters.unknownSourceOrgan')
          : organSourceKeyMap[value]
            ? t(`organSources.${organSourceKeyMap[value]}`)
            : value,
      })),
    ]
  }, [sourceOptionsQuery.data, t])

  const datasetTotalPages = Math.max(1, Math.ceil((datasetsQuery.data?.total ?? 0) / datasetItemsPerPage))
  const datasetStartIndex = (datasetCurrentPage - 1) * datasetItemsPerPage
  const datasetEndIndex = datasetStartIndex + datasetItemsPerPage
  const paginatedDatasets = visibleDatasets
  const datasetPaginationStart = (datasetsQuery.data?.total ?? 0) === 0 ? 0 : datasetStartIndex + 1
  const datasetPaginationEnd = Math.min(datasetEndIndex, (datasetsQuery.data?.total ?? 0))
  const hasDatasetContent = visibleDatasets.length > 0 || (datasetsQuery.data?.total ?? 0) > 0
  const showInitialDatasetLoading = datasetsQuery.isLoading && !hasDatasetContent
  const isDatasetRefreshing = datasetsQuery.isFetching && hasDatasetContent

  const hasFileContent = (wsiListQuery.data?.items ?? []).length > 0 || (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) > 0 || (wsiListQuery.data?.total_cases ?? 0) > 0
  const showInitialFilesLoading = wsiListQuery.isLoading && !hasFileContent
  const isFilesRefreshing = wsiListQuery.isLoading && hasFileContent
  const filesViewState = getListPageFileViewState({
    selectedDatasetId,
    showInitialFilesLoading,
    hasFilesError: Boolean(wsiListQuery.error ? String(wsiListQuery.error) : undefined),
    itemCount: (wsiListQuery.data?.items ?? []).length,
    searchQuery,
    debouncedSearch,
  })

  const hasActiveDatasetFilters =
    datasetTaskFilter !== 'all' || datasetTypeFilter !== 'all' || datasetLevelFilter !== 'all' || datasetVisibilityFilter !== 'all' || datasetSourceFilter !== 'all' || datasetSearchQuery !== '' || datasetDebouncedSearch !== ''

  useEffect(() => {
    setDatasetCurrentPage((prev) => clampDatasetPage(prev, datasetTotalPages, {
      isError: datasetsQuery.isError,
      isFetching: datasetsQuery.isFetching,
      hasQueryData: Boolean(datasetsQuery.data),
    }))
  }, [datasetTotalPages, datasetsQuery.isError, datasetsQuery.isFetching, datasetsQuery.data])

  useEffect(() => {
    setDatasetPageInput(String(datasetCurrentPage))
  }, [datasetCurrentPage])

  useEffect(() => {
    setFilePageInput(String(currentPage))
  }, [currentPage])

  useEffect(() => {
    const sources = sourceOptionsQuery.data ?? []
    if (datasetSourceFilter !== 'all' && sources.length > 0 && !sources.includes(datasetSourceFilter)) {
      setDatasetSourceFilter('all')
    }
  }, [sourceOptionsQuery.data, datasetSourceFilter])

  useEffect(() => {
    if (selectedDatasetId) return
    return subscribeStorageSSE()
  }, [selectedDatasetId, subscribeStorageSSE])

  useEffect(() => {
    const justCompletedDeleteTasks = tasks.filter(
      t => t.type === 'delete_dataset' && t.status === 'success' && !completedDeleteTaskIdsRef.current.has(t.id)
    )
    if (justCompletedDeleteTasks.length === 0) return

    // Collect names of deleted datasets for optimistic removal
    const deletedNames = new Set(
      justCompletedDeleteTasks.map(t => t.datasetName).filter(Boolean)
    )

    for (const task of justCompletedDeleteTasks) {
      completedDeleteTaskIdsRef.current.add(task.id)
    }

    // Optimistic update: immediately remove deleted datasets from all cached pages
    if (deletedNames.size > 0) {
      qc.setQueriesData<{ items?: DatasetSummary[]; total?: number }>(
        { queryKey: [DATASET_REPOSITORY_QUERY_KEYS.pages] },
        (oldData) => {
          if (!oldData?.items) return oldData
          const filtered = oldData.items.filter(
            (d) => !deletedNames.has(d.dataset_name)
          )
          return {
            ...oldData,
            items: filtered,
            total: Math.max(0, (oldData.total ?? 0) - (oldData.items.length - filtered.length))
          }
        }
      )
    }

    // Also clean up pending delete overlays for these tasks
    for (const task of justCompletedDeleteTasks) {
      const rawTaskId = task.id.replace(/^delete_dataset_/, '')
      if (pendingDeleteRef.current.has(rawTaskId)) {
        pendingDeleteRef.current.delete(rawTaskId)
        removeDeletingDatasetByTaskId(rawTaskId)
      }
    }

    // Single background refetch to reconcile with server (e.g. fix total count, pagination)
    void invalidateDatasetRepositoryCache(qc)
  }, [tasks, qc, removeDeletingDatasetByTaskId])

  useEffect(() => {
    if (pendingDeleteRef.current.size === 0) return
    const fetchedIds = new Set(
      (datasetsQuery.data?.items ?? []).map((d: DatasetSummary) => d.dataset_id).filter(Boolean)
    )
    for (const [taskId, datasetId] of pendingDeleteRef.current) {
      if (!fetchedIds.has(datasetId)) {
        pendingDeleteRef.current.delete(taskId)
        removeDeletingDatasetByTaskId(taskId)
      }
    }
  }, [datasetsQuery.data, removeDeletingDatasetByTaskId])

  useEffect(() => {
    if (selectedDatasetId) return
    const justCompleted = tasks.filter(
      t => (t.type === 'upload' || t.type === 'batch_import' || t.type === 'extraction') &&
        t.status === 'success' &&
        !completedUploadTaskIdsRef.current.has(t.id)
    )
    if (justCompleted.length === 0) return
    for (const task of justCompleted) {
      completedUploadTaskIdsRef.current.add(task.id)
    }
    setDatasetCurrentPage(1)
    void invalidateDatasetRepositoryCache(qc)
  }, [tasks, qc, selectedDatasetId])

  useEffect(() => {
    if (selectedDatasetId && !selectedDatasetSummary) {
      void (async () => {
        try {
          const dataset = await fetchDatasetSummary(selectedDatasetId)
          setSelectedDatasetSummary(dataset)
          setSelectedDatasetName(dataset.dataset_name)
          setSelectedDatasetType(getNormalizedDatasetTaskType(dataset.task_types[0]))
        } catch (err) {
          console.error('Failed to load selected dataset summary:', err)
        }
      })()
    }
  }, [selectedDatasetId, selectedDatasetSummary])

  // Debounce search input → debouncedSearch (800ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setCurrentPage((previousPage) => (previousPage === 1 ? previousPage : 1))
      setDebouncedSearch(searchQuery)
    }, 800)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Debounce dataset search input → datasetDebouncedSearch (800ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setDatasetCurrentPage((previousPage) => (previousPage === 1 ? previousPage : 1))
      setDatasetDebouncedSearch(datasetSearchQuery)
    }, 800)
    return () => clearTimeout(timer)
  }, [datasetSearchQuery])

  const commitDatasetPageInput = (rawValue: string) => {
    const trimmed = rawValue.trim()
    if (!trimmed) {
      setDatasetPageInput(String(datasetCurrentPage))
      return
    }

    const parsedPage = Number.parseInt(trimmed, 10)
    if (Number.isNaN(parsedPage)) {
      setDatasetPageInput(String(datasetCurrentPage))
      return
    }

    const nextPage = Math.min(Math.max(parsedPage, 1), datasetTotalPages)
    setDatasetCurrentPage(nextPage)
    setDatasetPageInput(String(nextPage))
  }

  const commitFilePageInput = (rawValue: string, totalPages: number) => {
    const trimmed = rawValue.trim()
    if (!trimmed) {
      setFilePageInput(String(currentPage))
      return
    }

    if (!/^\d+$/.test(trimmed)) {
      setFilePageInput(String(currentPage))
      return
    }

    const parsedPage = Number.parseInt(trimmed, 10)
    if (Number.isNaN(parsedPage)) {
      setFilePageInput(String(currentPage))
      return
    }

    const nextPage = Math.min(Math.max(parsedPage, 1), totalPages)
    setCurrentPage(nextPage)
    setFilePageInput(String(nextPage))
  }

  const handleBackToDatasets = () => {
    // If we came from AI Chat, go back to AI Chat
    if (fromAIChat) {
      navigate('/dashboard')
      return
    }
    // Otherwise, go back to dataset list
    setSelectedDatasetId(null)
    setSelectedDatasetName('')
    setSelectedDatasetType('classification')
    setSelectedDatasetSummary(null)
    setSearchQuery('')
    setDebouncedSearch('')
    setCurrentPage(1)
    setSelectedIds(new Set())
    setExpandedCases(new Set())
    setSortColumn(null)
    setSortDirection('asc')
  }

  const handleDatasetClick = (dataset: DatasetSummary) => {
    setSelectedDatasetId(dataset.dataset_id)
    setSelectedDatasetName(dataset.dataset_name)
    setSelectedDatasetType(getNormalizedDatasetTaskType(dataset.task_types[0]))
    setSelectedDatasetSummary(dataset)
    setCurrentPage(1)
    setSearchQuery('')
    setDebouncedSearch('')
    setExpandedCases(new Set())
    setSortColumn(null)
    setSortDirection('asc')
  }

  // Reload current dataset files (for use after edits/deletes)
  const reloadCurrentDataset = async () => {
    if (selectedDatasetId) {
      invalidateWSIListCache()
      await qc.invalidateQueries({ queryKey: ['wsi-list', selectedDatasetId] })
    }
  }
  const clearDatasetFilters = () => {
    setDatasetTaskFilter('all')
    setDatasetTypeFilter('all')
    setDatasetLevelFilter('all')
    setDatasetVisibilityFilter('all')
    setDatasetSourceFilter('all')
    setDatasetSearchQuery('')
    setDatasetCurrentPage(1)
  }

  const prefetchFilteredDatasets = useCallback((overrides: {
    taskType?: DatasetTaskFilter
    dataType?: DatasetTypeFilter
    level?: DatasetLevelFilter
  }) => {
    const taskType = overrides.taskType ?? datasetTaskFilter
    const dataType = overrides.dataType ?? datasetTypeFilter
    const level = overrides.level ?? datasetLevelFilter
    const pageSize = datasetViewMode === 'grid' ? 8 : datasetListItemsPerPage

    void qc.prefetchQuery({
      queryKey: buildDatasetRepositoryPageQueryKey({
        page: 1,
        pageSize,
        search: datasetDebouncedSearch,
        taskType,
        dataType,
        level,
        visibility: datasetVisibilityFilter,
        source: datasetSourceFilter,
      }),
      queryFn: () =>
        fetchDatasets(dataType === 'all' ? undefined : dataType, {
          page: 1,
          page_size: pageSize,
          task_type: getCanonicalDatasetTaskFilter(taskType),
          aggregation_level:
            level === 'all' ? undefined : level === 'patient' ? 'case' : 'file',
          source_organ: datasetSourceFilter === 'all' ? undefined : datasetSourceFilter,
          is_public: datasetVisibilityFilter === 'all' ? undefined : datasetVisibilityFilter === 'public',
          search: datasetDebouncedSearch || undefined,
        }),
      staleTime: 2 * 60 * 1000,
    })
  }, [qc, datasetTaskFilter, datasetTypeFilter, datasetLevelFilter, datasetVisibilityFilter, datasetSourceFilter, datasetViewMode, datasetListItemsPerPage, datasetDebouncedSearch])

  const renderDatasetFilterGroup = (
    label: string,
    value: string,
    options: Array<{ value: string; label: string }>,
    onChange: (value: string) => void,
    onHover?: (value: string) => void
  ) => (
    <div className="flex min-w-0 flex-col gap-1.5 sm:gap-2 lg:flex-row lg:items-center lg:gap-2.5">
      <p className="text-[10px] sm:text-[11px] font-semibold uppercase tracking-[0.16em] leading-none text-gray-400 whitespace-nowrap">
        {label}
      </p>
      <div className="flex min-w-0 flex-wrap items-center gap-1.5 sm:gap-2">
        {options.map((option) => {
          const selected = option.value === value

          return (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              onMouseEnter={!selected ? () => onHover?.(option.value) : undefined}
              className={`px-2.5 sm:px-3 py-1 rounded-lg text-[11px] sm:text-xs font-semibold transition-all whitespace-nowrap border ${selected
                ? 'bg-gray-900 text-white border-gray-900 shadow-sm'
                : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300 hover:text-gray-900 hover:bg-gray-50'
                }`}
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )

  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    // Convert FileList to Array
    const filesArray = Array.from(files)
    setSelectedFiles(filesArray)

    // Initialize metadata for each file
    const metadata = new Map<string, { label: string; case_id: string; age: string; gender: string }>()
    filesArray.forEach(file => {
      metadata.set(file.name, { label: '', case_id: '', age: '', gender: '' })
    })
    setFileMetadata(metadata)
    const dataset = (datasetsQuery.data?.items ?? []).find((d: DatasetSummary) => d.dataset_id === selectedDatasetId)
    const sourceState = toSourceSelectionState(dataset?.source_organ)
    setUploadDatasetSourceSelection(sourceState.selection)
    setUploadDatasetSourceCustom(sourceState.custom)

    // Show metadata modal
    setShowFileMetadataModal(true)
  }

  const handleConfirmUpload = async () => {
    if (selectedFiles.length === 0) return

    setShowFileMetadataModal(false)

    const newUploadingFiles = new Map<string, { progress: number; status: 'uploading' | 'success' | 'error'; error?: string }>()
    selectedFiles.forEach(file => {
      newUploadingFiles.set(file.name, { progress: 0, status: 'uploading' })
    })
    setUploadingFiles(newUploadingFiles)

    await runUpload(async () => {
      try {
        let successCount = 0
        let failedCount = 0
        const resolvedDatasetSource = resolveSourceValue(uploadDatasetSourceSelection, uploadDatasetSourceCustom)

        if (selectedDatasetId) {
          const currentDataset = (datasetsQuery.data?.items ?? []).find((d: DatasetSummary) => d.dataset_id === selectedDatasetId)
          const currentSource = currentDataset?.source_organ?.trim() || ''
          if (resolvedDatasetSource !== currentSource) {
            await updateDatasetProperties(selectedDatasetId, { source: resolvedDatasetSource })
            void invalidateDatasetSourceOptions(qc)
          }
        }

        for (let i = 0; i < selectedFiles.length; i++) {
          const file = selectedFiles[i]
          const metadata = fileMetadata.get(file.name)

          try {
            const age = metadata?.age ? parseInt(metadata.age) : undefined
            await uploadWSIFile(file, {
              label: selectedDatasetType === 'classification' ? (metadata?.label || undefined) : undefined,
              case_id: metadata?.case_id || undefined,
              age: age,
              gender: metadata?.gender || undefined,
              onProgress: (progress) => {
                setUploadingFiles(prev => {
                  const updated = new Map(prev)
                  updated.set(file.name, { progress, status: 'uploading' })
                  return updated
                })
              }
            })

            setUploadingFiles(prev => {
              const updated = new Map(prev)
              updated.set(file.name, { progress: 100, status: 'success' })
              return updated
            })
            successCount++
          } catch (err) {
            console.error(`Failed to upload ${file.name}:`, err)

            setUploadingFiles(prev => {
              const updated = new Map(prev)
              updated.set(file.name, { progress: 100, status: 'error', error: String(err) })
              return updated
            })
            failedCount++
          }
        }

        await reloadCurrentDataset()

        setTimeout(() => {
          setUploadingFiles(new Map())
        }, 3000)
      } catch (err) {
        console.error(err)
      }
    })

    setSelectedFiles([])
    setFileMetadata(new Map())
    setUploadDatasetSourceSelection('')
    setUploadDatasetSourceCustom('')
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const updateFileMetadata = (fileName: string, field: 'label' | 'case_id' | 'age' | 'gender', value: string) => {
    const newMetadata = new Map(fileMetadata)
    const current = newMetadata.get(fileName) || { label: '', case_id: '', age: '', gender: '' }
    newMetadata.set(fileName, { ...current, [field]: value })
    setFileMetadata(newMetadata)
  }

  const handleDeleteClick = async (wsi_id: string, label: string, original_filename?: string) => {
    setWsiToDelete({ wsi_id, label, original_filename })
    setWsiStorageInfo(null)
    setShowDeleteModal(true)

    // Load storage info
    await runStorageInfo(async () => {
      setWsiStorageInfo(await getWSIStorageInfo(wsi_id))
    })
  }

  const handleConfirmDelete = async () => {
    if (!wsiToDelete) return

    try {
      await addDeleteWSITask([wsiToDelete.wsi_id])
      setShowDeleteModal(false)
      setWsiToDelete(null)
      setWsiStorageInfo(null)
      // List will be refreshed when task completes - we can trigger a delayed refresh
      setTimeout(() => reloadCurrentDataset(), 500)
    } catch (err) {
      console.error('Failed to add delete task:', err)
      alert(t('listPage.failedDeleteWsi', { error: String(err) }))
    }
  }

  const toggleSelection = (wsi_id: string) => {
    const newSelected = new Set(selectedIds)
    if (newSelected.has(wsi_id)) {
      newSelected.delete(wsi_id)
    } else {
      newSelected.add(wsi_id)
    }
    setSelectedIds(newSelected)
  }

  const handleBatchDeleteClick = () => {
    if (selectedIds.size === 0) {
      alert(t('listPage.selectAtLeastOneToDelete'))
      return
    }
    setShowBatchDeleteModal(true)
  }

  const handleConfirmBatchDelete = async () => {
    await runDelete(async () => {
      try {
        if (datasetToDeleteId) {
          const idToRemove = datasetToDeleteId
          const deleteResponse = await startDeleteDatasetTask({
            dataset_id: datasetToDeleteId,
          })
          addDeletingDatasetName(deleteResponse.task_id, deleteResponse.dataset_name)
          pendingDeleteRef.current.set(deleteResponse.task_id, idToRemove)

          setShowBatchDeleteModal(false)
          setSelectedIds(new Set())
          toastSuccess(t('listPage.datasetDeleteStarted', { name: datasetToDeleteName }))
          setDatasetToDeleteId(null)
          setDatasetToDeleteName('')
          setDatasetToDeleteFileCount(0)
          void invalidateDatasetSourceOptions(qc)
        } else {
          const idsToDelete = Array.from(selectedIds)
          await addDeleteWSITask(idsToDelete)
          setShowBatchDeleteModal(false)
          setSelectedIds(new Set())
          setTimeout(() => reloadCurrentDataset(), 500)
        }
      } catch (err) {
        console.error('Batch delete error:', err)
        alert(t('listPage.failedDeleteFiles', { error: String(err) }))
      }
    })
  }
  const handleDatasetDeleteClick = (e: React.MouseEvent, datasetId: string | null, datasetName: string, fileCount: number) => {
    e.stopPropagation()
    if (!datasetId) {
      alert(t('listPage.cannotDeleteUncategorized'))
      return
    }
    setSelectedIds(new Set())
    setDatasetToDeleteId(datasetId)
    setDatasetToDeleteName(datasetName)
    setDatasetToDeleteFileCount(fileCount)
    setShowBatchDeleteModal(true)
  }

  const handleEditClick = (wsi: any) => {
    setEditingWSI({
      wsi_id: wsi.wsi_id,
      label: wsi.label,
      case_id: wsi.case_id,
      age: wsi.age,
      gender: wsi.gender,
      event_time: wsi.event_time,
      event_status: wsi.event_status
    })
    setEditLabel(wsi.label || '')
    setEditCaseId(wsi.case_id || '')
    setEditAge(wsi.age?.toString() || '')
    setEditGender(wsi.gender || '')
    setEditEventTime(wsi.event_time?.toString() || '')
    setEditEventStatus(wsi.event_status?.toString() || '')
    setShowEditModal(true)
  }

  const handleConfirmEdit = async () => {
    if (!editingWSI) return

    await runUpdate(async () => {
      try {
        const age = editAge ? parseInt(editAge) : undefined
        const event_time = editEventTime ? parseFloat(editEventTime) : undefined
        const event_status = editEventStatus ? parseInt(editEventStatus) : undefined

        await updateWSIMetadata(editingWSI.wsi_id, {
          label: editLabel || undefined,
          case_id: editCaseId || undefined,
          age: age,
          gender: editGender || undefined,
          event_time: event_time,
          event_status: event_status
        })
        setShowEditModal(false)
        setEditingWSI(null)
        await reloadCurrentDataset()
      } catch (err) {
        console.error('Failed to update WSI metadata:', err)
        alert(t('listPage.failedUpdateMetadata', { error: String(err) }))
      }
    })
  }

  const handleBatchEditClick = () => {
    if (selectedIds.size === 0) {
      alert(t('listPage.selectAtLeastOneToEdit'))
      return
    }
    setBatchEditLabel('')
    setBatchEditCaseId('')
    setBatchEditAge('')
    setBatchEditGender('')
    setBatchEditEventTime('')
    setBatchEditEventStatus('')
    setShowBatchEditModal(true)
  }

  const handleConfirmBatchEdit = async () => {
    if (selectedIds.size === 0) return

    // Check if at least one field is provided
    const hasUpdates = batchEditLabel || batchEditCaseId || batchEditAge || batchEditGender || batchEditEventTime || batchEditEventStatus
    if (!hasUpdates) {
      setShowBatchEditModal(false)
      return
    }

    await runBatchUpdate(async () => {
      try {
        const age = batchEditAge ? parseInt(batchEditAge) : undefined
        const event_time = batchEditEventTime ? parseFloat(batchEditEventTime) : undefined
        const event_status = batchEditEventStatus ? parseInt(batchEditEventStatus) : undefined

        const request = {
          wsi_ids: Array.from(selectedIds),
          label: batchEditLabel || undefined,
          case_id: batchEditCaseId || undefined,
          age: age,
          gender: batchEditGender || undefined,
          event_time: event_time,
          event_status: event_status
        }

        await startBatchUpdateMetadataTask(request)

        setShowBatchEditModal(false)
        setSelectedIds(new Set())
        toastSuccess(t('listPage.batchUpdateStarted', { count: request.wsi_ids.length }))
      } catch (err) {
        console.error('Failed to start batch edit:', err)
        toastError(err instanceof Error ? err.message : t('listPage.failedBatchEdit', { error: String(err) }))
      }
    })
  }

  // Open edit dataset modal
  const handleEditDatasetClick = (e: React.MouseEvent, dataset: DatasetSummary) => {
    e.stopPropagation()
    if (!dataset.dataset_id) return
    setDatasetEditorTab('details')
    setEditingDatasetId(dataset.dataset_id)
  }

  // Export labels handlers
  const handleExportLabelsClick = async (e: React.MouseEvent, dataset: DatasetSummary) => {
    e.stopPropagation()

    // Check if dataset has predefined splits
    if (dataset.has_predefined_splits) {
      // Direct export without modal
      await runExport(async () => {
        try {
          const result = await exportDatasetLabels(dataset.dataset_id!)
          toastSuccess(t('listPage.exportSuccess'))
          if (result.headers.get('X-PathLab-Export-Split-Fallback') === 'non_stratified') {
            toastSuccess(t('listPage.exportFallbackNonStratified'))
          }
        } catch (error) {
          console.error('Failed to export labels:', error)
          toastError(t('listPage.exportFailed'))
        }
      })
    } else {
      // Show modal for split configuration
      setExportingDataset(dataset)
      setShowExportModal(true)
    }
  }

  const handleExportConfirm = async (options: ExportLabelsOptions) => {
    if (!exportingDataset) return

    await runExport(async () => {
      try {
        const result = await exportDatasetLabels(exportingDataset.dataset_id!, options)
        toastSuccess(t('listPage.exportSuccess'))
        if (result.headers.get('X-PathLab-Export-Split-Fallback') === 'non_stratified') {
          toastSuccess(t('listPage.exportFallbackNonStratified'))
        }
      } catch (error) {
        console.error('Failed to export labels:', error)
        toastError(t('listPage.exportFailed'))
      }
    })
    setShowExportModal(false)
    setExportingDataset(null)
  }

  const handleExportCancel = () => {
    setShowExportModal(false)
    setExportingDataset(null)
  }

  const sortedItems = wsiListQuery.data?.items ?? []

  // Group items by case_id (for display within current page)
  const groupedByCaseId = React.useMemo(() => {
    const groups = new Map<string, { slides: ListWSIItem[]; isNoCase: boolean; order: number }>()
    const NO_CASE = '__no_case__'

    sortedItems.forEach((item: ListWSIItem, index: number) => {
      const normalizedCaseId = item.case_id?.trim()
      const isNoCase = !normalizedCaseId
      const groupKey = isNoCase ? `${NO_CASE}:${item.wsi_id}` : normalizedCaseId

      if (!groups.has(groupKey)) {
        groups.set(groupKey, { slides: [], isNoCase, order: index })
      }

      groups.get(groupKey)!.slides.push(item)
    })

    return Array.from(groups.entries())
      .sort(([, left], [, right]) => {
        if (left.isNoCase !== right.isNoCase) return left.isNoCase ? 1 : -1
        return left.order - right.order
      })
      .map(([groupKey, group]) => [groupKey, group.slides] as const)
  }, [sortedItems])

  const isPatchDataset = React.useMemo(() => {
    if (sortedItems.length === 0) return false
    const patchCount = sortedItems.filter((item: ListWSIItem) => getFileType(item.file_extension, item.file_size, item.data_type) === 'Patch').length
    return patchCount > sortedItems.length / 2
  }, [sortedItems])

  const useCaseGroupedView = Boolean(selectedDatasetId) && (
    selectedDatasetSummary?.data_type === 'wsi' || (!selectedDatasetSummary && !isPatchDataset)
  )

  const selectedDatasetVisualType = React.useMemo<'slides' | 'images'>(() => {
    if (selectedDatasetSummary) return getDatasetVisualType(selectedDatasetSummary)
    return isPatchDataset ? 'images' : 'slides'
  }, [selectedDatasetSummary, isPatchDataset])

  // Server-side pagination: dataset view is case-paginated for WSI datasets
  const totalPages = Math.max(1, useCaseGroupedView
    ? Math.ceil((wsiListQuery.data?.total_cases ?? 0) / itemsPerPage)
    : Math.ceil((wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) / itemsPerPage))
  const startIndex = (currentPage - 1) * itemsPerPage

  // All current-page items are already the "paginated" items (server-side pagination)
  const paginatedCases = useCaseGroupedView ? groupedByCaseId : null
  const paginatedItems = useCaseGroupedView ? [] : sortedItems

  // Batch selection logic — operates on current page items
  const pageSlides = useMemo(() => {
    if (useCaseGroupedView && paginatedCases) {
      return paginatedCases.flatMap(([, slides]) => slides)
    }
    return paginatedItems || []
  }, [useCaseGroupedView, paginatedCases, paginatedItems])

  const allPageSelected = pageSlides.length > 0 && pageSlides.every((s: ListWSIItem) => selectedIds.has(s.wsi_id))

  // Check if all items across all pages are selected (based on totalCount)
  const allFilteredSelected = selectedIds.size > 0 && selectedIds.size === (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0)

  const visibleFilePages = useMemo(() => getVisiblePaginationPages(currentPage, totalPages), [currentPage, totalPages])

  useEffect(() => {
    setCurrentPage((previousPage) => clampFilePage(previousPage, totalPages, {
      isError: wsiListQuery.isError,
      isFetching: wsiListQuery.isFetching,
      hasQueryData: Boolean(wsiListQuery.data),
    }))
  }, [totalPages, wsiListQuery.isError, wsiListQuery.isFetching, wsiListQuery.data])

  const handleSelectPage = () => {
    if (allFilteredSelected) {
      setSelectedIds(new Set())
      return
    }

    const newSelected = new Set(selectedIds)
    if (allPageSelected) {
      pageSlides.forEach((s: ListWSIItem) => { newSelected.delete(s.wsi_id) })
    } else {
      pageSlides.forEach((s: ListWSIItem) => { newSelected.add(s.wsi_id) })
    }
    setSelectedIds(newSelected)
  }

  // Handle selecting all filtered items (across all pages)
  const handleSelectAllFiltered = async () => {
    try {
      const d = await fetchWSIIds(
        selectedDatasetId!,
        undefined,
        debouncedSearch || undefined,
      )
      const allIds = new Set(d.items || [])
      setSelectedIds(allIds)
    } catch (e) {
      toastError(t('listPage.failedSelectAll'))
      console.error(e)
    }
  }

  // Toggle case expansion
  const toggleCaseExpansion = (caseId: string) => {
    setExpandedCases(prev => {
      const next = new Set(prev)
      if (next.has(caseId)) {
        next.delete(caseId)
      } else {
        next.add(caseId)
      }
      return next
    })
  }

  return (
    <div className="w-full space-y-6 h-full flex flex-col">
      <div className="flex-none">
        <PageHeader
          title={selectedDatasetId ? selectedDatasetName : sidebarText('data')}
          description={
            <>
              {selectedDatasetId ? (
                showInitialFilesLoading ? <span className="loading-shape loading-subtitle" aria-label={t('listPage.loadingFiles')}/> :
                  (wsiListQuery.error ? String(wsiListQuery.error) : undefined) && !hasFileContent ? t('listPage.errorLoadingFiles') :
                    <span className="flex items-center gap-2">
                      <FolderOpen className="w-4 h-4" />
                      {debouncedSearch
                        ? t('listPage.searchResultsInDataset', { count: (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) })
                        : t('listPage.filesInDataset', { count: (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) })}
                      {isFilesRefreshing && <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />}
                    </span>
              ) : (
                t('listPage.description')
              )}
            </>
          }
        >
          <div className="flex items-center gap-2">
            {selectedDatasetId && <Button variant="outline" onClick={() => {
              const conversation = sessionStorage.getItem('workbench:active-conversation')
              navigate(conversation ? `/dashboard/${conversation}` : '/dashboard', { state: { reference: { kind: 'dataset', id: selectedDatasetId } } })
            }}>@ {workbenchText('reference')}</Button>}
            {selectedDatasetId ? (
              <>
                <Button
                  variant="outline"
                  onClick={handleBackToDatasets}
                  className="gap-2"
                >
                  <ArrowLeft className="w-4 h-4" />
                  {fromAIChat ? t('listPage.backToChat') : t('listPage.backToRepository')}
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="outline"
                  onClick={() => navigate('/dashboard')}
                  className="gap-2"
                >
                  <ArrowLeft className="w-4 h-4" />
                  {t('listPage.backToDashboard')}
                </Button>
                <Button
                  onClick={() => navigate('/upload')}
                  className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white"
                >
                  <Upload className="w-4 h-4" />
                  {sidebarText('upload')}
                </Button>
              </>
            )}
          </div>
        </PageHeader>
      </div>

      {/* Registration Progress */}
      {uploadingFiles.size > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            {t('listPage.registeringFiles', { success: Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length, total: uploadingFiles.size })}
          </h3>
          <div className="space-y-3">
            {Array.from(uploadingFiles.entries()).map(([fileName, fileStatus]) => (
              <div key={fileName} className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 flex-1 min-w-0">
                    {fileStatus.status === 'uploading' && (
                      <Loader2 className="w-4 h-4 text-blue-600 animate-spin" />
                    )}
                    {fileStatus.status === 'success' && (
                      <CheckCircle className="w-4 h-4 text-green-600" />
                    )}
                    {fileStatus.status === 'error' && (
                      <X className="w-4 h-4 text-red-600" />
                    )}
                    <span className="text-sm font-medium text-gray-900 truncate">{fileName}</span>
                  </div>
                  <span className="text-xs text-gray-500 ml-2">
                    {fileStatus.status === 'uploading' && t('listPage.registering')}
                    {fileStatus.status === 'success' && t('listPage.complete')}
                    {fileStatus.status === 'error' && t('listPage.failed')}
                  </span>
                </div>
                {/* Progress Bar */}
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full transition-all duration-300 ${fileStatus.status === 'success' ? 'bg-green-600' :
                      fileStatus.status === 'error' ? 'bg-red-600' :
                        'bg-blue-600'
                      }`}
                    style={{ width: `${fileStatus.progress}%` }}
                  />
                </div>
                {fileStatus.error && (
                  <p className="text-xs text-red-600 mt-1">{fileStatus.error}</p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Hidden File Inputs */}
      <input
        ref={fileInputRef}
        type="file"
        accept={ALL_ACCEPT_STRING}
        multiple
        style={{ display: 'none' }}
        onChange={(e) => handleFileUpload(e.target.files)}
      />

      {/* === DATASETS VIEW (when no dataset is selected) === */}
      {!selectedDatasetId && (
        <>
          {/* Datasets Error State */}
          {(datasetsQuery.error ? String(datasetsQuery.error) : undefined) && !showInitialDatasetLoading && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
              <p className="font-medium">{t('listPage.errorLoadingDatasets')}</p>
              <p className="text-sm">
                {datasetsQuery.error instanceof ApiError && (datasetsQuery.error.isServerError() || datasetsQuery.error.isNetworkError())
                  ? t('listPage.errorServiceUnavailable')
                  : String(datasetsQuery.error)}
              </p>
            </div>
          )}

          {/* Datasets Empty State */}
          {!datasetsQuery.isLoading && !(datasetsQuery.error ? String(datasetsQuery.error) : undefined) && (datasetsQuery.data?.total ?? 0) === 0 && !hasActiveDatasetFilters && (
            <div className="flex flex-col items-center justify-center py-16 px-4 border-2 border-dashed border-gray-200 rounded-lg bg-gray-50">
              <div className="bg-white p-4 rounded-full border border-gray-200 shadow-sm mb-4">
                <Database className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-1">{t('listPage.noDatasetsFound')}</h3>
              <p className="text-sm text-gray-500 max-w-sm text-center">
                {t('listPage.noDatasetsDescription')}
              </p>
            </div>
          )}

          {/* Dataset Filters & Search */}
          {((datasetsQuery.data?.total ?? 0) > 0 || hasActiveDatasetFilters) && (
            <div className="flex flex-col gap-4">
              {/* Search Box */}
              <div className="relative w-full max-w-md transition-all duration-300 focus-within:ring-1 focus-within:ring-primary-500 focus-within:border-primary-500 rounded-lg">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Search className="h-4 sm:h-5 w-4 sm:w-5 text-gray-400" />
                </div>
                <input
                  type="text"
                  className="block w-full h-10 pl-10 pr-10 py-2 border border-gray-200 hover:border-gray-300 rounded-lg bg-white focus:bg-white placeholder-gray-400 focus:outline-none focus:ring-1 text-sm transition-colors shadow-sm"
                  placeholder={t('listPage.searchDatasetPlaceholder')}
                  value={datasetSearchQuery}
                  onChange={(e) => setDatasetSearchQuery(e.target.value)}
                />
                {datasetSearchQuery && (
                  <button
                    type="button"
                    className="absolute inset-y-0 right-0 pr-3 flex items-center"
                    onClick={() => setDatasetSearchQuery('')}
                  >
                    <X className="h-4 w-4 text-gray-400 hover:text-gray-600" />
                  </button>
                )}
              </div>

              {/* Filters Card */}
              <Card className="relative z-20 border-gray-100 shadow-sm bg-white/80 backdrop-blur-sm">
                <div className="px-4 py-3 sm:px-5 sm:py-3.5">
                  <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                    {/* Left Side: Filters */}
                    <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3 xl:flex-1">
                      {/* Filters */}
                      {renderDatasetFilterGroup(
                        t('listPage.filters.groups.taskType'),
                        datasetTaskFilter,
                        [
                          { value: 'all', label: t('common.all') },
                          { value: 'classification', label: t('listPage.classification') },
                          { value: 'survival', label: t('listPage.survival') },
                          { value: 'detection', label: t('detection.title') },
                          { value: 'segmentation', label: t('listPage.segmentation') },
                        ],
                        (nextValue) => { setDatasetTaskFilter(nextValue as DatasetTaskFilter); setDatasetCurrentPage(1) },
                        (v) => prefetchFilteredDatasets({ taskType: v as DatasetTaskFilter })
                      )}

                      {renderDatasetFilterGroup(
                        t('listPage.filters.groups.dataType'),
                        datasetTypeFilter,
                        [
                          { value: 'all', label: t('common.all') },
                          { value: 'wsi', label: t('listPage.wholeSlideImaging') },
                          { value: 'patch', label: t('listPage.patchCollection') },
                        ],
                        (nextValue) => { setDatasetTypeFilter(nextValue as DatasetTypeFilter); setDatasetCurrentPage(1) },
                        (v) => prefetchFilteredDatasets({ dataType: v as DatasetTypeFilter })
                      )}

                      {renderDatasetFilterGroup(
                        t('listPage.filters.groups.dataLevel'),
                        datasetLevelFilter,
                        [
                          { value: 'all', label: t('common.all') },
                          { value: 'file', label: t('listPage.fileLevel') },
                          { value: 'patient', label: t('listPage.patientLevel') },
                        ],
                        (nextValue) => { setDatasetLevelFilter(nextValue as DatasetLevelFilter); setDatasetCurrentPage(1) },
                        (v) => prefetchFilteredDatasets({ level: v as DatasetLevelFilter })
                      )}

                      {renderDatasetFilterGroup(
                        t('listPage.filters.groups.visibility'),
                        datasetVisibilityFilter,
                        [
                          { value: 'all', label: t('common.all') },
                          { value: 'public', label: t('listPage.public') },
                          { value: 'private', label: t('listPage.private') },
                        ],
                        (nextValue) => { setDatasetVisibilityFilter(nextValue as DatasetVisibilityFilter); setDatasetCurrentPage(1) }
                      )}

                      <div className="flex min-w-0 flex-col gap-1.5 sm:gap-2 lg:flex-row lg:items-center lg:gap-2.5">
                        <p className="text-[10px] sm:text-[11px] font-semibold uppercase tracking-[0.16em] leading-none text-gray-400 whitespace-nowrap">
                          {t('listPage.filters.groups.sourceOrgan')}
                        </p>
                        <Select
                          value={datasetSourceFilter}
                          onChange={(v) => { setDatasetSourceFilter(v); setDatasetCurrentPage(1) }}
                          options={datasetSourceOptions}
                          placeholder={t('listPage.filters.selectSourceOrgan')}
                          className="w-full min-w-[160px] sm:min-w-[180px] lg:w-[180px] xl:w-[200px]"
                          triggerClassName="h-8 px-2.5 text-xs sm:text-sm"
                        />
                      </div>
                    </div>

                  <div className="flex shrink-0 items-center gap-2 sm:gap-3 self-start xl:ml-4 xl:self-center">
                    <div className="inline-flex items-center rounded-lg bg-slate-100 p-0.5 shadow-inner">
                        <Tooltip content={t('listPage.view.iconView')}>
                          <button
                            type="button"
                            onClick={() => { setDatasetViewMode('grid'); setDatasetCurrentPage(1) }}
                            aria-label={t('listPage.view.iconView')}
                            className={`inline-flex h-8 w-8 items-center justify-center rounded-md transition-all ${datasetViewMode === 'grid'
                              ? 'bg-white text-slate-900 shadow-sm'
                              : 'text-slate-500 hover:text-slate-700'
                              }`}
                          >
                            <LayoutGrid className="h-3.5 w-3.5" />
                          </button>
                        </Tooltip>
                        <Tooltip content={t('listPage.view.listView')}>
                          <button
                            type="button"
                            onClick={() => { setDatasetViewMode('list'); setDatasetCurrentPage(1) }}
                            aria-label={t('listPage.view.listView')}
                            className={`inline-flex h-8 w-8 items-center justify-center rounded-md transition-all ${datasetViewMode === 'list'
                              ? 'bg-white text-slate-900 shadow-sm'
                              : 'text-slate-500 hover:text-slate-700'
                              }`}
                          >
                            <List className="h-3.5 w-3.5" />
                          </button>
                        </Tooltip>
                    </div>

                    <span className="inline-flex items-center rounded-full bg-slate-50 px-2.5 py-0.5 text-[11px] sm:text-xs font-medium text-slate-600 whitespace-nowrap">
                      {t('listPage.filters.compactSummary', {
                        shown: visibleDatasets.length,
                        total: (datasetsQuery.data?.total ?? 0),
                      })}
                    </span>

                    {hasActiveDatasetFilters && (
                      <button
                        type="button"
                        onClick={clearDatasetFilters}
                        className="text-[11px] sm:text-xs font-semibold text-indigo-600 hover:text-indigo-700 transition-colors whitespace-nowrap"
                      >
                        {t('listPage.filters.clear')}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </Card>
            </div>
          )}
          
          {/* Filtered Empty State */}
          {!datasetsQuery.isLoading && !(datasetsQuery.error ? String(datasetsQuery.error) : undefined) && hasActiveDatasetFilters && (
            ((datasetsQuery.data?.total ?? 0) === 0) ||
            ((datasetsQuery.data?.total ?? 0) > 0 && visibleDatasets.length === 0)
          ) && (
            <div className="flex flex-col items-center justify-center py-16 px-4 border-2 border-dashed border-gray-200 rounded-lg bg-gray-50">
              <div className="bg-white p-4 rounded-full border border-gray-200 shadow-sm mb-4">
                <Search className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-1">{t('listPage.noFilteredDatasets')}</h3>
              <p className="text-sm text-gray-500 max-w-sm text-center mb-5">
                {t('listPage.noFilteredDatasetsDescription')}
              </p>
              <Button variant="outline" onClick={clearDatasetFilters} className="gap-2">
                {t('listPage.filters.clear')}
              </Button>
            </div>
          )}

          {showInitialDatasetLoading && (
            <DatasetLoading header={false}/>
          )}

          {/* Datasets Grid */}
          {visibleDatasets.length > 0 && datasetViewMode === 'grid' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 sm:gap-6 p-1">
              {paginatedDatasets.map((dataset: DatasetSummary) => {
                const itemType = getDatasetVisualType(dataset)
                const normalizedTaskType = getNormalizedDatasetTaskType(dataset.task_types[0])
                const sourceOrganValue = getDatasetSourceOrganFilterValue(dataset.source_organ)
                const rawSource = dataset.source_organ?.trim()
                const sourceOrganLabel = sourceOrganValue === UNKNOWN_SOURCE_ORGAN_FILTER || !rawSource
                  ? t('listPage.filters.unknownSourceOrgan')
                  : organSourceKeyMap[rawSource]
                    ? t(`organSources.${organSourceKeyMap[rawSource]}`)
                    : rawSource

                const isDeleting = deletingDatasetNames.has(dataset.dataset_name)
                const isUnavailable = isExternalUnavailable(dataset)

                return (
                  <DatasetCard
                    key={dataset.dataset_id ?? dataset.dataset_name}
                    dataset={dataset}
                    itemType={itemType}
                    normalizedTaskType={normalizedTaskType}
                    sourceOrganLabel={sourceOrganLabel}
                    sourceOrganValue={sourceOrganValue}
                    isDeleting={isDeleting}
                    isUnavailable={isUnavailable}
                    isAdmin={isAdmin}
                    exporting={exporting}
                    exportingDatasetId={exportingDataset?.dataset_id ?? null}
                    onClick={() => !isUnavailable && handleDatasetClick(dataset)}
                    onExportClick={(e) => handleExportLabelsClick(e, dataset)}
                    onEditClick={(e) => handleEditDatasetClick(e, dataset)}
                    onDeleteClick={(e) => handleDatasetDeleteClick(e, dataset.dataset_id, dataset.dataset_name, dataset.file_count)}
                    unknownSourceOrganFilter={UNKNOWN_SOURCE_ORGAN_FILTER}
                  />
                )
              })}

              {/* Add New Dataset Card */}
              {datasetCurrentPage === datasetTotalPages && (
                <button
                  type="button"
                  onClick={() => navigate('/upload')}
                  className="flex flex-col items-center justify-center p-6 rounded-xl border-2 border-dashed border-slate-200 hover:border-blue-400 hover:bg-blue-50/50 transition-all duration-300 group min-h-[220px]"
                >
                  <div className="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center mb-4 group-hover:bg-white group-hover:shadow-md transition-all">
                    <Upload className="w-6 h-6 text-slate-400 group-hover:text-blue-600" />
                  </div>
                  <h3 className="text-lg font-bold text-slate-600 group-hover:text-blue-700">{t('listPage.newDataset')}</h3>
                  <p className="text-sm text-slate-400 text-center mt-2 group-hover:text-slate-500">
                    {t('listPage.newDatasetDescription')}
                  </p>
                </button>
              )}
            </div>
          )}

          {/* Datasets List */}
          {visibleDatasets.length > 0 && datasetViewMode === 'list' && (
            <div className="space-y-3 p-1">
              {paginatedDatasets.map((dataset: DatasetSummary) => {
                const itemType = getDatasetVisualType(dataset)
                const normalizedTaskType = getNormalizedDatasetTaskType(dataset.task_types[0])
                const sourceOrganValue = getDatasetSourceOrganFilterValue(dataset.source_organ)
                const rawSource = dataset.source_organ?.trim()
                const sourceOrganLabel = sourceOrganValue === UNKNOWN_SOURCE_ORGAN_FILTER || !rawSource
                  ? t('listPage.filters.unknownSourceOrgan')
                  : organSourceKeyMap[rawSource]
                    ? t(`organSources.${organSourceKeyMap[rawSource]}`)
                    : rawSource

                const isDeleting = deletingDatasetNames.has(dataset.dataset_name)
                const isUnavailable = isExternalUnavailable(dataset)

                return (
                  <Card
                    key={dataset.dataset_id ?? dataset.dataset_name}
                    className={`group border-slate-200 bg-white transition-all duration-200 relative overflow-hidden ${isDeleting ? 'pointer-events-none' : 'hover:shadow-md'} ${isUnavailable ? 'opacity-60' : ''}`}
                    onClick={isDeleting || isUnavailable ? undefined : () => handleDatasetClick(dataset)}
                  >
                    {isDeleting && (
                      <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/75 backdrop-blur-[2px] rounded-xl">
                        <div className="flex items-center gap-2">
                          <Loader2 className="w-5 h-5 animate-spin text-red-400" />
                          <span className="text-sm font-medium text-red-500">{t('listPage.datasetDeleting')}</span>
                        </div>
                      </div>
                    )}
                    {isUnavailable && (
                      <div className="absolute inset-0 z-20 flex items-center justify-center bg-white/60 backdrop-blur-[1px] rounded-xl">
                        <div className="flex flex-col items-center gap-2">
                          <span className="inline-flex items-center px-2.5 py-1 rounded-md text-[10px] sm:text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                            {t('listPage.externalUnavailable')}
                          </span>
                          {dataset.availability?.reason && (
                            <span className="text-[10px] sm:text-xs text-amber-600 max-w-[80%] text-center">{dataset.availability.reason}</span>
                          )}
                        </div>
                      </div>
                    )}
                    <div className="p-4 sm:p-5 flex flex-col gap-4">
                      <div className="flex items-start gap-4 min-w-0">
                        <div className={`p-3 rounded-2xl ${itemType === 'slides' ? 'bg-blue-50 text-blue-600' : 'bg-emerald-50 text-emerald-600'}`}>
                          {itemType === 'slides' ? (
                            <Microscope className="w-6 h-6" />
                          ) : (
                            <LayoutGrid className="w-6 h-6" />
                          )}
                        </div>

                        <div className="min-w-0 flex-1">
                          <div className="flex flex-col xl:flex-row xl:items-start xl:justify-between gap-3">
                            <div className="min-w-0">
                              <h3 className="text-lg sm:text-xl font-bold text-slate-900 line-clamp-2 leading-snug" title={dataset.dataset_name}>
                                {dataset.dataset_name}
                              </h3>
                              <div className="flex flex-wrap items-center gap-2 mt-2">
                                <p className="text-xs sm:text-sm text-slate-500 font-medium whitespace-nowrap">
                                  {itemType === 'slides' ? t('listPage.wholeSlideImaging') : t('listPage.patchCollection')}
                                </p>
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
                                  normalizedTaskType === 'survival'
                                    ? 'bg-amber-50 text-amber-700 border border-amber-100/50'
                                    : normalizedTaskType === 'segmentation'
                                      ? 'bg-violet-50 text-violet-700 border border-violet-100/50'
                                      : 'bg-indigo-50 text-indigo-700 border border-indigo-100/50'
                                }`}>
                                  {dataset.task_types.map(task => t(`training.taskSetup.${task}`)).join(' · ')}
                                </span>
                                {itemType === 'slides' && (
                                  <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
                                    dataset.aggregation_level === 'case'
                                      ? 'bg-purple-50 text-purple-700 border border-purple-100/50'
                                      : 'bg-orange-50 text-orange-700 border border-orange-100/50'
                                  }`}>
                                    {dataset.aggregation_level === 'case' ? (
                                      <><Users className="w-3 h-3" />{t('listPage.patientLevel')}</>
                                    ) : (
                                      <><FileImage className="w-3 h-3" />{t('listPage.fileLevel')}</>
                                    )}
                                  </span>
                                )}
                                <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold ${
                                  sourceOrganValue === UNKNOWN_SOURCE_ORGAN_FILTER
                                    ? 'bg-slate-50 text-slate-600 border border-slate-200/70'
                                    : 'bg-cyan-50 text-cyan-700 border border-cyan-100/70'
                                }`}>
                                  {sourceOrganLabel}
                                </span>
                                {dataset.is_public ? (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-100/70">
                                    <Globe className="w-2.5 h-2.5" />{t('listComponents.editModals.public')}
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-semibold bg-slate-50 text-slate-600 border border-slate-200/70">
                                    <Lock className="w-2.5 h-2.5" />{t('listComponents.editModals.private')}
                                  </span>
                                )}
                                {dataset.parent_dataset_name && (
                                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-medium bg-slate-50 text-slate-600 border border-slate-200/70">
                                    <GitMerge className="w-2.5 h-2.5 text-slate-400 flex-shrink-0" />
                                    <span className="text-slate-400">{t('listPage.derivedFrom')}</span>
                                    {' '}
                                    <span className="font-semibold text-slate-700 truncate max-w-[200px]" title={dataset.parent_dataset_name}>{dataset.parent_dataset_name}</span>
                                  </span>
                                )}
                              </div>
                            </div>

                            <div className="hidden xl:flex items-center gap-1">
                              {dataset.can_delete && (
                                 <>
                                   <Tooltip content={t('listPage.exportLabels')}>
                                     <Button
                                       variant="ghost"
                                       size="icon"
                                       className="h-8 w-8 text-slate-400 hover:text-green-600"
                                       onClick={(e) => handleExportLabelsClick(e, dataset)}
                                       disabled={exporting}
                                     >
                                       {exporting && exportingDataset?.dataset_id === dataset.dataset_id ? (
                                         <Loader2 className="w-4 h-4 animate-spin" />
                                       ) : (
                                         <Download className="w-4 h-4" />
                                       )}
                                     </Button>
                                   </Tooltip>
                                   <Tooltip content={t('listPage.editDataset')}>
                                     <Button
                                       variant="ghost"
                                       size="icon"
                                       className="h-8 w-8 text-slate-400 hover:text-blue-600"
                                       onClick={(e) => handleEditDatasetClick(e, dataset)}
                                     >
                                       <Pencil className="w-4 h-4" />
                                     </Button>
                                   </Tooltip>
                                    <Tooltip content={t('listPage.deleteDataset')}>
                                      <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-8 w-8 text-slate-400 hover:text-red-600"
                                        onClick={(e) => handleDatasetDeleteClick(e, dataset.dataset_id, dataset.dataset_name, dataset.file_count)}
                                      >
                                        <Trash2 className="w-4 h-4" />
                                      </Button>
                                    </Tooltip>
                                  </>
                                )}
                               <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-slate-500 transition-colors" />
                            </div>
                          </div>

                          <div className="flex flex-wrap items-center gap-3 sm:gap-4 text-xs sm:text-sm text-slate-500/90 pt-3 mt-3 border-t border-slate-100">
                            <span className="flex items-center gap-1.5 font-medium whitespace-nowrap">
                              <Database className="w-4 h-4 text-slate-400" />
                              {dataset.file_count} {itemType}
                            </span>
                            <span className="flex items-center gap-1.5 font-medium whitespace-nowrap">
                              <CheckCircle className="w-4 h-4 text-slate-400" />
                              {formatFileSize(dataset.total_size)}
                            </span>
                            {isAdmin && dataset.username && (
                              <span className="flex items-center gap-1.5 font-medium whitespace-nowrap text-slate-400">
                                <User className="w-3.5 h-3.5 text-slate-300" />
                                <span className="truncate max-w-[240px]" title={dataset.username}>{dataset.username}</span>
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex xl:hidden items-center justify-between pt-3 border-t border-slate-100">
                        <div className="flex items-center gap-1">
                           {dataset.can_delete && (
                             <>
                               <Tooltip content={t('listPage.exportLabels')}>
                                 <Button
                                   variant="ghost"
                                   size="icon"
                                   className="h-8 w-8 text-slate-400 hover:text-green-600"
                                   onClick={(e) => handleExportLabelsClick(e, dataset)}
                                   disabled={exporting}
                                 >
                                   {exporting && exportingDataset?.dataset_id === dataset.dataset_id ? (
                                     <Loader2 className="w-4 h-4 animate-spin" />
                                   ) : (
                                     <Download className="w-4 h-4" />
                                   )}
                                 </Button>
                               </Tooltip>
                               <Tooltip content={t('listPage.editDataset')}>
                                 <Button
                                   variant="ghost"
                                   size="icon"
                                   className="h-8 w-8 text-slate-400 hover:text-blue-600"
                                   onClick={(e) => handleEditDatasetClick(e, dataset)}
                                 >
                                   <Pencil className="w-4 h-4" />
                                 </Button>
                               </Tooltip>
                                <Tooltip content={t('listPage.deleteDataset')}>
                                  <Button
                                    variant="ghost"
                                    size="icon"
                                    className="h-8 w-8 text-slate-400 hover:text-red-600"
                                    onClick={(e) => handleDatasetDeleteClick(e, dataset.dataset_id, dataset.dataset_name, dataset.file_count)}
                                  >
                                    <Trash2 className="w-4 h-4" />
                                  </Button>
                                </Tooltip>
                              </>
                            )}
                         </div>
                         <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-slate-500 transition-colors" />
                      </div>
                    </div>
                  </Card>
                )
              })}

              {datasetCurrentPage === datasetTotalPages && (
                <button
                  type="button"
                  onClick={() => navigate('/upload')}
                  className="flex items-center justify-between gap-4 w-full p-5 rounded-xl border-2 border-dashed border-slate-200 hover:border-blue-400 hover:bg-blue-50/50 transition-all duration-300 group"
                >
                  <div className="flex items-center gap-4 min-w-0 text-left">
                    <div className="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center group-hover:bg-white group-hover:shadow-md transition-all">
                      <Upload className="w-6 h-6 text-slate-400 group-hover:text-blue-600" />
                    </div>
                    <div className="min-w-0">
                      <h3 className="text-lg font-bold text-slate-600 group-hover:text-blue-700">{t('listPage.newDataset')}</h3>
                      <p className="text-sm text-slate-400 group-hover:text-slate-500 truncate">
                        {t('listPage.newDatasetDescription')}
                      </p>
                    </div>
                  </div>
                  <ChevronRight className="w-5 h-5 text-slate-300 group-hover:text-blue-500 transition-colors" />
                </button>
              )}
            </div>
          )}

          {(datasetsQuery.data?.total ?? 0) > 0 && (
            <Card className="border-gray-100 bg-white/80 shadow-sm">
              <div className="px-4 sm:px-5 py-4 flex flex-col lg:flex-row items-center justify-between gap-4">
                <div className="text-xs sm:text-sm text-gray-500 font-medium text-center lg:text-left flex items-center gap-2">
                  <span>{t('listPage.pagination.summary', {
                    start: datasetPaginationStart,
                    end: datasetPaginationEnd,
                    total: (datasetsQuery.data?.total ?? 0),
                  })}</span>
                  {isDatasetRefreshing && (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />
                  )}
                </div>

                <div className="flex flex-col sm:flex-row items-center gap-3 sm:gap-4">
                  {datasetTotalPages > 1 && (
                    <div className="flex items-center gap-2 w-full sm:w-auto">
                      <span className="text-xs sm:text-sm text-gray-500 whitespace-nowrap">
                        {t('listPage.pagination.goToPage')}
                      </span>
                      <Input
                        value={datasetPageInput}
                        onChange={(event) => setDatasetPageInput(event.target.value.replace(/[^0-9]/g, ''))}
                        onBlur={() => commitDatasetPageInput(datasetPageInput)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            commitDatasetPageInput(datasetPageInput)
                          }

                          if (event.key === 'Escape') {
                            setDatasetPageInput(String(datasetCurrentPage))
                          }
                        }}
                        inputMode="numeric"
                        aria-label={t('listPage.pagination.goToPage')}
                        className="h-8 w-16 px-2 text-center text-xs sm:text-sm"
                      />
                      <span className="text-xs sm:text-sm text-gray-500 whitespace-nowrap">/ {datasetTotalPages}</span>
                    </div>
                  )}

                  {datasetViewMode === 'list' && (
                    <div className="flex items-center gap-2 w-full sm:w-auto">
                      <span className="text-xs sm:text-sm text-gray-500 whitespace-nowrap">
                        {t('listPage.pagination.itemsPerPage')}
                      </span>
                      <Select
                        value={String(datasetListItemsPerPage)}
                        onChange={(value) => {
                          setDatasetListItemsPerPage(Number(value))
                          setDatasetCurrentPage(1)
                        }}
                        options={[
                          { value: '5', label: '5' },
                          { value: '10', label: '10' },
                          { value: '20', label: '20' },
                        ]}
                        className="w-[88px]"
                      />
                    </div>
                  )}

                  <div className="flex items-center gap-2 sm:gap-3">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDatasetCurrentPage(prev => Math.max(prev - 1, 1))}
                      disabled={datasetCurrentPage === 1}
                      className="h-8 px-2 sm:px-3"
                    >
                      <ChevronLeft className="w-4 h-4 sm:mr-1" />
                      <span className="hidden sm:inline">{t('common.previous')}</span>
                    </Button>

                    <span className="text-xs sm:text-sm font-semibold text-gray-600 min-w-[92px] text-center">
                      {t('listPage.pagination.pageInfo', { current: datasetCurrentPage, total: datasetTotalPages })}
                    </span>

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setDatasetCurrentPage(prev => Math.min(prev + 1, datasetTotalPages))}
                      disabled={datasetCurrentPage === datasetTotalPages}
                      className="h-8 px-2 sm:px-3"
                    >
                      <span className="hidden sm:inline">{t('common.next')}</span>
                      <ChevronRight className="w-4 h-4 sm:ml-1" />
                    </Button>
                  </div>
                </div>
              </div>
            </Card>
          )}
        </>
      )}

      {/* === FILES VIEW (when a dataset is selected) === */}
      {selectedDatasetId && (
        <>
        {selectedDatasetSummary && <DatasetOverview dataset={selectedDatasetSummary}
          onEdit={selectedDatasetSummary.can_delete ? () => { setDatasetEditorTab('details'); setEditingDatasetId(selectedDatasetId) } : undefined}
          onLabels={selectedDatasetSummary.can_delete ? () => navigate('/upload', {state:{datasetId:selectedDatasetId,datasetName:selectedDatasetName,initialTab:'labels'}}) : undefined} />}
        <div className="mb-3 flex flex-wrap gap-2">
          {selectedDatasetSummary?.task_types.map(task => <button key={task} onClick={() => setSelectedDatasetType(getNormalizedDatasetTaskType(task))}
            className={`rounded-lg border px-3 py-1.5 text-xs ${getTaskFamily(task) === selectedDatasetType ? 'border-slate-400 bg-white text-slate-900' : 'border-slate-200 text-slate-500'}`}>{t(`training.taskSetup.${task}`)}</button>)}
        </div>
        </>
      )}

      {selectedDatasetId && (
        <>
          {/* Loading State */}
          {showInitialFilesLoading && (
            <DatasetLoading header={false} files/>
          )}

          {/* Error State */}
          {(wsiListQuery.error ? String(wsiListQuery.error) : undefined) && !showInitialFilesLoading && (
            <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg">
              <p className="font-medium">{t('listPage.errorLoadingFiles')}</p>
              <p className="text-sm">
                {wsiListQuery.error instanceof ApiError && (wsiListQuery.error.isServerError() || wsiListQuery.error.isNetworkError())
                  ? t('listPage.errorServiceUnavailable')
                  : String(wsiListQuery.error)}
              </p>
            </div>
          )}

          {/* Empty State */}
          {filesViewState.showDatasetEmptyState && (
            <div className="flex flex-col items-center justify-center py-16 px-4 border-2 border-dashed border-gray-200 rounded-lg bg-gray-50">
              <div className="bg-white p-4 rounded-full border border-gray-200 shadow-sm mb-4">
                <Microscope className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-medium text-gray-900 mb-1">{t('listPage.noFilesInDataset')}</h3>
              <p className="text-sm text-gray-500 max-w-sm text-center">
                {t('listPage.datasetEmptyDescription')}
              </p>
            </div>
          )}
        </>
      )}

      {/* Search and Batch Actions */}
      {filesViewState.showSearchActions && (
        <div className="flex flex-col sm:flex-row gap-3 mb-3 items-stretch sm:items-center justify-between">
          <div className="relative flex-1 max-w-md w-full">
            <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
              <Search className="h-4 sm:h-5 w-4 sm:w-5 text-gray-400" />
            </div>
            <input
              type="text"
              className="block w-full pl-9 sm:pl-10 pr-3 py-2 border border-gray-300 rounded-lg leading-5 bg-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 text-sm transition-all shadow-sm"
              placeholder={t('listPage.searchPlaceholder')}
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value)
              }}
            />
            {searchQuery && (
              <button
                type="button"
                className="absolute inset-y-0 right-0 pr-3 flex items-center"
                onClick={() => {
                  setSearchQuery('')
                }}
              >
                <X className="h-4 w-4 text-gray-400 hover:text-gray-600" />
              </button>
            )}
          </div>

          {selectedIds.size > 0 && (
            // Hidden visually but kept in DOM if needed for accessibility or other screen readers?
            // Actually let's just remove the visual rendering here since we move it to table header.
            // But ListPage has Edit/Delete specific actions which NewTaskPage doesn't have.
            // We should put these actions into the header as well.
            null
          )}
        </div>
      )}

      {/* Table - only show when a dataset is selected */}
      {filesViewState.showFileTableArea && (
        <>
          {filesViewState.showNoMatchingFilesState ? (
            <Card className="p-12 flex flex-col items-center justify-center bg-gray-50/50 border-dashed border-2 border-gray-200 rounded-2xl">
              <Search className="w-12 h-12 text-gray-300 mb-4" />
              <h3 className="text-lg font-medium text-gray-900">{t('listPage.noMatchingFiles')}</h3>
              <p className="text-gray-500 text-sm mt-1">{t('listPage.adjustSearchTerms')}</p>
              <Button
                variant="ghost"
                className="mt-4 text-primary-600 hover:text-primary-700"
                onClick={() => setSearchQuery('')}
              >
                {t('listPage.clearSearch')}
              </Button>
            </Card>
          ) : (
            <Card className="overflow-hidden shadow-sm border-gray-100 rounded-xl bg-white/50 backdrop-blur-sm min-h-[600px] flex flex-col">
              <div className="overflow-x-auto flex-1">
                <table className="w-full">
                  <thead>
                    <tr className={`h-[50px] bg-gray-50/80 border-b border-gray-100 backdrop-blur-md ${selectedIds.size > 0 ? 'bg-blue-50/50' : ''}`}>
                      <th className="px-3 sm:px-6 py-3 text-left w-10 sm:w-12">
                        <Checkbox
                          aria-label={t('common.selectAll')}
                          checked={allPageSelected}
                          onChange={handleSelectPage}
                        />
                      </th>
                      {selectedIds.size > 0 ? (
                        <th colSpan={10} className="px-3 sm:px-6 py-3 text-left">
                           <div className="flex items-center justify-between w-full">
                            <div className="flex items-center gap-4">
                               <span className="text-xs sm:text-sm font-bold text-blue-900">
                                 {t('listPage.selectedCount', { count: selectedIds.size })}
                              </span>
                              {!allFilteredSelected && (
                                 <button
                                   type="button"
                                   onClick={() => setSelectedIds(new Set())}
                                   className="text-[10px] sm:text-xs font-medium text-gray-500 hover:text-gray-700 underline"
                                 >
                                   {t('listPage.clearSelection')}
                                </button>
                              )}
                            </div>
                            <div className="flex items-center gap-3">
                               <button
                                 type="button"
                                 onClick={handleBatchEditClick}
                                 className="text-blue-600 hover:text-blue-700 text-xs sm:text-sm font-semibold flex items-center gap-1"
                              >
                                <Edit className="w-3.5 h-3.5" />
                                 {t('listPage.edit')}
                              </button>
                               <button
                                 type="button"
                                 onClick={handleBatchDeleteClick}
                                 className="text-red-600 hover:text-red-700 text-xs sm:text-sm font-semibold flex items-center gap-1"
                              >
                                <Trash2 className="w-3.5 h-3.5" />
                                 {t('listPage.delete')}
                              </button>
                            </div>
                          </div>
                        </th>
                      ) : (
                        <>
                          {([
                            'filename',
                            ...(selectedDatasetType === 'survival' ? ['event_time', 'event_status'] : ['label']),
                          ] as SortColumn[]).map((col, i) => {
                            const labels: Record<SortColumn, string> = {
                              filename: t('listPage.slideId'),
                              label: labelColumnTitle,
                              event_time: t('listPage.timeMonths'),
                              event_status: t('listPage.status'),
                            }
                            const isActive = sortColumn === col
                            const Icon = isActive ? (sortDirection === 'asc' ? ArrowUp : ArrowDown) : ChevronsUpDown
                            return (
                              <React.Fragment key={col}>
                                <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                                  <button
                                    type="button"
                                    onClick={() => handleSort(col)}
                                    onMouseEnter={() => prefetchSort(col)}
                                    className={`inline-flex items-center gap-1 rounded hover:text-gray-800 transition-colors ${isActive ? 'text-primary-600' : ''}`}
                                  >
                                    {labels[col]}
                                    <Icon className={`w-3 h-3 ${isActive ? 'text-primary-500' : 'text-gray-400'}`} />
                                  </button>
                                </th>
                                {i === 0 && (
                                  <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{t('listPage.type')}</th>
                                )}
                              </React.Fragment>
                            )
                          })}
                          <th className="px-3 sm:px-6 py-3 text-left text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{t('listPage.patientInfo')}</th>
                          <th className="px-3 sm:px-6 py-3 text-right text-[10px] sm:text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">{t('listPage.action')}</th>
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 bg-white/40">
                     {/* Batch Selection Banner — show prompt to select all when page is selected */}
                      {allPageSelected && !allFilteredSelected && (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) > pageSlides.length && (
                        <tr className="bg-blue-50/50">
                          <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
                            <span className="font-medium">{t('listPage.allPageSelected', { count: pageSlides.length })}</span>
                             <button
                              type="button"
                              onClick={handleSelectAllFiltered}
                              className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none"
                            >
                              {t('listPage.selectAllItems', { count: (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) })}
                            </button>
                          </td>
                        </tr>
                      )}
                      {/* Show when all items are selected */}
                      {allFilteredSelected && (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) > pageSlides.length && (
                        <tr className="bg-blue-50/50">
                          <td colSpan={100} className="px-4 py-2 text-center text-xs sm:text-sm text-gray-700 border-b border-blue-100">
                            <span className="font-medium">{t('listPage.allItemsSelected', { count: (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) })}</span>
                             <button
                               type="button"
                               onClick={() => setSelectedIds(new Set())}
                               className="ml-2 font-bold text-blue-600 hover:text-blue-800 hover:underline focus:outline-none"
                             >
                               {t('listPage.clearSelection')}
                            </button>
                          </td>
                        </tr>
                      )}

                    {useCaseGroupedView && paginatedCases ? (
                      // Grouped view - show WSI datasets by case
                      paginatedCases.map(([caseKey, slides]) => {
                        const representativeSlide = slides[0]
                        const displayCaseId = representativeSlide?.case_id?.trim() || null
                        const isNoCase = !displayCaseId
                        const isMultiSlide = slides.length > 1
                        const isExpanded = expandedCases.has(caseKey)
                        const allSelected = slides.every(s => selectedIds.has(s.wsi_id))
                        const someSelected = slides.some(s => selectedIds.has(s.wsi_id))

                        // Single-slide case: keep case-style row, but show actions directly
                        if (!isMultiSlide) {
                          const it = slides[0]
                          const isSelected = selectedIds.has(it.wsi_id)
                          return (
                            <tr
                              key={it.wsi_id}
                              className={`group transition-all duration-200 border-l-2 ${isSelected ? 'bg-blue-50/40 border-primary-500' : 'hover:bg-white/60 border-transparent hover:border-gray-200'}`}
                            >
                              <td className="px-3 sm:px-6 py-4 sm:py-5 w-10 sm:w-12">
                                <Checkbox
                                  aria-label={it.original_filename || it.wsi_id}
                                  checked={isSelected}
                                  onChange={() => toggleSelection(it.wsi_id)}
                                />
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex items-center gap-2 sm:gap-3 min-h-[3.5rem] sm:min-h-[4rem]">
                                  <Users className="w-4 h-4 sm:w-5 sm:h-5 text-blue-500" />
                                  <div className="flex flex-col min-w-[120px] sm:min-w-[150px]">
                                    <div className="flex flex-col sm:flex-row sm:items-center sm:gap-3">
                                      <span className="text-sm sm:text-base font-semibold text-gray-900">
                                        {isNoCase ? t('listPage.noCaseId') : t('listPage.caseLabel', { caseId: displayCaseId })}
                                      </span>
                                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 border border-blue-200 w-fit">
                                        {t('listPage.slideCountSingle', { count: 1 })}
                                      </span>
                                    </div>
                                    <span className="text-[10px] sm:text-sm text-gray-500 mt-0.5 truncate max-w-[150px] sm:max-w-[300px]" title={it.original_filename}>{it.original_filename}</span>
                                    <span className="text-[10px] sm:text-xs text-gray-400 mt-0.5 truncate max-w-[150px] sm:max-w-[300px]" title={it.wsi_id}>{it.wsi_id}</span>
                                   {it.parent_wsi_id && (
                                     <Link
                                       to={`/wsi/${encodeURIComponent(it.parent_wsi_id)}`}
                                       state={{ fromDataset: true, datasetId: selectedDatasetId, datasetName: selectedDatasetName }}
                                       className="group/link flex flex-col sm:flex-row items-start sm:items-center gap-1 sm:gap-1.5 mt-1"
                                       title={it.parent_wsi_name && it.parent_dataset_name ? t('annotation.croppedFromDataset', { datasetName: it.parent_dataset_name, slideName: it.parent_wsi_name }) : t('annotation.viewSource')}
                                       onClick={(e) => e.stopPropagation()}
                                     >
                                       <div className="flex items-center gap-1 flex-wrap">
                                         <span className="text-[10px] sm:text-[11px] font-medium text-gray-500 whitespace-nowrap bg-gray-100/80 px-1.5 py-0.5 rounded-sm border border-gray-200">
                                           {t('annotation.croppedFrom')}
                                         </span>
                                         {it.parent_wsi_name && it.parent_dataset_name ? (
                                           <>
                                             <span className="inline-flex flex-shrink-0 items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-orange-50 text-orange-700 border border-orange-200/60 transition-colors max-w-[100px] sm:max-w-[150px] truncate" title={it.parent_dataset_name}>
                                               <Database className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70 flex-shrink-0" />
                                               <span className="truncate">{it.parent_dataset_name}</span>
                                             </span>
                                             <span className="inline-flex flex-shrink-0 items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/60 group-hover/link:bg-blue-100 transition-colors max-w-[120px] sm:max-w-[200px] truncate" title={it.parent_wsi_name}>
                                               <FileImage className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70 flex-shrink-0" />
                                               <span className="truncate">{it.parent_wsi_name}</span>
                                             </span>
                                           </>
                                         ) : (
                                           <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/60 group-hover/link:bg-blue-100 transition-colors">
                                             <FileImage className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70" />
                                             {it.parent_wsi_id.slice(0, 8)}…
                                           </span>
                                         )}
                                       </div>
                                     </Link>
                                   )}
                                  </div>
                                </div>
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                {(() => {
                                  const fileType = getFileType(it.file_extension, it.file_size, it.data_type)
                                  return fileType === 'WSI' ? (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">{t('listPage.wsi')}</span>
                                  ) : (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">{t('listPage.patch')}</span>
                                  )
                                })()}
                              </td>
                              {selectedDatasetType === 'survival' ? (
                                <>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    {it.event_time != null ? (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-blue-100/80 text-blue-700 border border-blue-200/60 shadow-sm whitespace-nowrap">{it.event_time}</span>
                                    ) : (
                                      <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.notSet')}</span>
                                    )}
                                  </td>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    {it.event_status != null ? (
                                      <span className={`inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium border shadow-sm whitespace-nowrap ${it.event_status === 1 ? 'bg-red-100/80 text-red-700 border-red-200/60' : 'bg-green-100/80 text-green-700 border-green-200/60'}`}>
                                        {it.event_status === 1 ? t('listPage.event') : t('listPage.censored')}
                                      </span>
                                    ) : (
                                      <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.notSet')}</span>
                                    )}
                                  </td>
                                </>
                              ) : (
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {renderLabelBadge(it)}
                                </td>
                              )}
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex flex-wrap gap-1 sm:gap-2 items-center min-w-[100px]">
                                  {!(it.age || it.gender || it.source) ? (
                                    <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.notSpecified')}</span>
                                  ) : (
                                    <>
                                      {it.source && <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap"><span className="hidden sm:inline">{t('listPage.sourcePrefix')}</span><span className="sm:ml-1 text-blue-900">{organSourceKeyMap[it.source] ? String(t(`organSources.${organSourceKeyMap[it.source]}`)) : it.source}</span></span>}
                                      {it.age && <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{it.age}y</span>}
                                      {it.gender && <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{String(t(`listComponents.editModals.${it.gender.toLowerCase()}`, it.gender))}</span>}
                                    </>
                                  )}
                                </div>
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5 text-right">
                                <div className="flex items-center justify-end gap-1 sm:gap-3 sm:opacity-60 group-hover:opacity-100 transition-opacity">
                                  <Tooltip content={t('listPage.viewFile')}>
                                    <Link
                                      to={`/wsi/${encodeURIComponent(it.wsi_id)}`}
                                      state={{
                                        fromDataset: true,
                                        datasetId: selectedDatasetId,
                                        datasetName: selectedDatasetName
                                      }}
                                    >
                                      <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg"><Microscope className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button>
                                    </Link>
                                  </Tooltip>
                                  {it.can_delete && <Tooltip content={t('listPage.editMetadata')}><Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg" onClick={(e) => { e.preventDefault(); handleEditClick(it); }}><Edit className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button></Tooltip>}
                                  {it.can_delete && <Tooltip content={t('listPage.deleteFile')}><Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg" onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label ?? '', it.original_filename); }}><Trash2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" /></Button></Tooltip>}
                                </div>
                              </td>
                            </tr>
                          )
                        }

                        // Multi-slide case - render expandable group
                        return (
                          <React.Fragment key={caseKey}>
                            {/* Case header row */}
                            <tr
                              className={`group transition-all duration-200 border-l-2 cursor-pointer ${someSelected ? 'bg-blue-50/40 border-primary-500' : 'hover:bg-gray-50/60 border-transparent hover:border-blue-200'}`}
                              onClick={() => toggleCaseExpansion(caseKey)}
                            >
                              <td className="px-3 sm:px-6 py-4 sm:py-5 w-10 sm:w-12" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                                <Checkbox
                                  aria-label={t('common.selectAll')}
                                  checked={allSelected}
                                  indeterminate={someSelected && !allSelected}
                                  onChange={(e) => {
                                    const newSelected = new Set(selectedIds)
                                    if (e.target.checked) {
                                      slides.forEach(s => { newSelected.add(s.wsi_id) })
                                    } else {
                                      slides.forEach(s => { newSelected.delete(s.wsi_id) })
                                    }
                                    setSelectedIds(newSelected)
                                  }}
                                />
                              </td>
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex items-center gap-2 sm:gap-3 min-h-[3.5rem] sm:min-h-[4rem]">
                                  <ChevronDown className={`w-4 h-4 sm:w-5 sm:h-5 text-gray-400 transition-transform ${isExpanded ? '' : '-rotate-90'}`} />
                                  <div className="flex flex-col sm:flex-row sm:items-center sm:gap-3">
                                    <div className="flex items-center gap-2">
                                      <Users className="w-4 h-4 sm:w-5 sm:h-5 text-blue-500" />
                                      <span className="text-sm sm:text-base font-semibold text-gray-900">
                                        {isNoCase ? t('listPage.noCaseId') : t('listPage.caseLabel', { caseId: displayCaseId })}
                                      </span>
                                    </div>
                                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 border border-blue-200">
                                      {slides.length === 1
                                        ? t('listPage.slideCountSingle', { count: slides.length })
                                        : t('listPage.slidesCount', { count: slides.length })}
                                    </span>
                                  </div>
                                </div>
                              </td>

                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                {(() => {
                                  // eslint-disable-next-line
                                  const types = new Set(slides.map(s => getFileType(s.file_extension, s.file_size, s.data_type)))
                                  if (types.has('WSI') && types.has('Patch')) {
                                    return <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">{t('listPage.mixed')}</span>
                                  }
                                  const type = types.values().next().value || 'WSI'
                                  return type === 'WSI' ? (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">{t('listPage.wsi')}</span>
                                  ) : (
                                    <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">{t('listPage.patch')}</span>
                                  )
                                })()}
                              </td>

                              {selectedDatasetType === 'survival' ? (
                                <>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    <span className="text-gray-400 text-xs italic">{t('listPage.seeSlides')}</span>
                                  </td>
                                  <td className="px-3 sm:px-6 py-4 sm:py-5">
                                    {(() => {
                                      const events = slides.filter(s => s.event_status === 1).length
                                      const censored = slides.filter(s => s.event_status === 0).length
                                      if (events === 0 && censored === 0) return <span className="text-gray-300 text-xs italic">{t('listPage.notSet')}</span>
                                      return (
                                        <div className="flex flex-col gap-1">
                                          {events > 0 && <span className="text-xs text-red-600 font-medium">{t('listPage.eventCount', { count: events })}</span>}
                                          {censored > 0 && <span className="text-xs text-green-600 font-medium">{t('listPage.censoredCount', { count: censored })}</span>}
                                        </div>
                                      )
                                    })()}
                                  </td>
                                </>
                              ) : (
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {renderCaseLabelBadge(slides)}
                                </td>
                              )}

                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                <div className="flex flex-wrap gap-1 sm:gap-2 items-center min-w-[100px]">
                                  {(() => {
                                    const sources = Array.from(new Set(slides.map(s => s.source as string).filter(Boolean)))
                                    const ages = Array.from(new Set(slides.map(s => s.age).filter((a: any) => a !== null && a !== undefined)))
                                    const genders = Array.from(new Set(slides.map(s => s.gender as string).filter(Boolean)))

                                    if (sources.length === 0 && ages.length === 0 && genders.length === 0) {
                                      return <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.notSpecified')}</span>
                                    }

                                    return (
                                      <>
                                        {sources.length > 0 && (
                                          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">
                                            {sources.length === 1 ? <><span className="hidden sm:inline">{t('listPage.sourcePrefix')}</span><span className="sm:ml-1 text-blue-900">{organSourceKeyMap[sources[0]] ? t(`organSources.${organSourceKeyMap[sources[0]]}`) : sources[0]}</span></> : t('listPage.sourcesCount', { count: sources.length })}
                                          </span>
                                        )}
                                        {ages.length > 0 && (
                                          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                            {ages.length === 1 ? `${ages[0]}y` : `${Math.min(...ages as number[])}..${Math.max(...ages as number[])}y`}
                                          </span>
                                        )}
                                        {genders.length > 0 && (
                                          <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                            {genders.length === 1 ? t(`listComponents.editModals.${genders[0].toLowerCase()}`, genders[0]) : t('listPage.mixed')}
                                          </span>
                                        )}
                                      </>
                                    )
                                  })()}
                                </div>
                              </td>

                              <td className="px-3 sm:px-6 py-4 sm:py-5 text-right">
                                <span className="text-xs text-gray-400 whitespace-nowrap">{isExpanded ? t('listPage.collapse') : t('listPage.expand')}</span>
                              </td>
                            </tr>
                            {/* Expanded slides */}
                            {isExpanded && slides.map((it) => {
                              const isSelected = selectedIds.has(it.wsi_id)
                              return (
                                <tr
                                  key={it.wsi_id}
                                  className={`group transition-all duration-200 border-l-4 ${isSelected ? 'bg-blue-50/40 border-blue-400' : 'bg-gray-50/30 hover:bg-white/60 border-blue-200'}`}
                                >
                                  <td className="px-3 sm:px-6 py-3 sm:py-4 w-10 sm:w-12 pl-6 sm:pl-10">
                                    <Checkbox
                                      aria-label={it.original_filename || it.wsi_id}
                                      checked={isSelected}
                                      onChange={() => toggleSelection(it.wsi_id)}
                                    />
                                  </td>
                                  <td className="px-3 sm:px-6 py-3 sm:py-4">
                                    <div className="flex flex-col min-w-[120px] sm:min-w-[150px] pl-4 sm:pl-6 min-h-[3rem] justify-center">
                                      <span className="text-xs sm:text-sm font-medium text-gray-700 truncate max-w-[150px] sm:max-w-[200px]" title={it.wsi_id}>{it.wsi_id}</span>
                                      <span className="text-[10px] sm:text-xs text-gray-400 mt-0.5 truncate max-w-[150px] sm:max-w-[300px]" title={it.original_filename}>{it.original_filename}</span>
                                       {it.parent_wsi_id && (
                                         <Tooltip content={it.parent_wsi_name && it.parent_dataset_name ? t('annotation.croppedFromDataset', { datasetName: it.parent_dataset_name, slideName: it.parent_wsi_name }) : t('annotation.viewSource')}>
                                           <Link
                                             to={`/wsi/${encodeURIComponent(it.parent_wsi_id)}`}
                                             state={{ fromDataset: true, datasetId: selectedDatasetId, datasetName: selectedDatasetName }}
                                             className="group/link flex flex-col sm:flex-row items-start sm:items-center gap-1 sm:gap-1.5 mt-1"
                                             onClick={(e) => e.stopPropagation()}
                                           >
                                             <div className="flex items-center gap-1 flex-wrap">
                                               <span className="text-[10px] sm:text-[11px] font-medium text-gray-500 whitespace-nowrap bg-gray-100/80 px-1.5 py-0.5 rounded-sm border border-gray-200">
                                                 {t('annotation.croppedFrom')}
                                               </span>
                                               {it.parent_wsi_name && it.parent_dataset_name ? (
                                                 <>
                                                   <span className="inline-flex flex-shrink-0 items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-orange-50 text-orange-700 border border-orange-200/60 transition-colors max-w-[100px] sm:max-w-[150px] truncate" title={it.parent_dataset_name}>
                                                     <Database className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70 flex-shrink-0" />
                                                     <span className="truncate">{it.parent_dataset_name}</span>
                                                   </span>
                                                   <span className="inline-flex flex-shrink-0 items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/60 group-hover/link:bg-blue-100 transition-colors max-w-[120px] sm:max-w-[200px] truncate" title={it.parent_wsi_name}>
                                                     <FileImage className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70 flex-shrink-0" />
                                                     <span className="truncate">{it.parent_wsi_name}</span>
                                                   </span>
                                                 </>
                                               ) : (
                                                 <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/60 group-hover/link:bg-blue-100 transition-colors">
                                                   <FileImage className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70" />
                                                   {it.parent_wsi_id.slice(0, 8)}…
                                                 </span>
                                               )}
                                             </div>
                                           </Link>
                                         </Tooltip>
                                       )}
                                    </div>
                                  </td>
                                  <td className="px-3 sm:px-6 py-3 sm:py-4">
                                    {(() => {
                                      const fileType = getFileType(it.file_extension, it.file_size, it.data_type)
                                      return fileType === 'WSI' ? (
                                        <span className="inline-flex items-center px-1.5 sm:px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">{t('listPage.wsi')}</span>
                                      ) : (
                                        <span className="inline-flex items-center px-1.5 sm:px-2 py-0.5 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">{t('listPage.patch')}</span>
                                      )
                                    })()}
                                  </td>
                                  {selectedDatasetType === 'survival' ? (
                                    <>
                                      <td className="px-3 sm:px-6 py-3 sm:py-4">
                                        {it.event_time != null ? (
                                          <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100/80 text-blue-700 border border-blue-200/60 whitespace-nowrap">{it.event_time}</span>
                                        ) : (
                                          <span className="text-gray-300 text-[10px] italic">{t('listPage.notSet')}</span>
                                        )}
                                      </td>
                                      <td className="px-3 sm:px-6 py-3 sm:py-4">
                                        {it.event_status != null ? (
                                          <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border whitespace-nowrap ${it.event_status === 1 ? 'bg-red-100/80 text-red-700 border-red-200/60' : 'bg-green-100/80 text-green-700 border-green-200/60'}`}>
                                            {it.event_status === 1 ? t('listPage.event') : t('listPage.censored')}
                                          </span>
                                        ) : (
                                          <span className="text-gray-300 text-[10px] italic">{t('listPage.notSet')}</span>
                                        )}
                                      </td>
                                    </>
                                  ) : (
                                    <td className="px-3 sm:px-6 py-3 sm:py-4">
                                      {renderLabelBadge(it)}
                                    </td>
                                  )}
                                  <td className="px-3 sm:px-6 py-3 sm:py-4">
                                    <div className="flex flex-wrap gap-1 items-center min-w-[80px]">
                                      {!(it.age || it.gender || it.source) ? (
                                        <span className="text-gray-300 text-[10px] italic">-</span>
                                      ) : (
                                        <>
                                          {it.source && <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">{organSourceKeyMap[it.source] ? String(t(`organSources.${organSourceKeyMap[it.source]}`)) : it.source}</span>}
                                          {it.age && <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{it.age}y</span>}
                                          {it.gender && <span className="inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">{String(t(`listComponents.editModals.${it.gender.toLowerCase()}`, it.gender))}</span>}
                                        </>
                                      )}
                                    </div>
                                  </td>
                                  <td className="px-3 sm:px-6 py-3 sm:py-4 text-right">
                                    <div className="flex items-center justify-end gap-1 sm:gap-2 opacity-60 group-hover:opacity-100 transition-opacity">
                                      <Tooltip content={t('listPage.viewFile')}>
                                        <Link
                                          to={`/wsi/${encodeURIComponent(it.wsi_id)}`}
                                          state={{
                                            fromDataset: true,
                                            datasetId: selectedDatasetId,
                                            datasetName: selectedDatasetName
                                          }}
                                        >
                                          <Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg"><Microscope className="w-3 h-3 sm:w-4 sm:h-4" /></Button>
                                        </Link>
                                      </Tooltip>
                                      {it.can_delete && <Tooltip content={t('listPage.editMetadata')}><Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg" onClick={(e) => { e.preventDefault(); handleEditClick(it); }}><Edit className="w-3 h-3 sm:w-4 sm:h-4" /></Button></Tooltip>}
                                      {it.can_delete && <Tooltip content={t('listPage.deleteFile')}><Button variant="ghost" size="icon" className="h-6 w-6 sm:h-7 sm:w-7 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg" onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label ?? '', it.original_filename); }}><Trash2 className="w-3 h-3 sm:w-4 sm:h-4" /></Button></Tooltip>}
                                    </div>
                                  </td>
                                </tr>
                              )
                            })}
                          </React.Fragment>
                        )
                      })
                    ) : (
                      // Flat view - no multi-slide cases
                      paginatedItems.map((it: ListWSIItem) => {
                        const isSelected = selectedIds.has(it.wsi_id)
                        return (
                          <tr
                            key={it.wsi_id}
                            className={`group transition-all duration-200 border-l-2 ${isSelected ? 'bg-blue-50/40 border-primary-500' : 'hover:bg-white/60 border-transparent hover:border-gray-200'}`}
                          >
                            <td className="px-3 sm:px-6 py-4 sm:py-5 w-10 sm:w-12">
                              <Checkbox
                                aria-label={it.original_filename || it.wsi_id}
                                checked={isSelected}
                                onChange={() => toggleSelection(it.wsi_id)}
                              />
                            </td>
                            <td className="px-3 sm:px-6 py-4 sm:py-5">
                              <div className="flex flex-col min-w-[120px] sm:min-w-[150px] min-h-[3.5rem] sm:min-h-[4rem] justify-center">
                                <span className="text-sm sm:text-base font-semibold text-gray-900 truncate max-w-[150px] sm:max-w-[200px]" title={it.wsi_id}>{it.wsi_id}</span>
                                <span className="text-[10px] sm:text-sm text-gray-500 mt-0.5 truncate max-w-[150px] sm:max-w-[300px]" title={it.original_filename}>{it.original_filename}</span>
                                   {it.parent_wsi_id && (
                                     <Tooltip content={it.parent_wsi_name && it.parent_dataset_name ? t('annotation.croppedFromDataset', { datasetName: it.parent_dataset_name, slideName: it.parent_wsi_name }) : t('annotation.viewSource')}>
                                       <Link
                                         to={`/wsi/${encodeURIComponent(it.parent_wsi_id)}`}
                                         state={{ fromDataset: true, datasetId: selectedDatasetId, datasetName: selectedDatasetName }}
                                         className="group/link flex flex-col sm:flex-row items-start sm:items-center gap-1 sm:gap-1.5 mt-1"
                                         onClick={(e) => e.stopPropagation()}
                                       >
                                       <div className="flex items-center gap-1 flex-wrap">
                                         <span className="text-[10px] sm:text-[11px] font-medium text-gray-500 whitespace-nowrap bg-gray-100/80 px-1.5 py-0.5 rounded-sm border border-gray-200">
                                           {t('annotation.croppedFrom')}
                                         </span>
                                         {it.parent_wsi_name && it.parent_dataset_name ? (
                                           <>
                                             <span className="inline-flex flex-shrink-0 items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-orange-50 text-orange-700 border border-orange-200/60 transition-colors max-w-[100px] sm:max-w-[150px] truncate" title={it.parent_dataset_name}>
                                               <Database className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70 flex-shrink-0" />
                                               <span className="truncate">{it.parent_dataset_name}</span>
                                             </span>
                                             <span className="inline-flex flex-shrink-0 items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/60 group-hover/link:bg-blue-100 transition-colors max-w-[120px] sm:max-w-[200px] truncate" title={it.parent_wsi_name}>
                                               <FileImage className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70 flex-shrink-0" />
                                               <span className="truncate">{it.parent_wsi_name}</span>
                                             </span>
                                           </>
                                         ) : (
                                           <span className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-[10px] sm:text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200/60 group-hover/link:bg-blue-100 transition-colors">
                                             <FileImage className="w-2.5 h-2.5 sm:w-3 sm:h-3 mr-1 inline opacity-70" />
                                             {it.parent_wsi_id.slice(0, 8)}…
                                           </span>
                                         )}
                                       </div>
                                      </Link>
                                      </Tooltip>
                                    )}
                                 {it.case_id && !isPatchDataset && (
                                   <span className="text-[10px] sm:text-xs text-blue-600 mt-0.5 truncate max-w-[150px] sm:max-w-[200px]" title={t('listPage.caseLabel', { caseId: it.case_id })}>
                                     {t('listPage.caseLabel', { caseId: it.case_id })}
                                  </span>
                                )}
                              </div>
                            </td>
                            <td className="px-3 sm:px-6 py-4 sm:py-5">
                              {(() => {
                                const fileType = getFileType(it.file_extension, it.file_size, it.data_type)
                                return fileType === 'WSI' ? (
                                  <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-purple-100 text-purple-700 border border-purple-200 whitespace-nowrap">
                                    {t('listPage.wsi')}
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center px-1.5 sm:px-2.5 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-xs font-medium bg-green-100 text-green-700 border border-green-200 whitespace-nowrap">
                                    {t('listPage.patch')}
                                  </span>
                                )
                              })()}
                            </td>
                            {selectedDatasetType === 'survival' ? (
                              <>
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {it.event_time != null ? (
                                    <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium bg-blue-100/80 text-blue-700 border border-blue-200/60 shadow-sm whitespace-nowrap">
                                      {it.event_time}
                                    </span>
                                  ) : (
                                    <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.notSet')}</span>
                                  )}
                                </td>
                                <td className="px-3 sm:px-6 py-4 sm:py-5">
                                  {it.event_status != null ? (
                                    <span className={`inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-full text-xs sm:text-sm font-medium border shadow-sm whitespace-nowrap ${it.event_status === 1
                                      ? 'bg-red-100/80 text-red-700 border-red-200/60'
                                      : 'bg-green-100/80 text-green-700 border-green-200/60'
                                      }`}>
                                      {it.event_status === 1 ? t('listPage.event') : t('listPage.censored')}
                                    </span>
                                  ) : (
                                    <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.notSet')}</span>
                                  )}
                                </td>
                              </>
                            ) : (
                              <td className="px-3 sm:px-6 py-4 sm:py-5">
                                {renderLabelBadge(it)}
                              </td>
                            )}
                            <td className="px-3 sm:px-6 py-4 sm:py-5">
                              <div className="flex flex-wrap gap-1 sm:gap-2 items-center min-w-[100px]">
                                {!(it.age || it.gender || it.source) ? (
                                  <span className="text-gray-300 text-[10px] sm:text-sm italic">{t('listPage.notSpecified')}</span>
                                ) : (
                                  <>
                                    {it.source && (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-blue-50 text-blue-700 border border-blue-100 whitespace-nowrap">
                                        <span className="hidden sm:inline">{t('listPage.sourcePrefix')} </span><span className="sm:ml-1 text-blue-900">{organSourceKeyMap[it.source] ? t(`organSources.${organSourceKeyMap[it.source]}`) : it.source}</span>
                                      </span>
                                    )}
                                    {it.age && (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                        {it.age}y
                                      </span>
                                    )}
                                    {it.gender && (
                                      <span className="inline-flex items-center px-2 sm:px-3 py-0.5 sm:py-1 rounded-md text-[10px] sm:text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200 whitespace-nowrap">
                                        {String(t(`listComponents.editModals.${it.gender.toLowerCase()}`, it.gender))}
                                      </span>
                                    )}
                                  </>
                                )}
                              </div>
                            </td>
                            <td className="px-3 sm:px-6 py-4 sm:py-5 text-right">
                              <div className="flex items-center justify-end gap-1 sm:gap-3 sm:opacity-60 group-hover:opacity-100 transition-opacity">
                                <Tooltip content={t('listPage.viewFile')}>
                                  <Link
                                    to={`/wsi/${encodeURIComponent(it.wsi_id)}`}
                                    state={{
                                      fromDataset: true,
                                      datasetId: selectedDatasetId,
                                      datasetName: selectedDatasetName
                                    }}
                                  >
                                    <Button variant="ghost" size="icon" className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-blue-600 hover:bg-blue-50 rounded-lg">
                                      <Microscope className="w-3.5 h-3.5 sm:w-5 sm:h-5" />
                                    </Button>
                                  </Link>
                                </Tooltip>

                                {it.can_delete && (
                                  <Tooltip content={t('listPage.editMetadata')}>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-lg"
                                      onClick={(e) => { e.preventDefault(); handleEditClick(it); }}
                                    >
                                      <Edit className="w-3.5 h-3.5 sm:w-5 sm:h-5" />
                                    </Button>
                                  </Tooltip>
                                )}

                                {it.can_delete && (
                                  <Tooltip content={t('listPage.deleteFile')}>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="h-7 w-7 sm:h-9 sm:w-9 text-gray-500 hover:text-red-600 hover:bg-red-50 rounded-lg"
                                      onClick={(e) => { e.preventDefault(); handleDeleteClick(it.wsi_id, it.label ?? '', it.original_filename); }}
                                    >
                                      <Trash2 className="w-3.5 h-3.5 sm:w-5 sm:h-5" />
                                    </Button>
                                  </Tooltip>
                                )}
                              </div>
                            </td>
                          </tr>
                        )
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination Controls */}
              <div className="px-3 sm:px-6 py-4 border-t border-gray-100 flex flex-col lg:flex-row items-center justify-between gap-6 lg:gap-4 bg-gray-50/30 backdrop-blur-sm rounded-b-xl">
                <div className="text-[11px] sm:text-sm text-gray-500 font-medium order-3 lg:order-1 text-center lg:text-left flex items-center justify-center lg:justify-start gap-2">
                  {useCaseGroupedView ? (
                    <>
                       {t('listPage.showing')} <span className="text-gray-900">{(wsiListQuery.data?.total_cases ?? 0) === 0 ? 0 : startIndex + 1}</span> {t('listPage.to')}{' '}
                       <span className="text-gray-900">{Math.min(startIndex + itemsPerPage, (wsiListQuery.data?.total_cases ?? 0))}</span>{' '}
                       {t('listPage.of')} <span className="text-gray-900">{(wsiListQuery.data?.total_cases ?? 0)}</span> {t('listPage.cases')}
                       <span className="text-gray-400 font-normal ml-1 whitespace-nowrap">({t('listPage.slidesTotal', { count: (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) })})</span>
                    </>
                  ) : (
                    <>
                       {t('listPage.showing')} <span className="text-gray-900">{(wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0) === 0 ? 0 : startIndex + 1}</span> {t('listPage.to')}{' '}
                       <span className="text-gray-900">{Math.min(startIndex + itemsPerPage, (wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0))}</span>{' '}
                       {t('listPage.of')} <span className="text-gray-900">{(wsiListQuery.data?.total ?? wsiListQuery.data?.items?.length ?? 0)}</span> {t('listPage.files')}
                    </>
                  )}
                  {isFilesRefreshing && (
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-gray-400" />
                  )}
                </div>

                {totalPages > 1 && (
                  <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-6 order-1 lg:order-2 w-full lg:w-auto justify-center">
                    {/* Goto Page */}
                    <div className="flex items-center justify-center gap-1.5 sm:gap-2 bg-white/50 px-3 py-1.5 rounded-full border border-gray-100 sm:border-transparent">
                      <span className="text-[11px] sm:text-sm text-gray-500 whitespace-nowrap">{t('listPage.goTo')}</span>
                      <input
                        type="number"
                        min={1}
                        max={totalPages}
                        value={filePageInput}
                        onChange={(e) => {
                          setFilePageInput(e.target.value)
                        }}
                        onBlur={() => commitFilePageInput(filePageInput, totalPages)}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter') {
                            event.preventDefault()
                            commitFilePageInput(filePageInput, totalPages)
                          }
                          if (event.key === 'Escape') {
                            setFilePageInput(String(currentPage))
                          }
                        }}
                        className="w-10 sm:w-16 h-7 sm:h-9 px-1 sm:px-2 border border-gray-200 rounded-lg text-xs sm:text-sm text-center focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none transition-all font-semibold"
                      />
                      <span className="text-[11px] sm:text-sm text-gray-500 whitespace-nowrap">/ {totalPages}</span>
                    </div>

                    <div className="flex items-center gap-1.5 sm:gap-2 order-2 sm:order-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setCurrentPage(prev => Math.max(prev - 1, 1))}
                        disabled={currentPage === 1}
                        className="h-8 w-8 sm:h-9 sm:w-9 p-0 border-gray-200 hover:bg-white hover:text-primary-600 disabled:opacity-40"
                      >
                        <ChevronLeft className="h-4 h-4 sm:h-5 sm:w-5" />
                      </Button>

                      <div className="flex items-center gap-1">
                        {visibleFilePages
                          .map((page, index, array) => (
                            <React.Fragment key={page}>
                              {index > 0 && array[index - 1] !== page - 1 && (
                                <span className="px-0.5 sm:px-1 text-gray-400 text-xs text-center">...</span>
                              )}
                              <Button
                                variant={currentPage === page ? 'default' : 'ghost'}
                                size="sm"
                                onClick={() => setCurrentPage(page)}
                                className={`h-8 w-8 sm:h-9 sm:w-9 p-0 text-xs sm:text-sm font-medium transition-all ${currentPage === page
                                  ? 'bg-primary-600 text-white shadow-md shadow-primary-200 hover:bg-primary-700'
                                  : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100'
                                  }`}
                              >
                                {page}
                              </Button>
                            </React.Fragment>
                          ))}
                      </div>

                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setCurrentPage(prev => Math.min(prev + 1, totalPages))}
                        disabled={currentPage === totalPages}
                        className="h-8 w-8 sm:h-9 sm:w-9 p-0 border-gray-200 hover:bg-white hover:text-primary-600 disabled:opacity-40"
                      >
                        <ChevronRight className="h-4 h-4 sm:h-5 sm:w-5" />
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            </Card>
          )}
        </>
      )}

      {/* File Metadata Modal */}
      {showFileMetadataModal && (
        <FileMetadataModal
          selectedFiles={selectedFiles}
          fileMetadata={fileMetadata}
          datasetType={selectedDatasetType}
          datasetSourceSelection={uploadDatasetSourceSelection}
          datasetSourceCustom={uploadDatasetSourceCustom}
          onDatasetSourceSelectionChange={(value) => {
            setUploadDatasetSourceSelection(value)
            if (value !== 'Other') setUploadDatasetSourceCustom('')
          }}
          onDatasetSourceCustomChange={setUploadDatasetSourceCustom}
          onUpdateMetadata={updateFileMetadata}
          onCancel={() => {
            setShowFileMetadataModal(false)
            setSelectedFiles([])
            setFileMetadata(new Map())
            setUploadDatasetSourceSelection('')
            setUploadDatasetSourceCustom('')
            if (fileInputRef.current) {
              fileInputRef.current.value = ''
            }
          }}
          onConfirm={handleConfirmUpload}
          uploading={uploading}
        />
      )}


      {/* Delete Confirmation Modal */}
      {showDeleteModal && wsiToDelete && (
        <DeleteConfirmModal
          wsiToDelete={wsiToDelete}
          wsiStorageInfo={wsiStorageInfo}
          loadingStorageInfo={loadingStorageInfo}
          onCancel={() => {
            setShowDeleteModal(false)
            setWsiToDelete(null)
          }}
          onConfirm={handleConfirmDelete}
        />
      )}


      {/* Batch Delete Confirmation Modal */}
      {showBatchDeleteModal && (
        <BatchDeleteModal
          selectedIds={selectedIds}
          selectedCount={datasetToDeleteId ? datasetToDeleteFileCount : selectedIds.size}
          datasetToDeleteId={datasetToDeleteId ?? ''}
          datasetToDeleteName={datasetToDeleteName}
          deleting={deleting}
          onCancel={() => {
            setShowBatchDeleteModal(false)
            setDatasetToDeleteId(null)
            setDatasetToDeleteName('')
            setDatasetToDeleteFileCount(0)
          }}
          onConfirm={handleConfirmBatchDelete}
        />
      )}

      {/* Edit Metadata Modal */}
      {showEditModal && editingWSI && (
        <EditMetadataModal
          editingWSI={editingWSI}
          editLabel={editLabel}
          editCaseId={editCaseId}
          editAge={editAge}
          editGender={editGender}
          editEventTime={editEventTime}
          editEventStatus={editEventStatus}
          datasetType={selectedDatasetType}
          visualType={selectedDatasetVisualType}
          onEditLabelChange={setEditLabel}
          onEditCaseIdChange={setEditCaseId}
          onEditAgeChange={setEditAge}
          onEditGenderChange={setEditGender}
          onEditEventTimeChange={setEditEventTime}
          onEditEventStatusChange={setEditEventStatus}
          updating={updating}
          onCancel={() => {
            setShowEditModal(false)
            setEditingWSI(null)
          }}
          onConfirm={handleConfirmEdit}
        />
      )}

      {/* Batch Edit Metadata Modal */}
      {showBatchEditModal && (
        <BatchEditModal
          selectedCount={selectedIds.size}
          batchEditLabel={batchEditLabel}
          batchEditCaseId={batchEditCaseId}
          batchEditAge={batchEditAge}
          batchEditGender={batchEditGender}
          batchEditEventTime={batchEditEventTime}
          batchEditEventStatus={batchEditEventStatus}
          datasetType={selectedDatasetType}
          visualType={selectedDatasetVisualType}
          onBatchEditLabelChange={setBatchEditLabel}
          onBatchEditCaseIdChange={setBatchEditCaseId}
          onBatchEditAgeChange={setBatchEditAge}
          onBatchEditGenderChange={setBatchEditGender}
          onBatchEditEventTimeChange={setBatchEditEventTime}
          onBatchEditEventStatusChange={setBatchEditEventStatus}
          batchUpdating={batchUpdating}
          onCancel={() => setShowBatchEditModal(false)}
          onConfirm={handleConfirmBatchEdit}
        />
      )}

      {/* Edit Dataset Modal */}
      {editingDatasetId && (
        <DatasetEditor datasetId={editingDatasetId} initialTab={datasetEditorTab} onClose={() => setEditingDatasetId(null)} onSaved={saved => {
          const apply = (item: DatasetSummary): DatasetSummary => item.dataset_id === saved.dataset_id ? { ...item, ...saved, dataset_name: saved.name } : item
          qc.setQueriesData<{items: DatasetSummary[]}>({ queryKey: [DATASET_REPOSITORY_QUERY_KEYS.pages] }, value => value ? { ...value, items: value.items.map(apply) } : value)
          setSelectedDatasetSummary(value => value ? apply(value) : value)
          void invalidateDatasetRepositoryCache(qc); void reloadCurrentDataset()
          if (selectedDatasetId) void fetchDatasetSummary(selectedDatasetId).then(setSelectedDatasetSummary)
        }} />
      )}

      {/* Export Labels Modal */}
      {showExportModal && exportingDataset && (
        <ExportLabelsModal
          dataset={exportingDataset}
          onConfirm={handleExportConfirm}
          onCancel={handleExportCancel}
        />
      )}
    </div>
  )
}
