import { useState, useMemo, useEffect, useRef } from 'react'
import { useDraftState, clearDraftKeys } from '../lib/useDraftState'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { xlsxToCSV } from '../lib/csvImporter'
import { Tooltip } from '../components/ui/tooltip'
import {
  Download,
  X,
  AlertCircle,
  UploadCloud,
  Trash2,
  Edit2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Plus,
  Tags,
  Activity,
  Layers,
  ArrowLeft,
  FileSpreadsheet,
  CheckCircle2,
  FolderOpen,
  Image,
  FileJson,
  Folder,
} from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Checkbox } from '../components/ui/checkbox'
import { Select } from '../components/ui/select'
import { useBackgroundTask, UploadTaskFile } from '../contexts/BackgroundTaskContext'
import { useAuth } from '../contexts/AuthContext'
import { checkDuplicateFilenames, fetchDatasets, uploadDatasetSplits, downloadCSVTemplate, updateDatasetSource } from '../api'
import { ApiError } from '../api/client'
import { useToast } from '../contexts/ToastContext'
import { ALL_EXTENSIONS, PATCH_EXTENSIONS, TIF_EXTENSIONS, isSupportedName, isTmapDataFile, getBaseName, getFilePath } from '../constants/fileTypes'
import { parseCsvMetadata } from '../lib/csvImporter'
import { getSegmentationStem, mergeSegmentationJsonFiles, summarizeSegmentationMatches } from '../lib/segmentationUploadUtils'
import { organSources } from '../constants/wsi'
import {
  type LocalItem, type FileMetadata, type UploadMode, type DataLevel, type DataType,
  type ElectronApi, type MrxsDataFolder, type CollectionResult,
  defaultMetadata, generateCaseId,
  collectItemsFromDataTransfer, buildFileKey,
  BulkEditModal, DatasetConfigStep, SuccessStep
} from '../components/upload'

declare const window: Window & { api?: ElectronApi }

