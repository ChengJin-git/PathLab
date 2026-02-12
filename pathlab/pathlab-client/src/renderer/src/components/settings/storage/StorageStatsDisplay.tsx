import React from 'react'
import { StorageStats } from '../../../api'

interface StorageStatsDisplayProps {
  stats: StorageStats
  formatBytes: (bytes: number) => string
}

export const StorageStatsDisplay: React.FC<StorageStatsDisplayProps> = ({ stats, formatBytes }) => {
  const labelMap: { [key: string]: string } = {
    'wsi_files': 'Original Files',
    'coordinates': 'Coordinates',
    'masks': 'Masks',
    'ai_results': 'AI Results',
    'features_cache': 'Feature',
    'training': 'Training Data',
    'models': 'Models',
    'logs': 'Logs',
  }

  return (
    <>
      {/* Total Storage Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6 pb-6 border-b border-gray-200">
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">Total Storage</div>
          <div className="text-3xl font-bold text-gray-900">
            {stats.total_size_gb.toFixed(2)} <span className="text-lg text-gray-600">GB</span>
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {stats.total_size_mb.toFixed(2)} MB
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">Total Files</div>
          <div className="text-3xl font-bold text-gray-900">
            {Object.values(stats.breakdown).reduce((sum, info) => sum + info.file_count, 0)}
          </div>
          <div className="text-xs text-gray-500 mt-1">
            Across {Object.keys(stats.breakdown).length} categories
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4">
          <div className="text-sm text-gray-600 mb-1">Storage Location</div>
          <div className="text-xs font-mono text-gray-900 mt-2 break-all">
            {stats.uploads_dir}
          </div>
        </div>
      </div>

      {/* Storage Breakdown */}
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Storage Breakdown</h3>
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
        {Object.entries(stats.breakdown).map(([category, info]) => {
          const label = labelMap[category] || category
          return (
            <div key={category} className="border border-gray-200 rounded-lg p-3 hover:border-gray-300 transition-colors">
              <div className="text-xs text-gray-600 mb-1">{label}</div>
              <div className="text-xl font-bold text-gray-900">{info.file_count}</div>
              <div className="text-xs text-gray-500 mt-1">{formatBytes(info.size)}</div>
            </div>
          )
        })}
      </div>
    </>
  )
}

