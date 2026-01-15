import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { 
  Download, 
  CheckCircle2, 
  XCircle, 
  AlertCircle, 
  ArrowRight, 
  UploadCloud, 
  Settings2, 
  FileText, 
  User, 
  Trash2, 
  FolderOpen,
  Info
} from 'lucide-react'
import { uploadWSIByPath, uploadWSIFile } from '../api'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'

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
  // For MRXS: associated data folder; For TMAP: associated DT files
  associatedFiles?: File[]
  associatedPaths?: string[]
  // Type indicator
  type?: 'mrxs' | 'tmap' | 'standard'
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
  const [localItems, setLocalItems] = useState<LocalItem[]>([])
  const [localMetadata, setLocalMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>>(new Map())
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, UploadingFile>>(new Map())
  const [uploading, setUploading] = useState(false)
  const [showResults, setShowResults] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [showValidation, setShowValidation] = useState(false)
  const [ignoredCount, setIgnoredCount] = useState(0)
  const [batchMetadata, setBatchMetadata] = useState({ label: '', case_id: '', age: '', gender: '', source: '' })
  const [selectedItems, setSelectedItems] = useState<Set<string>>(new Set())

  // Generate random 5-character ID (e.g., AbC12)
  const generateCaseId = () => {
    const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    let result = ''
    for (let i = 0; i < 5; i++) {
      result += chars.charAt(Math.floor(Math.random() * chars.length))
    }
    return result
  }

  // Common organ/tissue sources for pathology (alphabetically sorted)
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

  // Supported ASlide formats
  const wsiExtensions = [
    '.svs', '.svslide',
    '.dyj', '.dyqx',
    '.tif', '.tiff',
    '.ndpi',
    '.vms', '.vmu',
    '.isyntax',
    '.ibl',
    '.kfb',
    '.scn',
    '.mrxs',
    '.mds', '.mdsx',
    '.vsi',
    '.qptiff',
    '.sdpc',
    '.tmap',
    '.tron',
    '.bif',
    '.zyp'
  ]

  const supportsNativePicker = typeof window !== 'undefined' && !!window.api?.files?.selectFiles

  const isSupportedName = (name: string) => {
    const normalized = name.toLowerCase()
    return wsiExtensions.some(ext => normalized.endsWith(ext))
  }

  // Check if a file is TMAP data file (.DT1, .DT2, etc.)
  const isTmapDataFile = (name: string) => {
    return /\.dt\d+$/i.test(name.toLowerCase())
  }

  // Get base name without extension
  const getBaseName = (name: string) => {
    const lastDot = name.lastIndexOf('.')
    return lastDot > 0 ? name.substring(0, lastDot) : name
  }

  const addLocalItems = (items: LocalItem[]) => {
    if (!items.length) return
    const filtered = items.filter(item => isSupportedName(item.name))
    setIgnoredCount(items.length - filtered.length)
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
    const filters = [{ name: 'WSI Files', extensions: wsiExtensions.map(ext => ext.replace('.', '')) }]

    const paths = await window.api.files.selectFiles({
      title: 'Select local files',
      filters
    })

    if (paths && paths.length > 0) {
      const items = paths.map(path => ({ key: path, name: path.split(/[/\\]/).pop() || path, path }))
      addLocalItems(items)
    }
  }

  const getFilePath = (file: File) => (file as any).path as string | undefined

  const buildFileKey = (file: File) => `${file.name}-${file.size}-${file.lastModified}`

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

  // Collect files from entry, returning both files and folder info
  interface CollectedEntry {
    file?: File
    folderName?: string
    folderFiles?: File[]
    isFolder: boolean
  }

  const collectEntriesWithFolders = async (entry: any, _parentPath: string = ''): Promise<CollectedEntry[]> => {
    if (entry?.isFile) {
      return new Promise(resolve => {
        entry.file((file: File) => {
          resolve([{ file, isFolder: false }])
        }, () => resolve([]))
      })
    }
    if (entry?.isDirectory) {
      const folderName = entry.name
      const entries = await readAllEntries(entry)
      const nestedEntries = await Promise.all(entries.map(e => collectEntriesWithFolders(e, folderName)))
      const allFiles = nestedEntries.flat().filter(e => e.file).map(e => e.file!)

      // Return the folder as a single entry with all its files
      return [{ folderName, folderFiles: allFiles, isFolder: true }]
    }
    return []
  }

  const collectItemsFromDataTransfer = async (dataTransfer: DataTransfer): Promise<LocalItem[]> => {
    const dataItems = Array.from(dataTransfer.items || [])
    const hasEntries = dataItems.some(item => (item as any).webkitGetAsEntry)

    // Collect all entries (files and folders separately)
    const allEntries: CollectedEntry[] = []

    if (hasEntries) {
      const entries = dataItems
        .map(item => (item as any).webkitGetAsEntry?.())
        .filter(Boolean)
      const nested = await Promise.all(entries.map(e => collectEntriesWithFolders(e)))
      allEntries.push(...nested.flat())
    } else {
      const files = Array.from(dataTransfer.files || [])
      allEntries.push(...files.map(file => ({ file, isFolder: false })))
    }

    // Separate files and folders
    const files = allEntries.filter(e => !e.isFolder && e.file).map(e => e.file!)
    const folders = allEntries.filter(e => e.isFolder)

    // Identify MRXS files and their data folders
    const mrxsFiles = files.filter(f => f.name.toLowerCase().endsWith('.mrxs'))

    // Identify TMAP files
    const tmapFiles = files.filter(f => f.name.toLowerCase().endsWith('.tmap'))

    // Identify DT files for TMAP
    const dtFiles = files.filter(f => isTmapDataFile(f.name))

    // Build LocalItems with associations
    const result: LocalItem[] = []
    const usedFiles = new Set<File>()
    const usedFolders = new Set<string>()

    // Check if in Electron mode
    const isElectron = files.length > 0 && files.some(f => getFilePath(f))

    // Process MRXS files
    for (const mrxsFile of mrxsFiles) {
      const baseName = getBaseName(mrxsFile.name)
      // Find matching folder
      const matchingFolder = folders.find(f => f.folderName === baseName)

      usedFiles.add(mrxsFile)
      if (matchingFolder) {
        usedFolders.add(baseName)
      }

      if (isElectron) {
        const path = getFilePath(mrxsFile)!
        result.push({
          key: path,
          name: mrxsFile.name,
          path,
          type: 'mrxs',
          associatedPaths: matchingFolder ? [/* folder path would be here */] : undefined
        })
      } else {
        result.push({
          key: buildFileKey(mrxsFile),
          name: mrxsFile.name,
          file: mrxsFile,
          type: 'mrxs',
          associatedFiles: matchingFolder?.folderFiles || []
        })
      }
    }

    // Process TMAP files
    for (const tmapFile of tmapFiles) {
      const baseName = getBaseName(tmapFile.name)
      // Find matching DT files
      const matchingDtFiles = dtFiles.filter(f => getBaseName(f.name) === baseName)

      usedFiles.add(tmapFile)
      matchingDtFiles.forEach(f => usedFiles.add(f))

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

    // Process remaining standard WSI files
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

    return result
  }

  const handleLocalMetadataChange = (key: string, field: string, value: string) => {
    setLocalMetadata(prev => {
      const updated = new Map(prev)
      const current = updated.get(key) || { label: '', case_id: '', age: '', gender: '', source: '' }
      updated.set(key, { ...current, [field]: value })
      return updated
    })
  }

  const applyBatchMetadata = () => {
    if (selectedItems.size === 0) return
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
  }

  const toggleSelectItem = (key: string) => {
    setSelectedItems(prev => {
      const updated = new Set(prev)
      if (updated.has(key)) {
        updated.delete(key)
      } else {
        updated.add(key)
      }
      return updated
    })
  }

  const toggleSelectAll = () => {
    if (selectedItems.size === localItems.length) {
      setSelectedItems(new Set())
    } else {
      setSelectedItems(new Set(localItems.map(item => item.key)))
    }
  }

  const handleLocalUpload = async () => {
    if (localItems.length === 0) return
    setShowValidation(true)
    const missingLabels = localItems.filter(item => !localMetadata.get(item.key)?.label?.trim())
    if (missingLabels.length > 0) return

    setUploading(true)
    const uploadMap = new Map<string, UploadingFile>()
    localItems.forEach(item => {
      uploadMap.set(item.key, { progress: 0, status: 'uploading' })
    })
    setUploadingFiles(uploadMap)

    for (const item of localItems) {
      const metadata = localMetadata.get(item.key)

      try {
        const age = metadata?.age ? parseInt(metadata.age) : undefined
        if (item.path) {
          await uploadWSIByPath(item.path, {
            label: metadata?.label || undefined,
            case_id: metadata?.case_id || undefined,
            age,
            gender: metadata?.gender || undefined,
            source: metadata?.source || undefined
          })
        } else if (item.file) {
          await uploadWSIFile(item.file, {
            label: metadata?.label || undefined,
            case_id: metadata?.case_id || undefined,
            age,
            gender: metadata?.gender || undefined,
            source: metadata?.source || undefined,
            associatedFiles: item.associatedFiles,
            onProgress: (progress) => {
              setUploadingFiles(prev => {
                const updated = new Map(prev)
                const current = updated.get(item.key)
                if (!current) return updated
                updated.set(item.key, { ...current, progress })
                return updated
              })
            }
          })
        } else {
          throw new Error('No file or path found for upload')
        }

        setUploadingFiles(prev => {
          const updated = new Map(prev)
          updated.set(item.key, { progress: 100, status: 'success' })
          return updated
        })
      } catch (error) {
        setUploadingFiles(prev => {
          const updated = new Map(prev)
          updated.set(item.key, { progress: 0, status: 'error', error: String(error) })
          return updated
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
    setBatchMetadata({ label: '', case_id: '', age: '', gender: '', source: '' })
    setSelectedItems(new Set())
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

  return (
    <div className="w-full px-4 max-w-7xl mx-auto pb-12">
      <PageHeader
        title="Register WSI"
        description="Register local whole slide images to the database."
      />

      {!showResults && (
        <div className="space-y-6">
          {localItems.length === 0 ? (
            <Card className="p-8 border-2 border-dashed border-slate-300 bg-slate-50/50 hover:bg-slate-50 transition-colors">
              <div 
                className={`flex flex-col items-center justify-center p-12 text-center cursor-pointer rounded-xl transition-all ${isDragging ? 'bg-blue-50 border-blue-400 scale-[1.01]' : ''}`}
                onDragOver={(e) => {
                  e.preventDefault()
                  setIsDragging(true)
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={async (e) => {
                  e.preventDefault()
                  setIsDragging(false)
                  const items = await collectItemsFromDataTransfer(e.dataTransfer)
                  addLocalItems(items)
                }}
              >
                <div className="w-20 h-20 bg-blue-100 rounded-full flex items-center justify-center mb-6">
                  <UploadCloud className="w-10 h-10 text-blue-600" />
                </div>
                <h3 className="text-xl font-semibold text-slate-900 mb-2">
                  Drag & Drop WSI files here
                </h3>
                <p className="text-slate-500 mb-8 max-w-sm mx-auto">
                  Support for .svs, .tif, .ndpi, .mrxs and other common whole slide image formats.
                </p>
                
                {supportsNativePicker && (
                  <button
                    onClick={handleLocalPathSelect}
                    className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium shadow-sm hover:shadow-md flex items-center gap-2"
                  >
                    <FolderOpen className="w-5 h-5" />
                    Browse Local Files
                  </button>
                )}
                
                {ignoredCount > 0 && (
                  <div className="mt-6 flex items-center gap-2 text-amber-600 px-4 py-2 bg-amber-50 rounded-full text-sm">
                    <AlertCircle className="w-4 h-4" />
                    <span>Ignored {ignoredCount} unsupported file(s)</span>
                  </div>
                )}
              </div>
            </Card>
          ) : (
            <div className="space-y-6">
              {/* Batch Metadata Panel */}
              <Card className="overflow-hidden border-blue-100 shadow-sm">
                <div className="border-b border-blue-100 bg-blue-50/50 px-6 py-4 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Settings2 className="w-5 h-5 text-blue-600" />
                    <h3 className="font-semibold text-blue-900">Batch Modification</h3>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-sm text-blue-600 bg-blue-100/50 px-3 py-1 rounded-full font-medium">
                      {selectedItems.size} selected
                    </span>
                    <button
                      onClick={applyBatchMetadata}
                      disabled={selectedItems.size === 0}
                      className="text-sm px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors disabled:opacity-50 font-medium"
                    >
                      Apply to Selected
                    </button>
                  </div>
                </div>
                
                <div className="p-6 bg-white">
                  <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
                    <div className="md:col-span-3 space-y-1">
                       <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider pl-1">Label</label>
                       <div className="relative">
                        <FileText className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
                        <input
                          type="text"
                          placeholder="Batch Label"
                          value={batchMetadata.label}
                          onChange={(e) => setBatchMetadata(prev => ({ ...prev, label: e.target.value }))}
                          className="w-full pl-9 pr-3 py-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
                        />
                       </div>
                    </div>
                    
                    <div className="md:col-span-2 space-y-1">
                       <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider pl-1">Case ID</label>
                       <input
                         type="text"
                         placeholder="Batch Case ID"
                         value={batchMetadata.case_id}
                         onChange={(e) => setBatchMetadata(prev => ({ ...prev, case_id: e.target.value }))}
                         className="w-full px-3 py-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
                       />
                    </div>
                    
                    <div className="md:col-span-2 space-y-1">
                       <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider pl-1">Age</label>
                       <input
                         type="number"
                         placeholder="Age"
                         value={batchMetadata.age}
                         onChange={(e) => setBatchMetadata(prev => ({ ...prev, age: e.target.value }))}
                         className="w-full px-3 py-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
                       />
                    </div>

                    <div className="md:col-span-3 space-y-1">
                         <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider pl-1">Source</label>
                         <select
                           value={batchMetadata.source}
                           onChange={(e) => setBatchMetadata(prev => ({ ...prev, source: e.target.value }))}
                           className="w-full px-2 py-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-sm"
                         >
                           <option value="">Select Source</option>
                           {organSources.map(organ => (
                             <option key={organ} value={organ}>{organ}</option>
                           ))}
                         </select>
                    </div>
                    
                    <div className="md:col-span-2 space-y-1">
                         <label className="text-xs font-semibold text-slate-500 uppercase tracking-wider pl-1">Gender</label>
                         <select
                           value={batchMetadata.gender}
                           onChange={(e) => setBatchMetadata(prev => ({ ...prev, gender: e.target.value }))}
                           className="w-full px-2 py-2 border border-slate-200 rounded-md focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 text-sm"
                         >
                           <option value="">Select Gender</option>
                           <option value="Male">Male</option>
                           <option value="Female">Female</option>
                           <option value="Unspecified">Any</option>
                         </select>
                    </div>
                  </div>
                </div>
              </Card>

              {/* Toolbar */}
              <div className="flex items-center justify-between px-2">
                 <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
                   Files to Register
                   <span className="bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full text-sm font-medium">{localItems.length}</span>
                 </h2>
                 <div className="flex items-center gap-3">
                   <label className="flex items-center gap-2 text-sm font-medium text-slate-600 cursor-pointer hover:text-slate-900">
                      <input
                        type="checkbox"
                        checked={selectedItems.size === localItems.length && localItems.length > 0}
                        onChange={toggleSelectAll}
                        className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                      />
                      Select All
                    </label>
                    {supportsNativePicker && (
                      <button 
                        onClick={handleLocalPathSelect}
                        className="text-sm text-blue-600 hover:text-blue-700 font-medium px-3 py-1.5 hover:bg-blue-50 rounded-md transition-colors"
                      >
                        + Add more files
                      </button>
                    )}
                 </div>
              </div>

              {/* Items List */}
              <div className="grid grid-cols-1 gap-4">
                {localItems.map((item) => {
                  const metadata = localMetadata.get(item.key) || { label: '', case_id: '', age: '', gender: '', source: '' }
                  const labelMissing = showValidation && !metadata.label.trim()
                  const isSelected = selectedItems.has(item.key)
                  const hasAssociatedFiles = (item.associatedFiles && item.associatedFiles.length > 0) ||
                                             (item.associatedPaths && item.associatedPaths.length > 0)
                  const associatedCount = item.associatedFiles?.length || item.associatedPaths?.length || 0

                  return (
                    <div
                      key={item.key}
                      className={`group relative bg-white border rounded-xl p-4 transition-all hover:shadow-md ${
                        isSelected
                          ? 'border-blue-400 ring-1 ring-blue-400/20 shadow-sm'
                          : 'border-slate-200'
                      }`}
                    >
                      <div className="absolute right-4 top-4 opacity-0 group-hover:opacity-100 transition-opacity">
                         <button
                           onClick={() => removeLocalItem(item.key)}
                           className="p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors"
                           title="Remove file"
                         >
                           <Trash2 className="w-4 h-4" />
                         </button>
                      </div>

                      <div className="flex flex-col md:flex-row gap-4">
                        {/* File Info */}
                        <div className="md:w-1/4 min-w-0 pr-4 border-r border-slate-100">
                          <div className="flex items-start gap-3">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleSelectItem(item.key)}
                              className="mt-1 w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500 flex-shrink-0"
                            />
                            <div className="min-w-0">
                               <h4 className="font-medium text-slate-900 truncate text-sm" title={item.name}>{item.name}</h4>
                               {item.path ? (
                                 <p className="text-xs text-slate-500 truncate mt-1 font-mono" title={item.path}>{item.path}</p>
                               ) : (
                                  <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 mt-1">
                                    {(item.file?.size || 0) / 1024 / 1024 > 1 ? `${((item.file?.size || 0) / 1024 / 1024).toFixed(1)} MB` : 'File'}
                                  </span>
                               )}
                               {/* Show file type badge */}
                               {(() => {
                                 const ext = item.name.split('.').pop()?.toUpperCase() || ''
                                 // For path mode, backend auto-detects associated files in same directory
                                 const isPathMode = !!item.path

                                 if (item.type === 'mrxs') {
                                   return (
                                     <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 mt-1 ml-1">
                                       MRXS {hasAssociatedFiles ? `+${associatedCount} files` : isPathMode ? '' : ''}
                                     </span>
                                   )
                                 } else if (item.type === 'tmap') {
                                   return (
                                     <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 mt-1 ml-1">
                                       TMAP {hasAssociatedFiles ? `+${associatedCount} DT files` : ''}
                                     </span>
                                   )
                                 } else {
                                   return (
                                     <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 mt-1 ml-1">
                                       {ext}
                                     </span>
                                   )
                                 }
                               })()}
                            </div>
                          </div>
                        </div>
                        
                        {/* Metadata Inputs */}
                        <div className="flex-1 grid grid-cols-1 md:grid-cols-12 gap-3 items-center">
                            <div className="md:col-span-3">
                                <input
                                  type="text"
                                  placeholder="Label (Required) *"
                                  value={metadata.label}
                                  onChange={(e) => handleLocalMetadataChange(item.key, 'label', e.target.value)}
                                  className={`w-full px-3 py-2 border rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 transition-all ${
                                    labelMissing ? 'border-red-400 bg-red-50 focus:border-red-500' : 'border-slate-200 focus:border-blue-500'
                                  }`}
                                />
                                {labelMissing && <p className="text-[10px] text-red-500 mt-1 pl-1">Required</p>}
                            </div>
                            
                            <div className="md:col-span-2">
                                <input
                                  type="text"
                                  placeholder="Case ID"
                                  value={metadata.case_id}
                                  onChange={(e) => handleLocalMetadataChange(item.key, 'case_id', e.target.value)}
                                  className="w-full px-3 py-2 border border-slate-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                                />
                            </div>

                            <div className="md:col-span-2">
                                <input
                                  type="number"
                                  placeholder="Age"
                                  value={metadata.age}
                                  onChange={(e) => handleLocalMetadataChange(item.key, 'age', e.target.value)}
                                  className="w-full px-3 py-2 border border-slate-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                                />
                            </div>

                            <div className="md:col-span-3">
                                <select
                                  value={metadata.source}
                                  onChange={(e) => handleLocalMetadataChange(item.key, 'source', e.target.value)}
                                  className="w-full px-2 py-2 border border-slate-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                                >
                                  <option value="">Source</option>
                                  {organSources.map(organ => (
                                    <option key={organ} value={organ}>{organ}</option>
                                  ))}
                                </select>
                            </div>
                            
                            <div className="md:col-span-2">
                                <select
                                  value={metadata.gender}
                                  onChange={(e) => handleLocalMetadataChange(item.key, 'gender', e.target.value)}
                                  className="w-full px-2 py-2 border border-slate-200 rounded-md text-sm focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                                >
                                  <option value="">Sex</option>
                                  <option value="Male">M</option>
                                  <option value="Female">F</option>
                                  <option value="Unspecified">?</option>
                                </select>
                            </div>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Add More Files Drop Zone */}
              <div
                className={`border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-all ${
                  isDragging
                    ? 'bg-blue-50 border-blue-400'
                    : 'border-slate-300 bg-slate-50/50 hover:bg-slate-50 hover:border-slate-400'
                }`}
                onDragOver={(e) => {
                  e.preventDefault()
                  setIsDragging(true)
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={async (e) => {
                  e.preventDefault()
                  setIsDragging(false)
                  const items = await collectItemsFromDataTransfer(e.dataTransfer)
                  addLocalItems(items)
                }}
              >
                <div className="flex items-center justify-center gap-3 text-slate-500">
                  <UploadCloud className="w-5 h-5" />
                  <span className="text-sm font-medium">Drop more files here to add</span>
                </div>
              </div>

              {/* Action Bar */}
              <div className="sticky bottom-6 z-10 bg-white/80 backdrop-blur-md border border-slate-200 shadow-xl rounded-2xl p-4 mt-8 flex items-center justify-between gap-4">
                 <div className="text-sm text-slate-500 pl-2">
                    Ready to register <strong className="text-slate-900">{localItems.length}</strong> slide(s).
                 </div>
                 <div className="flex gap-3">
                    <button
                      onClick={resetUpload}
                      disabled={uploading}
                      className="px-6 py-2.5 text-slate-700 font-medium hover:bg-slate-100 rounded-lg transition-colors border border-transparent hover:border-slate-200"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={handleLocalUpload}
                      disabled={uploading}
                      className="px-8 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-all font-semibold shadow-md active:scale-95 disabled:opacity-70 flex items-center gap-2"
                    >
                      {uploading ? (
                        <>
                          <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                          Processing...
                        </>
                      ) : (
                        <>
                          <Download className="w-5 h-5" />
                          Register
                        </>
                      )}
                    </button>
                 </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Results Section */}
      {showResults && (
        <Card className="max-w-xl mx-auto mt-12 p-12 text-center border-2 border-green-50 shadow-none bg-white">
          <div className="w-24 h-24 bg-green-50 rounded-full flex items-center justify-center mx-auto mb-8">
             <CheckCircle2 className="w-12 h-12 text-green-600" />
          </div>
          <h2 className="text-3xl font-bold text-slate-900 mb-4">Registration Complete</h2>
          <p className="text-lg text-slate-600 mb-8">
            Successfully registered <strong className="text-slate-900">{Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length}</strong> slides.
          </p>

          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <button
              onClick={() => navigate('/wsi-list')}
              className="px-8 py-3 bg-blue-600 text-white rounded-xl hover:bg-blue-700 transition-colors font-medium flex items-center justify-center gap-2 shadow-sm"
            >
              View Slides
              <ArrowRight className="w-5 h-5" />
            </button>
            <button
              onClick={resetUpload}
              className="px-8 py-3 border border-slate-200 text-slate-700 rounded-xl hover:bg-slate-50 transition-colors font-medium"
            >
              Register More
            </button>
          </div>
        </Card>
      )}
    </div>
  )
}

