import { useState, useMemo, useEffect, useRef, useReducer } from 'react'
import { useDraftState, clearDraftKeys } from '../lib/hooks/useDraftState'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { readFileText, xlsxToCSV } from '../lib/utils/csvImporter'
import Papa from 'papaparse'
import { Tooltip } from '../components/ui/tooltip'
import {
  Download,
  X,
  UploadCloud,
  Trash2,
  Edit2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Plus,
  Tags,
  Activity,
  FileJson,
  Info,
  Database,
  FileImage,
  ArrowRight,
  Search
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { Checkbox } from '../components/ui/checkbox'
import { Select } from '../components/ui/select'
import { useBackgroundTask, UploadTaskFile } from '../contexts/BackgroundTaskContext'
import { useAuth } from '../contexts/AuthContext'
import { checkDuplicateFilenames, fetchDatasets, fetchDatasetSummary, downloadCSVTemplate } from '../api'
import { getWorkspaceSelection } from '../lib/workspaceSelection'
import { useDebounce } from '../lib/hooks/useDebounce'
import { useUploadText } from '../components/upload/uploadText'
import { createDataset, importDatasetLabels } from '../api/datasetCatalog'
import { updateDatasetProperties } from '../api/wsi'
import DatasetEditor from '../components/datasets/DatasetEditor'
import { useDatasetText } from '../components/datasets/text'
import { parseLabelFiles } from '../components/datasets/labelImport'
import { UploadHeader } from '../components/upload/UploadHeader'
import { UploadEmptyState } from '../components/upload/UploadEmptyState'
import { UploadAttachment } from '../components/upload/UploadAttachment'
import '../components/upload/upload.css'
import { mergeCollection } from '../components/upload/mergeCollection'
import { yieldToBrowser } from '../components/upload/fileCollector'
import { formatFileSize } from '../lib/utils/utils'

export const DUPLICATE_CHECK_BATCH_SIZE = 1000
import { ApiError } from '../api/client'
import { useToast } from '../contexts/ToastContext'
import { ALL_EXTENSIONS, PATCH_EXTENSIONS, TIF_EXTENSIONS, isSupportedName, getBaseName } from '../constants/fileTypes'
import {
  getTaskFamily,
  resolveUploadTaskType,
  inferUploadDataType,
  type TaskFamily,
  type TaskType
} from '../constants/training'
import {
  getSegmentationStem,
  mergeSegmentationJsonFiles,
  summarizeSegmentationMatches
} from '../lib/utils/segmentationUploadUtils'
import { organSources } from '../constants/wsi'
import {
  type LocalItem,
  type FileMetadata,
  type UploadMode,
  type DataLevel,
  type CollectionResult,
  type CollectionProgressSnapshot,
  defaultMetadata,
  collectItemsFromDataTransfer,
  BulkEditModal,
  DatasetConfigStep,
  SuccessStep
} from '../components/upload'


const getCsvMetadataForItem = (item: LocalItem, csvMetadataMap: Map<string, any>) => {
  if (csvMetadataMap.size === 0) return {}
  const name = item.name.toLowerCase()
  const nameNoExt = name.replace(/\.[^/.]+$/, '')
  return csvMetadataMap.get(name) || csvMetadataMap.get(nameNoExt) || {}
}

const pickResolvedMetadataValue = (uiValue: unknown, csvValue: unknown) => {
  return uiValue === undefined ? csvValue : String(uiValue).trim()
}

const getUploadModeFamily = (uploadMode: UploadMode): TaskFamily | null => {
  return (
    getTaskFamily(uploadMode) ??
    (['classification', 'survival', 'segmentation'].includes(uploadMode) ? (uploadMode as TaskFamily) : null)
  )
}

const isClassificationUploadMode = (uploadMode: UploadMode) => getUploadModeFamily(uploadMode) === 'classification'
const isSurvivalUploadMode = (uploadMode: UploadMode) => getUploadModeFamily(uploadMode) === 'survival'
const isSegmentationUploadMode = (uploadMode: UploadMode) => {
  return ['segmentation', 'detection'].includes(getUploadModeFamily(uploadMode) || '')
}

const resolveItemMetadata = (
  item: LocalItem,
  uiMetadata: Partial<FileMetadata> | undefined,
  csvMetadataMap: Map<string, any>,
  uploadMode: UploadMode
) => {
  const csvMeta = getCsvMetadataForItem(item, csvMetadataMap)

  return {
    label: pickResolvedMetadataValue(uiMetadata?.label, csvMeta.label),
    case_id: pickResolvedMetadataValue(uiMetadata?.case_id, csvMeta.case_id),
    age: pickResolvedMetadataValue(uiMetadata?.age, csvMeta.age),
    gender: pickResolvedMetadataValue(uiMetadata?.gender, csvMeta.gender),
    event_time: pickResolvedMetadataValue(uiMetadata?.event_time, csvMeta.event_time),
    event_status: pickResolvedMetadataValue(uiMetadata?.event_status, csvMeta.event_status),
    split: csvMeta.split
  }
}

const buildCsvMetadataMapFromRows = async (headers: string[], rows: string[][]) => {
  const filenameIndex = headers.indexOf('filename')
  const metadataMap = new Map<string, any>()

  for (let index = 0; index < rows.length; index++) {
    const values = rows[index]
    const filename = values[filenameIndex]
    if (!filename) continue

    const row = headers.reduce<Record<string, string>>((acc, header, index) => {
      acc[header] = values[index] ?? ''
      return acc
    }, {})
    const normalizedName = filename.trim().toLowerCase()
    if (metadataMap.has(normalizedName)) throw new Error('Duplicate filename: ' + filename)
    metadataMap.set(normalizedName, row)

    if (index % 1000 === 999) await yieldToBrowser()
  }

  return metadataMap
}

export default function RegisterPage() {
  const { error: toastError, warning: toastWarning } = useToast()
  const navigate = useNavigate()
  const { addUploadTask } = useBackgroundTask()
  const { t } = useTranslation()
  const copy = useUploadText()
  const datasetText = useDatasetText()
  const [datasetDataType, setDatasetDataType] = useState<'patch' | 'wsi'>('patch')
  const [taskTypes, setTaskTypes] = useState<TaskType[]>(['patch_classification'])
  const [description, setDescription] = useState('')
  const [datasetMetadata, setDatasetMetadata] = useState<Record<string, unknown>>({})
  const [showLabelEditor, setShowLabelEditor] = useState(false)
  const [createdDatasetId, setCreatedDatasetId] = useState<string | null>(null)
  const [labelImportBusy, setLabelImportBusy] = useState(false)
  const [taskAnnotationFiles, setTaskAnnotationFiles] = useState<Partial<Record<TaskType, File>>>({})
  const { user, isAdmin } = useAuth()
  const location = useLocation()
  const workspaceId = getWorkspaceSelection().workspaceId

  // Upload mode state (classification or survival)
  const [uploadMode, setUploadMode] = useDraftState<UploadMode>('draft:upload:uploadMode', 'classification')
  // Aggregation level state (case-level or file-level)
  const [dataLevel, setDataLevel] = useDraftState<DataLevel>('draft:upload:dataLevel', 'file')

  // Dataset name (required for grouping files)
  const [datasetName, setDatasetName] = useDraftState<string>('draft:upload:datasetName', '')
  // Dataset ID (UUID) - only set when using existing dataset or passed from navigation
  const [datasetId, setDatasetId] = useState<string | null>(() => location.state?.datasetId || null)
  const [isPublic, setIsPublic] = useDraftState<boolean>('draft:upload:isPublic', false)
  const [datasetSourceSelection, setDatasetSourceSelection] = useDraftState<string>(
    'draft:upload:datasetSourceSelection',
    ''
  )
  const [datasetSourceCustom, setDatasetSourceCustom] = useDraftState<string>('draft:upload:datasetSourceCustom', '')

  // Steps: 1 - Dataset Name, 2 - File Upload
  const [step, setStep] = useState(1)
  const datasetSearch = useDebounce(datasetName.trim(), 250)
  const datasetsQuery = useQuery({
    queryKey: ['upload-datasets', user?.id, isAdmin, workspaceId, datasetSearch],
    queryFn: () =>
      fetchDatasets(undefined, {
        search: datasetSearch,
        page_size: 20,
        purpose: 'upload'
      }),
    staleTime: 30000
  })
  const selectedDataset = useQuery({
    queryKey: ['upload-dataset', user?.id, isAdmin, workspaceId, datasetId],
    queryFn: () => fetchDatasetSummary(datasetId!, 'upload'),
    enabled: !!datasetId,
    initialData: () => datasetsQuery.data?.items.find((item) => item.dataset_id === datasetId)
  })
  const existingDatasets =
    datasetsQuery.data?.items.filter((dataset) => dataset.dataset_id && (isAdmin || dataset.user_id === user?.id)) || []
  const currentDataset =
    selectedDataset.data && (isAdmin || selectedDataset.data.user_id === user?.id) ? selectedDataset.data : undefined
  // Toggle for Dataset Splits Configuration visibility
  const [showSplitConfig, setShowSplitConfig] = useState(false)

  // Checking for initial dataset from navigation state
  const fromAIChat = (location.state as { fromAIChat?: boolean } | null)?.fromAIChat === true
  // biome-ignore lint/correctness/useExhaustiveDependencies: setDatasetName/setUploadMode/setDataLevel are stable draft setters; location is the only meaningful trigger
  useEffect(() => {
    if (location.state) {
      if (location.state.datasetName) {
        setDatasetName(location.state.datasetName)
      }
      if (location.state.datasetId) {
        setDatasetId(location.state.datasetId)
      }
      if (location.state.taskTypes?.length) {
        setTaskTypes(location.state.taskTypes)
        setUploadMode(location.state.taskTypes[0])
        setDatasetDataType(location.state.taskTypes[0].startsWith('wsi_') ? 'wsi' : 'patch')
      }
      if (location.state.description) setDescription(location.state.description)
      if (location.state.metadata) setDatasetMetadata(location.state.metadata)
      if (location.state.dataType) setDatasetDataType(location.state.dataType)
      if (location.state.isPublic !== undefined) setIsPublic(location.state.isPublic)
      if (location.state.sourceOrgan) {
        setDatasetSourceSelection(
          organSources.includes(location.state.sourceOrgan) ? location.state.sourceOrgan : 'Other'
        )
        setDatasetSourceCustom(location.state.sourceOrgan)
      }
      // Single-task navigation is also an explicit selection, never inferred from labels.
      if (location.state.uploadMode) {
        const rawMode = location.state.uploadMode as UploadMode
        const family = getUploadModeFamily(rawMode)
        setUploadMode(rawMode === 'patch_detection' ? rawMode : (family ?? rawMode))
        const canonical = resolveUploadTaskType(rawMode)
        setTaskTypes([canonical])
        setDatasetDataType(canonical.startsWith('wsi_') ? 'wsi' : 'patch')
      }
      // Accept dataLevel from AI Chat navigation (case-level or file-level)
      if (location.state.dataLevel) {
        setDataLevel(location.state.dataLevel as DataLevel)
      }
      // Accept CSV content from AI Chat navigation
      if (location.state.csvContent && location.state.csvFileName) {
        // Create a File object from the CSV content
        const blob = new Blob([location.state.csvContent], {
          type: 'text/csv'
        })
        const file = new File([blob], location.state.csvFileName, {
          type: 'text/csv'
        })
        void processSplitFile(file, location.state.uploadMode || uploadMode)
        setShowSplitConfig(true) // Auto-expand the split config section
      }
      // If we have datasetName and uploadMode from AI Chat, skip to step 2
      if (location.state.datasetId || (location.state.datasetName && location.state.uploadMode)) {
        setStep(2)
      }
      if (location.state.initialTab === 'labels') setShowLabelEditor(true)
    }
  }, [location])

  const isExistingDataset = !!datasetId
  const isAppendingDataset = isExistingDataset && datasetId !== createdDatasetId
  const currentDataType = currentDataset?.data_type || datasetDataType

  // Explicit dataset identity owns the immutable upload axes.
  useEffect(() => {
    if (!currentDataset || !datasetId) return
    setDatasetName(currentDataset.dataset_name)
    const requestedTasks: TaskType[] = location.state?.taskTypes || []
    const tasks = [...new Set([...currentDataset.task_types, ...requestedTasks])]
    setTaskTypes(tasks)
    setDatasetDataType(currentDataset.data_type)
    setDescription(currentDataset.description || '')
    setDatasetMetadata(currentDataset.metadata)
    setUploadMode(tasks.find((task) => task.includes('classification')) || tasks[0])
    setDataLevel(currentDataset.aggregation_level)
    const source = currentDataset.source_organ || ''
    setDatasetSourceSelection(organSources.includes(source) ? source : source ? 'Other' : '')
    setDatasetSourceCustom(source)
  }, [currentDataset, datasetId])

  // State
  const [localItems, setLocalItems] = useState<LocalItem[]>([])
  const selectedFileSize = useMemo(
    () =>
      localItems.reduce(
        (total, item) =>
          total + (item.file?.size || 0) + (item.associatedFiles || []).reduce((size, file) => size + file.size, 0),
        0
      ),
    [localItems]
  )
  const itemsRef = useRef(localItems)
  itemsRef.current = localItems
  const localMetadata = useRef(new Map<string, Partial<FileMetadata>>()).current
  const [metadataVersion, refreshMetadata] = useReducer((value) => value + 1, 0)
  const [isDragging, setIsDragging] = useState(false)
  const [showValidation, setShowValidation] = useState(false)
  const [skippedDuplicateCount, setSkippedDuplicateCount] = useState(0) // Count of skipped duplicate files
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [collectionProgress, setCollectionProgress] = useState<CollectionProgressSnapshot | null>(null)
  const [isValidatingMetadata, setIsValidatingMetadata] = useState(false)
  const submissionLock = useRef(false)
  const collectionLock = useRef(false)
  const collectionVersion = useRef(0)
  const collectionAbort = useRef<AbortController>()
  useEffect(
    () => () => {
      collectionVersion.current++
      collectionAbort.current?.abort()
    },
    []
  )
  const csvVersion = useRef(0)
  const [splitFile, setSplitFile] = useState<File | null>(null)
  const [splitMetadata, setSplitMetadata] = useState<Map<string, any>>(new Map())

  // Sub-selection for bulk actions
  const selectedItems = useRef(new Set<string>()).current
  const [, refreshSelection] = useReducer((value) => value + 1, 0)
  const setSelectedItems = (update: Set<string> | ((previous: Set<string>) => Set<string>)) => {
    const next = typeof update === 'function' ? update(selectedItems) : update
    if (next !== selectedItems) {
      selectedItems.clear()
      for (const key of next) selectedItems.add(key)
    }
    refreshSelection()
  }
  const [showBulkEdit, setShowBulkEdit] = useState(false)

  // Pending associated data for MRXS/TMAP (waiting to be matched with main files)
  const [pendingMrxsFolders, setPendingMrxsFolders] = useState<Map<string, File[]>>(new Map()) // folderName -> files
  const [pendingTmapDtFiles, setPendingTmapDtFiles] = useState<Map<string, File[]>>(new Map()) // baseName -> dt files

  // Segmentation: track which images have matched JSON mask files (key = item key)
  const [matchedMasks, setMatchedMasks] = useState<Set<string>>(new Set())
  // Segmentation: JSON stems that arrived without a matching image yet (for retroactive matching)
  const [pendingJsonStems, setPendingJsonStems] = useState<Set<string>>(new Set())
  const [segmentationJsonFiles, setSegmentationJsonFiles] = useState<Map<string, File>>(new Map())
  const [segmentationDuplicateJsonStems, setSegmentationDuplicateJsonStems] = useState<Set<string>>(new Set())

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1)
  const [fileFilter, setFileFilter] = useState<'all' | 'missing-label'>('all')
  const [highlightedItemKey, setHighlightedItemKey] = useState<string | null>(null)
  const [itemsPerPage, setItemsPerPage] = useState(10)
  const [fileSearch, setFileSearch] = useState('')
  const search = useDebounce(fileSearch.trim().toLocaleLowerCase(), 180)

  // Batch metadata state (temporary for the modal)
  const [batchMetadata, setBatchMetadata] = useState<FileMetadata>({
    ...defaultMetadata
  })

  const getResolvedDatasetSource = () => {
    if (datasetSourceSelection === 'Other') {
      return datasetSourceCustom.trim()
    }
    return datasetSourceSelection.trim()
  }

  const tableContainerRef = useRef<HTMLDivElement>(null)
  const labelInputRefs = useRef<Map<string, HTMLInputElement | null>>(new Map())

  const itemIndex = useMemo(() => new Map(localItems.map((item) => [item.key, item])), [localItems])
  const missingLabels = useMemo(() => {
    if (!isClassificationUploadMode(uploadMode)) return new Map<string, LocalItem>()
    return new Map(
      localItems
        .filter((item) => {
          const meta = resolveItemMetadata(item, localMetadata.get(item.key), splitMetadata, uploadMode)
          return !String(meta.label ?? '').trim()
        })
        .map((item) => [item.key, item])
    )
  }, [localItems, splitMetadata, uploadMode])
  const missingLabelCount = missingLabels.size
  const missingLabelItems = useMemo(() => {
    if (fileFilter === 'missing-label') return Array.from(missingLabels.values())
    const first: LocalItem[] = []
    for (const item of missingLabels.values()) {
      first.push(item)
      if (first.length === 5) break
    }
    return first
  }, [missingLabels, metadataVersion, fileFilter])
  const searchItems = useMemo(
    () => (search ? localItems.filter((item) => item.name.toLocaleLowerCase().includes(search)) : localItems),
    [localItems, search]
  )
  const displayedItems = useMemo(
    () =>
      fileFilter === 'missing-label'
        ? search
          ? missingLabelItems.filter((item) => item.name.toLocaleLowerCase().includes(search))
          : missingLabelItems
        : searchItems,
    [fileFilter, missingLabelItems, searchItems, search]
  )
  const totalPages = Math.ceil(displayedItems.length / itemsPerPage)
  const paginatedItems = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage
    return displayedItems.slice(start, start + itemsPerPage)
  }, [displayedItems, currentPage, itemsPerPage])
  const showMissingLabelAlert = isClassificationUploadMode(uploadMode) && missingLabelCount > 0
  const showMissingLabelChips = missingLabelCount <= 5

  useEffect(() => {
    if (currentPage > totalPages && totalPages > 0) {
      setCurrentPage(totalPages)
    } else if (totalPages === 0 && currentPage !== 1) {
      setCurrentPage(1)
    }
  }, [totalPages, currentPage])

  useEffect(() => {
    if (fileFilter === 'missing-label' && missingLabelCount === 0) {
      setFileFilter('all')
    }
  }, [fileFilter, missingLabelCount])
  useEffect(() => {
    setCurrentPage(1)
  }, [search, itemsPerPage])
  useEffect(() => {
    tableContainerRef.current?.scrollTo?.({ top: 0 })
  }, [currentPage])

  useEffect(() => {
    if (!highlightedItemKey) return
    labelInputRefs.current.get(highlightedItemKey)?.focus()
  }, [highlightedItemKey, paginatedItems])

  useEffect(() => {
    if (!isSegmentationUploadMode(uploadMode)) {
      setMatchedMasks(new Set())
      setPendingJsonStems(new Set())
      return
    }

    const { matchedStems, orphanJsonStems } = summarizeSegmentationMatches(localItems, segmentationJsonFiles)
    setMatchedMasks(
      new Set(localItems.filter((item) => matchedStems.has(getSegmentationStem(item.name))).map((item) => item.key))
    )
    setPendingJsonStems(new Set(orphanJsonStems))
  }, [localItems, segmentationJsonFiles, uploadMode])

  const filePicker = useRef<HTMLInputElement>(null)
  const folderPicker = useRef<HTMLInputElement>(null)
  const pickFiles = async (input: HTMLInputElement) => {
    const files = Array.from(input.files || [])
    input.value = ''
    await handleCollectedDrop(
      { items: [], files } as unknown as DataTransfer,
      'uploadPage.skippedUnsupportedFilesShort'
    )
  }
  const segmentationJsonOnlyAppend =
    isSegmentationUploadMode(uploadMode) && !!datasetId && localItems.length === 0 && segmentationJsonFiles.size > 0
  const readyToUploadCount = segmentationJsonOnlyAppend ? segmentationJsonFiles.size : localItems.length
  const isCollecting = collectionProgress !== null && !collectionProgress.completed

  // --- Interaction Logic ---

  const handleCollectedDrop = async (
    dataTransfer: DataTransfer,
    unsupportedMessageKey: 'uploadPage.skippedUnsupportedFiles' | 'uploadPage.skippedUnsupportedFilesShort'
  ) => {
    if (collectionLock.current || submissionLock.current) return
    collectionLock.current = true
    collectionAbort.current = new AbortController()
    const version = collectionVersion.current
    setCollectionProgress({
      phase: 'preparing',
      totalTopLevelEntries: 0,
      processedItems: 0,
      discoveredFiles: 0,
      discoveredDirectories: 0,
      completed: false
    })

    try {
      const result = await collectItemsFromDataTransfer(dataTransfer, {
        onProgress: (progress) => setCollectionProgress({ ...progress, completed: false }),
        signal: collectionAbort.current.signal
      })

      if (result.unsupportedFileNames && result.unsupportedFileNames.length > 0) {
        if (unsupportedMessageKey === 'uploadPage.skippedUnsupportedFiles') {
          toastError(
            t(unsupportedMessageKey, {
              count: result.unsupportedFileNames.length,
              files: result.unsupportedFileNames.slice(0, 3).join(', '),
              more: result.unsupportedFileNames.length > 3 ? '...' : '',
              extensions: ALL_EXTENSIONS.join(', ')
            })
          )
        } else {
          toastError(
            t(unsupportedMessageKey, {
              count: result.unsupportedFileNames.length,
              files: result.unsupportedFileNames.slice(0, 3).join(', '),
              more: result.unsupportedFileNames.length > 3 ? '...' : ''
            })
          )
        }
      }

      if (version === collectionVersion.current) await processCollectionResult(result, version)
    } catch (error) {
      if (version !== collectionVersion.current || collectionAbort.current?.signal.aborted) return
      console.error('File collection error:', error)
      setSubmitError(t('chatComponents.datasetRegistration.fileProcessingError'))
    } finally {
      collectionLock.current = false
      setCollectionProgress(null)
    }
  }

  const processCollectionResult = async (result: CollectionResult, version: number) => {
    const { items, jsonFiles } = result
    let accepted = items.filter((item) => isSupportedName(item.name))
    if (isSegmentationUploadMode(uploadMode)) {
      const rejected = accepted.filter(
        (item) =>
          inferUploadDataType({
            fileName: item.name,
            fileSize: item.file?.size
          }) !== 'patch'
      )
      if (rejected.length) {
        setSubmitError(
          getUploadModeFamily(uploadMode) === 'detection' ? t('detection.patchOnly') : copy('segmentationOnly')
        )
        const rejectedKeys = new Set(rejected.map((item) => item.key))
        accepted = accepted.filter((item) => !rejectedKeys.has(item.key))
      }
    }
    if (items.length > 0) {
      if (datasetId && accepted.length > 0) {
        try {
          const allFilenames = accepted.map((item) => item.name)
          const duplicates = new Set<string>()
          // Four bounded requests in flight; avoid hundreds of serial round trips.
          for (let i = 0; i < allFilenames.length; i += DUPLICATE_CHECK_BATCH_SIZE * 4) {
            if (version !== collectionVersion.current) return
            const results = await Promise.all(
              Array.from(
                {
                  length: Math.min(4, Math.ceil((allFilenames.length - i) / DUPLICATE_CHECK_BATCH_SIZE))
                },
                (_, offset) =>
                  checkDuplicateFilenames(
                    allFilenames.slice(
                      i + offset * DUPLICATE_CHECK_BATCH_SIZE,
                      i + (offset + 1) * DUPLICATE_CHECK_BATCH_SIZE
                    ),
                    datasetId
                  )
              )
            )
            for (const result of results) for (const name of result.duplicates) duplicates.add(name)
            await yieldToBrowser()
          }
          if (duplicates.size > 0) {
            accepted = accepted.filter((item) => !duplicates.has(item.name))
            setSkippedDuplicateCount((prev) => prev + duplicates.size)
          }
        } catch (err) {
          console.warn('Failed to check duplicate filenames:', err)
          toastWarning(copy('duplicateCheck'))
        }
      }
    }
    if (version !== collectionVersion.current) return
    const merged = mergeCollection(
      itemsRef.current,
      { ...result, items: accepted },
      pendingMrxsFolders,
      pendingTmapDtFiles
    )
    itemsRef.current = merged.items
    setLocalItems(merged.items)
    setPendingMrxsFolders(merged.folders)
    setPendingTmapDtFiles(merged.data)
    if (isSegmentationUploadMode(uploadMode) && jsonFiles && jsonFiles.length > 0) {
      const masks = mergeSegmentationJsonFiles(segmentationJsonFiles, jsonFiles)
      setSegmentationJsonFiles(masks.jsonFilesByStem)
      if (masks.duplicateJsonStems.length > 0) {
        setSegmentationDuplicateJsonStems((prev) => new Set([...prev, ...masks.duplicateJsonStems]))
      }
    }
  }

  const handleMetadataChange = (key: string, field: string, value: string) => {
    localMetadata.set(key, { ...localMetadata.get(key), [field]: value })
    if (field === 'label') {
      if (value.trim()) missingLabels.delete(key)
      else if (itemIndex.has(key)) missingLabels.set(key, itemIndex.get(key)!)
    }
    refreshMetadata()
  }

  const removeLocalItem = (key: string) => {
    setLocalItems((prev) => prev.filter((i) => i.key !== key))
    localMetadata.delete(key)
    refreshMetadata()
    setSelectedItems((prev) => {
      prev.delete(key)
      return prev
    })
  }

  const removeSelectedItems = () => {
    setLocalItems(localItems.filter((i) => !selectedItems.has(i.key)))
    selectedItems.forEach((k) => localMetadata.delete(k))
    refreshMetadata()
    setSelectedItems(new Set())
  }

  const jumpToMissingLabelItem = (target: LocalItem) => {
    setFileSearch('')
    setFileFilter('all')
    const targetIndex = localItems.findIndex((item) => item.key === target.key)
    if (targetIndex >= 0) {
      setCurrentPage(Math.floor(targetIndex / itemsPerPage) + 1)
    }
    setHighlightedItemKey(target.key)
  }

  const toggleMissingLabelFilter = () => {
    setFileFilter((current) => (current === 'missing-label' ? 'all' : 'missing-label'))
    setCurrentPage(1)
  }

  // --- Bulk Edit Logic ---

  const handleApplyBulkEdit = () => {
    selectedItems.forEach((key) => {
      const item = itemIndex.get(key)
      if (!item) return
      const current = localMetadata.get(key) || {}
      localMetadata.set(key, {
        ...current,
        label: isClassificationUploadMode(uploadMode) ? batchMetadata.label || current.label : current.label,
        case_id: batchMetadata.case_id || current.case_id,
        age: batchMetadata.age || current.age,
        gender: batchMetadata.gender || current.gender,
        event_time: batchMetadata.event_time || current.event_time,
        event_status: batchMetadata.event_status || current.event_status
      })
      if (batchMetadata.label.trim()) missingLabels.delete(key)
    })
    refreshMetadata()
    setBatchMetadata({ ...defaultMetadata })
    setShowBulkEdit(false)
  }

  // --- Upload Logic ---

  const handleUpload = async () => {
    if (submissionLock.current || collectionLock.current || isValidatingMetadata) return
    if (datasetId && (!currentDataset || selectedDataset.isError)) {
      setSubmitError(copy('datasetFailed'))
      return
    }
    if (splitFileError) {
      setSubmitError(splitFileError)
      return
    }
    submissionLock.current = true
    setIsImporting(true)
    try {
      await submitUpload()
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error))
    } finally {
      submissionLock.current = false
      setIsImporting(false)
    }
  }

  const submitUpload = async () => {
    // Check if we have files OR a split file to upload
    if (
      localItems.length === 0 &&
      !splitFile &&
      !segmentationJsonOnlyAppend &&
      !Object.keys(taskAnnotationFiles).length
    )
      return
    setShowValidation(true)
    setSubmitError(null)

    // Validate dataset name is required
    if (!datasetName.trim()) {
      setSubmitError(t('uploadPage.datasetNameRequired'))
      return
    }
    if (
      !datasetId &&
      existingDatasets.some(
        (dataset) =>
          dataset.user_id === user?.id && dataset.dataset_name.toLowerCase() === datasetName.trim().toLowerCase()
      )
    ) {
      setSubmitError(copy('chooseDataset'))
      setStep(1)
      return
    }

    // --- CSV BINDING STRATEGY ---
    // 1. Existing dataset with no new local files: upload raw CSV so backend updates existing records.
    // 2. New dataset or appended local files: parse CSV on client and bind only to local items.

    const csvMetadataMap = splitMetadata
    let targetDatasetId = datasetId
    if (!targetDatasetId) {
      const saved = await createDataset({
        name: datasetName.trim(),
        data_type: datasetDataType,
        aggregation_level: dataLevel,
        task_types: taskTypes,
        description,
        metadata: datasetMetadata,
        source_organ: getResolvedDatasetSource(),
        is_public: isPublic
      })
      targetDatasetId = saved.dataset_id
      setCreatedDatasetId(saved.dataset_id)
      setDatasetId(saved.dataset_id)
    } else if (currentDataset && taskTypes.some((task) => !currentDataset.task_types.includes(task))) {
      await updateDatasetProperties(targetDatasetId, {
        task_types: taskTypes,
        revision: currentDataset.revision
      })
    }

    // Case 1: Existing Dataset CSV-only update - Upload CSV separately
    if (
      (splitFile || Object.keys(taskAnnotationFiles).length) &&
      localItems.length === 0 &&
      !segmentationJsonOnlyAppend
    ) {
      const fresh = await fetchDatasetSummary(targetDatasetId, 'upload')
      await importDatasetLabels(targetDatasetId, {
        revision: fresh.revision,
        task_types: taskTypes,
        ...(await parseLabelFiles(splitFile, taskAnnotationFiles))
      })
      setStep(3)
      return
    }

    if (readyToUploadCount === 0) return

    if (isSegmentationUploadMode(uploadMode)) {
      const invalidSegmentationItems = localItems.filter(
        (item) =>
          item.type !== 'standard' ||
          inferUploadDataType({
            fileName: item.name,
            fileSize: item.file?.size
          }) !== 'patch'
      )
      if (invalidSegmentationItems.length > 0) {
        setSubmitError(
          getUploadModeFamily(uploadMode) === 'detection' ? t('detection.patchOnly') : copy('segmentationOnly')
        )
        return
      }

      const { duplicateImageStems } = summarizeSegmentationMatches(localItems, segmentationJsonFiles)

      if (segmentationDuplicateJsonStems.size > 0) {
        setSubmitError(copy('duplicateMasks'))
        return
      }
      if (duplicateImageStems.length > 0) {
        setSubmitError(copy('duplicateMasks'))
        return
      }
      if (!datasetId && localItems.length === 0) {
        setSubmitError('Segmentation upload requires at least one image file when creating a new dataset.')
        return
      }
    }

    const resolvedDatasetSource = getResolvedDatasetSource()

    // Prepare items with resolved metadata (UI + CSV)
    const itemsWithMeta: {
      item: LocalItem
      finalMeta: ReturnType<typeof resolveItemMetadata>
    }[] = []
    const names = new Set<string>(),
      types = new Set<string>(),
      cases = new Map<string, string>()
    for (let i = 0; i < localItems.length; i++) {
      const item = localItems[i]
      const finalMeta = resolveItemMetadata(item, localMetadata.get(item.key), csvMetadataMap, uploadMode)
      const name = item.name.toLowerCase()
      if (names.has(name)) {
        setSubmitError(copy('duplicateNames'))
        return
      }
      names.add(name)
      if (item.missingAssociated && !item.path) {
        setSubmitError(copy('missingAssociated'))
        return
      }
      const type = inferUploadDataType({
        fileName: item.name,
        fileSize: item.file?.size,
        dataType: /\.tiff?$/i.test(item.name) ? currentDataType : undefined
      })
      types.add(type)
      if (
        types.size > 1 ||
        (currentDataType && type !== currentDataType) ||
        (type === 'patch' && (dataLevel === 'case' || isSurvivalUploadMode(uploadMode)))
      ) {
        setSubmitError(copy('mixedTypes'))
        return
      }
      if (dataLevel === 'case' && !String(finalMeta.case_id ?? '').trim()) {
        setSubmitError(copy('missingCase'))
        return
      }
      if (finalMeta.age && (!Number.isInteger(Number(finalMeta.age)) || Number(finalMeta.age) < 0)) {
        setSubmitError(copy('invalidAge'))
        return
      }
      const split = String(finalMeta.split || '')
        .trim()
        .toLowerCase()
      if (split && !['train', 'val', 'test'].includes(split)) {
        setSubmitError(copy('invalidSplit'))
        return
      }
      if (finalMeta.case_id && split) {
        const id = String(finalMeta.case_id)
        if (cases.has(id) && cases.get(id) !== split) {
          setSubmitError(copy('invalidSplit'))
          return
        }
        cases.set(id, split)
      }
      itemsWithMeta.push({ item, finalMeta: { ...finalMeta, split } })
      if (i % 500 === 499) await yieldToBrowser()
    }

    // Outcomes may be appended later. Supplied outcomes must be complete pairs.
    if (
      itemsWithMeta.some(
        ({ finalMeta }) =>
          (String(finalMeta.event_time ?? '').trim() !== '') !== (String(finalMeta.event_status ?? '').trim() !== '')
      )
    ) {
      setSubmitError(copy('invalidSurvival'))
      return
    }
    if (
      itemsWithMeta.some(
        ({ finalMeta }) =>
          String(finalMeta.event_time ?? '').trim() !== '' &&
          (!Number.isFinite(Number(finalMeta.event_time)) ||
            Number(finalMeta.event_time) < 0 ||
            !['0', '1'].includes(String(finalMeta.event_status)))
      )
    ) {
      setSubmitError(copy('invalidSurvival'))
      return
    }

    // Prepare files for background upload task
    const uploadFiles: UploadTaskFile[] = segmentationJsonOnlyAppend
      ? Array.from(segmentationJsonFiles.values()).map((file) => ({
          key: `seg-json-${file.name}-${file.size}`,
          name: file.name,
          file,
          metadata: {
            dataset_id: datasetId ?? undefined,
            task_type: resolveUploadTaskType(uploadMode, {
              fileName: file.name,
              fileSize: file.size,
              dataType: currentDataType
            })
          }
        }))
      : itemsWithMeta.map(({ item, finalMeta }) => {
          const age = finalMeta.age ? parseInt(String(finalMeta.age)) : undefined
          const eventTime = finalMeta.event_time ? parseFloat(String(finalMeta.event_time)) : undefined
          const eventStatus = finalMeta.event_status ? parseInt(String(finalMeta.event_status)) : undefined
          const matchedSegmentationJson = isSegmentationUploadMode(uploadMode)
            ? segmentationJsonFiles.get(getSegmentationStem(item.name))
            : undefined
          const canonicalTaskType = resolveUploadTaskType(uploadMode, {
            fileName: item.name,
            fileSize: item.file?.size ?? null,
            dataType: currentDataType
          })

          return {
            key: item.key,
            name: item.name,
            file: item.file,
            path: item.path,
            metadata: {
              dataset_id: targetDatasetId,
              dataset_name: datasetId ? undefined : datasetName.trim(),
              source_organ: datasetId ? undefined : resolvedDatasetSource || undefined,
              aggregation_level: datasetId ? undefined : dataLevel,
              is_public: datasetId ? undefined : isPublic,
              task_type: canonicalTaskType,
              label: finalMeta.label ? String(finalMeta.label) : undefined,
              case_id: finalMeta.case_id ? String(finalMeta.case_id) : undefined,
              age,
              gender: finalMeta.gender ? String(finalMeta.gender) : undefined,
              event_time: eventTime,
              event_status: eventStatus,
              split: finalMeta.split || undefined
            },
            associatedFiles:
              isSegmentationUploadMode(uploadMode) && matchedSegmentationJson
                ? [matchedSegmentationJson]
                : item.associatedFiles
          }
        })

    setIsImporting(true)
    try {
      const labels = await parseLabelFiles(splitFile, taskAnnotationFiles)
      const resolvedRows = new Map(itemsWithMeta.map(({ item, finalMeta }) => [item.name, finalMeta]))
      labels.rows = labels.rows
        .filter((row) => resolvedRows.has(String(row.filename)))
        .map((row) => {
          const resolved = resolvedRows.get(String(row.filename))!
          const values = { ...row }
          for (const [key, value] of Object.entries(resolved)) {
            if (value === undefined) continue
            if (value === '' && !(key in row)) continue
            values[key] =
              value === '' ? null : ['age', 'event_time', 'event_status'].includes(key) ? Number(value) : value
          }
          return values
        })
      // Add to background task queue
      await addUploadTask(uploadFiles, {
        labels:
          splitFile || Object.keys(taskAnnotationFiles).length
            ? {
                datasetId: targetDatasetId,
                body: {
                  revision: currentDataset?.revision || 1,
                  task_types: taskTypes,
                  ...labels
                }
              }
            : undefined,
        onComplete: () => {
          // Optionally refresh WSI list when complete
        }
      })

      // Show warning about not refreshing during upload
      toastWarning(t('uploadPage.uploadingWarning'), 8000)

      // Clear the form
      resetUpload()
      navigate('/dashboard')
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && error.details === 'DATASET_NAME_ALREADY_EXISTS') {
        const message = t('uploadPage.datasetNameExistsForCurrentUser')
        toastError(message)
        setSubmitError(message)
        setIsImporting(false)
        return
      }
      setSubmitError(error instanceof Error ? error.message : String(error))
      setIsImporting(false)
    }
  }

  const resetUpload = () => {
    setTaskAnnotationFiles({})
    setDescription('')
    setDatasetMetadata({})
    setTaskTypes(['patch_classification'])
    setDatasetDataType('patch')
    setUploadMode('patch_classification')
    collectionVersion.current++
    csvVersion.current++
    collectionAbort.current?.abort()
    clearDraftKeys('draft:upload:')
    setStep(1)
    setDatasetName('')
    setDatasetId(null)
    setCreatedDatasetId(null)
    setShowLabelEditor(false)
    setIsPublic(false)
    setLocalItems([])
    itemsRef.current = []
    localMetadata.clear()
    refreshMetadata()
    setShowValidation(false)
    setSkippedDuplicateCount(0)
    setSelectedItems(new Set())
    setSubmitError(null)
    setCollectionProgress(null)
    setIsValidatingMetadata(false)
    setSplitFile(null)
    setSplitMetadata(new Map())
    setMatchedMasks(new Set())
    setPendingJsonStems(new Set())
    setSegmentationJsonFiles(new Map())
    setSegmentationDuplicateJsonStems(new Set())
    setPendingMrxsFolders(new Map())
    setPendingTmapDtFiles(new Map())
    setDatasetSourceSelection('')
    setDatasetSourceCustom('')
    setSplitFileError(null)
    setSplitUploadSuccess(null)
    setFileFilter('all')
    setFileSearch('')
    setCurrentPage(1)
  }

  // --- Selection Logic ---

  const toggleSelectAll = () => {
    if (selectedItems.size === localItems.length) {
      setSelectedItems(new Set())
    } else {
      setSelectedItems(new Set(localItems.map((i) => i.key)))
    }
  }

  const toggleSelection = (key: string) => {
    setSelectedItems((prev) => {
      if (prev.has(key)) prev.delete(key)
      else prev.add(key)
      return prev
    })
  }

  // --- Split Upload Logic ---
  const [isImporting, setIsImporting] = useState(false)

  const [splitFileError, setSplitFileError] = useState<string | null>(null)

  const processSplitFile = async (file: File, mode: UploadMode = uploadMode) => {
    if (submissionLock.current) return
    const version = ++csvVersion.current
    setSplitFile(null)
    setSplitMetadata(new Map())
    setIsValidatingMetadata(true)
    setSplitFileError(null)
    const fileName = file.name.toLowerCase()

    // Client-side validation
    try {
      let csvContent: string
      let finalFile: File = file

      if (fileName.endsWith('.xls')) {
        setSplitFileError(copy('xlsUnsupported'))
        return
      }
      if (fileName.endsWith('.xlsx')) {
        const { sheetNames, csv } = await xlsxToCSV(await file.arrayBuffer())
        if (sheetNames.length > 1) {
          setSplitFileError(t('uploadPage.excelMultipleSheets'))
          return
        }
        csvContent = csv
        finalFile = new File([csv], file.name.replace(/\.xlsx$/i, '.csv'), {
          type: 'text/csv'
        })
      } else {
        csvContent = await readFileText(file)
      }

      if (version !== csvVersion.current) return
      const parsed =
        typeof Worker === 'undefined'
          ? Papa.parse<string[]>(csvContent, { skipEmptyLines: 'greedy' })
          : await new Promise<Papa.ParseResult<string[]>>((resolve) =>
              Papa.parse<string[]>(csvContent, {
                skipEmptyLines: 'greedy',
                worker: true,
                complete: resolve
              })
            )
      const rows = parsed.data as string[][]
      if (version !== csvVersion.current) return
      if (parsed.errors.length || rows.some((row) => row.length !== rows[0]?.length)) {
        setSplitFileError(copy('invalidCsv'))
        return
      }

      if (rows.length < 2) {
        setSplitFileError(t('uploadPage.fileEmptyOrNoData'))
        return
      }

      const headers = rows[0].map((h) =>
        h
          .replace(/^\uFEFF/, '')
          .toLowerCase()
          .trim()
      )
      if (new Set(headers).size !== headers.length) {
        setSplitFileError(copy('invalidCsv'))
        return
      }

      // Validate required columns based on upload mode
      if (!headers.includes('filename')) {
        setSplitFileError(t('uploadPage.missingFilenameColumn'))
        return
      }

      if (headers.includes('event_time') !== headers.includes('event_status')) {
        setSplitFileError(copy('invalidSurvival'))
        return
      }

      const metadata = await buildCsvMetadataMapFromRows(headers, rows.slice(1))
      if (version !== csvVersion.current) return
      setSplitMetadata(metadata)
      setSplitFile(finalFile)
    } catch (err) {
      if (version !== csvVersion.current) return
      setSplitMetadata(new Map())
      setSplitFileError(t('uploadPage.failedReadFile', { error: String(err) }))
    } finally {
      if (version === csvVersion.current) setIsValidatingMetadata(false)
    }
  }

  const clearSplitFile = () => {
    csvVersion.current++
    setIsValidatingMetadata(false)
    setSplitFileError(null)
    setSplitFile(null)
    setSplitMetadata(new Map())
  }

  const handleSplitFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      await processSplitFile(e.target.files[0])
    }
    e.target.value = ''
  }

  const handleCsvDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    const files = Array.from(e.dataTransfer.files)
    const csvFile = files.find((f) => {
      const name = f.name.toLowerCase()
      return name.endsWith('.csv') || name.endsWith('.xlsx') || name.endsWith('.xls')
    })
    if (csvFile) {
      await processSplitFile(csvFile)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      await downloadCSVTemplate(resolveUploadTaskType(uploadMode, { dataType: currentDataType }))
    } catch (e) {
      console.error('Failed to download template', e)
      toastError(e instanceof Error ? e.message : t('uploadPage.failedDownloadTemplate'))
    }
  }

  const [splitUploadSuccess, setSplitUploadSuccess] = useState<string | null>(null)

  // --- Render ---

  return (
    <div className="upload-page">
      <fieldset disabled={isImporting || labelImportBusy} className="contents">
        {submitError && step === 1 && (
          <p role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {submitError}
          </p>
        )}
        {splitFileError && step === 1 && (
          <p role="alert" className="mb-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {splitFileError}
          </p>
        )}
        <input
          ref={filePicker}
          type="file"
          multiple
          accept={[
            ...(isSegmentationUploadMode(uploadMode) ? [...PATCH_EXTENSIONS, ...TIF_EXTENSIONS] : ALL_EXTENSIONS),
            '.json'
          ].join(',')}
          className="hidden"
          onChange={(event) => void pickFiles(event.currentTarget)}
        />
        <input
          ref={folderPicker}
          type="file"
          multiple
          {...{ webkitdirectory: '' }}
          className="hidden"
          onChange={(event) => void pickFiles(event.currentTarget)}
        />
        {/* Bulk Edit Modal */}
        {showBulkEdit && (
          <BulkEditModal
            uploadMode={uploadMode}
            selectedCount={selectedItems.size}
            batchMetadata={batchMetadata}
            onBatchMetadataChange={setBatchMetadata}
            onApply={handleApplyBulkEdit}
            onClose={() => setShowBulkEdit(false)}
          />
        )}

        {/* Steps */}
        {step === 1 ? (
          <DatasetConfigStep
            datasetName={datasetName}
            onDatasetNameChange={(name) => {
              setDatasetName(name)
              setDatasetId(null)
              collectionVersion.current++
            }}
            dataType={datasetDataType}
            onDataTypeChange={(value) => {
              setDatasetDataType(value)
              setTaskTypes([value === 'patch' ? 'patch_classification' : 'wsi_classification'])
              setUploadMode(value === 'patch' ? 'patch_classification' : 'wsi_classification')
              if (value === 'patch') setDataLevel('file')
            }}
            taskTypes={taskTypes}
            onTaskTypesChange={(value) => {
              setTaskTypes(value)
              if (value.length) setUploadMode(value[0])
            }}
            description={description}
            onDescriptionChange={setDescription}
            metadata={datasetMetadata}
            onMetadataChange={setDatasetMetadata}
            dataLevel={dataLevel}
            onDataLevelChange={setDataLevel}
            datasetSourceSelection={datasetSourceSelection}
            datasetSourceCustom={datasetSourceCustom}
            onDatasetSourceSelectionChange={(value) => {
              setDatasetSourceSelection(value)
              if (value !== 'Other') setDatasetSourceCustom('')
            }}
            onDatasetSourceCustomChange={setDatasetSourceCustom}
            isExistingDataset={isExistingDataset}
            existingDatasets={existingDatasets}
            showOwners={isAdmin}
            onSelectDataset={(id) => {
              setDatasetId(id)
              collectionVersion.current++
            }}
            loading={
              datasetsQuery.isFetching ||
              (!!datasetId && selectedDataset.isLoading) ||
              datasetSearch !== datasetName.trim()
            }
            error={datasetsQuery.isError || (!!datasetId && selectedDataset.isError)}
            onRetry={() => {
              void datasetsQuery.refetch()
              if (datasetId) void selectedDataset.refetch()
            }}
            isPublic={isPublic}
            saving={isImporting}
            onIsPublicChange={setIsPublic}
            onNext={async () => {
              const trimmedDatasetName = datasetName.trim()
              if (
                trimmedDatasetName &&
                !isExistingDataset &&
                existingDatasets.some(
                  (dataset) =>
                    dataset.user_id === user?.id &&
                    dataset.dataset_name.toLowerCase() === trimmedDatasetName.toLowerCase()
                )
              ) {
                toastError(copy('chooseDataset'))
                return
              }
              setIsImporting(true)
              try {
                if (datasetId && currentDataset) {
                  await updateDatasetProperties(datasetId, {
                    task_types: taskTypes,
                    description,
                    metadata: datasetMetadata,
                    source: getResolvedDatasetSource(),
                    revision: currentDataset.revision
                  })
                  await selectedDataset.refetch()
                } else {
                  const saved = await createDataset({
                    name: trimmedDatasetName,
                    data_type: datasetDataType,
                    aggregation_level: dataLevel,
                    task_types: taskTypes,
                    description,
                    metadata: datasetMetadata,
                    source_organ: getResolvedDatasetSource(),
                    is_public: isPublic
                  })
                  setDatasetId(saved.dataset_id)
                  setCreatedDatasetId(saved.dataset_id)
                }
                setStep(2)
              } catch (error) {
                setSubmitError(String(error))
              } finally {
                setIsImporting(false)
              }
            }}
            onBack={() => navigate('/dashboard')}
          />
        ) : step === 3 ? (
          <SuccessStep
            datasetName={datasetName}
            splitUploadSuccess={splitUploadSuccess}
            fromAIChat={fromAIChat}
            onNavigate={() => navigate('/dashboard')}
            onReset={resetUpload}
          />
        ) : (
          <>
            <UploadHeader
              step={2}
              append={isAppendingDataset}
              onBack={() => navigate('/dashboard')}
              onSetup={() => setStep(1)}
            />
            <div className="upload-context">
              <span className="upload-context-icon">
                <Database size={20} strokeWidth={1.5} />
              </span>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2>{datasetName}</h2>
                  {isAppendingDataset && (
                    <span className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500">
                      {t('uploadPage.appendingData')}
                    </span>
                  )}
                </div>
                <p>
                  {datasetText(currentDataType)} ·{' '}
                  {taskTypes.map((task) => datasetText(getTaskFamily(task)!)).join(' / ')}
                  {isAppendingDataset && currentDataset
                    ? ` · ${copy('existingSamples')} ${currentDataset.file_count.toLocaleString()}`
                    : ''}
                </p>
              </div>
              <div className="upload-context-actions">
                <Button variant="ghost" size="sm" onClick={() => setStep(1)}>
                  <Edit2 size={13} className="mr-1.5" />
                  {t('uploadPage.changeInfo')}
                </Button>
              </div>
            </div>
            {isAppendingDataset && (
              <div className="upload-append-modes" aria-label={copy('appendTitle')}>
                <button type="button" aria-pressed={!showLabelEditor} onClick={() => setShowLabelEditor(false)}>
                  <FileImage size={20} strokeWidth={1.5} />
                  <span>
                    <strong>{copy('appendImages')}</strong>
                    <small>{copy('appendImagesHint')}</small>
                  </span>
                </button>
                <button type="button" aria-pressed={showLabelEditor} onClick={() => setShowLabelEditor(true)}>
                  <Tags size={20} strokeWidth={1.5} />
                  <span>
                    <strong>{copy('appendLabels')}</strong>
                    <small>{copy('appendLabelsHint')}</small>
                  </span>
                </button>
              </div>
            )}
            {isAppendingDataset && datasetId && (
              <div hidden={!showLabelEditor}>
                <DatasetEditor
                  key={datasetId}
                  datasetId={datasetId}
                  initialTab="labels"
                  embedded
                  onBusyChange={setLabelImportBusy}
                  onClose={() => setShowLabelEditor(false)}
                  onSaved={() => {
                    void selectedDataset.refetch()
                  }}
                />
              </div>
            )}
            {!showLabelEditor && (
              <>
                {isCollecting && collectionProgress && (
                  <div className="flex-none mb-2 px-2 sm:px-0">
                    <div className="rounded-xl border border-slate-200 bg-white px-4 py-4">
                      <div className="flex items-start gap-3">
                        <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-500">
                          <UploadCloud className="h-5 w-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                            <div>
                              <p className="font-medium text-slate-900">{t('uploadPage.collectionProgressTitle')}</p>
                              <p className="mt-1 text-sm text-slate-600">
                                {t('uploadPage.collectionProgressDescription')}
                              </p>
                            </div>
                            <span className="rounded-md bg-slate-50 px-2 py-1 text-xs text-slate-500">
                              {t(`uploadPage.collectionPhase.${collectionProgress.phase}`)}
                            </span>
                          </div>
                          <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
                            <span>
                              {t('uploadPage.collectionTopLevelEntries', {
                                count: collectionProgress.totalTopLevelEntries
                              })}
                            </span>
                            <span>
                              {t('uploadPage.collectionFilesDiscovered', {
                                count: collectionProgress.discoveredFiles
                              })}
                            </span>
                            <span>
                              {t('uploadPage.collectionFoldersDiscovered', {
                                count: collectionProgress.discoveredDirectories
                              })}
                            </span>
                          </div>
                          {collectionProgress.currentDirectoryName && (
                            <p className="mt-2 text-xs text-slate-500">
                              {t('uploadPage.collectionCurrentDirectory', {
                                name: collectionProgress.currentDirectoryName
                              })}
                            </p>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {localItems.length === 0 && !segmentationJsonOnlyAppend ? (
                  <UploadEmptyState
                    dataType={currentDataType}
                    dragging={isDragging}
                    busy={isCollecting || isImporting}
                    onDragging={setIsDragging}
                    onDrop={(data) => handleCollectedDrop(data, 'uploadPage.skippedUnsupportedFiles')}
                    onFiles={() => filePicker.current?.click()}
                    onFolder={() => folderPicker.current?.click()}
                  />
                ) : (
                  <div className="upload-files-panel">
                    <div className="upload-file-toolbar">
                      <h3>
                        {copy('selectedFiles')}
                        <span className="upload-count">
                          {readyToUploadCount.toLocaleString()}
                          {selectedFileSize > 0 ? ` · ${formatFileSize(selectedFileSize)}` : ''}
                        </span>
                      </h3>
                      <div className="flex flex-wrap items-center gap-3">
                        <div className="upload-task-tabs" aria-label={copy('sampleFields')}>
                          {taskTypes.map((task) => (
                            <button
                              key={task}
                              aria-pressed={getTaskFamily(task) === getTaskFamily(uploadMode)}
                              onClick={() => setUploadMode(task)}
                            >
                              {datasetText(getTaskFamily(task)!)}
                            </button>
                          ))}
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={isCollecting}
                          onClick={() => filePicker.current?.click()}
                          className="rounded-md shadow-none"
                        >
                          <Plus size={14} className="mr-1" />
                          {copy('chooseFiles')}
                        </Button>
                      </div>
                    </div>
                    {!segmentationJsonOnlyAppend && (
                      <>
                        {/* Toolbar */}
                        <div className="upload-selection-toolbar">
                          <div className="flex items-center gap-3 sm:gap-4 flex-wrap">
                            <label className="flex items-center gap-2 text-sm font-medium text-slate-600 cursor-pointer select-none shrink-0">
                              <Checkbox
                                checked={selectedItems.size === localItems.length && localItems.length > 0}
                                indeterminate={selectedItems.size > 0 && selectedItems.size < localItems.length}
                                onCheckedChange={() => toggleSelectAll()}
                              />
                              <span className="hidden sm:inline">
                                {t('uploadPage.selectAll', {
                                  count: localItems.length
                                })}
                              </span>
                              <span className="sm:hidden">
                                {t('uploadPage.fileCount', {
                                  count: localItems.length
                                })}
                              </span>
                            </label>
                            <label className="flex min-h-10 cursor-pointer items-center gap-2 text-xs text-slate-600">
                              <Checkbox
                                aria-label={copy('selectPage')}
                                checked={
                                  paginatedItems.length > 0 &&
                                  paginatedItems.every((item) => selectedItems.has(item.key))
                                }
                                indeterminate={
                                  paginatedItems.some((item) => selectedItems.has(item.key)) &&
                                  !paginatedItems.every((item) => selectedItems.has(item.key))
                                }
                                onCheckedChange={(checked) => {
                                  for (const item of paginatedItems) {
                                    if (checked) selectedItems.add(item.key)
                                    else selectedItems.delete(item.key)
                                  }
                                  refreshSelection()
                                }}
                              />
                              {copy('selectPage')}
                            </label>
                            {skippedDuplicateCount > 0 && (
                              <span className="text-[10px] sm:text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded-full border border-amber-200 whitespace-nowrap">
                                {t('uploadPage.duplicateCount', {
                                  count: skippedDuplicateCount
                                })}
                              </span>
                            )}
                            {selectedItems.size > 0 && (
                              <div className="flex items-center gap-1.5 sm:gap-2 animate-in fade-in slide-in-from-left-4 duration-200">
                                <div className="h-4 w-px bg-slate-300 mx-1 hidden sm:block" />
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  onClick={() => setShowBulkEdit(true)}
                                  className="h-7 sm:h-8 text-[10px] sm:text-xs font-medium px-2 sm:px-3"
                                >
                                  <Edit2 className="w-3 h-3 mr-1 sm:mr-1.5" />
                                  {t('uploadPage.edit')}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="destructive"
                                  onClick={removeSelectedItems}
                                  className="h-7 sm:h-8 text-[10px] sm:text-xs font-medium bg-red-50 text-red-600 hover:bg-red-100 border border-red-200 px-2 sm:px-3"
                                >
                                  <Trash2 className="w-3 h-3 mr-1 sm:mr-1.5" />
                                  {t('uploadPage.delete')}
                                </Button>
                              </div>
                            )}
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <div className="relative">
                              <Search size={13} className="absolute left-2.5 top-3 text-slate-400" />
                              <input
                                type="search"
                                aria-label={copy('searchFiles')}
                                placeholder={copy('searchFiles')}
                                value={fileSearch}
                                onChange={(event) => setFileSearch(event.target.value)}
                                className="min-h-9 min-w-0 rounded-md border border-slate-200 bg-white pl-8 pr-2 text-xs"
                              />
                            </div>
                          </div>
                        </div>
                      </>
                    )}

                    {/* Table Area */}
                    <div className="relative">
                      {segmentationJsonOnlyAppend ? (
                        <div
                          className="bg-white p-6 sm:p-8 flex items-center justify-center"
                          onDragOver={(e) => {
                            e.preventDefault()
                            setIsDragging(true)
                          }}
                          onDragLeave={() => setIsDragging(false)}
                          onDrop={async (e) => {
                            e.preventDefault()
                            setIsDragging(false)
                            await handleCollectedDrop(e.dataTransfer, 'uploadPage.skippedUnsupportedFilesShort')
                          }}
                        >
                          <div className="max-w-2xl w-full rounded-lg border border-slate-200 bg-slate-50 px-5 py-6 text-left">
                            <div className="flex items-start gap-3">
                              <FileJson className="w-6 h-6 text-green-600 shrink-0 mt-0.5" />
                              <div>
                                <h3 className="text-base sm:text-lg font-semibold text-green-900">
                                  {t('uploadPage.jsonOnlyAppendTitle')}
                                </h3>
                                <p className="text-sm text-green-800 mt-2 leading-relaxed">
                                  {t('uploadPage.jsonOnlyAppendDesc', {
                                    count: segmentationJsonFiles.size
                                  })}
                                </p>
                                <p className="text-xs text-green-700 mt-2 leading-relaxed">
                                  {t('uploadPage.jsonOnlyAppendNote')}
                                </p>
                              </div>
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div
                          className="upload-table-scroll"
                          ref={tableContainerRef}
                          onDragOver={(e) => {
                            e.preventDefault()
                            setIsDragging(true)
                          }}
                          onDragLeave={() => setIsDragging(false)}
                          onDrop={async (e) => {
                            e.preventDefault()
                            setIsDragging(false)
                            await handleCollectedDrop(e.dataTransfer, 'uploadPage.skippedUnsupportedFilesShort')
                          }}
                        >
                          {isDragging && (
                            <div className="absolute inset-0 z-40 bg-indigo-50/90 flex items-center justify-center border border-indigo-300 border-dashed rounded-lg pointer-events-none">
                              <div className="bg-white px-6 py-3 rounded-lg border border-indigo-100 text-sm text-slate-700 flex items-center gap-3">
                                <UploadCloud className="w-6 h-6" />
                                {t('uploadPage.dropToAddFiles')}
                              </div>
                            </div>
                          )}

                          <table className="w-full text-left border-collapse">
                            <thead className="bg-slate-50 sticky top-0 z-10 border-b border-slate-200">
                              <tr>
                                <th className="w-10 px-3 sm:px-4 py-2 bg-slate-50">
                                  <div className="sr-only">Select</div>
                                </th>
                                <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[180px] sm:min-w-[200px]">
                                  {t('uploadPage.fileName')}
                                </th>
                                {isClassificationUploadMode(uploadMode) ? (
                                  <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[120px] sm:min-w-[150px]">
                                    {t('uploadPage.label')}
                                  </th>
                                ) : isSurvivalUploadMode(uploadMode) ? (
                                  <>
                                    <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[90px] sm:min-w-[100px]">
                                      {t('uploadPage.eventTime')}
                                    </th>
                                    <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[80px] sm:min-w-[90px]">
                                      <span className="flex items-center gap-1">
                                        {t('uploadPage.status')}
                                        <Tooltip content={t('uploadPage.statusTooltip')}>
                                          <Info className="w-3 h-3 text-slate-400 hover:text-slate-600 cursor-help transition-colors" />
                                        </Tooltip>
                                      </span>
                                    </th>
                                  </>
                                ) : isSegmentationUploadMode(uploadMode) ? (
                                  <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[80px] sm:min-w-[100px]">
                                    {t('uploadPage.maskStatus')}
                                  </th>
                                ) : null}
                                <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[100px] sm:min-w-[120px]">
                                  {t('uploadPage.caseId')}
                                </th>
                                <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[70px] sm:min-w-[80px]">
                                  {t('uploadPage.age')}
                                </th>
                                <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[90px] sm:min-w-[100px]">
                                  {t('uploadPage.gender')}
                                </th>
                                <th className="w-10 px-3 py-2 bg-slate-50"></th>
                              </tr>
                            </thead>
                            <tbody className="bg-white divide-y divide-slate-100">
                              {paginatedItems.map((item) => {
                                const resolvedMeta = resolveItemMetadata(
                                  item,
                                  localMetadata.get(item.key),
                                  splitMetadata,
                                  uploadMode
                                )
                                const meta: FileMetadata = {
                                  label: String(resolvedMeta.label ?? ''),
                                  case_id: String(resolvedMeta.case_id ?? ''),
                                  age: String(resolvedMeta.age ?? ''),
                                  gender: String(resolvedMeta.gender ?? ''),
                                  event_time: String(resolvedMeta.event_time ?? ''),
                                  event_status: String(resolvedMeta.event_status ?? '')
                                }
                                const isSelected = selectedItems.has(item.key)
                                const isHighlighted = highlightedItemKey === item.key
                                // Validation based on mode
                                const hasError =
                                  showValidation &&
                                  isSurvivalUploadMode(uploadMode) &&
                                  !!meta.event_time.trim() !== !!meta.event_status.trim()

                                return (
                                  <tr
                                    key={item.key}
                                    data-testid={`row-${item.name}`}
                                    className={`group transition-colors ${isHighlighted ? 'bg-red-50' : isSelected ? 'bg-blue-50/30' : 'hover:bg-slate-50'}`}
                                  >
                                    <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                      <Checkbox
                                        aria-label={item.name}
                                        checked={isSelected}
                                        onCheckedChange={() => toggleSelection(item.key)}
                                      />
                                    </td>
                                    <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                      <div className="flex flex-col min-w-0">
                                        <span
                                          className="text-sm font-semibold text-slate-900 truncate max-w-[150px] sm:max-w-[300px]"
                                          title={item.name}
                                        >
                                          {item.name}
                                        </span>
                                        <div className="flex items-center gap-2 mt-1">
                                          <span className="text-[9px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded font-bold tracking-wider uppercase">
                                            {(item.name.split('.').pop() || 'tmp').substring(0, 4)}
                                          </span>
                                          {item.file && (
                                            <span className="text-[10px] tabular-nums text-slate-400">
                                              {formatFileSize(item.file.size)}
                                            </span>
                                          )}
                                          {item.path && (
                                            <span className="text-[9px] text-slate-400 font-mono">LOCAL</span>
                                          )}
                                          {item.type === 'mrxs' && item.missingAssociated && (
                                            <span
                                              className="text-[9px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-bold flex items-center gap-1"
                                              title={t('uploadPage.missingDataFolder', {
                                                folder: getBaseName(item.name)
                                              })}
                                            >
                                              {t('uploadPage.dataMissing')}
                                            </span>
                                          )}
                                        </div>
                                      </div>
                                    </td>
                                    {/* Classification: Label input | Survival: Event Time & Status inputs | Segmentation: no extra required fields */}
                                    {isClassificationUploadMode(uploadMode) ? (
                                      <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                        <input
                                          ref={(node) => {
                                            if (node) labelInputRefs.current.set(item.key, node)
                                            else labelInputRefs.current.delete(item.key)
                                          }}
                                          className={`w-full px-2 py-1.5 text-sm border rounded-lg hover:border-blue-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all ${hasError ? 'border-red-500 bg-red-50' : 'border-slate-100 bg-slate-50/50 hover:bg-white focus:bg-white'}`}
                                          placeholder={t('uploadPage.enterLabel')}
                                          value={meta.label}
                                          onChange={(e) => handleMetadataChange(item.key, 'label', e.target.value)}
                                        />
                                      </td>
                                    ) : isSurvivalUploadMode(uploadMode) ? (
                                      <>
                                        <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                          <input
                                            type="number"
                                            step="0.1"
                                            className={`w-full px-2 py-1.5 text-sm border rounded-lg hover:border-emerald-400 focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 outline-none transition-all ${hasError && !meta.event_time.trim() ? 'border-red-500 bg-red-50' : 'border-slate-100 bg-slate-50/50 hover:bg-white focus:bg-white'}`}
                                            placeholder={t('uploadPage.months')}
                                            value={meta.event_time}
                                            onChange={(e) =>
                                              handleMetadataChange(item.key, 'event_time', e.target.value)
                                            }
                                          />
                                        </td>
                                        <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                          <Select
                                            value={meta.event_status}
                                            onChange={(v) => handleMetadataChange(item.key, 'event_status', v)}
                                            options={[
                                              {
                                                value: '1',
                                                label: t('uploadPage.eventOption')
                                              },
                                              {
                                                value: '0',
                                                label: t('uploadPage.censoredOption')
                                              }
                                            ]}
                                            placeholder={t('uploadPage.statusDefault')}
                                            triggerClassName={
                                              hasError && !meta.event_status.trim() ? 'border-red-500 bg-red-50' : ''
                                            }
                                          />
                                        </td>
                                      </>
                                    ) : isSegmentationUploadMode(uploadMode) ? (
                                      <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                        {matchedMasks.has(item.key) ? (
                                          <span className="text-sm text-green-700">{t('uploadPage.maskFound')}</span>
                                        ) : (
                                          <span className="text-sm text-slate-400">{t('uploadPage.maskNotFound')}</span>
                                        )}
                                      </td>
                                    ) : null}
                                    <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                      <input
                                        className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                        placeholder={t('uploadPage.caseIdPlaceholder')}
                                        value={meta.case_id}
                                        onChange={(e) => handleMetadataChange(item.key, 'case_id', e.target.value)}
                                      />
                                    </td>
                                    <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                      <input
                                        type="number"
                                        className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                        placeholder={t('uploadPage.agePlaceholder')}
                                        value={meta.age}
                                        onChange={(e) => handleMetadataChange(item.key, 'age', e.target.value)}
                                      />
                                    </td>
                                    <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                      <Select
                                        value={meta.gender}
                                        onChange={(v) => handleMetadataChange(item.key, 'gender', v)}
                                        options={[
                                          {
                                            value: 'Male',
                                            label: t('uploadPage.genderM')
                                          },
                                          {
                                            value: 'Female',
                                            label: t('uploadPage.genderF')
                                          },
                                          { value: 'Unspecified', label: '?' }
                                        ]}
                                        placeholder="-"
                                      />
                                    </td>
                                    <td className="px-3 sm:px-4 py-3 align-middle text-right border-b border-slate-100">
                                      <button
                                        aria-label={`${t('uploadPage.removeFile')} ${item.name}`}
                                        onClick={() => removeLocalItem(item.key)}
                                        className="p-2 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                                      >
                                        <X className="w-4 h-4" />
                                      </button>
                                    </td>
                                  </tr>
                                )
                              })}
                            </tbody>
                          </table>
                          {!displayedItems.length && (
                            <p className="py-12 text-center text-sm text-slate-500">{copy('noMatches')}</p>
                          )}
                        </div>
                      )}
                    </div>
                    {!!localItems.length && (
                      <div className="upload-pagination">
                        <span>{copy('pageSize')}</span>
                        <Select
                          ariaLabel={copy('pageSize')}
                          value={String(itemsPerPage)}
                          onChange={(value) => setItemsPerPage(Number(value))}
                          options={[10, 25, 50, 100].map((value) => ({
                            value: String(value),
                            label: String(value)
                          }))}
                        />
                        {totalPages > 1 && (
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              disabled={currentPage === 1}
                              aria-label={t('uploadPage.previousPage')}
                              className="rounded p-2 disabled:opacity-30"
                              onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                            >
                              <ChevronLeft size={16} />
                            </button>
                            <span>
                              {t('uploadPage.pageIndicator', {
                                current: currentPage,
                                total: totalPages
                              })}
                            </span>
                            <input
                              type="number"
                              min={1}
                              max={totalPages}
                              aria-label={copy('goToPage')}
                              key={`${currentPage}:${totalPages}`}
                              defaultValue={currentPage}
                              onBlur={(event) =>
                                setCurrentPage(Math.min(totalPages, Math.max(1, Number(event.target.value) || 1)))
                              }
                              onKeyDown={(event) => {
                                if (event.key === 'Enter') event.currentTarget.blur()
                              }}
                              className="h-8 w-12 rounded-md border border-slate-200 px-2 text-xs"
                            />
                            <button
                              type="button"
                              disabled={currentPage === totalPages}
                              aria-label={t('uploadPage.nextPage')}
                              className="rounded p-2 disabled:opacity-30"
                              onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                            >
                              <ChevronRight size={16} />
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                )}

                {showMissingLabelAlert && (
                  <div
                    role="alert"
                    className="mx-2 sm:mx-0 mb-2 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-slate-700"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <div className="flex items-start gap-3 min-w-0">
                        <Info className="mt-0.5 h-5 w-5 shrink-0 text-slate-500" />
                        <div className="min-w-0">
                          <p className="text-sm font-semibold">
                            {t('uploadPage.missingLabelSummary', {
                              count: missingLabelCount
                            })}
                          </p>
                          <p className="mt-1 text-xs text-slate-500">{datasetText('labelsLater')}</p>
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        {showMissingLabelChips ? (
                          missingLabelItems.map((item) => (
                            <button
                              key={item.key}
                              type="button"
                              onClick={() => jumpToMissingLabelItem(item)}
                              className="max-w-[180px] cursor-pointer truncate rounded-lg border border-slate-200 bg-white px-3 py-1 text-xs text-slate-700 hover:bg-slate-100 focus-visible:ring-2 focus-visible:ring-primary-500"
                              title={item.name}
                            >
                              {item.name}
                            </button>
                          ))
                        ) : (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={toggleMissingLabelFilter}
                            className="h-8 rounded-md border-slate-200 bg-white text-xs font-medium text-slate-600 shadow-none"
                          >
                            {fileFilter === 'missing-label'
                              ? t('uploadPage.showAllFiles')
                              : t('uploadPage.showOnlyMissingLabels')}
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                <section className="upload-label-panel">
                  <button
                    type="button"
                    className="upload-label-heading"
                    aria-expanded={showSplitConfig}
                    aria-controls="upload-label-files"
                    onClick={() => setShowSplitConfig((value) => !value)}
                  >
                    <div>
                      <strong>
                        {t('uploadPage.datasetMetadataConfig')}{' '}
                        <span className="upload-optional">· {copy('optional')}</span>
                      </strong>
                      <p>{copy('attachmentsHint')}</p>
                    </div>
                    <ChevronDown
                      size={15}
                      className={`shrink-0 text-slate-400 transition-transform ${showSplitConfig ? 'rotate-180' : ''}`}
                    />
                  </button>
                  {showSplitConfig && (
                    <div className="upload-label-body" id="upload-label-files">
                      <UploadAttachment
                        label={datasetText('table')}
                        hint={copy('csvHint')}
                        accept=".csv,.xlsx,.xls"
                        file={splitFile}
                        onChange={handleSplitFileSelect}
                        onRemove={clearSplitFile}
                        onDrop={handleCsvDrop}
                        disabled={isImporting || isValidatingMetadata}
                        action={
                          <button type="button" onClick={handleDownloadTemplate} className="upload-back text-xs">
                            <Download size={13} />
                            {t('uploadPage.csvTemplate')}
                          </button>
                        }
                      />
                      {taskTypes
                        .filter((task) => ['patch_segmentation', 'patch_detection'].includes(task))
                        .map((task) => (
                          <UploadAttachment
                            key={task}
                            label={`${datasetText(getTaskFamily(task)!)} · ${datasetText('coco')}`}
                            hint={copy('spatialHint')}
                            accept=".json"
                            file={taskAnnotationFiles[task]}
                            onChange={(event) => {
                              const file = event.target.files?.[0]
                              setTaskAnnotationFiles((previous) => ({
                                ...previous,
                                [task]: file
                              }))
                            }}
                            onRemove={() =>
                              setTaskAnnotationFiles((previous) => {
                                const next = { ...previous }
                                delete next[task]
                                return next
                              })
                            }
                            disabled={isImporting}
                          />
                        ))}
                      <p className="mt-2 text-xs leading-6 text-slate-500">{datasetText('tableHint')}</p>
                      {isSurvivalUploadMode(uploadMode) && (
                        <p className="mt-2 text-xs text-slate-500">
                          {t('uploadPage.survivalStatusEvent')} · {t('uploadPage.survivalStatusCensored')}
                        </p>
                      )}
                      {splitFileError && (
                        <p role="alert" className="mt-3 text-sm text-red-600">
                          {splitFileError}
                        </p>
                      )}
                    </div>
                  )}
                </section>
                {submitError && (
                  <p
                    role="alert"
                    className="mt-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600"
                  >
                    {submitError}
                  </p>
                )}
                {isValidatingMetadata && (
                  <p role="status" className="mt-3 flex items-center gap-2 text-xs text-slate-500">
                    <Activity size={14} className="animate-spin" />
                    {t('uploadPage.validatingMetadata')}
                  </p>
                )}
                <footer className="upload-actionbar">
                  <div>
                    <strong>
                      {t('uploadPage.readyToRegister', {
                        count: readyToUploadCount
                      })}
                    </strong>
                    <p className="mt-1">{copy('submitHint')}</p>
                  </div>
                  <div className="upload-actionbar-actions">
                    <Button variant="ghost" disabled={isImporting} onClick={resetUpload}>
                      {t('uploadPage.cancel')}
                    </Button>
                    <Button
                      className="upload-primary"
                      onClick={handleUpload}
                      disabled={
                        isCollecting ||
                        isValidatingMetadata ||
                        isImporting ||
                        (readyToUploadCount === 0 && !splitFile && !Object.values(taskAnnotationFiles).some(Boolean))
                      }
                    >
                      {isImporting ? (
                        <>
                          <Activity size={14} className="mr-2 animate-spin" />
                          {t('uploadPage.importing')}
                        </>
                      ) : (
                        <>
                          {readyToUploadCount === 0 && splitFile
                            ? t('uploadPage.uploadCsv')
                            : isAppendingDataset
                              ? t('uploadPage.addToDataset')
                              : t('uploadPage.registerAll')}
                          <ArrowRight size={14} className="ml-3" />
                        </>
                      )}
                    </Button>
                  </div>
                </footer>
              </>
            )}
          </>
        )}
      </fieldset>
    </div>
  )
}
