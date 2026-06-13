import React from 'react'
import { useTranslation } from 'react-i18next'
import { Layers, Database, Info } from 'lucide-react'
import { Label } from '../../ui/label'
import { Tooltip } from '../../ui/tooltip'

interface DataLevelSelectionProps {
  batchDataLevel: 'case' | 'file'
  setBatchDataLevel: (level: 'case' | 'file') => void
  taskType?: 'classification' | 'survival' | 'segmentation'
}

export const DataLevelSelection: React.FC<DataLevelSelectionProps> = ({ batchDataLevel, setBatchDataLevel, taskType }) => {
  const { t } = useTranslation()

  return (
    <div className="bg-slate-50 rounded-lg p-4 space-y-3 border border-slate-200">
      <Label className="text-sm font-medium text-slate-900 block">{t('settings.storage.dataLevel')}</Label>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setBatchDataLevel('file')}
          className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
            batchDataLevel === 'file'
              ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
              : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
          }`}
        >
          <div className="flex items-center justify-center gap-2">
            <Layers className={`w-4 h-4 ${batchDataLevel === 'file' ? 'text-primary-700' : 'text-gray-400'}`} />
            {t('settings.storage.fileLevel')}
          </div>
        </button>
        <Tooltip content={taskType === 'segmentation' ? t('settings.storage.caseLevelDisabledForSegmentation') : undefined}>
          <button
            type="button"
            onClick={() => setBatchDataLevel('case')}
            disabled={taskType === 'segmentation'}
            className={`flex-1 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              taskType === 'segmentation'
                ? 'opacity-40 cursor-not-allowed bg-white text-gray-400 border border-gray-100'
                : batchDataLevel === 'case'
                  ? 'bg-primary-100 text-primary-900 border-2 border-primary-300 shadow-sm'
                  : 'bg-white text-gray-500 border border-gray-100 hover:border-primary-200 hover:text-primary-600'
            }`}
          >
            <div className="flex items-center justify-center gap-2">
              <Database className={`w-4 h-4 ${taskType === 'segmentation' ? 'text-gray-300' : batchDataLevel === 'case' ? 'text-primary-700' : 'text-gray-400'}`} />
              {t('settings.storage.caseLevel')}
            </div>
          </button>
        </Tooltip>
      </div>

      <div className="flex items-start gap-2 p-3 bg-white rounded-lg border border-slate-100">
        <Info className="w-4 h-4 text-primary-500 mt-0.5 flex-shrink-0" />
        <div className="text-xs text-gray-600">
          {batchDataLevel === 'file'
            ? t('settings.storage.fileLevelInfo')
            : t('settings.storage.caseLevelInfo')
          }
        </div>
      </div>
    </div>
  )
}
