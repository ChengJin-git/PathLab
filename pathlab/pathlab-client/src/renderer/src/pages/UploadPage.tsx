import { useState, useMemo, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Download,
  CheckCircle2,
  X,
  AlertCircle,
  ArrowRight,
  UploadCloud,
  Settings2,
  FileText,
  Trash2,
  FolderOpen,
  Edit2,
  Plus,
  ChevronLeft,
  ChevronRight
} from 'lucide-react'
import { uploadWSIByPath, uploadWSIFile } from '../api'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Checkbox } from '../components/ui/checkbox'

interface UploadingFile {
  progress: number
  status: 'uploading' | 'success' | 'error'
  error?: string
}

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

export default function RegisterPage() {
  const navigate = useNavigate()
  // State
  const [localItems, setLocalItems] = useState<LocalItem[]>([])
  const [localMetadata, setLocalMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>>(new Map())
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, UploadingFile>>(new Map())
  const [uploading, setUploading] = useState(false)
  const [showResults, setShowResults] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [showValidation, setShowValidation] = useState(false)
  // ignoredCount state was here but maybe less clear in table view? We can keep it as a toast or small alert.
  const [ignoredCount, setIgnoredCount] = useState(0)

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
  const [batchMetadata, setBatchMetadata] = useState({ label: '', case_id: '', age: '', gender: '', source: '' })

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

  const wsiExtensions = [
    '.svs', '.svslide', '.dyj', '.dyqx', '.tif', '.tiff', '.ndpi',
    '.vms', '.vmu', '.isyntax', '.ibl', '.kfb', '.scn', '.mrxs',
    '.mds', '.mdsx', '.vsi', '.qptiff', '.sdpc', '.tmap', '.tron',
    '.bif', '.zyp'
  ]

  const supportsNativePicker = typeof window !== 'undefined' && !!window.api?.files?.selectFiles

  const isSupportedName = (name: string) => {
    const normalized = name.toLowerCase()
    return wsiExtensions.some(ext => normalized.endsWith(ext))
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

  const processCollectionResult = (result: CollectionResult) => {
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
        setLocalItems(prev => {
          const merged = new Map(prev.map(item => [item.key, item]))

          // For new items, check if we have pending associated data
          filtered.forEach(item => {
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
          filtered.forEach(item => {
            if (!updated.has(item.key)) {
              updated.set(item.key, { label: '', case_id: generateCaseId(), age: '', gender: '', source: '' })
            }
          })
          return updated
        })
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
          updated.set(item.key, { label: '', case_id: generateCaseId(), age: '', gender: '', source: '' })
        }
      })
      return updated
    })
  }

  const handleLocalPathSelect = async () => {
    if (!window.api?.files?.selectFiles) return
    const filters = [{ name: 'Supported WSI Formats', extensions: wsiExtensions.map(ext => ext.replace(/^\./, '')) }]
    const paths = await window.api.files.selectFiles({ title: 'Select local files', filters })

    if (paths && paths.length > 0) {
      const items = paths.map(path => ({ key: path, name: path.split(/[/\\]/).pop() || path, path }))
      addLocalItems(items)
    }
  }

  const handleMetadataChange = (key: string, field: string, value: string) => {
    setLocalMetadata(prev => {
      const updated = new Map(prev)
      const current = updated.get(key) || { label: '', case_id: '', age: '', gender: '', source: '' }
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
        const current = updated.get(item.key) || { label: '', case_id: '', age: '', gender: '', source: '' }
        updated.set(item.key, {
          ...current,
          label: batchMetadata.label || current.label,
          case_id: batchMetadata.case_id || current.case_id,
          age: batchMetadata.age || current.age,
          gender: batchMetadata.gender || current.gender,
          source: batchMetadata.source || current.source
        })
      })
      return updated
    })
    setBatchMetadata({ label: '', case_id: '', age: '', gender: '', source: '' })
    setShowBulkEdit(false)
  }

  // --- Upload Logic ---

  const handleUpload = async () => {
    if (localItems.length === 0) return
    setShowValidation(true)
    const missingLabels = localItems.filter(item => !localMetadata.get(item.key)?.label?.trim())
    if (missingLabels.length > 0) {
      // Optional: scroll to first error
      return
    }

    setUploading(true)
    const uploadMap = new Map<string, UploadingFile>()
    localItems.forEach(item => uploadMap.set(item.key, { progress: 0, status: 'uploading' }))
    setUploadingFiles(uploadMap)

    for (const item of localItems) {
      const metadata = localMetadata.get(item.key)
      try {
        const age = metadata?.age ? parseInt(metadata.age) : undefined
        const uploadData = {
          label: metadata?.label || undefined,
          case_id: metadata?.case_id || undefined,
          age,
          gender: metadata?.gender || undefined,
          source: metadata?.source || undefined
        }

        if (item.path) {
          await uploadWSIByPath(item.path, uploadData)
        } else if (item.file) {
          await uploadWSIFile(item.file, {
            ...uploadData,
            associatedFiles: item.associatedFiles,
            onProgress: (progress) => {
              setUploadingFiles(prev => {
                const u = new Map(prev)
                const c = u.get(item.key)
                if (c) u.set(item.key, { ...c, progress })
                return u
              })
            }
          })
        }
        setUploadingFiles(prev => {
          const u = new Map(prev)
          u.set(item.key, { progress: 100, status: 'success' })
          return u
        })
      } catch (error) {
        setUploadingFiles(prev => {
          const u = new Map(prev)
          u.set(item.key, { progress: 0, status: 'error', error: String(error) })
          return u
        })
      }
    }
    setUploading(false)
    setShowResults(true)
  }

  const resetUpload = () => {
    setLocalItems([])
    setLocalMetadata(new Map())
    setUploadingFiles(new Map())
    setShowResults(false)
    setShowValidation(false)
    setIgnoredCount(0)
    setSelectedItems(new Set())
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

  // --- Render ---

  if (showResults) {
    return (
      <div className="w-full h-full flex items-center justify-center p-8">
        <Card className="max-w-xl w-full p-12 text-center border-2 border-green-50 shadow-none bg-white">
          <div className="w-24 h-24 bg-green-50 rounded-full flex items-center justify-center mx-auto mb-8">
            <CheckCircle2 className="w-12 h-12 text-green-600" />
          </div>
          <h2 className="text-3xl font-bold text-slate-900 mb-4">Registration Complete</h2>
          <p className="text-lg text-slate-600 mb-8">
            Successfully registered <strong className="text-slate-900">{Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length}</strong> slides.
          </p>
          <div className="flex gap-4 justify-center">
            <Button onClick={() => navigate('/wsi-list')} className="bg-blue-600 hover:bg-blue-700 h-12 px-8 text-lg">
              View Slides <ArrowRight className="ml-2 w-5 h-5" />
            </Button>
            <Button variant="outline" onClick={resetUpload} className="h-12 px-8 text-lg">
              Register More
            </Button>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Bulk Edit Modal */}
      {showBulkEdit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg p-6 animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between mb-6">
              <h3 className="text-lg font-semibold flex items-center gap-2">
                <Settings2 className="w-5 h-5 text-blue-600" />
                Batch Edit ({selectedItems.size} items)
              </h3>
              <button onClick={() => setShowBulkEdit(false)} className="text-slate-400 hover:text-slate-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-slate-500 uppercase">Label</label>
                <input
                  className="w-full px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                  placeholder="Apply label to all..."
                  value={batchMetadata.label}
                  onChange={e => setBatchMetadata(p => ({ ...p, label: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-500 uppercase">Case ID</label>
                  <input
                    className="w-full px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                    placeholder="Batch Case ID"
                    value={batchMetadata.case_id}
                    onChange={e => setBatchMetadata(p => ({ ...p, case_id: e.target.value }))}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-500 uppercase">Age</label>
                  <input
                    type="number"
                    className="w-full px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                    placeholder="Age"
                    value={batchMetadata.age}
                    onChange={e => setBatchMetadata(p => ({ ...p, age: e.target.value }))}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-500 uppercase">Source</label>
                  <select
                    className="w-full px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
                    value={batchMetadata.source}
                    onChange={e => setBatchMetadata(p => ({ ...p, source: e.target.value }))}
                  >
                    <option value="">No Change</option>
                    {organSources.map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-semibold text-slate-500 uppercase">Gender</label>
                  <select
                    className="w-full px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 outline-none"
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

            <div className="mt-8 flex justify-end gap-3">
              <Button variant="ghost" onClick={() => setShowBulkEdit(false)}>Cancel</Button>
              <Button onClick={handleApplyBulkEdit} className="bg-blue-600 hover:bg-blue-700 text-white">Apply Changes</Button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="flex-none mb-6">
        <PageHeader
          title="Register Files"
          description="Prepare and register whole slide images or image files."
        />
      </div>

      {localItems.length === 0 ? (
        <div className="flex-1 flex flex-col items-center justify-center p-8">
          <div
            className={`w-full max-w-2xl border-2 border-dashed rounded-2xl p-16 flex flex-col items-center justify-center text-center transition-all cursor-pointer ${isDragging ? 'border-blue-500 bg-blue-50/50 scale-[1.01]' : 'border-slate-300 hover:border-slate-400 bg-white'
              }`}
            onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={async e => {
              e.preventDefault()
              setIsDragging(false)
              const result = await collectItemsFromDataTransfer(e.dataTransfer)
              processCollectionResult(result)
            }}
            onClick={supportsNativePicker ? handleLocalPathSelect : undefined}
          >
            <div className="w-20 h-20 bg-blue-50 rounded-full flex items-center justify-center mb-6">
              <UploadCloud className="w-10 h-10 text-blue-600" />
            </div>
            <h3 className="text-xl font-semibold text-slate-900 mb-2">Drop slides here to begin</h3>
            <p className="text-slate-500 mb-6 max-w-sm">
              Support for .svs, .tif, .ndpi, .mrxs, .tmap and more. Folder upload supported.
            </p>
            {supportsNativePicker && (
              <Button>Browse Files</Button>
            )}
          </div>
        </div>
      ) : (
        <>
          {/* Toolbar */}
          <div className="flex-none px-6 py-2 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm font-medium text-slate-600 cursor-pointer select-none">
                <Checkbox
                  checked={selectedItems.size === localItems.length && localItems.length > 0}
                  onCheckedChange={() => toggleSelectAll()}
                />
                Select All ({localItems.length})
              </label>
              {selectedItems.size > 0 && (
                <div className="flex items-center gap-2 animate-in fade-in slide-in-from-left-4 duration-200">
                  <div className="h-4 w-px bg-slate-300 mx-2" />
                  <Button size="sm" variant="secondary" onClick={() => setShowBulkEdit(true)} className="h-8 text-xs font-medium">
                    <Edit2 className="w-3 h-3 mr-1.5" />
                    Edit Selected
                  </Button>
                  <Button size="sm" variant="destructive" onClick={removeSelectedItems} className="h-8 text-xs font-medium bg-red-50 text-red-600 hover:bg-red-100 border border-red-200">
                    <Trash2 className="w-3 h-3 mr-1.5" />
                    Delete
                  </Button>
                </div>
              )}
            </div>
            <div className="text-xs text-slate-400">
              Drag & drop more files to add to list
            </div>
          </div>

          {/* Table Area */}
          <Card className="flex-1 min-h-0 flex flex-col overflow-hidden mb-4">
            <div
              className="flex-1 overflow-auto bg-white"
              ref={tableContainerRef}
              onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={async e => {
                e.preventDefault()
                setIsDragging(false)
                const result = await collectItemsFromDataTransfer(e.dataTransfer)
                processCollectionResult(result)
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
                    <th className="w-10 px-4 py-2 bg-slate-50">
                      <div className="sr-only">Select</div>
                    </th>
                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 w-[25%] min-w-[200px]">File Name</th>
                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 w-[20%] min-w-[180px]">Label <span className="text-red-500">*</span></th>
                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 w-[15%] min-w-[120px]">Case ID</th>
                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 w-[8%] min-w-[80px]">Age</th>
                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 w-[10%] min-w-[100px]">Gender</th>
                    <th className="px-4 py-2 text-xs font-semibold text-slate-500 uppercase tracking-wider bg-slate-50 w-[15%] min-w-[140px]">Source</th>
                    <th className="w-12 px-4 py-2 bg-slate-50"></th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-slate-100">
                  {paginatedItems.map(item => {
                    const meta = localMetadata.get(item.key) || { label: '', case_id: '', age: '', gender: '', source: '' }
                    const isSelected = selectedItems.has(item.key)
                    const hasError = showValidation && !meta.label.trim()
                    const status = uploadingFiles.get(item.key)

                    return (
                      <tr key={item.key} className={`group hover:bg-slate-50 transition-colors ${isSelected ? 'bg-blue-50/30' : ''}`}>
                        <td className="px-4 py-2 align-middle border-b border-slate-100">
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => toggleSelection(item.key)}
                          />
                        </td>
                        <td className="px-4 py-2 align-middle border-b border-slate-100">
                          <div className="flex flex-col max-w-[240px]">
                            <span className="text-sm font-medium text-slate-900 truncate" title={item.name}>{item.name}</span>
                            <div className="flex items-center gap-2 mt-0.5">
                              <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 rounded uppercase font-bold tracking-tight">
                                {(item.name.split('.').pop() || 'tmp').substring(0, 4)}
                              </span>
                              {item.path && <span className="text-[10px] text-slate-400 truncate font-mono" title={item.path}>LOCAL</span>}
                              {item.type === 'mrxs' && item.missingAssociated && (
                                <span
                                  className="text-[10px] bg-amber-100 text-amber-700 px-1.5 rounded font-medium cursor-help"
                                  title={`Missing data folder: Please drag the "${getBaseName(item.name)}" folder`}
                                >
                                  ⚠ Missing data
                                </span>
                              )}
                            </div>
                            {status && (
                              <div className="mt-1">
                                {status.status === 'uploading' && (
                                  <div className="h-1 w-full bg-slate-100 rounded-full overflow-hidden">
                                    <div className="h-full bg-blue-500 transition-all duration-300" style={{ width: `${status.progress}%` }} />
                                  </div>
                                )}
                                {status.status === 'success' && <div className="text-[10px] text-green-600 font-medium">Uploaded</div>}
                                {status.status === 'error' && <div className="text-[10px] text-red-600 font-medium truncate" title={status.error}>Error</div>}
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-2 align-middle border-b border-slate-100">
                          <input
                            className={`w-full px-2 py-1 text-sm border rounded hover:border-blue-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all ${hasError ? 'border-red-500 bg-red-50' : 'border-transparent bg-transparent hover:bg-slate-100 focus:bg-white'}`}
                            placeholder="Label..."
                            value={meta.label}
                            onChange={e => handleMetadataChange(item.key, 'label', e.target.value)}
                          />
                        </td>
                        <td className="px-4 py-2 align-middle border-b border-slate-100">
                          <input
                            className="w-full px-2 py-1 text-sm border border-transparent rounded bg-transparent hover:bg-slate-100 hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all"
                            placeholder="ID..."
                            value={meta.case_id}
                            onChange={e => handleMetadataChange(item.key, 'case_id', e.target.value)}
                          />
                        </td>
                        <td className="px-4 py-2 align-middle border-b border-slate-100">
                          <input
                            type="number"
                            className="w-full px-2 py-1 text-sm border border-transparent rounded bg-transparent hover:bg-slate-100 hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all"
                            placeholder="Age"
                            value={meta.age}
                            onChange={e => handleMetadataChange(item.key, 'age', e.target.value)}
                          />
                        </td>
                        <td className="px-4 py-2 align-middle border-b border-slate-100">
                          <select
                            className="w-full px-2 py-1 text-sm border border-transparent rounded bg-transparent hover:bg-slate-100 hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all"
                            value={meta.gender}
                            onChange={e => handleMetadataChange(item.key, 'gender', e.target.value)}
                          >
                            <option value="">-</option>
                            <option value="Male">M</option>
                            <option value="Female">F</option>
                            <option value="Unspecified">?</option>
                          </select>
                        </td>
                        <td className="px-4 py-2 align-middle border-b border-slate-100">
                          <select
                            className="w-full px-2 py-1 text-sm border border-transparent rounded bg-transparent hover:bg-slate-100 hover:border-blue-400 focus:bg-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition-all"
                            value={meta.source}
                            onChange={e => handleMetadataChange(item.key, 'source', e.target.value)}
                          >
                            <option value="">-</option>
                            {organSources.map(o => <option key={o} value={o}>{o}</option>)}
                          </select>
                        </td>
                        <td className="px-4 py-2 align-middle text-right border-b border-slate-100">
                          <button
                            onClick={() => removeLocalItem(item.key)}
                            className="p-1.5 text-slate-300 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
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

          {/* Footer - Fixed at bottom */}
          <div className="flex-none bg-white border border-slate-200 rounded-xl px-8 py-3 flex items-center justify-between shadow-sm z-30">
            <div className="flex items-center gap-8">
              <div className="text-sm text-slate-500">
                Ready to register <strong className="text-slate-900">{localItems.length}</strong> slide(s).
              </div>
              {totalPages > 1 && (
                <div className="flex items-center gap-3">
                  <div className="h-4 w-px bg-slate-200" />
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-8 w-8 hover:bg-slate-50"
                      onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                      disabled={currentPage === 1}
                    >
                      <ChevronLeft className="h-4 w-4 text-slate-600" />
                    </Button>
                    <span className="text-xs font-semibold text-slate-600 min-w-[80px] text-center">
                      PAGE {currentPage} / {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="icon"
                      className="h-8 w-8 hover:bg-slate-50"
                      onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                      disabled={currentPage === totalPages}
                    >
                      <ChevronRight className="h-4 w-4 text-slate-600" />
                    </Button>
                  </div>
                </div>
              )}
            </div>
            <div className="flex gap-3">
              <Button variant="ghost" onClick={resetUpload} disabled={uploading}>
                Cancel
              </Button>
              <Button
                onClick={handleUpload}
                disabled={uploading || localItems.length === 0}
                className="bg-green-600 hover:bg-green-700 text-white min-w-[140px]"
              >
                {uploading ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
                    Processing...
                  </>
                ) : (
                  <>
                    <Download className="w-4 h-4 mr-2" />
                    Register All
                  </>
                )}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
