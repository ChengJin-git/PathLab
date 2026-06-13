import React from 'react'
import { useTranslation } from 'react-i18next'
import { StorageStats } from '../../../api'

interface StorageStatsDisplayProps {
  stats: StorageStats
  formatFileSize: (bytes: number) => string
}

export const StorageStatsDisplay: React.FC<StorageStatsDisplayProps> = ({ stats, formatFileSize }) => {
  const { t } = useTranslation()

  const labelMap: { [key: string]: string } = {
    'wsi_files': t('settings.storage.labelOriginalFiles'),
    'coordinates': t('settings.storage.labelCoordinates'),
    'masks': t('settings.storage.labelMasks'),
    'ai_results': t('settings.storage.labelAIResults'),
    'features_cache': t('settings.storage.labelFeature'),
    'training': t('settings.storage.labelTrainingData'),
    'models': t('settings.storage.labelModels'),
    'logs': t('settings.storage.labelLogs'),
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6 pb-6 border-b border-gray-200">
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">{t('settings.storage.totalStorage')}</div>
          {stats.total_size_gb >= 1024 ? (
            <>
              <div className="text-3xl font-bold text-gray-900">
                {(stats.total_size_gb / 1024).toFixed(2)} <span className="text-lg text-gray-600">TB</span>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {stats.total_size_gb.toFixed(1)} GB
              </div>
            </>
          ) : (
            <>
              <div className="text-3xl font-bold text-gray-900">
                {stats.total_size_gb.toFixed(2)} <span className="text-lg text-gray-600">GB</span>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {stats.total_size_mb.toFixed(2)} MB
              </div>
            </>
          )}
        </div>
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">{t('settings.storage.totalFiles')}</div>
          <div className="text-3xl font-bold text-gray-900">
            {Object.values(stats.breakdown).reduce((sum, info) => sum + info.file_count, 0)}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {t('settings.storage.acrossCategories', { count: Object.keys(stats.breakdown).length })}
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">{t('settings.storage.storageLocation')}</div>
          <div className="text-xs font-mono text-gray-900 mt-2 break-all">
            {stats.uploads_dir}
          </div>
        </div>
      </div>

      <h3 className="text-sm font-semibold text-gray-700 mb-3">{t('settings.storage.storageBreakdown')}</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {Object.entries(stats.breakdown).map(([category, info]) => {
          const label = labelMap[category] || category
          return (
            <div key={category} className="border border-gray-200 rounded-lg p-3 hover:border-gray-300 transition-colors">
              <div className="text-xs text-gray-600 mb-1">{label}</div>
              <div className="text-xl font-bold text-gray-900">{info.file_count}</div>
              <div className="text-xs text-gray-500 mt-1">{formatFileSize(info.size)}</div>
            </div>
          )
        })}
      </div>
    </>
  )
}
