import { useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Upload, FileSpreadsheet, Download, CheckCircle2, XCircle, AlertCircle, ArrowRight, Microscope, Image } from 'lucide-react'
import { uploadWSIFile, uploadWSIByCSV, downloadCSVTemplate } from '../api'
import { PageHeader } from '../components/PageHeader'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'

interface UploadingFile {
  progress: number
  status: 'uploading' | 'success' | 'error'
  error?: string
}

export default function UploadPage() {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const csvInputRef = useRef<HTMLInputElement>(null)

  const [dataLevel, setDataLevel] = useState<'wsi' | 'patch'>('wsi')
  const [uploadMethod, setUploadMethod] = useState<'file' | 'csv'>('file')
  const [selectedFiles, setSelectedFiles] = useState<File[]>([])
  const [fileMetadata, setFileMetadata] = useState<Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>>(new Map())
  const [uploadingFiles, setUploadingFiles] = useState<Map<string, UploadingFile>>(new Map())
  const [uploading, setUploading] = useState(false)
  const [csvResults, setCsvResults] = useState<any>(null)
  const [showResults, setShowResults] = useState(false)

  // File extensions based on data level
  const wsiExtensions = ['.svs', '.svslide', '.ndpi', '.scn', '.mrxs', '.bif', '.tif', '.tiff', '.vsi', '.vms', '.vmu', '.kfb', '.sdpc', '.TMAP', '.mds', '.mdsx', '.qptiff', '.tron', '.isyntax']
  const patchExtensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff']

  const acceptedFormats = dataLevel === 'wsi'
    ? wsiExtensions.join(',')
    : patchExtensions.join(',')

  const formatDescription = dataLevel === 'wsi'
    ? 'Supports .svs, .svslide, .ndpi, .scn, .mrxs, .bif, .tif, .tiff, .vsi, .vms, .vmu, .kfb, .sdpc, .TMAP, .mds, .mdsx, .qptiff, .tron, .isyntax'
    : 'Supports .jpg, .jpeg, .png, .bmp, .tif, .tiff'

  const handleFileSelect = (files: FileList | null) => {
    if (!files || files.length === 0) return

    const filesArray = Array.from(files)
    setSelectedFiles(filesArray)

    // Initialize metadata for each file
    const metadata = new Map<string, { label: string; case_id: string; age: string; gender: string; source: string }>()
    filesArray.forEach(file => {
      metadata.set(file.name, { label: '', case_id: '', age: '', gender: '', source: '' })
    })
    setFileMetadata(metadata)
  }

  const handleMetadataChange = (fileName: string, field: string, value: string) => {
    setFileMetadata(prev => {
      const updated = new Map(prev)
      const current = updated.get(fileName) || { label: '', case_id: '', age: '', gender: '', source: '' }
      updated.set(fileName, { ...current, [field]: value })
      return updated
    })
  }

  const handleFileUpload = async () => {
    if (selectedFiles.length === 0) return

    setUploading(true)
    const uploadMap = new Map<string, UploadingFile>()
    selectedFiles.forEach(file => {
      uploadMap.set(file.name, { progress: 0, status: 'uploading' })
    })
    setUploadingFiles(uploadMap)

    for (const file of selectedFiles) {
      const metadata = fileMetadata.get(file.name)

      try {
        const age = metadata?.age ? parseInt(metadata.age) : undefined
        await uploadWSIFile(file, {
          label: metadata?.label || undefined,
          case_id: metadata?.case_id || undefined,
          age: age,
          gender: metadata?.gender || undefined,
          source: metadata?.source || undefined,
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
      } catch (error) {
        setUploadingFiles(prev => {
          const updated = new Map(prev)
          updated.set(file.name, { progress: 0, status: 'error', error: String(error) })
          return updated
        })
      }
    }

    setUploading(false)
    setShowResults(true)
  }

  const handleCSVUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return

    const file = files[0]
    if (!file.name.endsWith('.csv')) {
      alert('Please select a CSV file')
      return
    }

    setUploading(true)

    try {
      const result = await uploadWSIByCSV(file)
      setCsvResults(result)
      setShowResults(true)
    } catch (error) {
      alert(`Failed to process CSV: ${error}`)
    } finally {
      setUploading(false)
      if (csvInputRef.current) {
        csvInputRef.current.value = ''
      }
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      await downloadCSVTemplate()
    } catch (error) {
      alert(`Failed to download template: ${error}`)
    }
  }

  const resetUpload = () => {
    setSelectedFiles([])
    setFileMetadata(new Map())
    setUploadingFiles(new Map())
    setCsvResults(null)
    setShowResults(false)
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (csvInputRef.current) csvInputRef.current.value = ''
  }

  return (
    <div className="w-full px-4">
      {/* Header */}
      <PageHeader
        title="Upload Files"
        description="Upload whole slide images or patch images to your collection"
      />

      {/* Data Level Selection */}
      <Card className="p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Select Data Level</h2>
        <div className="grid grid-cols-2 gap-4">
          <button
            onClick={() => {
              setDataLevel('wsi')
              setSelectedFiles([])
              setFileMetadata(new Map())
              if (fileInputRef.current) fileInputRef.current.value = ''
            }}
            className={`p-6 rounded-lg border-2 transition-all ${dataLevel === 'wsi'
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-200 hover:border-gray-300'
              }`}
          >
            <Microscope className="w-8 h-8 mx-auto mb-3 text-blue-600" />
            <h3 className="font-semibold text-gray-900 mb-1">WSI Level</h3>
            <p className="text-sm text-gray-600">Upload whole slide images</p>
          </button>
          <button
            onClick={() => {
              setDataLevel('patch')
              setSelectedFiles([])
              setFileMetadata(new Map())
              if (fileInputRef.current) fileInputRef.current.value = ''
            }}
            className={`p-6 rounded-lg border-2 transition-all ${dataLevel === 'patch'
                ? 'border-green-500 bg-green-50'
                : 'border-gray-200 hover:border-gray-300'
              }`}
          >
            <Image className="w-8 h-8 mx-auto mb-3 text-green-600" />
            <h3 className="font-semibold text-gray-900 mb-1">Patch Level</h3>
            <p className="text-sm text-gray-600">Upload patch/tile images</p>
          </button>
        </div>
      </Card>

      {/* Upload Method Selection */}
      <Card className="p-6 mb-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">Choose Upload Method</h2>
        <div className="grid grid-cols-2 gap-4">
          <button
            onClick={() => setUploadMethod('file')}
            className={`p-6 rounded-lg border-2 transition-all ${uploadMethod === 'file'
                ? 'border-blue-500 bg-blue-50'
                : 'border-gray-200 hover:border-gray-300'
              }`}
          >
            <Upload className="w-8 h-8 mx-auto mb-3 text-blue-600" />
            <h3 className="font-semibold text-gray-900 mb-1">File Upload</h3>
            <p className="text-sm text-gray-600">Upload individual files with metadata</p>
          </button>
          <button
            onClick={() => setUploadMethod('csv')}
            className={`p-6 rounded-lg border-2 transition-all ${uploadMethod === 'csv'
                ? 'border-purple-500 bg-purple-50'
                : 'border-gray-200 hover:border-gray-300'
              }`}
          >
            <FileSpreadsheet className="w-8 h-8 mx-auto mb-3 text-purple-600" />
            <h3 className="font-semibold text-gray-900 mb-1">Batch Import (CSV)</h3>
            <p className="text-sm text-gray-600">Import multiple files using a CSV file</p>
          </button>
        </div>
      </Card>

      {/* File Upload Section */}
      {uploadMethod === 'file' && !showResults && (
        <Card className="p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Select Files</h2>

          <div className="mb-6">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept={acceptedFormats}
              onChange={(e) => handleFileSelect(e.target.files)}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="w-full px-8 py-12 border-2 border-dashed border-gray-300 rounded-xl hover:border-blue-500 hover:bg-blue-50 transition-all disabled:opacity-50"
            >
              <Upload className="w-16 h-16 mx-auto mb-4 text-gray-400" />
              <p className="text-lg font-semibold text-gray-700 mb-2">
                Click to select {dataLevel === 'wsi' ? 'WSI' : 'Patch'} files
              </p>
              <p className="text-sm text-gray-500">{formatDescription}</p>
            </button>
          </div>

          {selectedFiles.length > 0 && (
            <>
              <h3 className="text-md font-semibold text-gray-900 mb-3">File Metadata ({selectedFiles.length} files)</h3>
              <div className="space-y-4 max-h-96 overflow-y-auto">
                {selectedFiles.map((file) => {
                  const metadata = fileMetadata.get(file.name) || { label: '', case_id: '', age: '', gender: '', source: '' }
                  const uploadStatus = uploadingFiles.get(file.name)

                  return (
                    <div key={file.name} className="border border-gray-200 rounded-lg p-4">
                      <div className="flex items-center justify-between mb-3">
                        <p className="font-medium text-gray-900 truncate flex-1">{file.name}</p>
                        {uploadStatus && (
                          <span className={`ml-2 px-2 py-1 text-xs font-medium rounded ${uploadStatus.status === 'success' ? 'bg-green-100 text-green-800' :
                              uploadStatus.status === 'error' ? 'bg-red-100 text-red-800' :
                                'bg-blue-100 text-blue-800'
                            }`}>
                            {uploadStatus.status === 'uploading' ? `${uploadStatus.progress}%` : uploadStatus.status}
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <input
                          type="text"
                          placeholder="Label (e.g., HSIL)"
                          value={metadata.label}
                          onChange={(e) => handleMetadataChange(file.name, 'label', e.target.value)}
                          disabled={uploading}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
                        />
                        <input
                          type="text"
                          placeholder="Case ID"
                          value={metadata.case_id}
                          onChange={(e) => handleMetadataChange(file.name, 'case_id', e.target.value)}
                          disabled={uploading}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
                        />
                        <input
                          type="number"
                          placeholder="Age"
                          value={metadata.age}
                          onChange={(e) => handleMetadataChange(file.name, 'age', e.target.value)}
                          disabled={uploading}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
                        />
                        <select
                          value={metadata.gender}
                          onChange={(e) => handleMetadataChange(file.name, 'gender', e.target.value)}
                          disabled={uploading}
                          className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
                        >
                          <option value="">Gender</option>
                          <option value="Male">Male</option>
                          <option value="Female">Female</option>
                        </select>
                      </div>
                    </div>
                  )
                })}
              </div>

              <div className="mt-6 flex gap-3">
                <button
                  onClick={handleFileUpload}
                  disabled={uploading}
                  className="flex-1 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-semibold disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {uploading ? (
                    <>
                      <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="w-5 h-5" />
                      Upload {selectedFiles.length} File(s)
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

      {/* CSV Upload Section */}
      {uploadMethod === 'csv' && !showResults && (
        <Card className="p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Batch Import via CSV</h2>

          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
            <h3 className="font-medium text-blue-900 mb-2">CSV Format</h3>
            <p className="text-sm text-blue-800 mb-3">Your CSV file should contain the following columns:</p>
            <code className="block bg-white px-3 py-2 rounded text-xs text-gray-800 mb-3">
              wsi_path,label,case_id,age,gender,source,wsi_id
            </code>
            <button
              onClick={handleDownloadTemplate}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Download Template
            </button>
          </div>

          <input
            ref={csvInputRef}
            type="file"
            accept=".csv"
            onChange={(e) => handleCSVUpload(e.target.files)}
            className="hidden"
          />
          <button
            onClick={() => csvInputRef.current?.click()}
            disabled={uploading}
            className="w-full px-8 py-12 border-2 border-dashed border-gray-300 rounded-xl hover:border-purple-500 hover:bg-purple-50 transition-all disabled:opacity-50"
          >
            <FileSpreadsheet className="w-16 h-16 mx-auto mb-4 text-gray-400" />
            <p className="text-lg font-semibold text-gray-700 mb-2">Click to select CSV file</p>
            <p className="text-sm text-gray-500">Upload a CSV file with WSI paths and metadata</p>
          </button>

          {uploading && (
            <div className="mt-4 p-4 bg-blue-50 border border-blue-200 rounded-lg">
              <div className="flex items-center gap-3">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
                <p className="text-sm text-blue-800">Processing CSV file...</p>
              </div>
            </div>
          )}
        </Card>
      )}

      {/* Results Section */}
      {showResults && (
        <Card className="p-6">
          <div className="text-center mb-6">
            <CheckCircle2 className="w-16 h-16 text-green-600 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Upload Complete</h2>
            {csvResults ? (
              <p className="text-gray-600">
                {csvResults.success} succeeded, {csvResults.failed} failed
              </p>
            ) : (
              <p className="text-gray-600">
                {Array.from(uploadingFiles.values()).filter(f => f.status === 'success').length} of {uploadingFiles.size} files uploaded successfully
              </p>
            )}
          </div>

          {/* CSV Results Details */}
          {csvResults && csvResults.results && csvResults.results.length > 0 && (
            <div className="mb-6 border border-gray-200 rounded-lg overflow-hidden">
              <div className="overflow-x-auto max-h-96">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">WSI ID</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Path</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                      <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">Message</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {csvResults.results.map((result: any, idx: number) => (
                      <tr key={idx} className={result.status === 'success' ? 'bg-green-50' : 'bg-red-50'}>
                        <td className="px-4 py-3 text-sm text-gray-900">{result.wsi_id || 'N/A'}</td>
                        <td className="px-4 py-3 text-sm text-gray-600 truncate max-w-xs" title={result.wsi_path}>
                          {result.wsi_path}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${result.status === 'success'
                              ? 'bg-green-100 text-green-800'
                              : 'bg-red-100 text-red-800'
                            }`}>
                            {result.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-gray-600">{result.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

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
              Upload More
            </button>
          </div>
        </Card>
      )}
    </div>
  )
}

