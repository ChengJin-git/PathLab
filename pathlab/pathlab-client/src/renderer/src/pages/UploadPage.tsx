import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, CheckCircle2, XCircle, AlertCircle, ArrowRight } from 'lucide-react'
import { uploadWSIByPath } from '../api'
import { PageHeader } from '../components/PageHeader'
import { Card } from '../components/ui/card'

interface UploadingFile {
  progress: number
  status: 'uploading' | 'success' | 'error'
  error?: string
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
  const [localPaths, setLocalPaths] = useState<string[]>([])
  const [localMetadata, setLocalMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>>(new Map())
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, UploadingFile>>(new Map())
  const [uploading, setUploading] = useState(false)
  const [showResults, setShowResults] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [showValidation, setShowValidation] = useState(false)
  const [ignoredCount, setIgnoredCount] = useState(0)

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

  const isSupportedPath = (path: string) => {
    const normalized = path.toLowerCase()
    return wsiExtensions.some(ext => normalized.endsWith(ext))
  }

  const addLocalPaths = (paths: string[]) => {
    if (!paths.length) return
    const filtered = paths.filter(isSupportedPath)
    setIgnoredCount(paths.length - filtered.length)
    if (filtered.length === 0) return
    setLocalPaths(prev => {
      const merged = new Set(prev)
      filtered.forEach(p => merged.add(p))
      return Array.from(merged)
    })

    setLocalMetadata(prev => {
      const updated = new Map(prev)
      filtered.forEach(path => {
        if (!updated.has(path)) {
          updated.set(path, { label: '', case_id: '', age: '', gender: '', source: '' })
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
      addLocalPaths(paths)
    }
  }

  const getFilePath = (file: File) => (file as any).path as string | undefined

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

  const collectPathsFromEntry = async (entry: any): Promise<string[]> => {
    if (entry?.isFile) {
      return new Promise(resolve => {
        entry.file((file: File) => {
          const path = getFilePath(file)
          resolve(path ? [path] : [])
        }, () => resolve([]))
      })
    }
    if (entry?.isDirectory) {
      const entries = await readAllEntries(entry)
      const nested = await Promise.all(entries.map(collectPathsFromEntry))
      return nested.flat()
    }
    return []
  }

  const collectPathsFromDataTransfer = async (dataTransfer: DataTransfer) => {
    const items = Array.from(dataTransfer.items || [])
    const hasEntries = items.some(item => (item as any).webkitGetAsEntry)
    if (hasEntries) {
      const entries = items
        .map(item => (item as any).webkitGetAsEntry?.())
        .filter(Boolean)
      const nested = await Promise.all(entries.map(collectPathsFromEntry))
      return nested.flat()
    }
    const files = Array.from(dataTransfer.files || [])
    return files.map(file => getFilePath(file)).filter(Boolean) as string[]
  }

  const handleLocalMetadataChange = (path: string, field: string, value: string) => {
    setLocalMetadata(prev => {
      const updated = new Map(prev)
      const current = updated.get(path) || { label: '', case_id: '', age: '', gender: '', source: '' }
      updated.set(path, { ...current, [field]: value })
      return updated
    })
  }

  const handleLocalUpload = async () => {
    if (localPaths.length === 0) return
    setShowValidation(true)
    const missingLabels = localPaths.filter(path => !localMetadata.get(path)?.label?.trim())
    if (missingLabels.length > 0) return

    setUploading(true)
    const uploadMap = new Map<string, UploadingFile>()
    localPaths.forEach(path => {
      uploadMap.set(path, { progress: 0, status: 'uploading' })
    })
    setUploadingFiles(uploadMap)

    for (const path of localPaths) {
      const metadata = localMetadata.get(path)

      try {
        const age = metadata?.age ? parseInt(metadata.age) : undefined
        await uploadWSIByPath(path, {
          label: metadata?.label || undefined,
          case_id: metadata?.case_id || undefined,
          age,
          gender: metadata?.gender || undefined,
          source: metadata?.source || undefined
        })

        setUploadingFiles(prev => {
          const updated = new Map(prev)
          updated.set(path, { progress: 100, status: 'success' })
          return updated
        })
      } catch (error) {
        setUploadingFiles(prev => {
          const updated = new Map(prev)
          updated.set(path, { progress: 0, status: 'error', error: String(error) })
          return updated
        })
      }
    }

    setUploading(false)
    setShowResults(true)
  }

  const resetUpload = () => {
    setLocalPaths([])
    setLocalMetadata(new Map())
    setUploadingFiles(new Map())
    setShowResults(false)
    setShowValidation(false)
    setIgnoredCount(0)
  }

  return (
    <div className="w-full px-4">
      {/* Header */}
      <PageHeader
        title="Register WSI"
        description="Register local whole slide images"
      />

      {/* Local Path Section */}
      {!showResults && (
        <Card className="p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Register Local WSI Files</h2>

          <div className="mb-6 space-y-3">
            <div
              className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors ${isDragging ? 'border-green-500 bg-green-50' : 'border-gray-200 bg-gray-50'}`}
              onDragOver={(e) => {
                e.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={async (e) => {
                e.preventDefault()
                setIsDragging(false)
                const paths = await collectPathsFromDataTransfer(e.dataTransfer)
                addLocalPaths(paths)
              }}
            >
              <p className="text-sm font-medium text-gray-900 mb-1">Drag & drop files or folders</p>
              <p className="text-xs text-gray-500">Unsupported files will be ignored</p>
            </div>

            <div className="flex flex-wrap gap-2 items-center">
              {supportsNativePicker && (
                <button
                  onClick={handleLocalPathSelect}
                  disabled={uploading}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors text-sm font-medium disabled:opacity-50"
                >
                  Select Local WSI Files
                </button>
              )}
              <span className="text-xs text-gray-500">
                Required: Label. Optional: Case ID, Age, Gender, Source.
              </span>
            </div>

            {ignoredCount > 0 && (
              <div className="text-xs text-amber-600">
                Ignored {ignoredCount} unsupported file(s).
              </div>
            )}
          </div>

          {localPaths.length > 0 && (
            <>
              <h3 className="text-md font-semibold text-gray-900 mb-3">Local File Metadata ({localPaths.length} files)</h3>
              <div className="space-y-4 max-h-[400px] overflow-y-auto">
                {localPaths.map((path, index) => {
                  const metadata = localMetadata.get(path) || { label: '', case_id: '', age: '', gender: '', source: '' }
                  const labelMissing = showValidation && !metadata.label.trim()
                  return (
                    <div key={path} className="border border-gray-200 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <span className="text-sm font-medium text-gray-900">{index + 1}. {path.split(/[/\\]/).pop()}</span>
                        <span className="text-xs text-gray-500 truncate max-w-xs" title={path}>{path}</span>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
                        <input
                          type="text"
                          placeholder="Label *"
                          value={metadata.label}
                          onChange={(e) => handleLocalMetadataChange(path, 'label', e.target.value)}
                          className={`px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent ${labelMissing ? 'border-red-500' : 'border-gray-300'}`}
                        />
                        <input
                          type="text"
                          placeholder="Case ID"
                          value={metadata.case_id}
                          onChange={(e) => handleLocalMetadataChange(path, 'case_id', e.target.value)}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
                        />
                        <input
                          type="number"
                          placeholder="Age"
                          value={metadata.age}
                          onChange={(e) => handleLocalMetadataChange(path, 'age', e.target.value)}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
                        />
                        <input
                          type="text"
                          placeholder="Source"
                          value={metadata.source}
                          onChange={(e) => handleLocalMetadataChange(path, 'source', e.target.value)}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
                        />
                        <select
                          value={metadata.gender}
                          onChange={(e) => handleLocalMetadataChange(path, 'gender', e.target.value)}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-green-500 focus:border-transparent"
                        >
                          <option value="">Gender</option>
                          <option value="Male">Male</option>
                          <option value="Female">Female</option>
                          <option value="Unspecified">Unspecified</option>
                        </select>
                      </div>
                      {labelMissing && (
                        <p className="text-xs text-red-600 mt-2">Label is required.</p>
                      )}
                    </div>
                  )
                })}
              </div>

              <div className="mt-6 flex gap-3">
                <button
                  onClick={handleLocalUpload}
                  disabled={uploading}
                  className="flex-1 px-6 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {uploading ? (
                    <>
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                      Registering...
                    </>
                  ) : (
                    <>
                      <Download className="w-5 h-5" />
                      Register {localPaths.length} File(s)
                    </>
                  )}
                </button>
                <button
                  onClick={resetUpload}
                  disabled={uploading}
                  className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-semibold disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </>
          )}
        </Card>
      )}

      {/* Results Section */}
      {showResults && (
        <Card className="p-6">
          <div className="text-center mb-6">
            <CheckCircle2 className="w-16 h-16 text-green-600 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Registration Complete</h2>
            <p className="text-gray-600">
              {Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length} of {uploadingFiles.size} files registered successfully
            </p>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => navigate('/wsi-list')}
              className="flex-1 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-semibold flex items-center justify-center gap-2"
            >
              View Slides
              <ArrowRight className="w-5 h-5" />
            </button>
            <button
              onClick={resetUpload}
              className="px-6 py-3 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors font-semibold"
            >
              Register More
            </button>
          </div>
        </Card>
      )}
    </div>
  )
}

