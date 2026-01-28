import { useState, useMemo, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import * as XLSX from 'xlsx'
import {
  Download,
  X,
  AlertCircle,
  UploadCloud,
  Settings2,
  Trash2,
  Edit2,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Database,
  ArrowRight,
  Plus,
  Tags,
  Activity,
  ArrowLeft,
  FileSpreadsheet,
  CheckCircle2
} from 'lucide-react'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Checkbox } from '../components/ui/checkbox'
import { useBackgroundTask, UploadTaskFile } from '../contexts/BackgroundTaskContext'
import { checkDuplicateFilenames, fetchDatasets, uploadDatasetSplits, downloadCSVTemplate } from '../api'
import { useLocation } from 'react-router-dom'
import { useToast } from '../contexts/ToastContext'

interface LocalItem {
  key: string
  name: string
  path?: string
  file?: File
  associatedFiles?: File[]
  associatedPaths?: string[]
  type?: 'mrxs' | 'tmap' | 'standard'
  missingAssociated?: boolean  // True if MRXS/TMAP is missing associated data
}

interface ElectronFilesApi {
  selectFiles?: (options?: { title?: string; filters?: { name: string; extensions: string[] }[] }) => Promise<string[] | null>
}

interface ElectronApi {
  files?: ElectronFilesApi
}

declare const window: Window & { api?: ElectronApi }

// Upload mode type: classification (label) or survival (event_time, event_status)
type UploadMode = 'classification' | 'survival'

// Metadata type with all possible fields
interface FileMetadata {
  label: string
  case_id: string
  age: string
  gender: string
  source: string
  // Survival analysis fields
  event_time: string
  event_status: string
}

const defaultMetadata: FileMetadata = {
  label: '',
  case_id: '',
  age: '',
  gender: '',
  source: '',
  event_time: '',
  event_status: ''
}

