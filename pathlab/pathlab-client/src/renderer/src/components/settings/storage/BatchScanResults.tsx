import React from 'react'
import {
  CheckCircle, AlertCircle, RefreshCw, Upload,
  Layers, Clock, Info
} from 'lucide-react'
import { Button } from '../../ui/button'
import { Label } from '../../ui/label'
import { Badge } from '../../ui/badge'
import { Checkbox } from '../../ui/checkbox'
import { ScanDirectoryResponse, DatasetSummary } from '../../../api'
import { DataLevelSelection } from './DataLevelSelection'
import { DatasetSelection } from './DatasetSelection'

interface BatchScanResultsProps {
  batchScanResult: ScanDirectoryResponse
  batchSelectedFiles: Set<string>
  batchDatasetMode: 'existing' | 'new'
  setBatchDatasetMode: (mode: 'existing' | 'new') => void
  batchSelectedDatasetId: string
  setBatchSelectedDatasetId: (id: string) => void
  batchNewDatasetNameRef: React.RefObject<HTMLInputElement>
  batchRegistering: boolean
  batchImportTaskId: string | null
  batchDatasets: DatasetSummary[]
  batchTaskType: 'classification' | 'survival'
  setBatchTaskType: (type: 'classification' | 'survival') => void
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
  handleBatchFileToggle: (path: string) => void
  handleBatchSelectAll: () => void
  handleBatchDeselectAll: () => void
  handleBatchRegister: () => Promise<void>
  formatFileSize: (bytes: number) => string
}

