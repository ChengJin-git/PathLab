import React from 'react'
import { HardDrive, Search, Trash2, RefreshCw, ChevronRight } from 'lucide-react'
import { Button } from '../../ui/button'
import { Checkbox } from '../../ui/checkbox'
import { ExternalDatasetInfo } from '../../../api'

interface ExternalDatasetsTableProps {
  externalDatasets: ExternalDatasetInfo[]
  loadingExternalDatasets: boolean
  externalDatasetsLoaded: boolean
  loadExternalDatasets: (forceRefresh?: boolean) => Promise<void>
  selectedExternalDatasets: Set<string>
  unbindingDatasets: boolean
  refreshExternalDatasets: () => Promise<void>
  handleExternalDatasetToggle: (datasetId: string | null) => void
  handleExternalDatasetSelectAll: () => void
  handleUnbindDataset: (datasetId: string, datasetName: string) => Promise<void>
  handleUnbindSelectedDatasets: () => Promise<void>
  navigate: (path: string) => void
}

export const ExternalDatasetsTable: React.FC<ExternalDatasetsTableProps> = ({
  externalDatasets,
  loadingExternalDatasets,
  externalDatasetsLoaded,
  loadExternalDatasets,
  selectedExternalDatasets,
  unbindingDatasets,
  refreshExternalDatasets,
  handleExternalDatasetToggle,
  handleExternalDatasetSelectAll,
  handleUnbindDataset,
  handleUnbindSelectedDatasets,
  navigate
}) => (
  <div className="border rounded-lg mt-4">
    <div className="bg-gray-50 px-4 py-3 border-b flex items-center justify-between">
      <h3 className="font-medium text-gray-900 flex items-center gap-2">
        <HardDrive className="w-4 h-4" />
        Externally Imported Datasets ({externalDatasetsLoaded ? externalDatasets.length : '—'})
      </h3>
      <div className="flex items-center gap-2">
        {externalDatasets.length > 0 && (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleExternalDatasetSelectAll}
              className="text-xs"
            >
              {selectedExternalDatasets.size === externalDatasets.filter(d => d.dataset_id).length ? 'Deselect All' : 'Select All'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleUnbindSelectedDatasets}
              disabled={selectedExternalDatasets.size === 0 || unbindingDatasets}
              className="gap-1 text-red-600 border-red-100 hover:bg-red-50 hover:text-red-700 hover:border-red-200"
            >
              {unbindingDatasets ? (
                <RefreshCw className="w-3 h-3 animate-spin" />
              ) : (
                <Trash2 className="w-3 h-3" />
              )}
              Unbind Selected ({selectedExternalDatasets.size})
            </Button>
          </>
        )}
        <Button
          variant="ghost"
          size="sm"
          onClick={externalDatasetsLoaded ? refreshExternalDatasets : () => loadExternalDatasets()}
          disabled={loadingExternalDatasets}
          className="gap-1"
        >
          <RefreshCw className={`w-3 h-3 ${loadingExternalDatasets ? 'animate-spin' : ''}`} />
          {externalDatasetsLoaded ? 'Refresh' : 'Load'}
        </Button>
      </div>
    </div>
    {loadingExternalDatasets ? (
      <div className="p-8 text-center text-gray-500">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
        Loading external datasets...
      </div>
    ) : !externalDatasetsLoaded ? (
      <div className="p-8 text-center text-gray-500">
        <HardDrive className="w-8 h-8 mx-auto mb-2 text-gray-300" />
        <p className="mb-2">External datasets have not been loaded yet.</p>
        <p className="text-xs text-gray-400 mb-3">Load dataset names and file counts from the database.</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => loadExternalDatasets()}
          className="gap-1"
        >
          <Search className="w-3 h-3" />
          Load External Datasets
        </Button>
      </div>
    ) : externalDatasets.length === 0 ? (
      <div className="p-8 text-center text-gray-500">
        <HardDrive className="w-8 h-8 mx-auto mb-2 text-gray-300" />
        <p>No externally imported datasets found.</p>
        <p className="text-xs mt-1">Use the form above to scan and register WSI files from external drives.</p>
      </div>
    ) : (
      <>
        <div className="max-h-80 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50/80 backdrop-blur-sm sticky top-0 border-b">
              <tr>
                <th className="px-3 py-3 text-left w-10"></th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700 min-w-[200px]">Dataset Name</th>
                <th className="px-4 py-3 text-left font-semibold text-gray-700">Files Count</th>
                <th className="px-4 py-3 text-center w-32 font-semibold text-gray-700">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {externalDatasets.map((dataset) => (
                <tr key={dataset.dataset_id || 'uncategorized'} className="hover:bg-gray-50/50 transition-colors group">
                  <td className="px-3 py-3">
                    {dataset.dataset_id && (
                      <Checkbox
                        checked={selectedExternalDatasets.has(dataset.dataset_id)}
                        onCheckedChange={() => handleExternalDatasetToggle(dataset.dataset_id!)}
                      />
                    )}
                  </td>
                  <td className="px-4 py-3 font-medium text-gray-900">
                    {dataset.dataset_name}
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    <span className="font-mono bg-gray-100 px-2 py-0.5 rounded text-xs">{dataset.total_files} files</span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    {dataset.dataset_id && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleUnbindDataset(dataset.dataset_id!, dataset.dataset_name)}
                        disabled={unbindingDatasets}
                        className="text-red-500 hover:text-red-700 hover:bg-red-50 gap-1.5 h-8 px-3 transition-all rounded-md border border-transparent hover:border-red-100"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                        <span className="text-xs font-semibold">Unbind</span>
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 bg-gray-50 border-t text-xs text-gray-500">
          <strong>Unbind</strong> removes database records only. Files on external drives are NOT deleted.
          To manage individual files, go to <button onClick={() => navigate('/wsi-list')} className="font-medium text-primary-600 hover:underline inline-flex items-center gap-0.5">Data Repository <ChevronRight className="w-3 h-3" /></button>.
        </div>
      </>
    )}
  </div>
)

