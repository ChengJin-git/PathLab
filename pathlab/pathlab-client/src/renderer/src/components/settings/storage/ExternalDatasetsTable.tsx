import React from 'react'
import { useTranslation } from 'react-i18next'
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
}) => {
  const { t } = useTranslation()

  return (
    <div className="border rounded-lg mt-4">
      <div className="bg-gray-50 px-4 py-3 border-b flex items-center justify-between">
        <h3 className="font-medium text-gray-900 flex items-center gap-2">
          <HardDrive className="w-4 h-4" />
          {externalDatasetsLoaded ? t('settings.storage.externalDatasetsTitle', { count: externalDatasets.length }) : t('settings.storage.externalDatasetsLoading')}
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
                {selectedExternalDatasets.size === externalDatasets.filter(d => d.dataset_id).length ? t('settings.storage.deselectAll') : t('settings.storage.selectAll')}
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
                {t('settings.storage.unbindSelected', { count: selectedExternalDatasets.size })}
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
            {externalDatasetsLoaded ? t('settings.storage.refresh') : t('settings.storage.load')}
          </Button>
        </div>
      </div>
      {loadingExternalDatasets ? (
        <div className="p-8 text-center text-gray-500">
          <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2" />
          {t('settings.storage.loadingExternalDatasets')}
        </div>
      ) : !externalDatasetsLoaded ? (
        <div className="p-8 text-center text-gray-500">
          <HardDrive className="w-8 h-8 mx-auto mb-2 text-gray-300" />
          <p className="mb-2">{t('settings.storage.externalDatasetsNotLoaded')}</p>
          <p className="text-xs text-gray-400 mb-3">{t('settings.storage.loadDatasetsHint')}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => loadExternalDatasets()}
            className="gap-1"
          >
            <Search className="w-3 h-3" />
            {t('settings.storage.loadExternalDatasets')}
          </Button>
        </div>
      ) : externalDatasets.length === 0 ? (
        <div className="p-8 text-center text-gray-500">
          <HardDrive className="w-8 h-8 mx-auto mb-2 text-gray-300" />
          <p>{t('settings.storage.noExternalDatasets')}</p>
          <p className="text-xs mt-1">{t('settings.storage.useFormAbove')}</p>
        </div>
      ) : (
        <>
          <div className="max-h-80 overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50/80 backdrop-blur-sm sticky top-0 border-b">
                <tr>
                  <th className="px-3 py-3 text-left w-10"></th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-700 min-w-[200px]">{t('settings.storage.datasetName')}</th>
                  <th className="px-4 py-3 text-left font-semibold text-gray-700">{t('settings.storage.filesCount')}</th>
                  <th className="px-4 py-3 text-center w-32 font-semibold text-gray-700">{t('settings.storage.action')}</th>
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
                      <span className="font-mono bg-gray-100 px-2 py-0.5 rounded text-xs">{t('settings.storage.fileCount', { count: dataset.total_files })}</span>
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
                          <span className="text-xs font-semibold">{t('settings.storage.unbind')}</span>
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-3 bg-gray-50 border-t text-xs text-gray-500">
            {t('settings.storage.unbindFooter')} <button onClick={() => navigate('/wsi-list')} className="font-medium text-primary-600 hover:underline inline-flex items-center gap-0.5">{t('settings.storage.dataRepository')} <ChevronRight className="w-3 h-3" /></button>
          </div>
        </>
      )}
    </div>
  )
}
