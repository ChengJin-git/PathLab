import React, { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { HardDrive, RefreshCw, Trash2, Search, CheckCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { getStorageStats, StorageStats, detectOrphanedFiles, cleanupOrphanedFiles, startCleanupEmptyDatasetsTask, OrphanedFilesInfo, CleanupResult, OrphanedFile } from '../api'
import { PageHeader, Card, Button } from '../components/common'
import { useToast } from '../contexts/ToastContext'
import { formatFileSize } from '../lib/utils'
import { useAsyncAction } from '../lib/useAsyncAction'

export default function StorageManagementPage() {
  const { t } = useTranslation()
  const { success: toastSuccess, error: toastError } = useToast()
  const qc = useQueryClient()

  const { data: stats, isLoading: loading, error: statsError, refetch: refetchStats } = useQuery({
    queryKey: ['storage-stats'],
    queryFn: () => getStorageStats(false),
    staleTime: 30 * 1000,
  })

  const error = statsError ? (statsError instanceof Error ? statsError.message : t('storagePage.errors.loadStatsFailed')) : null

  // Orphaned files state
  const [orphanedFiles, setOrphanedFiles] = useState<OrphanedFilesInfo | null>(null)
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null)
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set())
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())

  const [loadingOrphaned, runLoadingOrphaned] = useAsyncAction({
    onError: (err) => console.error('Failed to detect/cleanup orphaned files:', err)
  })
  const [startingEmptyDatasetCleanup, runStartingEmptyDatasetCleanup] = useAsyncAction({
    onError: (err) => toastError(err instanceof Error ? err.message : t('storagePage.errors.cleanupEmptyDatasetsFailed'))
  })

  const categoryLabels: { [key: string]: string } = {
    coordinates: t('storagePage.categories.coordinates'),
    masks: t('storagePage.categories.masks'),
    ai_results: t('storagePage.categories.aiResults'),
    features_cache: t('storagePage.categories.featuresCache'),
    training: t('storagePage.categories.training'),
    models: t('storagePage.categories.models'),
    logs: t('storagePage.categories.logs'),
    wsi_files: t('storagePage.categories.wsiFiles')
  }

  const orphanedCategoryItems = [
    { key: 'wsi_files', label: t('storagePage.orphanedCategories.wsiFiles'), data: orphanedFiles?.orphaned_wsi_files },
    { key: 'coordinates', label: t('storagePage.orphanedCategories.coordinates'), data: orphanedFiles?.orphaned_coordinates },
    { key: 'masks', label: t('storagePage.orphanedCategories.masks'), data: orphanedFiles?.orphaned_masks },
    { key: 'features_cache', label: t('storagePage.orphanedCategories.featuresCache'), data: orphanedFiles?.orphaned_features_cache },
    { key: 'ai_results', label: t('storagePage.orphanedCategories.aiResults'), data: orphanedFiles?.orphaned_ai_results },
    { key: 'training_dirs', label: t('storagePage.orphanedCategories.trainingDirs'), data: orphanedFiles?.orphaned_training_dirs },
    { key: 'logs', label: t('storagePage.orphanedCategories.logs'), data: orphanedFiles?.orphaned_logs }
  ]

  const handleRefresh = () => {
    void qc.invalidateQueries({ queryKey: ['storage-stats'] })
    void refetchStats()
  }

  const detectOrphaned = () => {
    setCleanupResult(null)
    return runLoadingOrphaned(async () => {
      const data = await detectOrphanedFiles()
      setOrphanedFiles(data)
    })
  }

  const handleCleanup = () => {
    if (!orphanedFiles) return
    const categories = selectedCategories.size > 0 ? Array.from(selectedCategories) : undefined
    return runLoadingOrphaned(async () => {
      const result = await cleanupOrphanedFiles(categories)
      setCleanupResult(result)
      void qc.invalidateQueries({ queryKey: ['storage-stats'] })
      void refetchStats()
      await detectOrphaned()
    })
  }

  const handleStartEmptyDatasetCleanup = () => runStartingEmptyDatasetCleanup(async () => {
    const result = await startCleanupEmptyDatasetsTask()
    if (result.task_id === 'no-op') {
      toastSuccess(t('storagePage.emptyDatasets.noop'))
    } else {
      toastSuccess(t('storagePage.emptyDatasets.started', { count: result.total_items }))
    }
  })

  const toggleCategory = (category: string) => {
    const newSelected = new Set(selectedCategories)
    if (newSelected.has(category)) {
      newSelected.delete(category)
    } else {
      newSelected.add(category)
    }
    setSelectedCategories(newSelected)
  }

  const toggleExpanded = (category: string) => {
    const newExpanded = new Set(expandedCategories)
    if (newExpanded.has(category)) {
      newExpanded.delete(category)
    } else {
      newExpanded.add(category)
    }
    setExpandedCategories(newExpanded)
  }

  const getCategoryLabel = (category: string): string => {
    return categoryLabels[category] || category
  }

  const getCategoryColor = (category: string): string => {
    const colors: { [key: string]: string } = {
      coordinates: 'bg-blue-100 text-blue-800',
      masks: 'bg-yellow-100 text-yellow-800',
      ai_results: 'bg-purple-100 text-purple-800',
      features_cache: 'bg-green-100 text-green-800',
      training: 'bg-pink-100 text-pink-800',
      models: 'bg-indigo-100 text-indigo-800',
      logs: 'bg-gray-100 text-gray-800',
      wsi_files: 'bg-red-100 text-red-800'
    }
    return colors[category] || 'bg-gray-100 text-gray-800'
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">{t('storagePage.loadingStats')}</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="w-full h-full p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-red-800 font-semibold mb-2">{t('common.error')}</h3>
          <p className="text-red-600">{error}</p>
          <button
            onClick={handleRefresh}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            {t('storagePage.retry')}
          </button>
        </div>
      </div>
    )
  }

  if (!stats) {
    return null
  }

  // Sort categories by size (descending)
  const sortedCategories = Object.entries(stats.breakdown).sort(
    ([, a], [, b]) => b.size - a.size
  )

  return (
    <div className="w-full h-full p-6">
      <PageHeader
        title={t('storagePage.title')}
        description={t('storagePage.description')}
        actions={
          <Button
            onClick={handleRefresh}
            disabled={loading || loadingOrphaned}
            variant="primary"
            icon={RefreshCw}
          >
            {t('common.refresh')}
          </Button>
        }
      />

      {/* Total Storage Card */}
      <div className="bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl shadow-lg p-8 mb-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold mb-2 opacity-90">{t('storagePage.totalStorageUsage')}</h2>
            <div className="text-5xl font-bold mb-2">
              {stats.total_size_gb.toFixed(2)} GB
            </div>
            <div className="text-blue-100">
              {formatFileSize(stats.total_size)} ({stats.total_size_mb.toFixed(2)} MB)
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm opacity-90 mb-1">{t('storagePage.storageLocation')}</div>
            <div className="text-xs font-mono bg-blue-700 bg-opacity-50 px-3 py-2 rounded">
              {stats.uploads_dir}
            </div>
            <div className="text-xs opacity-75 mt-2">
              {t('storagePage.lastUpdated', {
                time: (() => {
                  const d = stats.timestamp;
                  const normalized = (!d.endsWith('Z') && !d.includes('+')) ? `${d}Z` : d;
                  return new Date(normalized).toLocaleString();
                })()
              })}
            </div>
          </div>
        </div>
      </div>

      {/* Storage Breakdown */}
      <Card title={t('storagePage.storageBreakdown')} className="mb-6">
        <div className="p-6">
          <div className="space-y-4">
            {sortedCategories.map(([category, info]) => {
              const percentage = stats.total_size > 0 ? (info.size / stats.total_size * 100) : 0
              
              return (
                <div key={category} className="border-b border-gray-200 pb-4 last:border-b-0">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-3">
                      <span className={`px-3 py-1 rounded-full text-sm font-medium ${getCategoryColor(category)}`}>
                        {getCategoryLabel(category)}
                      </span>
                      <span className="text-sm text-gray-600">
                        {info.file_count === 1
                          ? t('storagePage.fileCount.singular')
                          : t('storagePage.fileCount.plural', { count: info.file_count })}
                      </span>
                    </div>
                    <div className="text-right">
                      <div className="font-semibold text-gray-900">
                        {formatFileSize(info.size)}
                      </div>
                      <div className="text-sm text-gray-600">
                        {percentage.toFixed(1)}%
                      </div>
                    </div>
                  </div>
                  
                  {/* Progress bar */}
                  <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                      style={{ width: `${percentage}%` }}
                    />
                  </div>
                </div>
              )
            })}
          </div>

          {/* Summary Stats */}
          <div className="mt-6 pt-6 border-t border-gray-200">
            <div className="grid grid-cols-3 gap-4">
              <div className="text-center">
                <div className="text-2xl font-bold text-gray-900">
                  {Object.values(stats.breakdown).reduce((sum, info) => sum + info.file_count, 0)}
                </div>
                <div className="text-sm text-gray-600">{t('storagePage.summary.totalFiles')}</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-gray-900">
                  {Object.keys(stats.breakdown).length}
                </div>
                <div className="text-sm text-gray-600">{t('storagePage.summary.categories')}</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-gray-900">
                  {formatFileSize(
                    Object.values(stats.breakdown).reduce((sum, info) => sum + info.size, 0) /
                    Object.values(stats.breakdown).filter(info => info.file_count > 0).length
                  )}
                </div>
                <div className="text-sm text-gray-600">{t('storagePage.summary.avgPerCategory')}</div>
              </div>
            </div>
          </div>
        </div>
      </Card>

      <Card
        title={t('storagePage.emptyDatasets.title')}
        icon={Trash2}
        iconColor="text-rose-600"
        className="mb-6"
        headerAction={
          <Button
            onClick={handleStartEmptyDatasetCleanup}
            disabled={loading || startingEmptyDatasetCleanup}
            variant="danger"
            size="sm"
            icon={Trash2}
          >
            {startingEmptyDatasetCleanup
              ? t('storagePage.emptyDatasets.starting')
              : t('storagePage.emptyDatasets.button')}
          </Button>
        }
      >
        <div className="p-6">
          <p className="text-sm text-gray-700 leading-6">
            {t('storagePage.emptyDatasets.description')}
          </p>
        </div>
      </Card>

      {/* Orphaned Files Management */}
      <Card 
        title={t('storagePage.orphanedFiles.title')} 
        icon={AlertCircle}
        iconColor="text-orange-600"
        className="mb-6"
        headerAction={
          <Button
            onClick={detectOrphaned}
            disabled={loading || loadingOrphaned}
            variant="outline"
            size="sm"
            icon={Search}
          >
            {loadingOrphaned ? t('storagePage.orphanedFiles.scanning') : t('storagePage.orphanedFiles.scanButton')}
          </Button>
        }
      >
        <div className="p-6">
          {orphanedFiles && (
            <div className="space-y-4">
              {/* Summary */}
              <div className="bg-orange-50 border border-orange-200 rounded-lg p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="text-2xl font-bold text-orange-900 flex items-center gap-2">
                      {t('storagePage.orphanedFiles.filesCount', { count: orphanedFiles.total_orphaned_count })}
                      {orphanedFiles.cached && (
                        <span className={`text-xs font-normal px-2 py-0.5 rounded-full ${
                          orphanedFiles.stale
                            ? 'bg-yellow-100 text-yellow-700'
                            : 'bg-blue-100 text-blue-700'
                        }`}>
                          {orphanedFiles.stale ? (
                            <span className="flex items-center gap-1">
                              <RefreshCw className="w-3 h-3 animate-spin" />
                              {t('storagePage.orphanedFiles.updating')}
                            </span>
                          ) : t('storagePage.orphanedFiles.cached')}
                        </span>
                      )}
                    </div>
                    <div className="text-sm text-orange-700">
                      {t('storagePage.orphanedFiles.orphanedSize', { size: formatFileSize(orphanedFiles.total_orphaned_size) })}
                    </div>
                  </div>
                  {orphanedFiles.total_orphaned_count > 0 && (
                    <Button
                      onClick={handleCleanup}
                      disabled={loading || loadingOrphaned}
                      variant="danger"
                      icon={Trash2}
                    >
                      {selectedCategories.size > 0
                        ? t('storagePage.orphanedFiles.cleanSelected', { count: selectedCategories.size })
                        : t('storagePage.orphanedFiles.cleanAll')}
                    </Button>
                  )}
                </div>
              </div>

              {/* Cleanup Result */}
              {cleanupResult && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                  <div className="flex items-start gap-3">
                    <CheckCircle className="w-6 h-6 text-green-600 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="font-semibold text-green-900 mb-2">{cleanupResult.summary}</p>
                      {cleanupResult.failed.length > 0 && (
                        <div className="text-sm text-red-700">
                          <p className="font-semibold">{t('storagePage.orphanedFiles.failedToDelete')}</p>
                          <ul className="list-disc list-inside">
                            {cleanupResult.failed.slice(0, 5).map(([path, error], idx) => (
                              <li key={idx}>{path}: {error}</li>
                            ))}
                            {cleanupResult.failed.length > 5 && (
                              <li>{t('storagePage.orphanedFiles.andMore', { count: cleanupResult.failed.length - 5 })}</li>
                            )}
                          </ul>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {/* Categories */}
              {orphanedFiles.total_orphaned_count > 0 && (
                <div className="space-y-2">
                  {orphanedCategoryItems.filter(cat => cat.data && cat.data.length > 0).map(category => {
                    const categoryData = category.data!
                    const totalSize = categoryData.reduce((sum: number, file: OrphanedFile) => sum + file.size, 0)
                    const isExpanded = expandedCategories.has(category.key)
                    const isSelected = selectedCategories.has(category.key)

                    return (
                      <div key={category.key} className="border border-gray-200 rounded-lg overflow-hidden">
                        <div className="bg-gray-50 p-3 flex items-center justify-between">
                          <div className="flex items-center gap-3 flex-1">
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onChange={() => toggleCategory(category.key)}
                              className="w-4 h-4 text-orange-600 rounded focus:ring-orange-500"
                            />
                            <button
                              onClick={() => toggleExpanded(category.key)}
                              className="flex items-center gap-2 flex-1 text-left"
                            >
                              {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                              <span className="font-medium">{category.label}</span>
                              <span className="text-sm text-gray-600">
                                ({t('storagePage.orphanedFiles.categoryInfo', { count: categoryData.length, size: formatFileSize(totalSize) })})
                              </span>
                            </button>
                          </div>
                        </div>

                        {isExpanded && (
                          <div className="p-4 bg-gray-50/50 max-h-80 overflow-y-auto rounded-b-lg border-t border-gray-100">
                            <div className="space-y-0 relative text-sm">
                              {categoryData.map((file: OrphanedFile, idx: number) => (
                                <div key={idx} className="flex justify-between items-center py-3 border-b border-gray-200/60 last:border-0 hover:bg-white transition-colors px-2 rounded-md">
                                  <span className="text-gray-700 font-medium truncate flex-1 mr-4" title={file.path}>
                                    {file.path.split('/').pop()}
                                  </span>
                                  <span className="text-gray-500 font-medium text-xs whitespace-nowrap bg-white px-2 py-1 rounded border border-gray-200 shadow-sm">
                                    {formatFileSize(file.size)}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      </Card>    
    </div>
  )
}