export default function RegisterPage() {
  const { error: toastError, warning: toastWarning } = useToast()
  const navigate = useNavigate()
  const { addUploadTask } = useBackgroundTask()
  const { t } = useTranslation()
  const { user } = useAuth()

  // Upload mode state (classification or survival)
  const [uploadMode, setUploadMode] = useDraftState<UploadMode>('draft:upload:uploadMode', 'classification')
  // Aggregation level state (case-level or file-level)
  const [dataLevel, setDataLevel] = useDraftState<DataLevel>('draft:upload:dataLevel', 'file')

  // Dataset name (required for grouping files)
  const [datasetName, setDatasetName] = useDraftState<string>('draft:upload:datasetName', '')
  // Dataset ID (UUID) - only set when using existing dataset or passed from navigation
  const [datasetId, setDatasetId] = useState<string | null>(null)
  const [isPublic, setIsPublic] = useDraftState<boolean>('draft:upload:isPublic', false)
  const [datasetSourceSelection, setDatasetSourceSelection] = useDraftState<string>('draft:upload:datasetSourceSelection', '')
  const [datasetSourceCustom, setDatasetSourceCustom] = useDraftState<string>('draft:upload:datasetSourceCustom', '')
  // Source organ of the existing dataset (for auto-fill when appending)
  const [existingDatasetSource, setExistingDatasetSource] = useState<string | undefined>()

  // Steps: 1 - Dataset Name, 2 - File Upload
  const [step, setStep] = useState(1)
  const { data: datasetsData } = useQuery({
    queryKey: ['datasets'],
    queryFn: async () => {
      const data = await fetchDatasets()
      const sortedDatasetNames = data.items
        .map((dataset, index) => ({ dataset, index }))
        .sort((a, b) => {
          const aMissing = !a.dataset.source_organ?.trim()
          const bMissing = !b.dataset.source_organ?.trim()
          if (aMissing !== bMissing) return aMissing ? -1 : 1
          return a.index - b.index
        })
        .map(({ dataset }) => dataset.dataset_name)

      const typeMap = new Map<string, UploadMode>()
      const levelMap = new Map<string, DataLevel>()
      const dataTypeMap = new Map<string, DataType>()
      const idMap = new Map<string, string | null>()
      const sourceOrganMap = new Map<string, string | null>()
      data.items.forEach(d => {
        typeMap.set(d.dataset_name, d.task_type as UploadMode)
        levelMap.set(d.dataset_name, d.aggregation_level as DataLevel)
        dataTypeMap.set(d.dataset_name, d.data_type as DataType)
        idMap.set(d.dataset_name, d.dataset_id)
        sourceOrganMap.set(d.dataset_name, d.source_organ ?? null)
      })
      return { sortedDatasetNames, typeMap, levelMap, dataTypeMap, idMap, sourceOrganMap, items: data.items }
    },
    staleTime: 5 * 60 * 1000,
  })

  const existingDatasets = datasetsData?.sortedDatasetNames ?? []
  const existingDatasetTypes = datasetsData?.typeMap ?? new Map<string, UploadMode>()
  const existingDatasetLevels = datasetsData?.levelMap ?? new Map<string, DataLevel>()
  const existingDatasetDataTypes = datasetsData?.dataTypeMap ?? new Map<string, DataType>()
  const datasetNameToId = datasetsData?.idMap ?? new Map<string, string | null>()
  const datasetNameToSourceOrgan = datasetsData?.sourceOrganMap ?? new Map<string, string | null>()
  const existingDatasetOwners = useMemo(() => {
    if (!datasetsData?.items) return new Set<string>()
    const currentUserId = user?.id
    return new Set(
      datasetsData.items
        .filter(dataset => !!currentUserId && dataset.user_id === currentUserId)
        .map(dataset => dataset.dataset_name.trim().toLowerCase())
    )
  }, [datasetsData?.items, user?.id])
  // Toggle for Dataset Splits Configuration visibility
  const [showSplitConfig, setShowSplitConfig] = useState(false)

  // Checking for initial dataset from navigation state
  const location = useLocation()
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
      // Accept uploadMode from AI Chat navigation
      if (location.state.uploadMode) {
        setUploadMode(location.state.uploadMode as UploadMode)
      }
      // Accept dataLevel from AI Chat navigation (case-level or file-level)
      if (location.state.dataLevel) {
        setDataLevel(location.state.dataLevel as DataLevel)
      }
      // Accept CSV content from AI Chat navigation
      if (location.state.csvContent && location.state.csvFileName) {
        // Create a File object from the CSV content
        const blob = new Blob([location.state.csvContent], { type: 'text/csv' })
        const file = new File([blob], location.state.csvFileName, { type: 'text/csv' })
        setSplitFile(file)
        setShowSplitConfig(true) // Auto-expand the split config section
      }
      // If we have datasetName and uploadMode from AI Chat, skip to step 2
      if (location.state.datasetName && location.state.uploadMode) {
        setStep(2)
      }
    }
  }, [location])



  const isExistingDataset = useMemo(() => {
    return existingDatasets.includes(datasetName.trim())
  }, [datasetName, existingDatasets])

  // Get the data type (wsi/patch) for the current dataset (only for existing datasets)
  const currentDataType = useMemo(() => {
    const trimmed = datasetName.trim()
    return existingDatasetDataTypes.get(trimmed) || null
  }, [datasetName, existingDatasetDataTypes])

  // Auto-select analysis type, data level, and datasetId for existing datasets
  // biome-ignore lint/correctness/useExhaustiveDependencies: setUploadMode/setDataLevel are stable draft setters; datasetName and dataset maps are the actual triggers
  useEffect(() => {
    const trimmed = datasetName.trim()
    if (existingDatasetTypes.has(trimmed)) {
      setUploadMode(existingDatasetTypes.get(trimmed)!)
    }
    if (existingDatasetLevels.has(trimmed)) {
      setDataLevel(existingDatasetLevels.get(trimmed)!)
    }
    // Set datasetId when user types or selects an existing dataset name
    if (datasetNameToId.has(trimmed)) {
      setDatasetId(datasetNameToId.get(trimmed) ?? null)
    } else {
      // New dataset - clear datasetId
      setDatasetId(null)
    }
    // Set existingDatasetSource for existing datasets
    if (datasetNameToSourceOrgan.has(trimmed)) {
      setExistingDatasetSource(datasetNameToSourceOrgan.get(trimmed) ?? undefined)
    } else {
      setExistingDatasetSource(undefined)
    }
  }, [datasetName, existingDatasetTypes, existingDatasetLevels, datasetNameToId, datasetNameToSourceOrgan])

  // State
  const [localItems, setLocalItems] = useState<LocalItem[]>([])
  const [localMetadata, setLocalMetadata] = useState<Map<string, FileMetadata>>(new Map())
  const [isDragging, setIsDragging] = useState(false)
  const [showValidation, setShowValidation] = useState(false)
  // ignoredCount state was here but maybe less clear in table view? We can keep it as a toast or small alert.
  const [ignoredCount, setIgnoredCount] = useState(0)
  const [skippedDuplicateCount, setSkippedDuplicateCount] = useState(0) // Count of skipped duplicate files
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Sub-selection for bulk actions
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())
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
  const itemsPerPage = 10

  // Batch metadata state (temporary for the modal)
  const [batchMetadata, setBatchMetadata] = useState<FileMetadata>({ ...defaultMetadata })

  const getResolvedDatasetSource = () => {
    if (datasetSourceSelection === 'Other') {
      return datasetSourceCustom.trim()
    }
    return datasetSourceSelection.trim()
  }

  const tableContainerRef = useRef<HTMLDivElement>(null)

  const totalPages = Math.ceil(localItems.length / itemsPerPage)
  const paginatedItems = useMemo(() => {
    const start = (currentPage - 1) * itemsPerPage
    return localItems.slice(start, start + itemsPerPage)
  }, [localItems, currentPage, itemsPerPage])

  useEffect(() => {
    if (currentPage > totalPages && totalPages > 0) {
      setCurrentPage(totalPages)
    } else if (totalPages === 0 && currentPage !== 1) {
      setCurrentPage(1)
    }
  }, [totalPages, currentPage])

  useEffect(() => {
    if (uploadMode !== 'segmentation') {
      setMatchedMasks(new Set())
      setPendingJsonStems(new Set())
      return
    }

    const { matchedStems, orphanJsonStems } = summarizeSegmentationMatches(localItems, segmentationJsonFiles)
    setMatchedMasks(new Set(localItems.filter(item => matchedStems.has(getSegmentationStem(item.name))).map(item => item.key)))
    setPendingJsonStems(new Set(orphanJsonStems))
  }, [localItems, segmentationJsonFiles, uploadMode])

  const supportsNativePicker = typeof window !== 'undefined' && !!window.api?.files?.selectFiles
  const segmentationJsonOnlyAppend = uploadMode === 'segmentation' && !!datasetId && localItems.length === 0 && segmentationJsonFiles.size > 0
  const readyToUploadCount = segmentationJsonOnlyAppend ? segmentationJsonFiles.size : localItems.length

  // --- Interaction Logic ---

  const processCollectionResult = async (result: CollectionResult) => {
    const { items, orphanFolders, orphanDtFiles, jsonFiles } = result

    // First, try to match orphan data with existing items
    setLocalItems(prev => {
      let updated = [...prev]

      // Match orphan folders with existing MRXS items
      for (const folder of orphanFolders) {
        const mrxsName = `${folder.folderName}.mrxs`
        const matchingItemIndex = updated.findIndex(
          item => item.type === 'mrxs' && item.name.toLowerCase() === mrxsName.toLowerCase()
        )
        if (matchingItemIndex >= 0) {
          const item = updated[matchingItemIndex]
          updated[matchingItemIndex] = {
            ...item,
            associatedFiles: [...(item.associatedFiles || []), ...folder.folderFiles],
            missingAssociated: false
          }
        }
      }

      // Match orphan dt files with existing TMAP items
      orphanDtFiles.forEach((dtFiles, baseName) => {
        const matchingItemIndex = updated.findIndex(
          item => item.type === 'tmap' && getBaseName(item.name).toLowerCase() === baseName.toLowerCase()
        )
        if (matchingItemIndex >= 0) {
          const item = updated[matchingItemIndex]
          updated[matchingItemIndex] = {
            ...item,
            associatedFiles: [...(item.associatedFiles || []), ...dtFiles],
            missingAssociated: false
          }
        }
      })

      return updated
    })

    // Store unmatched orphan data for future matching
    const unmatchedFolders: MrxsDataFolder[] = []
    const unmatchedDtFiles = new Map<string, File[]>()

    // Check which orphans couldn't be matched with existing items
    setLocalItems(prev => {
      for (const folder of orphanFolders) {
        const mrxsName = `${folder.folderName}.mrxs`
        const hasMatch = prev.some(
          item => item.type === 'mrxs' && item.name.toLowerCase() === mrxsName.toLowerCase()
        )
        if (!hasMatch) {
          unmatchedFolders.push(folder)
        }
      }

      orphanDtFiles.forEach((dtFiles, baseName) => {
        const hasMatch = prev.some(
          item => item.type === 'tmap' && getBaseName(item.name).toLowerCase() === baseName.toLowerCase()
        )
        if (!hasMatch) {
          unmatchedDtFiles.set(baseName, dtFiles)
        }
      })

      return prev
    })

    // Save unmatched orphans for future use
    if (unmatchedFolders.length > 0) {
      setPendingMrxsFolders(prev => {
        const next = new Map(prev)
        unmatchedFolders.forEach(f => next.set(f.folderName.toLowerCase(), f.folderFiles))
        return next
      })
    }
    if (unmatchedDtFiles.size > 0) {
      setPendingTmapDtFiles(prev => {
        const next = new Map(prev)
        unmatchedDtFiles.forEach((files, baseName) => {
          const existing = next.get(baseName.toLowerCase()) || []
          next.set(baseName.toLowerCase(), [...existing, ...files])
        })
        return next
      })
    }

    // Now add new items
    if (items.length > 0) {
      const filtered = items.filter(item => isSupportedName(item.name))
      setIgnoredCount(prev => prev + (items.length - filtered.length))

      if (filtered.length > 0) {
        // Check for duplicate filenames in database
        const filenames = filtered.map(item => item.name)
        let nonDuplicateItems = filtered
        try {
          const duplicateCheck = await checkDuplicateFilenames(filenames)
          if (duplicateCheck.duplicates.length > 0) {
            const duplicateSet = new Set(duplicateCheck.duplicates)
            nonDuplicateItems = filtered.filter(item => !duplicateSet.has(item.name))
            setSkippedDuplicateCount(prev => prev + duplicateCheck.duplicates.length)
          }
        } catch (err) {
          // If API fails, continue without duplicate check
          console.warn('Failed to check duplicate filenames:', err)
        }

        if (nonDuplicateItems.length > 0) {
          setLocalItems(prev => {
            const merged = new Map(prev.map(item => [item.key, item]))

            // For new items, check if we have pending associated data
            nonDuplicateItems.forEach(item => {
              let updatedItem = { ...item }

              if (item.type === 'mrxs' && item.missingAssociated) {
                const baseName = getBaseName(item.name).toLowerCase()
                const pendingFiles = pendingMrxsFolders.get(baseName)
                if (pendingFiles && pendingFiles.length > 0) {
                  updatedItem = {
                    ...updatedItem,
                    associatedFiles: [...(updatedItem.associatedFiles || []), ...pendingFiles],
                    missingAssociated: false
                  }
                  // Remove from pending
                  setPendingMrxsFolders(prev => {
                    const next = new Map(prev)
                    next.delete(baseName)
                    return next
                  })
                }
              }

              if (item.type === 'tmap' && item.missingAssociated) {
                const baseName = getBaseName(item.name).toLowerCase()
                const pendingFiles = pendingTmapDtFiles.get(baseName)
                if (pendingFiles && pendingFiles.length > 0) {
                  updatedItem = {
                    ...updatedItem,
                    associatedFiles: [...(updatedItem.associatedFiles || []), ...pendingFiles],
                    missingAssociated: false
                  }
                  // Remove from pending
                  setPendingTmapDtFiles(prev => {
                    const next = new Map(prev)
                    next.delete(baseName)
                    return next
                  })
                }
              }

              merged.set(updatedItem.key, updatedItem)
            })

            return Array.from(merged.values())
          })

          setLocalMetadata(prev => {
            const updated = new Map(prev)
            nonDuplicateItems.forEach(item => {
              if (!updated.has(item.key)) {
                updated.set(item.key, { ...defaultMetadata, case_id: generateCaseId() })
              }
            })
            return updated
          })
        }
      }
    }

    if (uploadMode === 'segmentation' && jsonFiles && jsonFiles.length > 0) {
      let duplicateJsonStems: string[] = []
      setSegmentationJsonFiles(prev => {
        const merged = mergeSegmentationJsonFiles(prev, jsonFiles)
        duplicateJsonStems = merged.duplicateJsonStems
        return merged.jsonFilesByStem
      })
      if (duplicateJsonStems.length > 0) {
        setSegmentationDuplicateJsonStems(prev => new Set([...prev, ...duplicateJsonStems]))
      }
    }
  }

  // Legacy function for simple item arrays (used by handleLocalPathSelect)
  const addLocalItems = (items: LocalItem[]) => {
    if (!items.length) return
    const filtered = items.filter(item => isSupportedName(item.name))
    setIgnoredCount(prev => prev + (items.length - filtered.length))
    if (filtered.length === 0) return

    setLocalItems(prev => {
      const merged = new Map(prev.map(item => [item.key, item]))
      filtered.forEach(item => merged.set(item.key, item))
      return Array.from(merged.values())
    })

    setLocalMetadata(prev => {
      const updated = new Map(prev)
      filtered.forEach(item => {
        if (!updated.has(item.key)) {
          updated.set(item.key, { ...defaultMetadata, case_id: generateCaseId() })
        }
      })
      return updated
    })
  }

  const handleLocalPathSelect = async () => {
    if (!window.api?.files?.selectFiles) return
    const patchOnlyExtensions = [...PATCH_EXTENSIONS, ...TIF_EXTENSIONS]
    const activeExtensions = uploadMode === 'segmentation' ? patchOnlyExtensions : ALL_EXTENSIONS
    const filterName = uploadMode === 'segmentation' ? 'Patch Images' : 'Supported Formats (WSI & Patch)'
    const filters = [{ name: filterName, extensions: activeExtensions.map(ext => ext.replace(/^\./, '')) }]
    const paths = await window.api.files.selectFiles({ title: 'Select local files', filters })

    if (paths && paths.length > 0) {
      const items = paths.map(path => ({ key: path, name: path.split(/[/\\]/).pop() || path, path }))
      addLocalItems(items)
    }
  }

  const handleMetadataChange = (key: string, field: string, value: string) => {
    setLocalMetadata(prev => {
      const updated = new Map(prev)
      const current = updated.get(key) || { ...defaultMetadata }
      updated.set(key, { ...current, [field]: value })
      return updated
    })
  }

  const removeLocalItem = (key: string) => {
    setLocalItems(prev => prev.filter(i => i.key !== key))
    setLocalMetadata(prev => {
      const next = new Map(prev)
      next.delete(key)
      return next
    })
    setSelectedItems(prev => {
      const next = new Set(prev)
      next.delete(key)
      return next
    })
  }

  const removeSelectedItems = () => {
    setLocalItems(prev => prev.filter(i => !selectedItems.has(i.key)))
    setLocalMetadata(prev => {
      const next = new Map(prev)
      selectedItems.forEach(k => next.delete(k))
      return next
    })
    setSelectedItems(new Set())
  }

  // --- Bulk Edit Logic ---

  const handleApplyBulkEdit = () => {
    setLocalMetadata(prev => {
      const updated = new Map(prev)
      localItems.forEach(item => {
        if (!selectedItems.has(item.key)) return
        const current = updated.get(item.key) || { ...defaultMetadata }
        updated.set(item.key, {
          ...current,
          label: uploadMode === 'classification' ? (batchMetadata.label || current.label) : current.label,
          case_id: batchMetadata.case_id || current.case_id,
          age: batchMetadata.age || current.age,
          gender: batchMetadata.gender || current.gender,
          event_time: batchMetadata.event_time || current.event_time,
          event_status: batchMetadata.event_status || current.event_status
        })
      })
      return updated
    })
    setBatchMetadata({ ...defaultMetadata })
    setShowBulkEdit(false)
  }

  // --- Upload Logic ---

  const handleUpload = async () => {
    // Check if we have files OR a split file to upload
    if (localItems.length === 0 && !splitFile && !segmentationJsonOnlyAppend) return
    setShowValidation(true)
    setSubmitError(null)

    // Validate dataset name is required
    if (!datasetName.trim()) {
      setSubmitError(t('uploadPage.datasetNameRequired'))
      return
    }

    // --- CSV BINDING STRATEGY ---
    // 1. Existing Dataset: Use handleUploadSplit (Client uploads raw CSV, Backend binds)
    // 2. New Dataset: Parse CSV on Client, bind to files, create dataset with metadata

    let csvMetadataMap = new Map<string, any>()

    // Case 1: Existing Dataset - Upload CSV separately
    if (splitFile && datasetId) {
      const success = await handleUploadSplit()
      if (!success) {
        setSubmitError(t('uploadPage.failedUploadCsv'))
        return
      }

      // If we only had a CSV and no files, we are done
      if (localItems.length === 0 && !segmentationJsonOnlyAppend) {
        setStep(3)
        return
      }
    }

    // Case 2: New Dataset - Parse CSV to bind to files
    if (splitFile && !datasetId) {
      try {
        csvMetadataMap = await parseCsvMetadata(splitFile)
        console.log(`[Upload] Parsed ${csvMetadataMap.size} entries from CSV for binding`)
      } catch (err) {
        console.error("Failed to parse split file for binding", err)
        setSubmitError(t('uploadPage.failedParseCsv', { error: String(err) }))
        return
      }
    }

    if (readyToUploadCount === 0) return

    if (uploadMode === 'segmentation') {
      const invalidSegmentationItems = localItems.filter(item => item.type !== 'standard')
      if (invalidSegmentationItems.length > 0) {
        setSubmitError('Segmentation upload only supports patch/image files.')
        return
      }

      const { duplicateImageStems } = summarizeSegmentationMatches(localItems, segmentationJsonFiles)

      if (segmentationDuplicateJsonStems.size > 0) {
        setSubmitError(`Duplicate segmentation JSON stems detected: ${Array.from(segmentationDuplicateJsonStems).join(', ')}`)
        return
      }
      if (duplicateImageStems.length > 0) {
        setSubmitError(`Duplicate segmentation image stems detected: ${duplicateImageStems.join(', ')}`)
        return
      }
      if (!datasetId && localItems.length === 0) {
        setSubmitError('Segmentation upload requires at least one image file when creating a new dataset.')
        return
      }
    }

    const resolvedDatasetSource = getResolvedDatasetSource()

    // Prepare items with resolved metadata (UI + CSV)
    const itemsWithMeta = localItems.map(item => {
      const uiMeta = localMetadata.get(item.key) || {} as FileMetadata
      let csvMeta: any = {}

      if (csvMetadataMap.size > 0) {
        const name = item.name.toLowerCase()
        const nameNoExt = name.replace(/\.[^/.]+$/, "")
        // Try exact match, then name-without-extension
        csvMeta = csvMetadataMap.get(name) || csvMetadataMap.get(nameNoExt) || {}
      }

      // Merge: UI takes precedence if non-empty, otherwise CSV
      return {
        item,
        finalMeta: {
          label: uploadMode === 'segmentation' ? undefined : ((uiMeta.label && uiMeta.label.trim()) ? uiMeta.label : csvMeta.label),
          case_id: (uiMeta.case_id && uiMeta.case_id.trim()) ? uiMeta.case_id : csvMeta.case_id,
          age: (uiMeta.age && uiMeta.age.trim()) ? uiMeta.age : csvMeta.age,
          gender: (uiMeta.gender && uiMeta.gender.trim()) ? uiMeta.gender : csvMeta.gender,
          event_time: (uiMeta.event_time && uiMeta.event_time.trim()) ? uiMeta.event_time : csvMeta.event_time,
          event_status: (uiMeta.event_status && uiMeta.event_status.trim()) ? uiMeta.event_status : csvMeta.event_status
        }
      }
    })

    // Validate based on upload mode (using resolved metadata)
    if (uploadMode === 'classification') {
      const missingLabels = itemsWithMeta.filter(({ finalMeta }) => !finalMeta.label?.toString().trim())
      if (missingLabels.length > 0) {
        // Validation failed - we rely on the UI to show red borders
        // But UI only knows localMetadata.
        // If CSV provided labels but some are still missing, we block.
        // If NO CSV, we obviously block.
        // We set error message to help user
        if (csvMetadataMap.size > 0) {
          setSubmitError(t('uploadPage.validationMissingLabels', { count: missingLabels.length }))
        }
        return
      }
    } else if (uploadMode === 'survival') {
      // Survival mode: require event_time and event_status
      const missingSurvival = itemsWithMeta.filter(({ finalMeta }) => {
        return !finalMeta.event_time?.toString().trim() || !finalMeta.event_status?.toString().trim()
      })
      if (missingSurvival.length > 0) {
        if (csvMetadataMap.size > 0) {
          setSubmitError(t('uploadPage.validationMissingSurvival', { count: missingSurvival.length }))
        }
        return
      }
    }

    // Prepare files for background upload task
    const uploadFiles: UploadTaskFile[] = segmentationJsonOnlyAppend
      ? Array.from(segmentationJsonFiles.values()).map(file => ({
        key: `seg-json-${file.name}-${file.size}`,
        name: file.name,
        file,
        metadata: {
          dataset_id: datasetId ?? undefined,
          task_type: uploadMode,
        }
      }))
      : itemsWithMeta.map(({ item, finalMeta }) => {
        const age = finalMeta.age ? parseInt(String(finalMeta.age)) : undefined
        const eventTime = finalMeta.event_time ? parseFloat(String(finalMeta.event_time)) : undefined
        const eventStatus = finalMeta.event_status ? parseInt(String(finalMeta.event_status)) : undefined
        const matchedSegmentationJson = uploadMode === 'segmentation'
          ? segmentationJsonFiles.get(getSegmentationStem(item.name))
          : undefined

        return {
          key: item.key,
          name: item.name,
          file: item.file,
          path: item.path,
          metadata: {
            dataset_id: datasetId ?? undefined,
            dataset_name: datasetId ? undefined : datasetName.trim(),
            source_organ: datasetId ? undefined : (resolvedDatasetSource || undefined),
            aggregation_level: datasetId ? undefined : dataLevel,
            is_public: datasetId ? undefined : isPublic,
            task_type: uploadMode,
            label: uploadMode !== 'segmentation' && finalMeta.label ? String(finalMeta.label) : undefined,
            case_id: finalMeta.case_id ? String(finalMeta.case_id) : undefined,
            age,
            gender: finalMeta.gender ? String(finalMeta.gender) : undefined,
            event_time: eventTime,
            event_status: eventStatus
          },
          associatedFiles: uploadMode === 'segmentation' && matchedSegmentationJson
            ? [matchedSegmentationJson]
            : item.associatedFiles
        }
      })

    try {
      // Add to background task queue
      addUploadTask(uploadFiles, {
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
      if (
        error instanceof ApiError &&
        error.status === 409 &&
        error.details === 'DATASET_NAME_ALREADY_EXISTS'
      ) {
        const message = t('uploadPage.datasetNameExistsForCurrentUser')
        toastError(message)
        setSubmitError(message)
        return
      }
      setSubmitError(error instanceof Error ? error.message : String(error))
    }
  }

  const resetUpload = () => {
    clearDraftKeys('draft:upload:')
    setStep(1)
    setDatasetName('')
    setDatasetId(null)
    setIsPublic(false)
    setLocalItems([])
    setLocalMetadata(new Map())
    setShowValidation(false)
    setIgnoredCount(0)
    setSkippedDuplicateCount(0)
    setSelectedItems(new Set())
    setSubmitError(null)
    setMatchedMasks(new Set())
    setPendingJsonStems(new Set())
    setSegmentationJsonFiles(new Map())
    setSegmentationDuplicateJsonStems(new Set())
  }

  // --- Selection Logic ---

  const toggleSelectAll = () => {
    if (selectedItems.size === localItems.length) {
      setSelectedItems(new Set())
    } else {
      setSelectedItems(new Set(localItems.map(i => i.key)))
    }
  }

  const toggleSelection = (key: string) => {
    setSelectedItems(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // --- Split Upload Logic ---
  const [splitFile, setSplitFile] = useState<File | null>(null)
  const [uploadingSplit, setUploadingSplit] = useState(false)

  const [splitFileError, setSplitFileError] = useState<string | null>(null)
  const [isCsvDragging, setIsCsvDragging] = useState(false)

  const processSplitFile = async (file: File) => {
    setSplitFileError(null)
    const fileName = file.name.toLowerCase()

    // Client-side validation
    try {
      let csvContent: string
      let finalFile: File = file

      if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
        const { sheetNames, csv } = await xlsxToCSV(await file.arrayBuffer())
        if (sheetNames.length > 1) {
          setSplitFileError(t('uploadPage.excelMultipleSheets'))
          return
        }
        csvContent = csv
        finalFile = new File([new Blob([csv], { type: 'text/csv' })], file.name, { type: 'text/csv' })
      } else {
        csvContent = await file.text()
      }

      const lines = csvContent.split('\n').filter(line => line.trim() !== '')

      if (lines.length < 2) {
        setSplitFileError(t('uploadPage.fileEmptyOrNoData'))
        return
      }

      const headers = lines[0].toLowerCase().split(',').map(h => h.trim())

      // Validate required columns based on upload mode
      if (!headers.includes('filename')) {
        setSplitFileError(t('uploadPage.missingFilenameColumn'))
        return
      }

      if (uploadMode === 'classification') {
        if (!headers.includes('label')) {
          setSplitFileError(t('uploadPage.missingLabelColumn'))
          return
        }
      } else if (uploadMode === 'survival') {
        // survival mode
        if (!headers.includes('event_time')) {
          setSplitFileError(t('uploadPage.missingEventTimeColumn'))
          return
        }
        if (!headers.includes('event_status')) {
          setSplitFileError(t('uploadPage.missingEventStatusColumn'))
          return
        }
      }

      setSplitFile(finalFile)
    } catch (err) {
      setSplitFileError(t('uploadPage.failedReadFile', { error: String(err) }))
    }
  }

  const handleSplitFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      await processSplitFile(e.target.files[0])
    }
  }

  const handleCsvDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    e.stopPropagation()
    setIsCsvDragging(false)
    const files = Array.from(e.dataTransfer.files)
    const csvFile = files.find(f => {
      const name = f.name.toLowerCase()
      return name.endsWith('.csv') || name.endsWith('.xlsx') || name.endsWith('.xls')
    })
    if (csvFile) {
      await processSplitFile(csvFile)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      await downloadCSVTemplate(uploadMode)
    } catch (e) {
      console.error("Failed to download template", e)
      toastError(e instanceof Error ? e.message : t('uploadPage.failedDownloadTemplate'))
    }
  }

  const [splitUploadSuccess, setSplitUploadSuccess] = useState<string | null>(null)

  const handleUploadSplit = async () => {
    if (!splitFile || !datasetName) return false

    // uploadDatasetSplits requires dataset_id - only works for existing datasets
    if (!datasetId) {
      setSplitFileError(t('uploadPage.cannotUploadSplitsNewDataset'))
      return false
    }

    setUploadingSplit(true)
    setSplitFileError(null)
    setSplitUploadSuccess(null)
    try {
      const result = await uploadDatasetSplits(datasetId, splitFile)
      // Build detailed success message
      let successMsg = t('uploadPage.splitUpdatedSlides', { count: result.updated_count })
      if (result.auto_val_count > 0) {
        successMsg += `. ${t('uploadPage.splitAutoAssignedVal', { count: result.auto_val_count })}`
      }
      if (result.not_found_count > 0) {
        successMsg += `. ${t('uploadPage.splitFilesNotFound', { count: result.not_found_count })}`
      }
      setSplitUploadSuccess(successMsg)
      setSplitFile(null)
      return true
    } catch (e) {
      console.error("Failed to upload splits", e)
      setSplitFileError(String(e))
      return false
    } finally {
      setUploadingSplit(false)
    }
  }

  // --- Render ---

  return (
    <div className="flex flex-col h-full w-full">
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
          onDatasetNameChange={setDatasetName}
          uploadMode={uploadMode}
          onUploadModeChange={setUploadMode}
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
          existingDatasetSource={existingDatasetSource}
          showValidation={showValidation}
          fromAIChat={fromAIChat}
          isPublic={isPublic}
          onIsPublicChange={setIsPublic}
          onNext={async () => {
            const trimmedDatasetName = datasetName.trim()
            if (
              trimmedDatasetName &&
              !isExistingDataset &&
              existingDatasetOwners.has(trimmedDatasetName.toLowerCase())
            ) {
              toastError(t('uploadPage.datasetNameExistsForCurrentUser'))
              return
            }
            if (isExistingDataset && datasetId) {
              const resolvedSource = getResolvedDatasetSource()
              if (resolvedSource && resolvedSource !== existingDatasetSource) {
                try {
                  await updateDatasetSource(datasetId, resolvedSource)
                } catch (e) {
                  console.warn('Failed to update dataset source organ:', e)
                }
              }
            }
            setStep(2)
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
          <div className="flex-none mb-2 px-2 sm:px-0">
            <PageHeader
              title={t('uploadPage.title')}
              description={<span className="text-xs sm:text-base">{t('uploadPage.description')}</span>}
            >
              <Button
                variant="outline"
                onClick={() => navigate('/dashboard')}
                className="gap-2 h-9 sm:h-10 text-xs sm:text-sm"
              >
                <ArrowLeft className="w-4 h-4" />
                <span className="hidden sm:inline">{t('uploadPage.backToDashboard')}</span>
                <span className="sm:hidden">{t('uploadPage.back')}</span>
              </Button>
            </PageHeader>
          </div>
          <div className="flex-none mb-2 px-2 sm:px-0">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between bg-slate-50/50 p-3 sm:p-2 sm:px-4 rounded-xl border border-slate-100 gap-3">
              <div className="flex items-center gap-3 sm:gap-4 text-left">
                <div className="p-2 sm:p-3 bg-white rounded-lg sm:rounded-xl shadow-sm border border-slate-100 flex-shrink-0">
                  {uploadMode === 'classification' ? (
                    <Tags className="w-5 h-5 sm:w-6 sm:h-6 text-blue-600" />
                  ) : uploadMode === 'segmentation' ? (
                    <Layers className="w-5 h-5 sm:w-6 sm:h-6 text-violet-600" />
                  ) : (
                    <Activity className="w-5 h-5 sm:w-6 sm:h-6 text-emerald-600" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="text-lg sm:text-xl font-bold text-slate-900 truncate max-w-[150px] sm:max-w-none">{datasetName}</h2>
                    {isExistingDataset && (
                      <span className="px-2 py-0.5 bg-amber-50 text-amber-600 rounded-full text-[9px] sm:text-[10px] font-bold border border-amber-100 whitespace-nowrap">
                        {t('uploadPage.appendingData')}
                      </span>
                    )}
                  </div>
                  <p className="text-xs sm:text-sm text-slate-500">
                    {currentDataType === 'patch' ? t('uploadPage.patchCollection') : currentDataType === 'wsi' ? t('uploadPage.wsiCollection') : t('uploadPage.dataset')}
                    {' · '}
                    <span className="capitalize">{uploadMode === 'classification' ? t('uploadPage.classification') : uploadMode === 'survival' ? t('uploadPage.survival') : t('uploadPage.segmentation')}</span>
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" className="rounded-xl px-4 h-9 sm:h-10 w-full sm:w-auto shrink-0 justify-center" onClick={() => setStep(1)}>
                <Edit2 className="w-4 h-4 mr-2" /> {t('uploadPage.changeInfo')}
              </Button>
            </div>
          </div>


          {localItems.length === 0 && !isExistingDataset ? (
            <div className="flex-1 flex flex-col items-center justify-center p-4 sm:p-8 bg-slate-50/50 rounded-2xl sm:rounded-3xl m-2 sm:m-4 border border-slate-100">
              {/* Show CSV ready card when we have a splitFile from AI Chat */}
              {splitFile && (
                <div className="w-full max-w-2xl mb-6 p-4 bg-gradient-to-r from-green-50 to-emerald-50 border border-green-200 rounded-xl">
                  <div className="flex items-start gap-3">
                    <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0">
                      <FileSpreadsheet className="w-5 h-5 text-green-600" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h4 className="font-semibold text-green-800">{t('uploadPage.labelFileReady')}</h4>
                      <p className="text-sm text-green-700 mt-1">
                        <span className="font-medium">{splitFile.name}</span> {t('uploadPage.labelFileLoaded')}
                      </p>
                      <p className="text-xs text-green-600 mt-2">
                        {t('uploadPage.dropImageFilesBelow')}
                      </p>
                    </div>
                  </div>
                </div>
              )}
              <div
                className={`w-full max-w-4xl min-h-[300px] sm:min-h-[500px] border-2 border-dashed rounded-[1.5rem] sm:rounded-[2.5rem] p-8 sm:p-24 flex flex-col items-center justify-center text-center transition-all cursor-pointer shadow-sm ${isDragging ? 'border-blue-500 bg-blue-50/50 scale-[1.01] ring-8 ring-blue-500/5' : 'border-slate-300 hover:border-blue-400 hover:bg-white hover:shadow-md bg-white'
                  }`}
                onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={async e => {
                  e.preventDefault()
                  setIsDragging(false)
                  const result = await collectItemsFromDataTransfer(e.dataTransfer)
                  if (result.unsupportedFileNames && result.unsupportedFileNames.length > 0) {
                    toastError(t('uploadPage.skippedUnsupportedFiles', { count: result.unsupportedFileNames.length, files: result.unsupportedFileNames.slice(0, 3).join(', '), more: result.unsupportedFileNames.length > 3 ? '...' : '', extensions: ALL_EXTENSIONS.join(', ') }))
                  }
                  await processCollectionResult(result)
                }}
                onClick={supportsNativePicker ? handleLocalPathSelect : undefined}
              >
                <div className="w-16 h-16 sm:w-24 sm:h-24 bg-blue-50 rounded-full flex items-center justify-center mb-4 sm:mb-8">
                  <UploadCloud className="w-8 h-8 sm:w-12 sm:h-12 text-blue-600" />
                </div>
                <h3 className="text-xl sm:text-3xl font-bold text-slate-900 mb-2 sm:mb-4">{t('uploadPage.dropFilesHere')}</h3>
                <p className="text-sm sm:text-lg text-slate-500 mb-2 sm:mb-4 max-w-xl leading-relaxed px-4">
                  {uploadMode === 'segmentation' ? t('uploadPage.supportedFormatsPatch') : t('uploadPage.supportedFormats')}
                </p>
                <p className="text-xs sm:text-sm text-slate-400 mb-4 sm:mb-6 max-w-xl leading-relaxed px-4">
                  {uploadMode === 'classification' ? t('uploadPage.dropHintClassification') : uploadMode === 'survival' ? t('uploadPage.dropHintSurvival') : t('uploadPage.dropHintSegmentation')}
                </p>
                {uploadMode === 'segmentation' && (
                  <div className="mb-6 sm:mb-10 text-left w-full max-w-sm transition-all">
                    <div className="flex items-center gap-2 mb-3 text-sm font-semibold text-slate-800">
                      <FolderOpen className="w-4 h-4 text-amber-500" />
                      {t('uploadPage.folderStructureTitle')}
                    </div>
                    <div className="space-y-2 text-xs text-slate-600 font-medium">

                      {/* Folder Item */}
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-default">
                        <Folder className="w-4 h-4 text-blue-400 shrink-0" />
                        <span className="truncate">{t('uploadPage.folderExampleFolder')}</span>
                      </div>

                      {/* Inside Folder */}
                      <div className="pl-6 space-y-1.5 border-l-2 border-slate-100 ml-3">
                        <div className="flex items-center gap-2 px-2 py-1 rounded-md cursor-default">
                          <Image className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                          <span className="truncate">{t('uploadPage.folderExampleImg1')}</span>
                        </div>
                        <div className="flex items-center gap-2 px-2 py-1 rounded-md cursor-default">
                          <FileJson className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                          <span className="truncate">{t('uploadPage.folderExampleJson1')}</span>
                        </div>
                        <div className="flex items-center gap-2 px-2 py-1 rounded-md cursor-default">
                          <Image className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                          <span className="truncate">{t('uploadPage.folderExampleImg2')}</span>
                        </div>
                        <div className="flex items-center gap-2 px-2 py-1 rounded-md cursor-default">
                          <FileJson className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                          <span className="truncate">{t('uploadPage.folderExampleJson2')}</span>
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 pt-2 text-[11px] text-slate-500 bg-slate-50 p-2.5 rounded-lg flex flex-row items-center gap-2.5">
                      <div className="flex items-center justify-center bg-blue-100 w-4 h-4 rounded-full shrink-0">
                        <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                      </div>
                      <p className="leading-none m-0 p-0 text-slate-500">{t('uploadPage.folderStructureNote')}</p>
                    </div>
                  </div>
                )}

                {(uploadMode === 'classification' || uploadMode === 'survival') && (
                  <div className="mb-6 sm:mb-10 text-left w-full max-w-sm transition-all">
                    <div className="flex items-center gap-2 mb-3 text-sm font-semibold text-slate-800">
                      <FolderOpen className="w-4 h-4 text-amber-500" />
                      {t('uploadPage.folderStructureTitle')}
                    </div>
                    <div className="space-y-2 text-xs text-slate-600 font-medium">

                      {/* Folder Item */}
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-default">
                        <Folder className="w-4 h-4 text-blue-400 shrink-0" />
                        <span className="truncate">{t('uploadPage.folderExampleFolder')}</span>
                      </div>

                      {/* Inside Folder */}
                      <div className="pl-6 space-y-1.5 border-l-2 border-slate-100 ml-3 mb-2">
                        <div className="flex items-center gap-2 px-2 py-1 rounded-md cursor-default">
                          <Image className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                          <span className="truncate">{t('uploadPage.folderExampleImg1')}</span>
                        </div>
                        <div className="flex items-center gap-2 px-2 py-1 rounded-md cursor-default">
                          <Image className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                          <span className="truncate">{t('uploadPage.folderExampleImg2')}</span>
                        </div>
                      </div>

                      {/* Excel File outside folder */}
                      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md cursor-default mt-2">
                        <FileSpreadsheet className="w-4 h-4 text-emerald-500 shrink-0" />
                        <span className="truncate">
                          {uploadMode === 'classification'
                            ? t('uploadPage.folderExampleExcelClassification')
                            : t('uploadPage.folderExampleExcelSurvival')}
                        </span>
                      </div>
                    </div>
                  </div>
                )}
                {supportsNativePicker && (
                  <Button size="lg" className="px-6 sm:px-10 h-12 sm:h-14 text-base sm:text-lg rounded-full shadow-lg shadow-blue-500/20">
                    {t('uploadPage.browseFiles')}
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <>
              {!segmentationJsonOnlyAppend && (
                <>
                  {/* Toolbar */}
                  <div className="flex-none px-3 sm:px-6 py-2 bg-slate-50 border-b border-slate-200 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 sm:gap-4">
                    <div className="flex items-center gap-3 sm:gap-4 flex-wrap">
                      <label className="flex items-center gap-2 text-sm font-medium text-slate-600 cursor-pointer select-none shrink-0">
                        <Checkbox
                          checked={selectedItems.size === localItems.length && localItems.length > 0}
                          onCheckedChange={() => toggleSelectAll()}
                        />
                        <span className="hidden sm:inline">{t('uploadPage.selectAll', { count: localItems.length })}</span>
                        <span className="sm:hidden">{t('uploadPage.fileCount', { count: localItems.length })}</span>
                      </label>
                      {skippedDuplicateCount > 0 && (
                        <span className="text-[10px] sm:text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded-full border border-amber-200 whitespace-nowrap">
                          {t('uploadPage.duplicateCount', { count: skippedDuplicateCount })}
                        </span>
                      )}
                      {selectedItems.size > 0 && (
                        <div className="flex items-center gap-1.5 sm:gap-2 animate-in fade-in slide-in-from-left-4 duration-200">
                          <div className="h-4 w-px bg-slate-300 mx-1 hidden sm:block" />
                          <Button size="sm" variant="secondary" onClick={() => setShowBulkEdit(true)} className="h-7 sm:h-8 text-[10px] sm:text-xs font-medium px-2 sm:px-3">
                            <Edit2 className="w-3 h-3 mr-1 sm:mr-1.5" />
                            {t('uploadPage.edit')}
                          </Button>
                          <Button size="sm" variant="destructive" onClick={removeSelectedItems} className="h-7 sm:h-8 text-[10px] sm:text-xs font-medium bg-red-50 text-red-600 hover:bg-red-100 border border-red-200 px-2 sm:px-3">
                            <Trash2 className="w-3 h-3 mr-1 sm:mr-1.5" />
                            {t('uploadPage.delete')}
                          </Button>
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2 px-3 sm:px-4 py-1.5 bg-blue-50 text-blue-700 rounded-full text-[10px] sm:text-sm font-semibold border border-blue-100 shadow-sm justify-center sm:justify-start">
                      <UploadCloud className="w-3 h-3 sm:w-4 sm:h-4" />
                      {t('uploadPage.dropMoreFiles')}
                    </div>
                  </div>
                </>
              )}

              {/* Table Area */}
              <Card className="flex-1 min-h-0 flex flex-col overflow-hidden mb-2 sm:mb-4 mx-2 sm:mx-0 max-h-[600px]">
                {segmentationJsonOnlyAppend ? (
                  <div className="flex-1 bg-white p-6 sm:p-8 flex items-center justify-center">
                    <div className="max-w-2xl w-full rounded-2xl border border-green-200 bg-green-50 px-5 py-6 text-left">
                      <div className="flex items-start gap-3">
                        <FileJson className="w-6 h-6 text-green-600 shrink-0 mt-0.5" />
                        <div>
                          <h3 className="text-base sm:text-lg font-semibold text-green-900">{t('uploadPage.jsonOnlyAppendTitle')}</h3>
                          <p className="text-sm text-green-800 mt-2 leading-relaxed">
                            {t('uploadPage.jsonOnlyAppendDesc', { count: segmentationJsonFiles.size })}
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
                    className="flex-1 overflow-x-auto overflow-y-auto bg-white"
                    ref={tableContainerRef}
                    onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
                    onDragLeave={() => setIsDragging(false)}
                    onDrop={async e => {
                      e.preventDefault()
                      setIsDragging(false)
                      const result = await collectItemsFromDataTransfer(e.dataTransfer)
                      if (result.unsupportedFileNames && result.unsupportedFileNames.length > 0) {
                        toastError(t('uploadPage.skippedUnsupportedFilesShort', { count: result.unsupportedFileNames.length, files: result.unsupportedFileNames.slice(0, 3).join(', '), more: result.unsupportedFileNames.length > 3 ? '...' : '' }))
                      }
                      await processCollectionResult(result)
                    }}
                  >
                  {isDragging && (
                    <div className="absolute inset-0 z-40 bg-blue-500/10 backdrop-blur-[1px] flex items-center justify-center border-4 border-blue-500 border-dashed m-4 rounded-xl pointer-events-none">
                      <div className="bg-white px-8 py-4 rounded-full shadow-xl font-bold text-blue-600 flex items-center gap-3">
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
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[180px] sm:min-w-[200px]">{t('uploadPage.fileName')}</th>
                        {uploadMode === 'classification' ? (
                          <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[120px] sm:min-w-[150px]">{t('uploadPage.label')} <span className="text-red-500">*</span></th>
                        ) : uploadMode === 'survival' ? (
                          <>
                            <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[90px] sm:min-w-[100px]">{t('uploadPage.eventTime')} <span className="text-red-500">*</span></th>
                            <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[80px] sm:min-w-[90px]">{t('uploadPage.status')} <span className="text-red-500">*</span></th>
                          </>
                        ) : uploadMode === 'segmentation' ? (
                          <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[80px] sm:min-w-[100px]">{t('uploadPage.maskStatus')}</th>
                        ) : null}
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[100px] sm:min-w-[120px]">{t('uploadPage.caseId')}</th>
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[70px] sm:min-w-[80px]">{t('uploadPage.age')}</th>
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[90px] sm:min-w-[100px]">{t('uploadPage.gender')}</th>
                        <th className="w-10 px-3 py-2 bg-slate-50"></th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-slate-100">
                      {paginatedItems.map(item => {
                        const meta = localMetadata.get(item.key) || { ...defaultMetadata }
                        const isSelected = selectedItems.has(item.key)
                        // Validation based on mode
                        const hasError = showValidation && (
                          uploadMode === 'classification'
                            ? !meta.label.trim()
                            : uploadMode === 'survival'
                              ? (!meta.event_time.trim() || !meta.event_status.trim())
                              : false
                        )

                        return (
                          <tr key={item.key} className={`group hover:bg-slate-50 transition-colors ${isSelected ? 'bg-blue-50/30' : ''}`}>
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <Checkbox
                                checked={isSelected}
                                onCheckedChange={() => toggleSelection(item.key)}
                              />
                            </td>
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <div className="flex flex-col min-w-0">
                                <span className="text-sm font-semibold text-slate-900 truncate max-w-[150px] sm:max-w-[300px]" title={item.name}>{item.name}</span>
                                <div className="flex items-center gap-2 mt-1">
                                  <span className="text-[9px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded font-bold tracking-wider uppercase">
                                    {(item.name.split('.').pop() || 'tmp').substring(0, 4)}
                                  </span>
                                  {item.path && <span className="text-[9px] text-slate-400 font-mono">LOCAL</span>}
                                  {item.type === 'mrxs' && item.missingAssociated && (
                                    <span
                                      className="text-[9px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-bold flex items-center gap-1"
                                      title={t('uploadPage.missingDataFolder', { folder: getBaseName(item.name) })}
                                    >
                                      {t('uploadPage.dataMissing')}
                                    </span>
                                  )}
                                </div>
                              </div>
                            </td>
                            {/* Classification: Label input | Survival: Event Time & Status inputs | Segmentation: no extra required fields */}
                            {uploadMode === 'classification' ? (
                              <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                <input
                                  className={`w-full px-2 py-1.5 text-sm border rounded-lg hover:border-blue-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all ${hasError ? 'border-red-500 bg-red-50' : 'border-slate-100 bg-slate-50/50 hover:bg-white focus:bg-white'}`}
                                  placeholder={t('uploadPage.enterLabel')}
                                  value={meta.label}
                                  onChange={e => handleMetadataChange(item.key, 'label', e.target.value)}
                                />
                              </td>
                            ) : uploadMode === 'survival' ? (
                              <>
                                <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                  <input
                                    type="number"
                                    step="0.1"
                                    className={`w-full px-2 py-1.5 text-sm border rounded-lg hover:border-emerald-400 focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 outline-none transition-all ${hasError && !meta.event_time.trim() ? 'border-red-500 bg-red-50' : 'border-slate-100 bg-slate-50/50 hover:bg-white focus:bg-white'}`}
                                    placeholder={t('uploadPage.months')}
                                    value={meta.event_time}
                                    onChange={e => handleMetadataChange(item.key, 'event_time', e.target.value)}
                                  />
                                </td>
                                 <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                   <Select
                                     value={meta.event_status}
                                     onChange={(v) => handleMetadataChange(item.key, 'event_status', v)}
                                     options={[
                                       { value: '1', label: t('uploadPage.eventOption') },
                                       { value: '0', label: t('uploadPage.censoredOption') },
                                     ]}
                                     placeholder={t('uploadPage.statusDefault')}
                                     triggerClassName={hasError && !meta.event_status.trim() ? 'border-red-500 bg-red-50' : ''}
                                   />
                                 </td>
                              </>
                            ) : uploadMode === 'segmentation' ? (
                              <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                {matchedMasks.has(item.key) ? (
                                  <span className="text-sm text-green-700">
                                    {t('uploadPage.maskFound')}
                                  </span>
                                ) : (
                                  <span className="text-sm text-slate-400">
                                    {t('uploadPage.maskNotFound')}
                                  </span>
                                )}
                              </td>
                            ) : null}
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <input
                                className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                placeholder={t('uploadPage.caseIdPlaceholder')}
                                value={meta.case_id}
                                onChange={e => handleMetadataChange(item.key, 'case_id', e.target.value)}
                              />
                            </td>
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <input
                                type="number"
                                className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                placeholder={t('uploadPage.agePlaceholder')}
                                value={meta.age}
                                onChange={e => handleMetadataChange(item.key, 'age', e.target.value)}
                              />
                            </td>
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <Select
                                value={meta.gender}
                                onChange={(v) => handleMetadataChange(item.key, 'gender', v)}
                                options={[
                                  { value: 'Male', label: t('uploadPage.genderM') },
                                  { value: 'Female', label: t('uploadPage.genderF') },
                                  { value: 'Unspecified', label: '?' },
                                ]}
                                placeholder="-"
                              />
                            </td>
                            <td className="px-3 sm:px-4 py-3 align-middle text-right border-b border-slate-100">
                              <button
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
                  </div>
                )}
              </Card>

              {/* Dataset Metadata Configuration - metadata update via File */}
              <Card className="flex-none p-3 sm:p-4 mb-2 transition-all mx-2 sm:mx-0">
                <div
                  className="flex items-center justify-between cursor-pointer select-none"
                  onClick={() => setShowSplitConfig(!showSplitConfig)}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <FileSpreadsheet className="w-4 h-4 sm:w-5 sm:h-5 text-blue-600 shrink-0" />
                    <div className="min-w-0">
                      <h2 className="text-sm sm:text-base font-semibold text-slate-900 truncate">
                        {t('uploadPage.datasetMetadataConfig')}
                      </h2>
                      {!showSplitConfig && (
                        <p className="text-[10px] sm:text-xs text-slate-500 truncate">
                          {t('uploadPage.optionalMetadataUpload')}
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 ml-2">
                    {showSplitConfig && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDownloadTemplate();
                        }}
                        className="text-[10px] sm:text-xs h-7 gap-1 px-2"
                      >
                        <Download className="w-3 h-3" />
                        {t('uploadPage.csvTemplate')}
                      </Button>
                    )}

                    {showSplitConfig ? (
                      <ChevronUp className="w-4 h-4 text-slate-400" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-slate-400" />
                    )}
                  </div>
                </div>

                {showSplitConfig && (
                  <div className="mt-4 animate-in slide-in-from-top-2 duration-200">
                    <p className="text-xs sm:text-sm text-gray-500 mb-3 leading-relaxed">
                      {t('uploadPage.uploadMetadataDescription')}
                    </p>

                    {/* Help text - different for classification vs survival vs segmentation */}
                    <div className="mb-4 p-2 sm:p-3 bg-blue-50 rounded-lg text-[10px] sm:text-sm text-blue-800">
                      <p className="font-bold mb-1">{t('uploadPage.fileFormatTitle', { mode: uploadMode === 'classification' ? t('uploadPage.classification') : uploadMode === 'survival' ? t('uploadPage.survival') : t('uploadPage.segmentation') })}</p>
                      <ul className="list-disc list-inside space-y-0.5 text-blue-700">
                        {uploadMode === 'classification' && (
                          <li><code className="bg-blue-100 px-1 rounded">filename</code>, <code className="bg-blue-100 px-1 rounded">label</code></li>
                        )}
                        {uploadMode === 'survival' && (
                          <li><code className="bg-blue-100 px-1 rounded">filename</code></li>
                        )}
                        {uploadMode === 'survival' && (
                          <li><code className="bg-blue-100 px-1 rounded">event_time</code>, <code className="bg-blue-100 px-1 rounded">event_status</code></li>
                        )}
                        {uploadMode === 'segmentation' && (
                          <li><code className="bg-blue-100 px-1 rounded">filename</code></li>
                        )}
                        <li className="hidden sm:list-item">{t('uploadPage.optionalFields')} <code className="bg-blue-100 px-1 rounded">case_id</code>, <code className="bg-blue-100 px-1 rounded">age</code>, <code className="bg-blue-100 px-1 rounded">gender</code>, <code className="bg-blue-100 px-1 rounded">split</code></li>
                      </ul>
                    </div>

                    <div
                      className={`flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 p-3 sm:p-4 rounded-lg border border-dashed transition-all ${isCsvDragging ? 'border-blue-400 bg-blue-50/50' : 'bg-gray-50 border-gray-300 hover:border-blue-300'}`}
                      onDragOver={e => { e.preventDefault(); e.stopPropagation(); setIsCsvDragging(true) }}
                      onDragLeave={e => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setIsCsvDragging(false) }}
                      onDrop={handleCsvDrop}
                    >
                      {splitFile ? (
                        // Show selected file info when we have a splitFile
                        <div className="flex-1 flex items-center gap-3">
                          <div className="flex items-center gap-2 px-3 py-2 bg-white rounded-lg border border-green-200 flex-1 min-w-0">
                            <FileSpreadsheet className="w-4 h-4 text-green-600 flex-shrink-0" />
                            <span className="text-sm text-gray-700 truncate">{splitFile.name}</span>
                            <span className="text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded-full flex-shrink-0">
                              {(splitFile.size / 1024).toFixed(1)} KB
                            </span>
                          </div>
                          <Tooltip content={t('uploadPage.removeFile')}>
                          <button
                            onClick={() => setSplitFile(null)}
                            className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors flex-shrink-0"
                          >
                            <X className="w-4 h-4" />
                          </button>
                          </Tooltip>
                        </div>
                      ) : (
                        // Show file input when no file is selected
                        <div className="flex-1 overflow-hidden">
                          <input
                            type="file"
                            accept=".csv,.xlsx,.xls"
                            className="block w-full text-[10px] sm:text-sm text-gray-500 file:mr-2 sm:file:mr-4 file:py-1.5 sm:file:py-2 file:px-3 sm:file:px-4 file:rounded-full file:border-0 file:text-[10px] sm:file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 cursor-pointer"
                            onChange={handleSplitFileSelect}
                          />
                        </div>
                      )}
                      {splitFile && (
                        <div className="flex items-center gap-2 text-[10px] sm:text-sm text-green-600 font-medium bg-green-50 px-3 py-1.5 rounded-lg border border-green-100 justify-center">
                          <CheckCircle2 className="w-3 h-3 sm:w-4 sm:h-4" />
                          {t('uploadPage.ready')}
                        </div>
                      )}
                    </div>

                    {/* Error message */}
                    {splitFileError && (
                      <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                        <span className="font-medium">{t('uploadPage.errorPrefix')} </span>{splitFileError}
                      </div>
                    )}

                    {/* Success message */}
                    {splitUploadSuccess && (
                      <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
                        <span className="font-medium">{t('uploadPage.successPrefix')} </span>{splitUploadSuccess}
                      </div>
                    )}
                  </div>
                )}
              </Card>

              {/* Footer - Fixed at bottom */}
              <div className="flex-none bg-white border border-slate-200 rounded-xl px-4 sm:px-8 py-3 flex flex-col sm:flex-row items-stretch sm:items-center justify-between shadow-sm z-30 gap-4 sm:gap-0 mt-2">
                <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-8">
                  <div className="text-xs sm:text-sm text-slate-500 whitespace-nowrap">
                    {t('uploadPage.readyToRegister', { count: readyToUploadCount })}
                  </div>
                  {totalPages > 1 && (
                    <div className="flex items-center gap-3">
                      <div className="h-4 w-px bg-slate-200 hidden sm:block" />
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-8 w-8 hover:bg-slate-50 shrink-0"
                          onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                          disabled={currentPage === 1}
                        >
                          <ChevronLeft className="h-4 w-4 text-slate-600" />
                        </Button>
                        <span className="text-[10px] sm:text-xs font-semibold text-slate-600 min-w-[70px] sm:min-w-[80px] text-center whitespace-nowrap">
                          {t('uploadPage.pageIndicator', { current: currentPage, total: totalPages })}
                        </span>
                        <Button
                          variant="outline"
                          size="icon"
                          className="h-8 w-8 hover:bg-slate-50 shrink-0"
                          onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                          disabled={currentPage === totalPages}
                        >
                          <ChevronRight className="h-4 w-4 text-slate-600" />
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
                <div className="flex flex-col sm:flex-row gap-3">
                  {submitError && (
                    <div className="flex items-center gap-2 px-3 py-1.5 bg-red-50 text-red-600 rounded-lg text-xs">
                      <AlertCircle className="w-4 h-4 shrink-0" />
                      <span className="truncate">{submitError}</span>
                    </div>
                  )}
                  <div className="flex gap-2">
                    <Button variant="ghost" className="h-10 flex-1 sm:flex-none" onClick={resetUpload}>
                      {t('uploadPage.cancel')}
                    </Button>
                    <Button
                      onClick={handleUpload}
                      disabled={readyToUploadCount === 0 && !splitFile}
                      className={`${isExistingDataset ? 'bg-amber-600 hover:bg-amber-700' : 'bg-green-600 hover:bg-green-700'} text-white flex-1 sm:min-w-[160px] rounded-xl h-10 shadow-sm`}
                    >
                      {isExistingDataset ? (
                        <>
                          <Plus className="w-4 h-4 mr-2 shrink-0" />
                          <span className="truncate">{readyToUploadCount === 0 && splitFile ? t('uploadPage.uploadCsv') : t('uploadPage.addToDataset')}</span>
                        </>
                      ) : (
                        <>
                          <Download className="w-4 h-4 mr-2 shrink-0" />
                          <span className="truncate">{readyToUploadCount === 0 && splitFile ? t('uploadPage.uploadCsv') : t('uploadPage.registerAll')}</span>
                        </>
                      )}
                    </Button>
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}
    </div>
  )
}