export default function RegisterPage() {
  const { error: toastError } = useToast()
  const navigate = useNavigate()
  const { addUploadTask } = useBackgroundTask()

  // Upload mode state (classification or survival)
  const [uploadMode, setUploadMode] = useState<UploadMode>('classification')

  // Dataset name (required for grouping files)
  const [datasetName, setDatasetName] = useState('')
  // Dataset ID (UUID) - only set when using existing dataset or passed from navigation
  const [datasetId, setDatasetId] = useState<string | null>(null)

  // Steps: 1 - Dataset Name, 2 - File Upload
  const [step, setStep] = useState(1)
  // Store full dataset info including id and name
  const [existingDatasetsInfo, setExistingDatasetsInfo] = useState<{dataset_id: string | null, dataset_name: string, dataset_type: UploadMode}[]>([])
  const [existingDatasets, setExistingDatasets] = useState<string[]>([])
  const [existingDatasetTypes, setExistingDatasetTypes] = useState<Map<string, UploadMode>>(new Map())
  // Map from dataset_name to dataset_id for quick lookup
  const [datasetNameToId, setDatasetNameToId] = useState<Map<string, string | null>>(new Map())
  // Toggle for Dataset Splits Configuration visibility
  const [showSplitConfig, setShowSplitConfig] = useState(false)

  // Checking for initial dataset from navigation state
  const location = useLocation()
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

  useEffect(() => {
    const loadDatasets = async () => {
      try {
        const data = await fetchDatasets()
        // Store full dataset info
        setExistingDatasetsInfo(data.items.map(d => ({
          dataset_id: d.dataset_id,
          dataset_name: d.dataset_name,
          dataset_type: d.dataset_type as UploadMode
        })))
        setExistingDatasets(data.items.map(d => d.dataset_name))
        const typeMap = new Map<string, UploadMode>()
        const idMap = new Map<string, string | null>()
        data.items.forEach(d => {
          typeMap.set(d.dataset_name, d.dataset_type as UploadMode)
          idMap.set(d.dataset_name, d.dataset_id)
        })
        setExistingDatasetTypes(typeMap)
        setDatasetNameToId(idMap)
      } catch (err) {
        console.error('Failed to load datasets', err)
      }
    }
    loadDatasets()
  }, [])

  const isExistingDataset = useMemo(() => {
    return existingDatasets.includes(datasetName.trim())
  }, [datasetName, existingDatasets])

  // Auto-select analysis type and datasetId for existing datasets
  useEffect(() => {
    const trimmed = datasetName.trim()
    if (existingDatasetTypes.has(trimmed)) {
      setUploadMode(existingDatasetTypes.get(trimmed)!)
    }
    // Set datasetId when user types or selects an existing dataset name
    if (datasetNameToId.has(trimmed)) {
      setDatasetId(datasetNameToId.get(trimmed) ?? null)
    } else {
      // New dataset - clear datasetId
      setDatasetId(null)
    }
  }, [datasetName, existingDatasetTypes, datasetNameToId])

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

  // Pagination State
  const [currentPage, setCurrentPage] = useState(1)
  const itemsPerPage = 10

  // Batch metadata state (temporary for the modal)
  const [batchMetadata, setBatchMetadata] = useState<FileMetadata>({ ...defaultMetadata })

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

  // --- Logic Helpers ---

  const generateCaseId = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    let result = ''
    for (let i = 0; i < 5; i++) {
      result += chars.charAt(Math.floor(Math.random() * chars.length))
    }
    return result
  }

  const organSources = [
    'Adrenal Gland', 'Aorta', 'Bladder', 'Blood Vessel', 'Bone', 'Bone Marrow',
    'Brain', 'Breast', 'Bronchus', 'Cartilage', 'Cervix', 'Colon',
    'Endometrium', 'Esophagus', 'Eye', 'Fallopian Tube', 'Gallbladder',
    'Heart', 'Joint', 'Kidney', 'Larynx', 'Liver', 'Lung', 'Lymph Node',
    'Mesentery', 'Muscle', 'Oral Cavity', 'Ovary', 'Pancreas', 'Parathyroid',
    'Penis', 'Peripheral Nerve', 'Peritoneum', 'Pharynx', 'Pituitary Gland',
    'Pleura', 'Prostate', 'Rectum', 'Retina', 'Salivary Gland', 'Skin',
    'Small Intestine', 'Soft Tissue', 'Spinal Cord', 'Spleen', 'Stomach',
    'Testis', 'Thymus', 'Thyroid', 'Tongue', 'Tonsil', 'Trachea',
    'Ureter', 'Urethra', 'Uterus', 'Vagina', 'Vulva', 'Other'
  ]

  // WSI file extensions
  const wsiExtensions = [
    '.svs', '.svslide', '.dyj', '.dyqx', '.tif', '.tiff', '.ndpi',
    '.vms', '.vmu', '.isyntax', '.ibl', '.kfb', '.scn', '.mrxs',
    '.mds', '.mdsx', '.vsi', '.qptiff', '.sdpc', '.tmap', '.tron',
    '.bif', '.zyp'
  ]

  // Patch/image file extensions
  const patchExtensions = ['.png', '.jpg', '.jpeg', '.bmp']

  // All supported file extensions (WSI + Patch)
  const allSupportedExtensions = [...wsiExtensions, ...patchExtensions]

  const supportsNativePicker = typeof window !== 'undefined' && !!window.api?.files?.selectFiles

  const isSupportedName = (name: string) => {
    const normalized = name.toLowerCase()
    return allSupportedExtensions.some(ext => normalized.endsWith(ext))
  }

  const isTmapDataFile = (name: string) => /\.dt\d+$/i.test(name.toLowerCase())
  const getBaseName = (name: string) => {
    const lastDot = name.lastIndexOf('.')
    return lastDot > 0 ? name.substring(0, lastDot) : name
  }
  const getFilePath = (file: File) => (file as any).path as string | undefined
  const buildFileKey = (file: File) => `${file.name}-${file.size}-${file.lastModified}`

  // --- File Collection Logic ---
  // Design: User drags a single folder containing WSI files.
  // Sub-folders are ONLY for MRXS associated data (same name as .mrxs file).
  // Files in sub-folders should NOT be treated as independent WSI files.

  const readAllEntries = async (directoryEntry: any): Promise<any[]> => {
    const reader = directoryEntry.createReader()
    const entries: any[] = []
    while (true) {
      const batch: any[] = await new Promise(resolve => reader.readEntries(resolve, () => resolve([])))
      if (!batch.length) break
      entries.push(...batch)
    }
    return entries
  }

  // Recursively collect all files from a directory (for MRXS data folders)
  const collectAllFilesFromDirectory = async (directoryEntry: any): Promise<File[]> => {
    const entries = await readAllEntries(directoryEntry)
    const files: File[] = []
    for (const entry of entries) {
      if (entry.isFile) {
        const file = await new Promise<File | null>(resolve => {
          entry.file((f: File) => resolve(f), () => resolve(null))
        })
        if (file) files.push(file)
      } else if (entry.isDirectory) {
        const subFiles = await collectAllFilesFromDirectory(entry)
        files.push(...subFiles)
      }
    }
    return files
  }

  interface MrxsDataFolder {
    folderName: string
    folderFiles: File[]
  }

  interface CollectionResult {
    items: LocalItem[]
    orphanFolders: MrxsDataFolder[]  // Folders without matching .mrxs
    orphanDtFiles: Map<string, File[]>  // baseName -> dt files without matching .tmap
  }

  const collectItemsFromDataTransfer = async (dataTransfer: DataTransfer): Promise<CollectionResult> => {
    const dataItems = Array.from(dataTransfer.items || [])
    const hasEntries = dataItems.some(item => (item as any).webkitGetAsEntry)

    // First-level files (WSI candidates) and sub-folders (MRXS data only)
    const firstLevelFiles: File[] = []
    const mrxsDataFolders: MrxsDataFolder[] = []
    // Track directly dragged folders (potential MRXS data folders dragged separately)
    const directlyDraggedFolders: MrxsDataFolder[] = []

    if (hasEntries) {
      const topEntries = dataItems.map(item => (item as any).webkitGetAsEntry?.()).filter(Boolean)

      for (const entry of topEntries) {
        if (entry.isFile) {
          // Directly dragged file -> WSI candidate
          const file = await new Promise<File | null>(resolve => {
            entry.file((f: File) => resolve(f), () => resolve(null))
          })
          if (file) firstLevelFiles.push(file)
        } else if (entry.isDirectory) {
          // Check if this folder contains WSI files (then it's a container)
          // or only data files (then it might be an MRXS data folder)
          const folderEntries = await readAllEntries(entry)
          const hasWsiFiles = folderEntries.some(e => e.isFile && isSupportedName(e.name))

          if (hasWsiFiles) {
            // This is a container folder with WSI files
            for (const subEntry of folderEntries) {
              if (subEntry.isFile) {
                const file = await new Promise<File | null>(resolve => {
                  subEntry.file((f: File) => resolve(f), () => resolve(null))
                })
                if (file) firstLevelFiles.push(file)
              } else if (subEntry.isDirectory) {
                // Sub-folder -> ONLY for MRXS associated data
                const subFolderFiles = await collectAllFilesFromDirectory(subEntry)
                mrxsDataFolders.push({
                  folderName: subEntry.name,
                  folderFiles: subFolderFiles
                })
              }
            }
          } else {
            // This might be a directly dragged MRXS data folder
            const folderFiles = await collectAllFilesFromDirectory(entry)
            directlyDraggedFolders.push({
              folderName: entry.name,
              folderFiles
            })
          }
        }
      }
    } else {
      // Fallback: no webkitGetAsEntry support
      const files = Array.from(dataTransfer.files || [])
      firstLevelFiles.push(...files)
    }

    const files = firstLevelFiles
    const folders = [...mrxsDataFolders, ...directlyDraggedFolders]

    const mrxsFiles = files.filter(f => f.name.toLowerCase().endsWith('.mrxs'))
    const tmapFiles = files.filter(f => f.name.toLowerCase().endsWith('.tmap'))
    const dtFiles = files.filter(f => isTmapDataFile(f.name))

    const result: LocalItem[] = []
    const usedFiles = new Set<File>()
    const usedFolders = new Set<string>()

    // Electron Mode Check
    const isElectron = files.length > 0 && files.some(f => getFilePath(f))

    // MRXS
    for (const mrxsFile of mrxsFiles) {
      const baseName = getBaseName(mrxsFile.name)
      // Case-insensitive matching for folder name
      const matchingFolder = folders.find(f => f.folderName.toLowerCase() === baseName.toLowerCase())
      usedFiles.add(mrxsFile)
      if (matchingFolder) usedFolders.add(matchingFolder.folderName)

      const hasAssociated = !!matchingFolder && matchingFolder.folderFiles.length > 0

      if (isElectron) {
        const path = getFilePath(mrxsFile)!
        result.push({
          key: path,
          name: mrxsFile.name,
          path,
          type: 'mrxs',
          associatedPaths: matchingFolder ? [] : undefined,
          missingAssociated: !hasAssociated
        })
      } else {
        result.push({
          key: buildFileKey(mrxsFile),
          name: mrxsFile.name,
          file: mrxsFile,
          type: 'mrxs',
          associatedFiles: matchingFolder?.folderFiles || [],
          missingAssociated: !hasAssociated
        })
      }
    }

    // TMAP
    for (const tmapFile of tmapFiles) {
      const baseName = getBaseName(tmapFile.name)
      const matchingDtFiles = dtFiles.filter(f => getBaseName(f.name) === baseName)
      usedFiles.add(tmapFile)
      matchingDtFiles.forEach(f => usedFiles.add(f))

      // TMAP dt files are optional, so no missingAssociated warning
      if (isElectron) {
        const path = getFilePath(tmapFile)!
        result.push({
          key: path,
          name: tmapFile.name,
          path,
          type: 'tmap',
          associatedPaths: matchingDtFiles.map(f => getFilePath(f)!).filter(Boolean)
        })
      } else {
        result.push({
          key: buildFileKey(tmapFile),
          name: tmapFile.name,
          file: tmapFile,
          type: 'tmap',
          associatedFiles: matchingDtFiles
        })
      }
    }

    // Standard
    for (const file of files) {
      if (usedFiles.has(file)) continue
      if (!isSupportedName(file.name)) continue
      if (isElectron) {
        const path = getFilePath(file)!
        result.push({ key: path, name: file.name, path, type: 'standard' })
      } else {
        result.push({ key: buildFileKey(file), name: file.name, file, type: 'standard' })
      }
    }

    // Collect orphan folders (MRXS data folders without matching .mrxs)
    const orphanFolders = folders.filter(f => !usedFolders.has(f.folderName))

    // Collect orphan dt files (without matching .tmap)
    const orphanDtFiles = new Map<string, File[]>()
    for (const dtFile of dtFiles) {
      if (usedFiles.has(dtFile)) continue
      const baseName = getBaseName(dtFile.name)
      if (!orphanDtFiles.has(baseName)) {
        orphanDtFiles.set(baseName, [])
      }
      orphanDtFiles.get(baseName)!.push(dtFile)
    }

    return { items: result, orphanFolders, orphanDtFiles }
  }

  // --- Interaction Logic ---

  const processCollectionResult = async (result: CollectionResult) => {
    const { items, orphanFolders, orphanDtFiles } = result

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
    const filters = [{ name: 'Supported Formats (WSI & Patch)', extensions: allSupportedExtensions.map(ext => ext.replace(/^\./, '')) }]
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
          label: batchMetadata.label || current.label,
          case_id: batchMetadata.case_id || current.case_id,
          age: batchMetadata.age || current.age,
          gender: batchMetadata.gender || current.gender,
          source: batchMetadata.source || current.source,
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
    if (localItems.length === 0 && !splitFile) return
    setShowValidation(true)
    setSubmitError(null)

    // Validate dataset name is required
    if (!datasetName.trim()) {
      setSubmitError('Dataset name is required')
      return
    }

    // 1. Handle separate Split CSV Upload if Pending
    if (splitFile) {
      const success = await handleUploadSplit()
      if (!success) {
         setSubmitError('Failed to upload CSV')
         return 
      }
      
      // If we only had a CSV and no files, we are done
      if (localItems.length === 0) {
        setStep(3)
        return
      }
    }

    if (localItems.length === 0) return

    // ... Validate based on upload mode ...
    if (uploadMode === 'classification') {
      const missingLabels = localItems.filter(item => !localMetadata.get(item.key)?.label?.trim())
      if (missingLabels.length > 0) {
        return
      }
    } else {
      // Survival mode: require event_time and event_status
      const missingSurvival = localItems.filter(item => {
        const meta = localMetadata.get(item.key)
        return !meta?.event_time?.trim() || !meta?.event_status?.trim()
      })
      if (missingSurvival.length > 0) {
        return
      }
    }

    // Prepare files for background upload task
    const uploadFiles: UploadTaskFile[] = localItems.map(item => {
      const meta = localMetadata.get(item.key)
      const age = meta?.age ? parseInt(meta.age) : undefined
      const eventTime = meta?.event_time ? parseFloat(meta.event_time) : undefined
      const eventStatus = meta?.event_status ? parseInt(meta.event_status) : undefined
      return {
        key: item.key,
        name: item.name,
        file: item.file,
        path: item.path,
        metadata: {
          // Use dataset_id for existing datasets, dataset_name for new datasets
          dataset_id: datasetId ?? undefined,
          dataset_name: datasetId ? undefined : datasetName.trim(),
          label: meta?.label || undefined,
          case_id: meta?.case_id || undefined,
          age,
          gender: meta?.gender || undefined,
          source: meta?.source || undefined,
          event_time: eventTime,
          event_status: eventStatus
        },
        associatedFiles: item.associatedFiles
      }
    })

    try {
      // Add to background task queue
      addUploadTask(uploadFiles, {
        onComplete: () => {
          // Optionally refresh WSI list when complete
        }
      })

      // Clear the form
      resetUpload()
      navigate('/dashboard')
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : String(error))
    }
  }

  const resetUpload = () => {
    setStep(1)
    setDatasetName('')
    setDatasetId(null)
    setLocalItems([])
    setLocalMetadata(new Map())
    setShowValidation(false)
    setIgnoredCount(0)
    setSkippedDuplicateCount(0)
    setSelectedItems(new Set())
    setSubmitError(null)
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

  const handleSplitFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    setSplitFileError(null)
    if (e.target.files && e.target.files.length > 0) {
      const file = e.target.files[0]
      const fileName = file.name.toLowerCase()

      // Client-side validation
      try {
        let csvContent: string
        let finalFile: File = file

        // Handle XLSX files - convert to CSV
        if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls')) {
          const arrayBuffer = await file.arrayBuffer()
          const workbook = XLSX.read(arrayBuffer, { type: 'array' })

          if (workbook.SheetNames.length > 1) {
            setSplitFileError('Excel file has multiple sheets. Please use a file with only one sheet.')
            return
          }

          const worksheet = workbook.Sheets[workbook.SheetNames[0]]
          csvContent = XLSX.utils.sheet_to_csv(worksheet)

          // Create a new File object with CSV content but keep original name for display
          const blob = new Blob([csvContent], { type: 'text/csv' })
          finalFile = new File([blob], file.name, { type: 'text/csv' })
        } else {
          // CSV file - read directly
          csvContent = await file.text()
        }

        const lines = csvContent.split('\n').filter(line => line.trim() !== '')

        if (lines.length < 2) {
          setSplitFileError('File is empty or has no data rows')
          return
        }

        const headers = lines[0].toLowerCase().split(',').map(h => h.trim())

        if (!headers.includes('filename')) {
          setSplitFileError('File must contain "filename" column')
          return
        }

        if (!headers.includes('split')) {
          setSplitFileError('File must contain "split" column')
          return
        }

        setSplitFile(finalFile)
      } catch (err) {
        setSplitFileError('Failed to read file: ' + String(err))
      }
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      await downloadCSVTemplate(uploadMode)
    } catch (e) {
      console.error("Failed to download template", e)
      toastError(e instanceof Error ? e.message : "Failed to download template")
    }
  }

  const [splitUploadSuccess, setSplitUploadSuccess] = useState<string | null>(null)

  const handleUploadSplit = async () => {
    if (!splitFile || !datasetName) return false

    // uploadDatasetSplits requires dataset_id - only works for existing datasets
    if (!datasetId) {
      setSplitFileError('Cannot upload splits for a new dataset. Please upload files first to create the dataset, then upload splits from the Dataset page.')
      return false
    }

    setUploadingSplit(true)
    setSplitFileError(null)
    setSplitUploadSuccess(null)
    try {
      const result = await uploadDatasetSplits(datasetId, splitFile)
      // Build detailed success message
      let successMsg = `Updated ${result.updated_count} slides`
      if (result.auto_val_count > 0) {
        successMsg += `. Auto-assigned ${result.auto_val_count} samples to val (10% from train)`
      }
      if (result.not_found_count > 0) {
        successMsg += `. Warning: ${result.not_found_count} files not found`
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
        <div className="fixed inset-0 z-[100] bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-white rounded-[1.5rem] sm:rounded-3xl shadow-2xl w-full max-w-lg p-5 sm:p-8 animate-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-lg sm:text-xl font-bold text-slate-900 flex items-center gap-2">
                  <Settings2 className="w-5 h-5 text-blue-600" />
                  Batch Edit
                </h3>
                <p className="text-xs sm:text-sm text-slate-500 mt-1">{selectedItems.size} items selected</p>
              </div>
              <button onClick={() => setShowBulkEdit(false)} className="p-2 text-slate-400 hover:text-slate-600 rounded-full hover:bg-slate-100 transition-colors">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4 sm:space-y-6">
              {/* Classification: Label | Survival: Event Time & Status */}
              {uploadMode === 'classification' ? (
                <div className="space-y-1.5">
                  <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Label</label>
                  <input
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all"
                    placeholder="Apply label to all..."
                    value={batchMetadata.label}
                    onChange={e => setBatchMetadata(p => ({ ...p, label: e.target.value }))}
                  />
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3 sm:gap-4">
                  <div className="space-y-1.5">
                    <label className="text-[10px] sm:text-xs font-semibold text-emerald-600 uppercase tracking-wider">Event Time</label>
                    <input
                      type="number"
                      step="0.1"
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-emerald-500/10 focus:border-emerald-500 outline-none"
                      placeholder="Months..."
                      value={batchMetadata.event_time}
                      onChange={e => setBatchMetadata(p => ({ ...p, event_time: e.target.value }))}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-[10px] sm:text-xs font-semibold text-emerald-600 uppercase tracking-wider">Status</label>
                    <select
                      className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-emerald-500/10 focus:border-emerald-500 outline-none"
                      value={batchMetadata.event_status}
                      onChange={e => setBatchMetadata(p => ({ ...p, event_status: e.target.value }))}
                    >
                      <option value="">No Change</option>
                      <option value="1">Event (1)</option>
                      <option value="0">Censored (0)</option>
                    </select>
                  </div>
                </div>
              )}
              <div className="grid grid-cols-2 gap-3 sm:gap-4">
                <div className="space-y-1.5">
                  <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Case ID</label>
                  <input
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                    placeholder="Batch ID"
                    value={batchMetadata.case_id}
                    onChange={e => setBatchMetadata(p => ({ ...p, case_id: e.target.value }))}
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Age</label>
                  <input
                    type="number"
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                    placeholder="Age"
                    value={batchMetadata.age}
                    onChange={e => setBatchMetadata(p => ({ ...p, age: e.target.value }))}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3 sm:gap-4">
                <div className="space-y-1.5">
                  <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Source</label>
                  <select
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                    value={batchMetadata.source}
                    onChange={e => setBatchMetadata(p => ({ ...p, source: e.target.value }))}
                  >
                    <option value="">No Change</option>
                    {organSources.map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-[10px] sm:text-xs font-semibold text-slate-500 uppercase tracking-wider">Gender</label>
                  <select
                    className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none"
                    value={batchMetadata.gender}
                    onChange={e => setBatchMetadata(p => ({ ...p, gender: e.target.value }))}
                  >
                    <option value="">No Change</option>
                    <option value="Male">Male</option>
                    <option value="Female">Female</option>
                    <option value="Unspecified">Any</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="mt-8 flex flex-col sm:flex-row justify-end gap-3">
              <Button variant="ghost" className="h-11 sm:h-10 order-2 sm:order-1 font-semibold" onClick={() => setShowBulkEdit(false)}>Cancel</Button>
              <Button onClick={handleApplyBulkEdit} className="bg-blue-600 hover:bg-blue-700 text-white h-11 sm:h-10 shadow-lg shadow-blue-500/20 order-1 sm:order-2 font-semibold">Apply Changes</Button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      {step === 1 ? (
        <>
          <div className="flex-none mb-6">
            <PageHeader
              title="Register Files"
              description="Prepare and register local files."
            >
              <Button
                variant="outline"
                onClick={() => navigate('/dashboard')}
                className="gap-2"
              >
                <ArrowLeft className="w-4 h-4" />
                Back to Dashboard
              </Button>
            </PageHeader>
          </div>
          <div className="flex-1 flex flex-col items-center lg:justify-center p-2 sm:p-4 lg:-mt-12">
            <div className="w-full max-w-xl">
              <div className="text-center mb-6 sm:mb-8">
                <h1 className="text-3xl sm:text-4xl font-bold text-slate-900 mb-2 sm:mb-3">Create Dataset</h1>
                <p className="text-base sm:text-lg text-slate-500 px-4">Define a dataset name and analysis type to get started.</p>
              </div>

              <Card className="p-5 sm:p-8 shadow-xl border-slate-100 rounded-[1.5rem] sm:rounded-[2rem] overflow-hidden">
                <div className="space-y-6 sm:space-y-8">
                  <div>
                    <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">Dataset Name</label>
                    <div className="relative">
                      <input
                        type="text"
                        className={`w-full px-4 sm:px-5 py-3 sm:py-4 text-base sm:text-lg border rounded-xl sm:rounded-2xl focus:ring-4 focus:ring-blue-500/10 focus:border-blue-500 outline-none transition-all ${showValidation && !datasetName.trim()
                          ? 'border-red-500 bg-red-50'
                          : 'border-slate-200 bg-slate-50/50 hover:border-slate-300'
                          }`}
                        placeholder="e.g., Lung Cancer Trial 2024"
                        value={datasetName}
                        onChange={e => setDatasetName(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && datasetName.trim() && setStep(2)}
                        autoFocus
                      />
                      {isExistingDataset && (
                        <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-1.5 px-3 py-1 bg-amber-50 text-amber-600 rounded-full text-xs font-bold border border-amber-100">
                          <Plus className="w-3 h-3" />
                          EXISTING DATASET
                        </div>
                      )}
                    </div>
                    {existingDatasets.length > 0 && !datasetName.trim() && (
                      <div className="mt-4">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">Or select existing</p>
                        <div className="flex flex-wrap gap-2">
                          {existingDatasets.slice(0, 8).map(name => (
                            <button
                              key={name}
                              type="button"
                              onClick={() => setDatasetName(name)}
                              className="px-3 py-1.5 text-xs bg-white border border-slate-200 text-slate-600 rounded-lg hover:border-blue-500 hover:text-blue-600 transition-all shadow-sm"
                            >
                              {name}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <p className="mt-3 text-sm text-slate-400">
                      {isExistingDataset
                        ? 'This dataset already exists. New files will be appended to it.'
                        : 'Choose a unique name to identify this collection of slides.'}
                    </p>
                  </div>

                  <div>
                    <label className="block text-xs sm:text-sm font-semibold text-slate-700 mb-2 sm:mb-3 uppercase tracking-wider">Analysis Type</label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                      <button
                        onClick={() => !isExistingDataset && setUploadMode('classification')}
                        disabled={isExistingDataset}
                        className={`flex flex-row sm:flex-col items-center sm:items-start p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${uploadMode === 'classification'
                          ? 'border-blue-500 bg-blue-50/50'
                          : `border-slate-100 bg-white ${!isExistingDataset ? 'hover:border-slate-200' : ''}`
                          } ${isExistingDataset ? 'cursor-not-allowed' : ''} ${isExistingDataset && uploadMode !== 'classification' ? 'opacity-40' : ''}`}
                      >
                        <div className={`p-2 rounded-lg mr-4 sm:mr-0 sm:mb-3 ${uploadMode === 'classification' ? 'bg-blue-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                          <Tags className="w-5 h-5" />
                        </div>
                        <div>
                          <span className={`font-bold block ${uploadMode === 'classification' ? 'text-blue-900' : 'text-slate-900'}`}>Classification</span>
                          <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">Diagnostic labels & categories</span>
                        </div>
                      </button>

                      <button
                        onClick={() => !isExistingDataset && setUploadMode('survival')}
                        disabled={isExistingDataset}
                        className={`flex flex-row sm:flex-col items-center sm:items-start p-4 sm:p-5 rounded-xl sm:rounded-2xl border-2 transition-all text-left ${uploadMode === 'survival'
                          ? 'border-emerald-500 bg-emerald-50/50'
                          : `border-slate-100 bg-white ${!isExistingDataset ? 'hover:border-slate-200' : ''}`
                          } ${isExistingDataset ? 'cursor-not-allowed' : ''} ${isExistingDataset && uploadMode !== 'survival' ? 'opacity-40' : ''}`}
                      >
                        <div className={`p-2 rounded-lg mr-4 sm:mr-0 sm:mb-3 ${uploadMode === 'survival' ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-400'}`}>
                          <Activity className="w-5 h-5" />
                        </div>
                        <div>
                          <span className={`font-bold block ${uploadMode === 'survival' ? 'text-emerald-900' : 'text-slate-900'}`}>Survival Analysis</span>
                          <span className="text-[10px] sm:text-xs text-slate-500 mt-0.5 sm:mt-1">Event time & status tracking</span>
                        </div>
                      </button>
                    </div>
                  </div>

                  <Button
                    size="lg"
                    className="w-full h-14 sm:h-16 text-base sm:text-lg rounded-xl sm:rounded-2xl bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-500/20 mt-2 sm:mt-4"
                    disabled={!datasetName.trim()}
                    onClick={() => setStep(2)}
                  >
                    Next: Choose Files <ArrowRight className="ml-2 w-4 h-4 sm:w-5 sm:h-5" />
                  </Button>
                </div>
              </Card>
            </div>
          </div>
        </>
      ) : step === 3 ? (
        <div className="flex-1 flex flex-col items-center lg:justify-center p-4 sm:p-8 lg:-mt-12">
          <Card className="w-full max-w-4xl overflow-hidden shadow-2xl border-slate-100 rounded-[1.5rem] sm:rounded-[2rem] bg-white ring-1 ring-slate-900/5 animate-in zoom-in-95 duration-300">
            <div className="grid grid-cols-1 md:grid-cols-2 min-h-[300px] md:min-h-[420px]">
              {/* Left Column: Success State & Actions */}
              <div className="bg-slate-50/80 p-6 sm:p-10 flex flex-col justify-center items-center text-center border-b md:border-b-0 md:border-r border-slate-100">
                <div className="w-16 h-16 sm:w-20 sm:h-20 bg-green-100 text-green-600 rounded-full flex items-center justify-center mb-4 sm:mb-6 ring-8 ring-green-50 shadow-sm">
                  <CheckCircle2 className="w-8 h-8 sm:w-10 sm:h-10" />
                </div>
                
                <h2 className="text-xl sm:text-2xl font-bold text-slate-900 mb-2 sm:mb-3 tracking-tight">Import Successful</h2>
                <p className="text-sm sm:text-slate-500 mb-6 sm:mb-8 max-w-[240px] leading-relaxed">
                  Dataset information has been updated successfully.
                </p>

                <div className="flex flex-col gap-3 w-full max-w-xs">
                  <Button
                    size="lg"
                    className="w-full h-11 text-base font-semibold bg-slate-900 hover:bg-black text-white shadow-lg shadow-slate-200"
                    onClick={() => navigate('/dashboard')}
                  >
                    Go to Dashboard
                  </Button>
                  <Button
                    variant="outline"
                    className="w-full h-11 text-base border-slate-200 text-slate-600 hover:bg-white hover:border-slate-300"
                    onClick={resetUpload}
                  >
                    Upload More
                  </Button>
                </div>
              </div>

              {/* Right Column: Summary Details */}
              <div className="p-6 sm:p-10 flex flex-col justify-center bg-white relative">
                 <h3 className="text-[10px] sm:text-xs font-bold text-slate-900 uppercase tracking-widest mb-4 sm:mb-6 border-b border-slate-100 pb-3">Dataset Summary</h3>
                 
                 <div className="space-y-4 sm:space-y-6">
                    <div>
                      <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Target Dataset</div>
                      <div className="text-base sm:text-lg font-bold text-slate-900 truncate flex items-center gap-2">
                        <Database className="w-4 h-4 text-blue-500" />
                        {datasetName}
                      </div>
                    </div>

                    <div>
                      <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">Action</div>
                      <div className="text-xs sm:text-sm font-medium text-slate-700 bg-slate-50 inline-block px-3 py-1 rounded-md border border-slate-200">
                        Metadata / Split Update (CSV)
                      </div>
                    </div>

                    {splitUploadSuccess && (
                      <div>
                        <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">Import Result</div>
                        <div className="text-xs sm:text-sm text-slate-600 bg-green-50/50 p-3 sm:p-4 rounded-xl border border-green-100 leading-relaxed text-wrap break-words">
                           {splitUploadSuccess}
                        </div>
                      </div>
                    )}
                 </div>
              </div>
            </div>
          </Card>
        </div>
      ) : (
        <>
          <div className="flex-none mb-2 px-2 sm:px-0">
            <PageHeader
              title="Register Files"
              description={<span className="text-xs sm:text-base">Prepare and register local files.</span>}
            >
              <Button
                variant="outline"
                onClick={() => navigate('/dashboard')}
                className="gap-2 h-9 sm:h-10 text-xs sm:text-sm"
              >
                <ArrowLeft className="w-4 h-4" />
                <span className="hidden sm:inline">Back to Dashboard</span>
                <span className="sm:hidden">Back</span>
              </Button>
            </PageHeader>
          </div>
          <div className="flex-none mb-2 px-2 sm:px-0">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between bg-slate-50/50 p-3 sm:p-2 sm:px-4 rounded-xl border border-slate-100 gap-3">
              <div className="flex items-center gap-3 sm:gap-4 text-left">
                <div className="p-2 sm:p-3 bg-white rounded-lg sm:rounded-xl shadow-sm border border-slate-100 flex-shrink-0">
                  {uploadMode === 'classification' ? (
                    <Tags className="w-5 h-5 sm:w-6 sm:h-6 text-blue-600" />
                  ) : (
                    <Activity className="w-5 h-5 sm:w-6 sm:h-6 text-emerald-600" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h2 className="text-lg sm:text-xl font-bold text-slate-900 truncate max-w-[150px] sm:max-w-none">{datasetName}</h2>
                    {isExistingDataset && (
                      <span className="px-2 py-0.5 bg-amber-50 text-amber-600 rounded-full text-[9px] sm:text-[10px] font-bold border border-amber-100 whitespace-nowrap">
                        APPENDING DATA
                      </span>
                    )}
                  </div>
                  <p className="text-xs sm:text-sm text-slate-500 capitalize">{uploadMode} Dataset</p>
                </div>
              </div>
              <Button variant="outline" size="sm" className="rounded-xl px-4 h-9 sm:h-10 w-full sm:w-auto shrink-0 justify-center" onClick={() => setStep(1)}>
                <Edit2 className="w-4 h-4 mr-2" /> Change Info
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
                      <h4 className="font-semibold text-green-800">Label File Ready</h4>
                      <p className="text-sm text-green-700 mt-1">
                        <span className="font-medium">{splitFile.name}</span> has been loaded with your labels and splits.
                      </p>
                      <p className="text-xs text-green-600 mt-2">
                        Now drop your image files below to match them with the CSV data.
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
                  await processCollectionResult(result)
                }}
                onClick={supportsNativePicker ? handleLocalPathSelect : undefined}
              >
                <div className="w-16 h-16 sm:w-24 sm:h-24 bg-blue-50 rounded-full flex items-center justify-center mb-4 sm:mb-8">
                  <UploadCloud className="w-8 h-8 sm:w-12 sm:h-12 text-blue-600" />
                </div>
                <h3 className="text-xl sm:text-3xl font-bold text-slate-900 mb-2 sm:mb-4">Drop files here to begin</h3>
                <p className="text-sm sm:text-lg text-slate-500 mb-6 sm:mb-10 max-w-xl leading-relaxed px-4">
                  Support for common WSI formats and image files. <br className="hidden sm:block" />
                </p>
                {supportsNativePicker && (
                  <Button size="lg" className="px-6 sm:px-10 h-12 sm:h-14 text-base sm:text-lg rounded-full shadow-lg shadow-blue-500/20">
                    Browse Files
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <>
              {/* Toolbar */}
              <div className="flex-none px-3 sm:px-6 py-2 bg-slate-50 border-b border-slate-200 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 sm:gap-4">
                <div className="flex items-center gap-3 sm:gap-4 flex-wrap">
                  <label className="flex items-center gap-2 text-sm font-medium text-slate-600 cursor-pointer select-none shrink-0">
                    <Checkbox
                      checked={selectedItems.size === localItems.length && localItems.length > 0}
                      onCheckedChange={() => toggleSelectAll()}
                    />
                    <span className="hidden sm:inline">Select All ({localItems.length})</span>
                    <span className="sm:hidden">{localItems.length} Files</span>
                  </label>
                  {skippedDuplicateCount > 0 && (
                    <span className="text-[10px] sm:text-xs text-amber-600 bg-amber-50 px-2 py-1 rounded-full border border-amber-200 whitespace-nowrap">
                      {skippedDuplicateCount} duplicate{skippedDuplicateCount > 1 ? 's' : ''}
                    </span>
                  )}
                  {selectedItems.size > 0 && (
                    <div className="flex items-center gap-1.5 sm:gap-2 animate-in fade-in slide-in-from-left-4 duration-200">
                      <div className="h-4 w-px bg-slate-300 mx-1 hidden sm:block" />
                      <Button size="sm" variant="secondary" onClick={() => setShowBulkEdit(true)} className="h-7 sm:h-8 text-[10px] sm:text-xs font-medium px-2 sm:px-3">
                        <Edit2 className="w-3 h-3 mr-1 sm:mr-1.5" />
                        Edit
                      </Button>
                      <Button size="sm" variant="destructive" onClick={removeSelectedItems} className="h-7 sm:h-8 text-[10px] sm:text-xs font-medium bg-red-50 text-red-600 hover:bg-red-100 border border-red-200 px-2 sm:px-3">
                        <Trash2 className="w-3 h-3 mr-1 sm:mr-1.5" />
                        Delete
                      </Button>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 px-3 sm:px-4 py-1.5 bg-blue-50 text-blue-700 rounded-full text-[10px] sm:text-sm font-semibold border border-blue-100 shadow-sm justify-center sm:justify-start">
                  <UploadCloud className="w-3 h-3 sm:w-4 sm:h-4" />
                  Drop more files to add to list
                </div>
              </div>

              {/* Table Area */}
              <Card className="flex-1 min-h-0 flex flex-col overflow-hidden mb-2 sm:mb-4 mx-2 sm:mx-0">
                <div
                  className="flex-1 overflow-x-auto overflow-y-auto bg-white"
                  ref={tableContainerRef}
                  onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
                  onDragLeave={() => setIsDragging(false)}
                  onDrop={async e => {
                    e.preventDefault()
                    setIsDragging(false)
                    const result = await collectItemsFromDataTransfer(e.dataTransfer)
                    await processCollectionResult(result)
                  }}
                >
                  {isDragging && (
                    <div className="absolute inset-0 z-40 bg-blue-500/10 backdrop-blur-[1px] flex items-center justify-center border-4 border-blue-500 border-dashed m-4 rounded-xl pointer-events-none">
                      <div className="bg-white px-8 py-4 rounded-full shadow-xl font-bold text-blue-600 flex items-center gap-3">
                        <UploadCloud className="w-6 h-6" />
                        Drop to add files
                      </div>
                    </div>
                  )}

                  <table className="w-full text-left border-collapse">
                    <thead className="bg-slate-50 sticky top-0 z-10 border-b border-slate-200">
                      <tr>
                        <th className="w-10 px-3 sm:px-4 py-2 bg-slate-50">
                          <div className="sr-only">Select</div>
                        </th>
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[180px] sm:min-w-[200px]">File Name</th>
                        {uploadMode === 'classification' ? (
                          <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[120px] sm:min-w-[150px]">Label <span className="text-red-500">*</span></th>
                        ) : (
                          <>
                            <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[90px] sm:min-w-[100px]">Event Time <span className="text-red-500">*</span></th>
                            <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[80px] sm:min-w-[90px]">Status <span className="text-red-500">*</span></th>
                          </>
                        )}
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[100px] sm:min-w-[120px]">Case ID</th>
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[70px] sm:min-w-[80px]">Age</th>
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[90px] sm:min-w-[100px]">Gender</th>
                        <th className="px-3 sm:px-4 py-2 text-[10px] sm:text-xs font-bold text-slate-500 uppercase tracking-wider bg-slate-50 min-w-[120px] sm:min-w-[140px]">Source</th>
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
                            : (!meta.event_time.trim() || !meta.event_status.trim())
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
                                      title={`Missing data folder: Please drag the "${getBaseName(item.name)}" folder`}
                                    >
                                      ⚠ DATA MISSING
                                    </span>
                                  )}
                                </div>
                              </div>
                            </td>
                            {/* Classification: Label input | Survival: Event Time & Status inputs */}
                            {uploadMode === 'classification' ? (
                              <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                <input
                                  className={`w-full px-2 py-1.5 text-sm border rounded-lg hover:border-blue-400 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all ${hasError ? 'border-red-500 bg-red-50' : 'border-slate-100 bg-slate-50/50 hover:bg-white focus:bg-white'}`}
                                  placeholder="Enter label"
                                  value={meta.label}
                                  onChange={e => handleMetadataChange(item.key, 'label', e.target.value)}
                                />
                              </td>
                            ) : (
                              <>
                                <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                  <input
                                    type="number"
                                    step="0.1"
                                    className={`w-full px-2 py-1.5 text-sm border rounded-lg hover:border-emerald-400 focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 outline-none transition-all ${hasError && !meta.event_time.trim() ? 'border-red-500 bg-red-50' : 'border-slate-100 bg-slate-50/50 hover:bg-white focus:bg-white'}`}
                                    placeholder="Months"
                                    value={meta.event_time}
                                    onChange={e => handleMetadataChange(item.key, 'event_time', e.target.value)}
                                  />
                                </td>
                                <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                                  <select
                                    className={`w-full px-2 py-1.5 text-sm border rounded-lg hover:border-emerald-400 focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 outline-none transition-all ${hasError && !meta.event_status.trim() ? 'border-red-500 bg-red-50' : 'border-slate-100 bg-slate-50/50 hover:bg-white focus:bg-white'}`}
                                    value={meta.event_status}
                                    onChange={e => handleMetadataChange(item.key, 'event_status', e.target.value)}
                                  >
                                    <option value="">Status</option>
                                    <option value="1">Event (1)</option>
                                    <option value="0">Censored (0)</option>
                                  </select>
                                </td>
                              </>
                            )}
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <input
                                className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                placeholder="Case ID"
                                value={meta.case_id}
                                onChange={e => handleMetadataChange(item.key, 'case_id', e.target.value)}
                              />
                            </td>
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <input
                                type="number"
                                className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                placeholder="Age"
                                value={meta.age}
                                onChange={e => handleMetadataChange(item.key, 'age', e.target.value)}
                              />
                            </td>
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <select
                                className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                value={meta.gender}
                                onChange={e => handleMetadataChange(item.key, 'gender', e.target.value)}
                              >
                                <option value="">-</option>
                                <option value="Male">M</option>
                                <option value="Female">F</option>
                                <option value="Unspecified">?</option>
                              </select>
                            </td>
                            <td className="px-3 sm:px-4 py-3 align-middle border-b border-slate-100">
                              <select
                                className="w-full px-2 py-1.5 text-sm border border-slate-100 rounded-lg bg-slate-50/50 hover:bg-white hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 outline-none transition-all"
                                value={meta.source}
                                onChange={e => handleMetadataChange(item.key, 'source', e.target.value)}
                              >
                                <option value="">Source</option>
                                {organSources.map(o => <option key={o} value={o}>{o}</option>)}
                              </select>
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
              </Card>

              {/* Dataset Metadata Configuration - batch update via CSV */}
              <Card className="flex-none p-3 sm:p-4 mb-2 transition-all mx-2 sm:mx-0">
                <div
                  className="flex items-center justify-between cursor-pointer select-none"
                  onClick={() => setShowSplitConfig(!showSplitConfig)}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <FileSpreadsheet className="w-4 h-4 sm:w-5 sm:h-5 text-blue-600 shrink-0" />
                    <div className="min-w-0">
                      <h2 className="text-sm sm:text-base font-semibold text-slate-900 truncate">
                        Dataset Metadata Configuration
                      </h2>
                      {!showSplitConfig && (
                        <p className="text-[10px] sm:text-xs text-slate-500 truncate">
                          Optional: Batch update via CSV
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
                        Template
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
                      Upload a file to batch update metadata. Supports CSV and Excel (.xlsx) formats.
                    </p>

                {/* Help text - different for classification vs survival */}
                <div className="mb-4 p-2 sm:p-3 bg-blue-50 rounded-lg text-[10px] sm:text-sm text-blue-800">
                  <p className="font-bold mb-1">File Format ({uploadMode === 'classification' ? 'Classification' : 'Survival'}):</p>
                  <ul className="list-disc list-inside space-y-0.5 text-blue-700">
                    <li><code className="bg-blue-100 px-1 rounded">filename</code>{uploadMode === 'classification' ? ', ' : ''}{uploadMode === 'classification' && <code className="bg-blue-100 px-1 rounded">label</code>}</li>
                    {uploadMode === 'survival' && (
                      <li><code className="bg-blue-100 px-1 rounded">event_time</code>, <code className="bg-blue-100 px-1 rounded">event_status</code></li>
                    )}
                    <li className="hidden sm:list-item">Optional: <code className="bg-blue-100 px-1 rounded">case_id</code>, <code className="bg-blue-100 px-1 rounded">age</code>, <code className="bg-blue-100 px-1 rounded">gender</code>, <code className="bg-blue-100 px-1 rounded">source</code>, <code className="bg-blue-100 px-1 rounded">split</code></li>
                  </ul>
                </div>

                <div className="flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 bg-gray-50 p-3 sm:p-4 rounded-lg border border-dashed border-gray-300">
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
                      <button
                        onClick={() => setSplitFile(null)}
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors flex-shrink-0"
                        title="Remove file"
                      >
                        <X className="w-4 h-4" />
                      </button>
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
                        Ready
                     </div>
                  )}
                </div>

                {/* Error message */}
                {splitFileError && (
                  <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                    <span className="font-medium">Error: </span>{splitFileError}
                  </div>
                )}

                {/* Success message */}
                {splitUploadSuccess && (
                  <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700">
                    <span className="font-medium">Success: </span>{splitUploadSuccess}
                  </div>
                )}
                  </div>
                )}
              </Card>

              {/* Footer - Fixed at bottom */}
              <div className="flex-none bg-white border border-slate-200 rounded-xl px-4 sm:px-8 py-3 flex flex-col sm:flex-row items-stretch sm:items-center justify-between shadow-sm z-30 gap-4 sm:gap-0 mt-2">
                <div className="flex flex-col sm:flex-row items-center gap-4 sm:gap-8">
                  <div className="text-xs sm:text-sm text-slate-500 whitespace-nowrap">
                    Ready to register <strong className="text-slate-900">{localItems.length}</strong> file(s).
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
                          PAGE {currentPage} / {totalPages}
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
                      Cancel
                    </Button>
                    <Button
                      onClick={handleUpload}
                      disabled={localItems.length === 0 && !splitFile}
                      className={`${isExistingDataset ? 'bg-amber-600 hover:bg-amber-700' : 'bg-green-600 hover:bg-green-700'} text-white flex-1 sm:min-w-[160px] rounded-xl h-10 shadow-sm`}
                    >
                      {isExistingDataset ? (
                        <>
                          <Plus className="w-4 h-4 mr-2 shrink-0" />
                          <span className="truncate">{localItems.length === 0 && splitFile ? 'Upload CSV' : 'Add to Dataset'}</span>
                        </>
                      ) : (
                        <>
                          <Download className="w-4 h-4 mr-2 shrink-0" />
                          <span className="truncate">{localItems.length === 0 && splitFile ? 'Upload CSV' : 'Register All'}</span>
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
