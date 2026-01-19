import { useEffect, useState, useCallback } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  fetchWSIDetail,
  fetchAvailableHeatmaps,
  HeatmapData,
  AvailableHeatmap,
  HeatmapPoint,
  getPatchImageUrl
} from '../api'
import WSIViewer from '../components/WSIViewer'
import { Card } from '../components/common'
import { ArrowLeft, Microscope, Layers, ChevronDown, TrendingUp, TrendingDown, Loader2, Download } from 'lucide-react'

/**
 * Export patches as a ZIP file containing images
 */
async function exportPatchesAsZip(
  wsi_id: string,
  patches: HeatmapPoint[],
  prefix: string,
  fileName: string
) {
  // Dynamically import JSZip
  const JSZip = (await import('jszip')).default
  const zip = new JSZip()

  // Download all patch images
  const downloadPromises = patches.map(async (patch, idx) => {
    const url = getPatchImageUrl(wsi_id, patch.x, patch.y, 256)
    try {
      const response = await fetch(url)
      if (response.ok) {
        const blob = await response.blob()
        const paddedIdx = String(idx + 1).padStart(2, '0')
        const attention = (patch.weight * 100).toFixed(1)
        zip.file(`${prefix}_${paddedIdx}_attn${attention}_x${patch.x}_y${patch.y}.png`, blob)
      }
    } catch (err) {
      console.error(`Failed to download patch ${idx}:`, err)
    }
  })

  await Promise.all(downloadPromises)

  // Generate and download the ZIP file
  const content = await zip.generateAsync({ type: 'blob' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(content)
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(link.href)
}

export default function DetailPage() {
  const { wsi_id = '' } = useParams()
  const [detail, setDetail] = useState<any>()
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.5)

  // Multi-task heatmap state
  const [availableHeatmaps, setAvailableHeatmaps] = useState<AvailableHeatmap[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | undefined>()
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null)
  const [loadingHeatmaps, setLoadingHeatmaps] = useState(true)

  // Export state
  const [exportingTop, setExportingTop] = useState(false)
  const [exportingBottom, setExportingBottom] = useState(false)

  // Export handlers
  const handleExportTop = async () => {
    if (!heatmapData?.top_patches || heatmapData.top_patches.length === 0) return
    setExportingTop(true)
    try {
      const taskName = availableHeatmaps.find(h => h.task_id === selectedTaskId)?.task_name || 'task'
      const fileName = `${wsi_id}_${taskName}_top10_patches.zip`
      await exportPatchesAsZip(wsi_id, heatmapData.top_patches, 'top', fileName)
    } finally {
      setExportingTop(false)
    }
  }

  const handleExportBottom = async () => {
    if (!heatmapData?.bottom_patches || heatmapData.bottom_patches.length === 0) return
    setExportingBottom(true)
    try {
      const taskName = availableHeatmaps.find(h => h.task_id === selectedTaskId)?.task_name || 'task'
      const fileName = `${wsi_id}_${taskName}_bottom10_patches.zip`
      await exportPatchesAsZip(wsi_id, heatmapData.bottom_patches, 'bottom', fileName)
    } finally {
      setExportingBottom(false)
    }
  }

  // Load WSI detail and available heatmaps
  useEffect(() => {
    const loadData = async () => {
      // Load WSI detail
      fetchWSIDetail(wsi_id).then(setDetail)

      // Load available heatmaps
      setLoadingHeatmaps(true)
      try {
        const heatmaps = await fetchAvailableHeatmaps(wsi_id)
        setAvailableHeatmaps(heatmaps)
        // Auto-select first heatmap if available
        if (heatmaps.length > 0 && heatmaps[0].task_id) {
          setSelectedTaskId(heatmaps[0].task_id)
          setShowHeatmap(true)
        }
      } finally {
        setLoadingHeatmaps(false)
      }
    }
    loadData()
  }, [wsi_id])

  // Handle heatmap loaded callback from WSIViewer
  const handleHeatmapLoaded = useCallback((data: HeatmapData | null) => {
    setHeatmapData(data)
  }, [])

  if (!detail) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <p className="text-gray-500 font-medium">Loading slide information...</p>
        </div>
      </div>
    )
  }

  const meta = detail.meta || {}

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Left: WSI Viewer */}
      <div className="flex-1 flex flex-col bg-gray-50 relative">
        <div className="flex items-center px-6 py-3 bg-white border-b border-gray-200 gap-4 shadow-sm z-10">
          <Link
            to="/wsi-list"
            className="flex items-center gap-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 text-sm font-medium px-3 py-1.5 rounded-md transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to List
          </Link>
          <div className="w-px h-5 bg-gray-200"></div>
          <h3 className="flex items-center gap-2 text-gray-900 text-base font-semibold flex-1" title={`UUID: ${wsi_id}`}>
            <Microscope className="w-4 h-4 text-blue-600" />
            {meta?.original_filename || wsi_id}
          </h3>
        </div>
        <div className="flex-1 relative bg-gray-100">
          <WSIViewer
            wsi_id={wsi_id}
            showHeatmap={showHeatmap}
            heatmapOpacity={heatmapOpacity}
            taskId={selectedTaskId}
            onHeatmapLoaded={handleHeatmapLoaded}
          />

          {/* Heatmap Controls Overlay */}
          {availableHeatmaps.length > 0 && (
            <div className="absolute bottom-4 left-4 bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200 p-3 z-20">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setShowHeatmap(!showHeatmap)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
                    showHeatmap
                      ? 'bg-indigo-100 text-indigo-700 border border-indigo-300'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'
                  }`}
                >
                  <Layers className="w-4 h-4" />
                  {showHeatmap ? 'Hide' : 'Show'} Heatmap
                </button>

                {showHeatmap && (
                  <div className="flex items-center gap-2 pl-3 border-l border-gray-200">
                    <span className="text-xs text-gray-500">Opacity:</span>
                    <input
                      type="range"
                      min="0.1"
                      max="0.9"
                      step="0.1"
                      value={heatmapOpacity}
                      onChange={(e) => setHeatmapOpacity(parseFloat(e.target.value))}
                      className="w-20 accent-indigo-600"
                    />
                    <span className="text-xs text-gray-600 w-8">{Math.round(heatmapOpacity * 100)}%</span>
                  </div>
                )}
              </div>

              {showHeatmap && (
                <div className="mt-2 pt-2 border-t border-gray-100">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-400 uppercase tracking-wide">Attention:</span>
                    <div className="flex-1 h-2 rounded-full bg-gradient-to-r from-blue-500 via-green-500 via-yellow-500 to-red-500"></div>
                    <span className="text-[10px] text-gray-500">Low → High</span>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Right: Attention Analysis Panel */}
      <div className="w-[420px] bg-gray-50 border-l border-gray-200 overflow-y-auto p-4">
        {/* Loading state */}
        {loadingHeatmaps && (
          <div className="flex items-center justify-center py-12">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
              <p className="text-sm text-gray-500">Loading analysis data...</p>
            </div>
          </div>
        )}

        {/* No heatmaps available */}
        {!loadingHeatmaps && availableHeatmaps.length === 0 && (
          <Card className="overflow-hidden">
            <div className="p-8 text-center">
              <Layers className="w-12 h-12 text-gray-300 mx-auto mb-3" />
              <h3 className="text-sm font-semibold text-gray-700 mb-2">No Attention Data Available</h3>
              <p className="text-xs text-gray-500">
                This slide has no AI analysis results with attention data.
                Please run an analysis task first.
              </p>
            </div>
          </Card>
        )}

        {/* Heatmaps available */}
        {!loadingHeatmaps && availableHeatmaps.length > 0 && (
          <>
            {/* Task Selector Card */}
            <Card className="mb-4 overflow-hidden">
              <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
                <Layers className="w-4 h-4 text-indigo-500" />
                <h3 className="m-0 text-sm font-semibold text-gray-900">Select Task</h3>
                <span className="ml-auto text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
                  {availableHeatmaps.length} available
                </span>
              </div>
              <div className="p-3">
                <div className="relative">
                  <select
                    value={selectedTaskId || ''}
                    onChange={(e) => setSelectedTaskId(e.target.value || undefined)}
                    className="w-full px-3 py-2.5 pr-8 text-sm border border-gray-200 rounded-lg bg-white appearance-none cursor-pointer hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  >
                    {availableHeatmaps.map((hm) => (
                      <option key={hm.task_id || hm.attention_file} value={hm.task_id || ''}>
                        {hm.task_name || hm.task_type} {hm.prediction && `→ ${hm.prediction}`}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
                </div>

                {/* Selected task prediction info */}
                {heatmapData && (
                  <div className="mt-3 p-3 bg-gradient-to-br from-indigo-50 to-blue-50 rounded-lg border border-indigo-200">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-indigo-700 font-semibold uppercase tracking-wider">Prediction</span>
                      <span className="text-xs text-gray-500">{heatmapData.num_patches?.toLocaleString()} patches</span>
                    </div>
                    <div className="text-lg font-bold text-indigo-700">{heatmapData.prediction || 'N/A'}</div>
                    {heatmapData.probs && Object.keys(heatmapData.probs).length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(heatmapData.probs)
                          .sort(([, a], [, b]) => (b as number) - (a as number))
                          .slice(0, 3)
                          .map(([cls, prob]) => (
                            <span key={cls} className="text-xs bg-white/70 px-2 py-0.5 rounded border border-indigo-100">
                              {cls}: {((prob as number) * 100).toFixed(1)}%
                            </span>
                          ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Card>

            {/* Top Attention Patches Card */}
            {heatmapData?.top_patches && heatmapData.top_patches.length > 0 && (
              <Card className="mb-4 overflow-hidden">
                <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-red-50 to-white">
                  <TrendingUp className="w-4 h-4 text-red-500" />
                  <h3 className="m-0 text-sm font-semibold text-gray-900">High Attention Regions</h3>
                  <span className="ml-auto text-xs text-red-600 bg-red-100 px-2 py-0.5 rounded font-medium">
                    Top 10
                  </span>
                  <button
                    onClick={handleExportTop}
                    disabled={exportingTop}
                    className="flex items-center gap-1 px-2 py-1 text-xs text-red-600 hover:text-red-700 hover:bg-red-100 rounded transition-colors disabled:opacity-50"
                    title="Export Top 10 patches as ZIP"
                  >
                    {exportingTop ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Download className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
                <div className="p-3">
                  <div className="grid grid-cols-5 gap-2">
                    {heatmapData.top_patches.map((patch, idx) => (
                      <div
                        key={`top-${idx}`}
                        className="relative aspect-square rounded-lg overflow-hidden border-2 border-red-300 shadow-sm hover:border-red-500 hover:shadow-md transition-all cursor-pointer group"
                        title={`Attention: ${(patch.weight * 100).toFixed(1)}%\nPosition: (${patch.x}, ${patch.y})`}
                      >
                        <img
                          src={getPatchImageUrl(wsi_id, patch.x, patch.y, 256)}
                          alt={`Top ${idx + 1}`}
                          className="w-full h-full object-cover"
                          loading="lazy"
                        />
                        <div className="absolute top-0 left-0 bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-br">
                          {idx + 1}
                        </div>
                        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <span className="text-[9px] text-white font-medium">
                            {(patch.weight * 100).toFixed(1)}%
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            )}

            {/* Bottom Attention Patches Card */}
            {heatmapData?.bottom_patches && heatmapData.bottom_patches.length > 0 && (
              <Card className="mb-4 overflow-hidden">
                <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-blue-50 to-white">
                  <TrendingDown className="w-4 h-4 text-blue-500" />
                  <h3 className="m-0 text-sm font-semibold text-gray-900">Low Attention Regions</h3>
                  <span className="ml-auto text-xs text-blue-600 bg-blue-100 px-2 py-0.5 rounded font-medium">
                    Bottom 10
                  </span>
                  <button
                    onClick={handleExportBottom}
                    disabled={exportingBottom}
                    className="flex items-center gap-1 px-2 py-1 text-xs text-blue-600 hover:text-blue-700 hover:bg-blue-100 rounded transition-colors disabled:opacity-50"
                    title="Export Bottom 10 patches as ZIP"
                  >
                    {exportingBottom ? (
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    ) : (
                      <Download className="w-3.5 h-3.5" />
                    )}
                  </button>
                </div>
                <div className="p-3">
                  <div className="grid grid-cols-5 gap-2">
                    {heatmapData.bottom_patches.map((patch, idx) => (
                      <div
                        key={`bottom-${idx}`}
                        className="relative aspect-square rounded-lg overflow-hidden border-2 border-blue-200 shadow-sm hover:border-blue-400 hover:shadow-md transition-all cursor-pointer group"
                        title={`Attention: ${(patch.weight * 100).toFixed(1)}%\nPosition: (${patch.x}, ${patch.y})`}
                      >
                        <img
                          src={getPatchImageUrl(wsi_id, patch.x, patch.y, 256)}
                          alt={`Bottom ${idx + 1}`}
                          className="w-full h-full object-cover"
                          loading="lazy"
                        />
                        <div className="absolute top-0 left-0 bg-blue-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-br">
                          {idx + 1}
                        </div>
                        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <span className="text-[9px] text-white font-medium">
                            {(patch.weight * 100).toFixed(1)}%
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
            )}
          </>
        )}
      </div>
    </div>
  )
}
