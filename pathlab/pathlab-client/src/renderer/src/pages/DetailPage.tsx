import { useEffect, useState, useCallback } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  fetchWSIDetail,
  fetchAvailableHeatmaps,
  fetchWSIList,
  HeatmapData,
  AvailableHeatmap,
  HeatmapPoint,
  getPatchImageUrl,
  WSISummary
} from '../api'
import WSIViewer from '../components/WSIViewer'
import { Card } from '../components/common'
import { ArrowLeft, Microscope, Layers, ChevronDown, TrendingUp, TrendingDown, Loader2, Download, CheckCircle2, History, ChevronLeft, ChevronRight } from 'lucide-react'
import { Badge } from '../components/ui/badge'

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
  const navigate = useNavigate()
  const [detail, setDetail] = useState<any>()
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.5)

  // Navigation state
  const [allWSIs, setAllWSIs] = useState<WSISummary[]>([])

  // Multi-task heatmap state
  const [availableHeatmaps, setAvailableHeatmaps] = useState<AvailableHeatmap[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | undefined>()
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null)
  const [loadingHeatmaps, setLoadingHeatmaps] = useState(true)

  // Export state
  const [exportingTop, setExportingTop] = useState(false)
  const [exportingBottom, setExportingBottom] = useState(false)
  
  // UI State
  const [isTaskDropdownOpen, setIsTaskDropdownOpen] = useState(false)

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

  // Load WSI list for navigation
  useEffect(() => {
    fetchWSIList().then(res => {
      if (res && res.items) {
        setAllWSIs(res.items)
      }
    })
  }, [])

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

  const currentIndex = allWSIs.findIndex(w => w.wsi_id === wsi_id)
  const prevWSI = currentIndex > 0 ? allWSIs[currentIndex - 1] : null
  const nextWSI = currentIndex >= 0 && currentIndex < allWSIs.length - 1 ? allWSIs[currentIndex + 1] : null

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
        <div className="flex items-center px-4 py-3 bg-white border-b border-gray-200 gap-4 shadow-sm z-10">
          <Link
            to="/wsi-list"
            className="flex items-center gap-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100/80 text-sm font-medium px-3 py-2 rounded-lg transition-all"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </Link>
          <div className="w-px h-6 bg-gray-100"></div>
          
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <h3 className="flex items-center gap-2 text-gray-900 text-base font-semibold truncate" title={`UUID: ${wsi_id}`}>
              <Microscope className="w-4 h-4 text-indigo-600" />
              {meta?.original_filename || wsi_id}
            </h3>
          </div>

          <div className="flex items-center gap-1 bg-gray-50 p-1 rounded-lg border border-gray-100">
             <button
               onClick={() => prevWSI && navigate(`/wsi/${prevWSI.wsi_id}`)}
               disabled={!prevWSI}
               className="p-1.5 rounded-md hover:bg-white hover:shadow-sm text-gray-500 hover:text-indigo-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:shadow-none disabled:cursor-not-allowed transition-all"
               title={prevWSI ? `Previous` : 'No previous slide'}
             >
               <ChevronLeft className="w-5 h-5" />
             </button>
             <div className="w-px h-4 bg-gray-200"></div>
             <button
               onClick={() => nextWSI && navigate(`/wsi/${nextWSI.wsi_id}`)}
               disabled={!nextWSI}
               className="p-1.5 rounded-md hover:bg-white hover:shadow-sm text-gray-500 hover:text-indigo-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:shadow-none disabled:cursor-not-allowed transition-all"
               title={nextWSI ? `Next` : 'No next slide'}
             >
               <ChevronRight className="w-5 h-5" />
             </button>
          </div>
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
      <div className="w-[500px] bg-gray-50 border-l border-gray-200 overflow-y-auto p-6 flex flex-col gap-6">
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
            <Card className="mb-4 overflow-visible">
              <div className="flex items-center gap-2.5 px-4 py-3 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
                <Layers className="w-4 h-4 text-indigo-500" />
                <h3 className="m-0 text-sm font-semibold text-gray-900">Select Task</h3>
                <span className="ml-auto text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded">
                  {availableHeatmaps.length} available
                </span>
              </div>
              <div className="p-3 relative">
                <div className="relative">
                  <button
                    onClick={() => setIsTaskDropdownOpen(!isTaskDropdownOpen)}
                    className={`w-full flex items-center justify-between px-3 py-2.5 bg-white border rounded-lg shadow-sm transition-all duration-200 focus:outline-none focus:ring-4 focus:ring-indigo-500/10 active:scale-[0.99] group ${
                      isTaskDropdownOpen ? 'border-indigo-500 ring-4 ring-indigo-500/10' : 'border-gray-200 hover:border-indigo-300 hover:shadow-md'
                    }`}
                  >
                    <div className="flex flex-col items-start gap-1">
                      <span className="text-gray-900 font-semibold text-sm tracking-tight text-left">
                         {(() => {
                            const task = availableHeatmaps.find(h => h.task_id === selectedTaskId);
                            if (!task) return 'Select a task...';
                            // Use classes as primary display if available
                            if (task.classes && task.classes.length > 0) {
                              return task.classes.join(' vs ');
                            }
                            return task.task_name || task.task_type;
                         })()}
                      </span>
                      {(() => {
                           const task = availableHeatmaps.find(h => h.task_id === selectedTaskId);
                           if (task) {
                               return (
                                   <div className="flex items-center gap-2">
                                       <Badge variant="secondary" className="bg-indigo-50 text-indigo-700 hover:bg-indigo-100 text-[10px] uppercase tracking-wider font-bold px-1.5 py-0">
                                            {task.task_type || 'Unknown'}
                                       </Badge>
                                       {task.prediction && (
                                           <span className="text-xs text-gray-400 font-medium">
                                                → {task.prediction}
                                           </span>
                                       )}
                                   </div>
                               )
                           }
                           return null;
                      })()}
                    </div>
                     <ChevronDown
                        className={`w-4 h-4 text-gray-400 transition-transform duration-300 ease-in-out group-hover:text-indigo-500 ${
                          isTaskDropdownOpen ? 'rotate-180 text-indigo-500' : ''
                        }`}
                      />
                  </button>

                  {isTaskDropdownOpen && (
                    <>
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setIsTaskDropdownOpen(false)}
                      />
                      <div className="absolute z-20 w-full mt-2 bg-white/90 backdrop-blur-xl border border-white/20 rounded-xl shadow-2xl shadow-indigo-500/10 overflow-hidden animate-in fade-in zoom-in-95 duration-200 origin-top ring-1 ring-black/5">
                        <div className="max-h-[320px] overflow-y-auto py-2 scrollbar-thin scrollbar-thumb-gray-200">
                          {availableHeatmaps.map(hm => (
                            <button
                              key={hm.task_id || hm.attention_file}
                              onClick={() => {
                                setSelectedTaskId(hm.task_id)
                                setIsTaskDropdownOpen(false)
                              }}
                              className="w-full text-left px-2 py-1 mx-2 rounded-lg transition-all duration-200 group/item flex items-center mb-1 last:mb-0 relative overflow-hidden max-w-[calc(100%-16px)]"
                            >
                              <div className={`absolute inset-0 transition-opacity duration-200 ${
                                selectedTaskId === (hm.task_id || '')
                                  ? 'bg-indigo-600 opacity-100'
                                  : 'bg-gray-50 opacity-0 group-hover/item:opacity-100'
                              }`} />
                              
                              <div className="relative z-10 w-full px-3 py-2.5 flex items-center justify-between">
                                <div className="flex flex-col gap-1 w-full">
                                  <div className="flex items-center justify-between">
                                      <span className={`text-[13px] font-semibold tracking-tight transition-colors duration-200 ${
                                        selectedTaskId === (hm.task_id || '') ? 'text-white' : 'text-gray-700'
                                      }`}>
                                        {/* Use classes as primary display if available */}
                                        {hm.classes && hm.classes.length > 0
                                          ? hm.classes.join(' vs ')
                                          : (hm.task_name || hm.task_type)
                                        }
                                      </span>
                                      {selectedTaskId === (hm.task_id || '') && (
                                          <CheckCircle2 className="w-3.5 h-3.5 text-white" />
                                      )}
                                  </div>
                                  <div className="flex items-center gap-2">
                                    <span className={`text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full transition-colors duration-200 ${
                                      selectedTaskId === (hm.task_id || '')
                                        ? 'bg-white/20 text-white'
                                        : 'bg-indigo-50 text-indigo-700'
                                    }`}>
                                      {hm.task_type || 'Unknown'}
                                    </span>
                                    {hm.prediction && (
                                      <span className={`text-[10px] transition-colors duration-200 ${
                                        selectedTaskId === (hm.task_id || '') ? 'text-indigo-100' : 'text-gray-400'
                                      }`}>
                                        → {hm.prediction}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </button>
                          ))}
                          {availableHeatmaps.length === 0 && (
                            <div className="px-4 py-8 text-sm text-gray-500 text-center flex flex-col items-center gap-2">
                               <div className="w-8 h-8 rounded-full bg-gray-50 flex items-center justify-center">
                                 <History className="w-4 h-4 text-gray-400" />
                               </div>
                               <p>No tasks available</p>
                            </div>
                          )}
                        </div>
                      </div>
                    </>
                  )}
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
              <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
                <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-red-50/50 to-white">
                  <div className="p-1.5 bg-red-100/50 rounded-md">
                    <TrendingUp className="w-4 h-4 text-red-600" />
                  </div>
                  <h3 className="text-sm font-semibold text-gray-900 tracking-tight">High Attention Regions</h3>
                  <div className="ml-auto flex items-center gap-3">
                    <Badge variant="secondary" className="bg-red-50 text-red-700 hover:bg-red-100 px-2.5 font-semibold">
                      Top 10
                    </Badge>
                    <button
                      onClick={handleExportTop}
                      disabled={exportingTop}
                      className="text-gray-400 hover:text-red-600 transition-colors"
                      title="Export Top 10 patches as ZIP"
                    >
                      {exportingTop ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
                <div className="p-5">
                  <div className="grid grid-cols-5 gap-3">
                    {heatmapData.top_patches.map((patch, idx) => (
                      <div
                        key={`top-${idx}`}
                        className="relative aspect-square rounded-xl overflow-hidden border border-gray-100 shadow-sm hover:ring-2 hover:ring-red-500 hover:shadow-lg transition-all duration-300 cursor-pointer group"
                        title={`Attention: ${(patch.weight * 100).toFixed(1)}%\nPosition: (${patch.x}, ${patch.y})`}
                      >
                        <img
                          src={getPatchImageUrl(wsi_id, patch.x, patch.y, 256)}
                          alt={`Top ${idx + 1}`}
                          className="w-full h-full object-cover transform group-hover:scale-110 transition-transform duration-500"
                          loading="lazy"
                        />
                        <div className="absolute top-1 left-1 bg-red-600/90 backdrop-blur-sm text-white text-[10px] font-bold w-5 h-5 flex items-center justify-center rounded-lg shadow-sm">
                          {idx + 1}
                        </div>
                        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-1.5 opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-2 group-hover:translate-y-0">
                          <span className="text-[10px] text-white font-medium flex justify-center">
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
              <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
                <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-blue-50/50 to-white">
                  <div className="p-1.5 bg-blue-100/50 rounded-md">
                    <TrendingDown className="w-4 h-4 text-blue-600" />
                  </div>
                  <h3 className="text-sm font-semibold text-gray-900 tracking-tight">Low Attention Regions</h3>
                  <div className="ml-auto flex items-center gap-3">
                    <Badge variant="secondary" className="bg-blue-50 text-blue-700 hover:bg-blue-100 px-2.5 font-semibold">
                      Bottom 10
                    </Badge>
                    <button
                      onClick={handleExportBottom}
                      disabled={exportingBottom}
                      className="text-gray-400 hover:text-blue-600 transition-colors"
                      title="Export Bottom 10 patches as ZIP"
                    >
                      {exportingBottom ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Download className="w-4 h-4" />
                      )}
                    </button>
                  </div>
                </div>
                <div className="p-5">
                  <div className="grid grid-cols-5 gap-3">
                    {heatmapData.bottom_patches.map((patch, idx) => (
                      <div
                        key={`bottom-${idx}`}
                        className="relative aspect-square rounded-xl overflow-hidden border border-gray-100 shadow-sm hover:ring-2 hover:ring-blue-500 hover:shadow-lg transition-all duration-300 cursor-pointer group"
                        title={`Attention: ${(patch.weight * 100).toFixed(1)}%\nPosition: (${patch.x}, ${patch.y})`}
                      >
                        <img
                          src={getPatchImageUrl(wsi_id, patch.x, patch.y, 256)}
                          alt={`Bottom ${idx + 1}`}
                          className="w-full h-full object-cover transform group-hover:scale-110 transition-transform duration-500"
                          loading="lazy"
                        />
                        <div className="absolute top-1 left-1 bg-blue-600/90 backdrop-blur-sm text-white text-[10px] font-bold w-5 h-5 flex items-center justify-center rounded-lg shadow-sm">
                          {idx + 1}
                        </div>
                        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-1.5 opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-2 group-hover:translate-y-0">
                          <span className="text-[10px] text-white font-medium flex justify-center">
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