export const BatchScanResults: React.FC<BatchScanResultsProps> = ({
  batchScanResult,
  batchSelectedFiles,
  batchDatasetMode,
  setBatchDatasetMode,
  batchSelectedDatasetId,
  setBatchSelectedDatasetId,
  batchNewDatasetNameRef,
  batchRegistering,
  batchImportTaskId,
  batchDatasets,
  batchTaskType,
  setBatchTaskType,
  batchDataLevel,
  setBatchDataLevel,
  handleBatchFileToggle,
  handleBatchSelectAll,
  handleBatchDeselectAll,
  handleBatchRegister,
  formatFileSize
}) => (
  <div className="space-y-4">
    <div className="flex items-center justify-between">
      <div className="text-sm text-gray-600">
        Found <span className="font-semibold text-gray-900">{batchScanResult.total_count}</span> files
        ({batchScanResult.files.filter(f => f.data_type === 'wsi').length} WSI, {batchScanResult.files.filter(f => f.data_type === 'patch').length} patch, {batchScanResult.valid_count} valid, {formatFileSize(batchScanResult.total_size)} total)
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" onClick={handleBatchSelectAll}>
          Select All Valid
        </Button>
        <Button variant="outline" size="sm" onClick={handleBatchDeselectAll}>
          Deselect All
        </Button>
      </div>
    </div>

    {/* File List */}
    <div className="max-h-80 overflow-y-auto border border-gray-100 rounded-xl shadow-sm bg-white">
      <table className="w-full text-sm">
        <thead className="bg-gray-50/80 backdrop-blur-sm sticky top-0 border-b border-gray-100">
          <tr>
            <th className="px-3 py-3 text-left w-10"></th>
            <th className="px-3 py-3 text-left font-semibold text-gray-700">Filename</th>
            <th className="px-3 py-3 text-left w-16 font-semibold text-gray-700">Type</th>
            <th className="px-3 py-3 text-left w-20 font-semibold text-gray-700">Format</th>
            <th className="px-3 py-3 text-right w-24 font-semibold text-gray-700">Size</th>
            <th className="px-3 py-3 text-left w-32 font-semibold text-gray-700">Status</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {batchScanResult.files.map((file) => (
            <tr
              key={file.path}
              className={`hover:bg-gray-50/50 transition-colors ${!file.valid ? 'opacity-60' : ''}`}
            >
              <td className="px-3 py-3">
                <Checkbox
                  checked={batchSelectedFiles.has(file.path)}
                  onCheckedChange={() => handleBatchFileToggle(file.path)}
                  disabled={!file.valid}
                />
              </td>
              <td className="px-3 py-3 font-medium text-xs truncate max-w-xs" title={file.path}>
                {file.filename}
              </td>
              <td className="px-3 py-3">
                <span className={`inline-flex px-2 py-0.5 text-xs rounded ${
                  file.data_type === 'wsi' ? 'bg-blue-100 text-blue-700' : 'bg-amber-100 text-amber-700'
                }`}>
                  {file.data_type === 'wsi' ? 'WSI' : 'Patch'}
                </span>
              </td>
              <td className="px-3 py-3">
                <span className={`inline-flex px-2 py-0.5 text-xs rounded ${
                  file.format_type === 'mrxs' ? 'bg-purple-100 text-purple-700' :
                  file.format_type === 'tmap' ? 'bg-primary-100 text-primary-700' :
                  'bg-gray-100 text-gray-700'
                }`}>
                  {file.extension}
                </span>
              </td>
              <td className="px-3 py-3 text-right text-gray-500">
                {formatFileSize(file.size)}
              </td>
              <td className="px-3 py-3">
                {file.valid ? (
                  <Badge variant="outline" className="bg-green-50 text-green-700 border-green-200 gap-1 py-0 px-2 font-normal">
                    <CheckCircle className="w-3 h-3" /> Valid
                  </Badge>
                ) : (
                  <Badge variant="outline" className="bg-red-50 text-red-700 border-red-200 gap-1 py-0 px-2 font-normal" title={file.validation_message || ''}>
                    <AlertCircle className="w-3 h-3" /> Invalid
                  </Badge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>

    {/* Task Type Selection */}
    <div className="bg-slate-50 rounded-lg p-4 space-y-3 border border-slate-200">
      <Label className="text-sm font-medium text-slate-900 block">Task Type</Label>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setBatchTaskType('classification')}
          className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
            batchTaskType === 'classification'
              ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
              : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Layers className={`w-4 h-4 ${batchTaskType === 'classification' ? 'text-primary-700' : 'text-gray-400'}`} />
            Classification
          </div>
        </button>
        <button
          type="button"
          onClick={() => setBatchTaskType('survival')}
          className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
            batchTaskType === 'survival'
              ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
              : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Clock className={`w-4 h-4 ${batchTaskType === 'survival' ? 'text-primary-700' : 'text-gray-400'}`} />
            Survival Analysis
          </div>
        </button>
      </div>

      {/* Info message based on task type */}
      <div className="flex items-start gap-2 p-3 bg-white rounded-lg border border-slate-100">
        <Info className="w-4 h-4 text-primary-500 mt-0.5 flex-shrink-0" />
        <div className="text-xs text-gray-600">
          {batchTaskType === 'classification' ? (
            <>
              Files will be registered with default label: <span className="font-medium text-gray-800">"External Import"</span>
              <br />
              You can modify labels later in the <span className="font-medium text-primary-600">Data Repository</span> page.
            </>
          ) : (
            <>
              Files will be registered with <span className="font-medium text-gray-800">no event time/status</span> set.
              <br />
              You can set survival data later in the <span className="font-medium text-primary-600">Data Repository</span> page.
            </>
          )}
        </div>
      </div>
    </div>

    {/* Data Level Selection */}
    <DataLevelSelection batchDataLevel={batchDataLevel} setBatchDataLevel={setBatchDataLevel} />

    {/* Dataset Selection */}
    <DatasetSelection
      batchDatasetMode={batchDatasetMode}
      setBatchDatasetMode={setBatchDatasetMode}
      batchSelectedDatasetId={batchSelectedDatasetId}
      setBatchSelectedDatasetId={setBatchSelectedDatasetId}
      batchNewDatasetNameRef={batchNewDatasetNameRef}
      batchDatasets={batchDatasets}
    />

    {/* Register Button */}
    <div className="flex items-center justify-between">
      <div className="text-sm text-gray-600">
        {batchSelectedFiles.size} file(s) selected
      </div>
      <Button
        onClick={handleBatchRegister}
        disabled={batchSelectedFiles.size === 0 || batchRegistering}
        className="gap-2"
      >
        {batchRegistering ? (
          <>
            <RefreshCw className="w-4 h-4 animate-spin" />
            Registering...
          </>
        ) : (
          <>
            <Upload className="w-4 h-4" />
            Register Selected ({batchSelectedFiles.size})
          </>
        )}
      </Button>
    </div>

    {/* Task Submitted Message */}
    {batchImportTaskId && (
      <div className="p-4 rounded-lg border bg-blue-50 border-blue-200">
        <div className="flex items-center gap-2 font-semibold text-blue-700">
          <CheckCircle className="w-5 h-5" />
          Import Task Submitted
        </div>
        <div className="text-sm text-blue-600 mt-1">
          Task ID: <span className="font-mono">{batchImportTaskId}</span>
        </div>
        <div className="text-sm text-blue-600 mt-1">
          Files are being registered in the background. Check the notification center for progress.
        </div>
      </div>
    )}
  </div>
)

