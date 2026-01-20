import React, { useState, useEffect } from 'react'
import { HardDrive, RefreshCw, Trash2, Search, CheckCircle, AlertCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { getStorageStats, StorageStats, detectOrphanedFiles, cleanupOrphanedFiles, OrphanedFilesInfo, CleanupResult } from '../api'
import { PageHeader, Card, Button } from '../components/common'

export default function StorageManagementPage() {
  const [stats, setStats] = useState<StorageStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Orphaned files state
  const [orphanedFiles, setOrphanedFiles] = useState<OrphanedFilesInfo | null>(null)
  const [loadingOrphaned, setLoadingOrphaned] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<CleanupResult | null>(null)
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set())
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set())

  useEffect(() => {
    loadStats()
  }, [])

  const loadStats = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getStorageStats()
      setStats(data)
    } catch (err) {
      console.error('Failed to load storage stats:', err)
      setError(err instanceof Error ? err.message : 'Failed to load storage stats')
    } finally {
      setLoading(false)
    }
  }

  const detectOrphaned = async () => {
    setLoadingOrphaned(true)
    setError(null)
    setCleanupResult(null)
    try {
      const data = await detectOrphanedFiles()
      setOrphanedFiles(data)
    } catch (err) {
      console.error('Failed to detect orphaned files:', err)
      setError(err instanceof Error ? err.message : 'Failed to detect orphaned files')
    } finally {
      setLoadingOrphaned(false)
    }
  }

  const handleCleanup = async () => {
    if (!orphanedFiles) return

    const categories = selectedCategories.size > 0
      ? Array.from(selectedCategories)
      : undefined

    setLoadingOrphaned(true)
    setError(null)
    try {
      const result = await cleanupOrphanedFiles(categories)
      setCleanupResult(result)
      // Refresh both stats and orphaned files
      await loadStats()
      await detectOrphaned()
    } catch (err) {
      console.error('Failed to cleanup orphaned files:', err)
      setError(err instanceof Error ? err.message : 'Failed to cleanup orphaned files')
    } finally {
      setLoadingOrphaned(false)
    }
  }

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

  const formatBytes = (bytes: number): string => {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`
  }

  const getCategoryLabel = (category: string): string => {
    const labels: { [key: string]: string } = {
      coordinates: 'Coordinates Cache',
      masks: 'Tissue Masks',
      ai_results: 'AI Results',
      training: 'Training Features',
      models: 'Trained Models',
      logs: 'Training Logs',
      wsi_files: 'WSI Files'
    }
    return labels[category] || category
  }

  const getCategoryColor = (category: string): string => {
    const colors: { [key: string]: string } = {
      coordinates: 'bg-blue-100 text-blue-800',
      masks: 'bg-yellow-100 text-yellow-800',
      ai_results: 'bg-purple-100 text-purple-800',
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
          <p className="text-gray-600">Loading storage statistics...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="w-full h-full p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <h3 className="text-red-800 font-semibold mb-2">Error</h3>
          <p className="text-red-600">{error}</p>
          <button
            onClick={loadStats}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded hover:bg-red-700"
          >
            Retry
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
        title="Storage Management"
        description="Monitor and manage system storage usage"
        actions={
          <Button
            onClick={loadStats}
            variant="primary"
            icon={RefreshCw}
          >
            Refresh
          </Button>
        }
      />

      {/* Total Storage Card */}
      <div className="bg-gradient-to-br from-blue-500 to-blue-600 rounded-xl shadow-lg p-8 mb-6 text-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold mb-2 opacity-90">Total Storage Usage</h2>
            <div className="text-5xl font-bold mb-2">
              {stats.total_size_gb.toFixed(2)} GB
            </div>
            <div className="text-blue-100">
              {formatBytes(stats.total_size)} ({stats.total_size_mb.toFixed(2)} MB)
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm opacity-90 mb-1">Storage Location</div>
            <div className="text-xs font-mono bg-blue-700 bg-opacity-50 px-3 py-2 rounded">
              {stats.uploads_dir}
            </div>
            <div className="text-xs opacity-75 mt-2">
              Last updated: {(() => {
                const d = stats.timestamp;
                const normalized = (!d.endsWith('Z') && !d.includes('+')) ? `${d}Z` : d;
                return new Date(normalized).toLocaleString();
              })()}
            </div>
          </div>
        </div>
      </div>

      {/* Storage Breakdown */}
      <Card title="Storage Breakdown" className="mb-6">
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
                        {info.file_count} {info.file_count === 1 ? 'file' : 'files'}
                      </span>
                    </div>
                    <div className="text-right">
                      <div className="font-semibold text-gray-900">
                        {formatBytes(info.size)}
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
                <div className="text-sm text-gray-600">Total Files</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-gray-900">
                  {Object.keys(stats.breakdown).length}
                </div>
                <div className="text-sm text-gray-600">Categories</div>
              </div>
              <div className="text-center">
                <div className="text-2xl font-bold text-gray-900">
                  {formatBytes(
                    Object.values(stats.breakdown).reduce((sum, info) => sum + info.size, 0) /
                    Object.values(stats.breakdown).filter(info => info.file_count > 0).length
                  )}
                </div>
                <div className="text-sm text-gray-600">Avg per Category</div>
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* Orphaned Files Management */}
      <Card 
        title="Orphaned Files Detection" 
        icon={AlertCircle}
        iconColor="text-orange-600"
        className="mb-6"
        headerAction={
          <Button
            onClick={detectOrphaned}
            disabled={loadingOrphaned}
            variant="outline"
            size="sm"
            icon={Search}
          >
            {loadingOrphaned ? 'Scanning...' : 'Scan for Orphaned Files'}
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
                    <div className="text-2xl font-bold text-orange-900">
                      {orphanedFiles.total_orphaned_count} files
                    </div>
                    <div className="text-sm text-orange-700">
                      {formatBytes(orphanedFiles.total_orphaned_size)} orphaned
                    </div>
                  </div>
                  {orphanedFiles.total_orphaned_count > 0 && (
                    <Button
                      onClick={handleCleanup}
                      disabled={loadingOrphaned}
                      variant="danger"
                      icon={Trash2}
                    >
                      {selectedCategories.size > 0
                        ? `Clean Selected (${selectedCategories.size})`
                        : 'Clean All'}
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
                          <p className="font-semibold">Failed to delete:</p>
                          <ul className="list-disc list-inside">
                            {cleanupResult.failed.slice(0, 5).map(([path, error], idx) => (
                              <li key={idx}>{path}: {error}</li>
                            ))}
                            {cleanupResult.failed.length > 5 && (
                              <li>... and {cleanupResult.failed.length - 5} more</li>
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
                  {[
                    { key: 'wsi_files', label: 'WSI Files', data: orphanedFiles.orphaned_wsi_files },
                    { key: 'coordinates', label: 'Coordinates', data: orphanedFiles.orphaned_coordinates },
                    { key: 'masks', label: 'Masks', data: orphanedFiles.orphaned_masks },
                    { key: 'ai_results', label: 'AI Results', data: orphanedFiles.orphaned_ai_results },
                    { key: 'training_dirs', label: 'Training Directories', data: orphanedFiles.orphaned_training_dirs },
                    { key: 'logs', label: 'Logs', data: orphanedFiles.orphaned_logs }
                  ].filter(cat => cat.data.length > 0).map(category => {
                    const totalSize = category.data.reduce((sum, file) => sum + file.size, 0)
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
                                ({category.data.length} files, {formatBytes(totalSize)})
                              </span>
                            </button>
                          </div>
                        </div>

                        {isExpanded && (
                          <div className="p-4 bg-gray-50/50 max-h-80 overflow-y-auto rounded-b-lg border-t border-gray-100">
                            <div className="space-y-0 relative text-sm">
                              {category.data.map((file, idx) => (
                                <div key={idx} className="flex justify-between items-center py-3 border-b border-gray-200/60 last:border-0 hover:bg-white transition-colors px-2 rounded-md">
                                  <span className="text-gray-700 font-medium truncate flex-1 mr-4" title={file.path}>
                                    {file.path.split('/').pop()}
                                  </span>
                                  <span className="text-gray-500 font-medium text-xs whitespace-nowrap bg-white px-2 py-1 rounded border border-gray-200 shadow-sm">
                                    {formatBytes(file.size)}
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

      {/* Info Card */}
      <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <AlertCircle className="w-6 h-6 text-blue-600 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-blue-800">
            <p className="font-semibold mb-1">Storage Management Tips</p>
            <ul className="list-disc list-inside space-y-1 text-blue-700">
              <li><strong>Standard Delete:</strong> Removes WSI and direct derivatives (coords, masks), keeps training features</li>
              <li><strong>Complete Delete:</strong> Removes all associated files including training features</li>
              <li><strong>Orphaned Files:</strong> Files that exist on disk but not in database - safe to clean up</li>
              <li>Storage statistics are updated in real-time when you refresh this page</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}

