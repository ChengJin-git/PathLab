import React from 'react'
import { useTranslation } from 'react-i18next'
import { AlertCircle, Trash2, RefreshCw } from 'lucide-react'
import { Button } from '../../ui/button'
import { Checkbox } from '../../ui/checkbox'
import type { ExternalFileInfo } from '../../../api/storage'

interface UnavailableFilesListProps {
  unavailableFiles: ExternalFileInfo[]
  selectedUnavailableFiles: Set<string>
  setSelectedUnavailableFiles: React.Dispatch<React.SetStateAction<Set<string>>>
  deletingUnavailableFiles: boolean
  handleDeleteUnavailableFiles: () => void | Promise<void>
}

export const UnavailableFilesList: React.FC<UnavailableFilesListProps> = ({
  unavailableFiles,
  selectedUnavailableFiles,
  setSelectedUnavailableFiles,
  deletingUnavailableFiles,
  handleDeleteUnavailableFiles
}) => {
  const { t } = useTranslation()

  const handleToggle = (wsiId: string) => {
    setSelectedUnavailableFiles((prev) => {
      const next = new Set(prev)
      if (next.has(wsiId)) {
        next.delete(wsiId)
      } else {
        next.add(wsiId)
      }
      return next
    })
  }

  const handleSelectAll = () => {
    if (selectedUnavailableFiles.size === unavailableFiles.length) {
      setSelectedUnavailableFiles(new Set())
    } else {
      setSelectedUnavailableFiles(new Set(unavailableFiles.map((f) => f.wsi_id)))
    }
  }

  return (
    <div className="border border-rose-100 rounded-2xl overflow-hidden shadow-sm">
      <div className="bg-rose-50/50 px-5 py-4 border-b border-rose-100 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-rose-100 rounded-lg">
            <AlertCircle className="w-4 h-4 text-rose-600" />
          </div>
          <div>
            <h3 className="font-bold text-rose-900 text-sm">
              {t('settings.storage.unavailableFilesTitle', { count: unavailableFiles.length })}
            </h3>
            <p className="text-xs text-rose-600/70 mt-0.5">
              {t('settings.storage.unavailableFilesDescription')}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleSelectAll}
            className="text-xs text-rose-700 hover:bg-rose-100"
          >
            {selectedUnavailableFiles.size === unavailableFiles.length ? t('settings.storage.deselectAll') : t('settings.storage.selectAll')}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleDeleteUnavailableFiles}
            disabled={selectedUnavailableFiles.size === 0 || deletingUnavailableFiles}
            className="gap-1.5 text-rose-600 border-rose-200 hover:bg-rose-50 hover:text-rose-700 hover:border-rose-300 font-semibold"
          >
            {deletingUnavailableFiles ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                {t('settings.storage.deleting')}
              </>
            ) : (
              <>
                <Trash2 className="w-3.5 h-3.5" />
                {t('settings.storage.deleteSelected', { count: selectedUnavailableFiles.size })}
              </>
            )}
          </Button>
        </div>
      </div>

      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="bg-rose-50/30 backdrop-blur-sm sticky top-0 border-b border-rose-100">
            <tr>
              <th className="px-4 py-3 text-left w-10"></th>
              <th className="px-4 py-3 text-left font-semibold text-rose-800 text-xs uppercase tracking-wider">{t('settings.storage.filename')}</th>
              <th className="px-4 py-3 text-left font-semibold text-rose-800 text-xs uppercase tracking-wider">{t('settings.storage.dataset')}</th>
              <th className="px-4 py-3 text-left font-semibold text-rose-800 text-xs uppercase tracking-wider max-w-xs">{t('settings.storage.path')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-rose-50">
            {unavailableFiles.map((file) => (
              <tr
                key={file.wsi_id}
                className="hover:bg-rose-50/50 transition-colors"
              >
                <td className="px-4 py-3">
                  <Checkbox
                    checked={selectedUnavailableFiles.has(file.wsi_id)}
                    onCheckedChange={() => handleToggle(file.wsi_id)}
                  />
                </td>
                <td className="px-4 py-3 font-medium text-rose-900">
                  {file.original_filename}
                </td>
                <td className="px-4 py-3 text-rose-700/80">
                  {file.dataset_name || <span className="text-rose-400 italic">{t('settings.storage.uncategorized')}</span>}
                </td>
                <td className="px-4 py-3 text-rose-600/70 text-xs font-mono truncate max-w-xs" title={file.wsi_path}>
                  {file.wsi_path}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="px-5 py-3 bg-rose-50/30 border-t border-rose-100 text-xs text-rose-600/80">
        {t('settings.storage.deleteFooter')}
      </div>
    </div>
  )
}
