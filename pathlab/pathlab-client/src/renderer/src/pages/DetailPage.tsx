import { useEffect, useState, useCallback, useRef } from 'react'
import { useParams, Link, useNavigate } from 'react-router-dom'
import {
  fetchWSIDetail,
  fetchAvailableHeatmaps,
  fetchWSIList,
  deleteWSIResults,
  HeatmapData,
  AvailableHeatmap,
  HeatmapPoint,
  getPatchImageUrl,
  WSISummary,
  PatchCAMData,
  fetchPatchCAMData,
  getPatchCAMImageUrl,
  getPatchFileImageUrl
} from '../api'
import WSIViewer from '../components/WSIViewer'
import { Card } from '../components/common'
import { ArrowLeft, Microscope, Layers, ChevronDown, TrendingUp, TrendingDown, Loader2, Download, CheckCircle2, History, ChevronLeft, ChevronRight, Trash2, Plus, Minus, RotateCcw, Maximize2, X } from 'lucide-react'
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

/**
 * Format classes for display
 * - 2 classes: "A vs B"
 * - 3 classes: "A, B, C"
 * - >3 classes: "A, B, C +N more"
 */
function formatClasses(classes: string[] | null | undefined, maxShow: number = 3): string | null {
  if (!classes || classes.length === 0) return null
  if (classes.length === 2) {
    return classes.join(' vs ')
  }
  if (classes.length <= maxShow) {
    return classes.join(', ')
  }
  const shown = classes.slice(0, maxShow)
  const remaining = classes.length - maxShow
  return `${shown.join(', ')} +${remaining} more`
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

  // Delete state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deletingResults, setDeletingResults] = useState(false)
  const [deleteMode, setDeleteMode] = useState<'all' | 'task'>('task') // 'all' = delete all results, 'task' = delete selected task only

  // Patch CAM state (for patch-level classification tasks)
  const [patchCAMData, setPatchCAMData] = useState<PatchCAMData | null>(null)

  // Patch viewer zoom and pan state
  const [patchZoom, setPatchZoom] = useState(1)
  const [patchPan, setPatchPan] = useState({ x: 0, y: 0 })
  const [isPanning, setIsPanning] = useState(false)
  const [panStart, setPanStart] = useState({ x: 0, y: 0 })
  const patchContainerRef = useRef<HTMLDivElement>(null)

  // Patch viewer controls
  const handlePatchZoomIn = () => setPatchZoom(prev => Math.min(prev * 1.3, 10))
  const handlePatchZoomOut = () => setPatchZoom(prev => Math.max(prev / 1.3, 0.5))
  const handlePatchReset = () => {
    setPatchZoom(1)
    setPatchPan({ x: 0, y: 0 })
  }
  const handlePatchFullscreen = () => {
    if (patchContainerRef.current) {
      if (document.fullscreenElement) {
        document.exitFullscreen()
      } else {
        patchContainerRef.current.requestFullscreen()
      }
    }
  }

  // Mouse wheel zoom for patch viewer
  const handlePatchWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    if (e.deltaY < 0) {
      setPatchZoom(prev => Math.min(prev * 1.1, 10))
    } else {
      setPatchZoom(prev => Math.max(prev / 1.1, 0.5))
    }
  }, [])

  // Pan and click handlers for patch viewer
  const [clickStart, setClickStart] = useState({ x: 0, y: 0 })

  const handlePatchMouseDown = useCallback((e: React.MouseEvent) => {
    setClickStart({ x: e.clientX, y: e.clientY })
    if (patchZoom > 1) {
      setIsPanning(true)
      setPanStart({ x: e.clientX - patchPan.x, y: e.clientY - patchPan.y })
    }
  }, [patchZoom, patchPan])

  const handlePatchMouseMove = useCallback((e: React.MouseEvent) => {
    if (isPanning) {
      setPatchPan({
        x: e.clientX - panStart.x,
        y: e.clientY - panStart.y
      })
    }
  }, [isPanning, panStart])

  const handlePatchMouseUp = useCallback((e: React.MouseEvent) => {
    setIsPanning(false)
    // Click to zoom (if mouse didn't move much)
    const dx = Math.abs(e.clientX - clickStart.x)
    const dy = Math.abs(e.clientY - clickStart.y)
    if (dx < 5 && dy < 5) {
      setPatchZoom(prev => Math.min(prev * 1.5, 10))
    }
  }, [clickStart])

  const handlePatchMouseLeave = useCallback(() => {
    setIsPanning(false)
  }, [])

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

  // Delete results handler
  const handleDeleteResults = async () => {
    setDeletingResults(true)
    try {
      const taskIdToDelete = deleteMode === 'task' ? selectedTaskId : undefined
      await deleteWSIResults(wsi_id, taskIdToDelete)

      // Refresh heatmaps list
      const heatmaps = await fetchAvailableHeatmaps(wsi_id)
      setAvailableHeatmaps(heatmaps)

      // Reset selection if needed
      if (deleteMode === 'all' || !heatmaps.find(h => h.task_id === selectedTaskId)) {
        if (heatmaps.length > 0) {
          setSelectedTaskId(heatmaps[0].task_id ?? undefined)
        } else {
          setSelectedTaskId(undefined)
          setHeatmapData(null)
          setShowHeatmap(false)
        }
      }

      setShowDeleteConfirm(false)
    } catch (err) {
      console.error('Failed to delete results:', err)
      alert(`Failed to delete results: ${err}`)
    } finally {
      setDeletingResults(false)
    }
  }

  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

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
      } catch (err) {
        console.error('Failed to fetch available heatmaps:', err)
        setAvailableHeatmaps([])
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

  // Get selected task and check if it's patch-level
  const selectedTask = availableHeatmaps.find(h => h.task_id === selectedTaskId)
  const isPatchLevel = selectedTask?.data_level === 'patch'

  // Load patch CAM data when selecting a patch-level task
  useEffect(() => {
    if (isPatchLevel && selectedTaskId) {
      fetchPatchCAMData(wsi_id, selectedTaskId).then(setPatchCAMData)
    } else {
      setPatchCAMData(null)
    }
  }, [wsi_id, selectedTaskId, isPatchLevel])

  const currentIndex = allWSIs.findIndex(w => w.wsi_id === wsi_id)
  const prevWSI = currentIndex > 0 ? allWSIs[currentIndex - 1] : null
  const nextWSI = currentIndex >= 0 && currentIndex < allWSIs.length - 1 ? allWSIs[currentIndex + 1] : null

  if (!detail) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <p className="text-gray-500 font-medium">Loading file information...</p>
        </div>
      </div>
    )
  }

  const meta = detail.meta || {}

  return (
    <div className="flex flex-col lg:flex-row h-screen bg-gray-50 overflow-hidden">
      {/* Left: WSI Viewer */}
      <div className="flex-1 flex flex-col bg-gray-50 relative min-h-[50vh] lg:min-h-0">
        <div className="flex items-center px-2 sm:px-4 py-2 sm:py-3 bg-white border-b border-gray-200 gap-2 sm:gap-4 shadow-sm z-10">
          <Link
            to="/wsi-list"
            className="flex items-center gap-1 sm:gap-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100/80 text-xs sm:text-sm font-medium px-2 sm:px-3 py-1.5 sm:py-2 rounded-lg transition-all"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">Back</span>
          </Link>
          <div className="w-px h-6 bg-gray-100"></div>
          
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <h3 className="flex items-center gap-2 text-gray-900 text-sm sm:text-base font-semibold truncate" title={`UUID: ${wsi_id}`}>
              <Microscope className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-indigo-600" />
              <span className="truncate">{meta?.original_filename || wsi_id}</span>
            </h3>
          </div>

          <div className="flex items-center gap-1 sm:gap-2">
            <div className="flex items-center gap-1 bg-gray-50 p-1 rounded-lg border border-gray-100">
               <button
                 onClick={() => prevWSI && navigate(`/wsi/${prevWSI.wsi_id}`)}
                 disabled={!prevWSI}
                 className="p-1 sm:p-1.5 rounded-md hover:bg-white hover:shadow-sm text-gray-500 hover:text-indigo-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:shadow-none disabled:cursor-not-allowed transition-all"
                 title={prevWSI ? `Previous` : 'No previous slide'}
               >
                 <ChevronLeft className="w-4 h-4 sm:w-5 sm:h-5" />
               </button>
               <div className="w-px h-4 bg-gray-200"></div>
               <button
                 onClick={() => nextWSI && navigate(`/wsi/${nextWSI.wsi_id}`)}
                 disabled={!nextWSI}
                 className="p-1 sm:p-1.5 rounded-md hover:bg-white hover:shadow-sm text-gray-500 hover:text-indigo-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:shadow-none disabled:cursor-not-allowed transition-all"
                 title={nextWSI ? `Next` : 'No next slide'}
               >
                 <ChevronRight className="w-4 h-4 sm:w-5 sm:h-5" />
               </button>
            </div>

            <button
               onClick={() => setIsSidebarOpen(!isSidebarOpen)}
               className={`lg:hidden p-2 rounded-lg ${isSidebarOpen ? 'bg-indigo-100 text-indigo-700' : 'bg-white text-gray-500 border border-gray-200 shadow-sm'}`}
            >
              <Layers className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 relative bg-gray-100 overflow-hidden">
          {/* Conditional Viewer: WSI Viewer for WSI-level, Patch Viewer for patch-level */}
          {isPatchLevel ? (
            // Patch-level heatmap viewer with zoom/pan controls
            <div
              ref={patchContainerRef}
              className="w-full h-full flex items-center justify-center overflow-hidden bg-gray-100"
              onWheel={handlePatchWheel}
              onMouseDown={handlePatchMouseDown}
              onMouseMove={handlePatchMouseMove}
              onMouseUp={handlePatchMouseUp}
              onMouseLeave={handlePatchMouseLeave}
              style={{ cursor: patchZoom > 1 ? (isPanning ? 'grabbing' : 'grab') : 'default' }}
            >
              {/* Zoom Controls - horizontal like WSI */}
              <div
                className="absolute top-4 left-4 flex flex-row items-center gap-0.5 z-30 bg-white rounded-lg shadow-lg border border-gray-200 p-1"
                onMouseDown={(e) => e.stopPropagation()}
                onMouseUp={(e) => e.stopPropagation()}
              >
                <button
                  onClick={handlePatchZoomIn}
                  className="p-2 hover:bg-gray-100 rounded transition-colors text-gray-600 hover:text-gray-900"
                  title="Zoom In"
                >
                  <Plus className="w-4 h-4" />
                </button>
                <button
                  onClick={handlePatchZoomOut}
                  className="p-2 hover:bg-gray-100 rounded transition-colors text-gray-600 hover:text-gray-900"
                  title="Zoom Out"
                >
                  <Minus className="w-4 h-4" />
                </button>
                <div className="h-5 w-px bg-gray-200 mx-0.5" />
                <button
                  onClick={handlePatchReset}
                  className="p-2 hover:bg-gray-100 rounded transition-colors text-gray-600 hover:text-gray-900"
                  title="Reset View"
                >
                  <RotateCcw className="w-4 h-4" />
                </button>
                <button
                  onClick={handlePatchFullscreen}
                  className="p-2 hover:bg-gray-100 rounded transition-colors text-gray-600 hover:text-gray-900"
                  title="Fullscreen"
                >
                  <Maximize2 className="w-4 h-4" />
                </button>
              </div>

              <div
                className="relative max-w-[600px] max-h-full aspect-square transition-transform duration-100"
                style={{
                  transform: `scale(${patchZoom}) translate(${patchPan.x / patchZoom}px, ${patchPan.y / patchZoom}px)`,
                  transformOrigin: 'center center'
                }}
              >
                {/* Patch image */}
                <img
                  src={getPatchFileImageUrl(wsi_id)}
                  alt="Patch"
                  className="w-full h-full object-contain rounded-xl shadow-lg select-none"
                  draggable={false}
                />
                {/* Heatmap overlay */}
                {showHeatmap && selectedTaskId && (
                  <img
                    src={getPatchCAMImageUrl(wsi_id, selectedTaskId)}
                    alt="Heatmap Overlay"
                    className="absolute inset-0 w-full h-full object-contain rounded-xl pointer-events-none select-none"
                    style={{ opacity: heatmapOpacity }}
                    draggable={false}
                  />
                )}
              </div>
            </div>
          ) : (
            // WSI-level viewer
            <WSIViewer
              wsi_id={wsi_id}
              showHeatmap={showHeatmap}
              heatmapOpacity={heatmapOpacity}
              taskId={selectedTaskId}
              onHeatmapLoaded={handleHeatmapLoaded}
            />
          )}

          {/* Heatmap Controls Overlay */}
          {availableHeatmaps.length > 0 && (
            <div className="absolute bottom-4 left-4 right-4 sm:right-auto bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200 p-2 sm:p-3 z-20">
              <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
                <button
                  onClick={() => setShowHeatmap(!showHeatmap)}
                  className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs sm:text-sm font-medium transition-all ${
                    showHeatmap
                      ? 'bg-indigo-100 text-indigo-700 border border-indigo-300'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'
                  }`}
                >
                  <Layers className="w-4 h-4" />
                  {showHeatmap ? 'Hide' : 'Show'} Heatmap
                </button>

                {showHeatmap && (
                  <div className="flex items-center gap-2 px-2 sm:px-0 sm:pl-3 border-t sm:border-t-0 sm:border-l border-gray-200 pt-2 sm:pt-0">
                    <span className="text-[10px] sm:text-xs text-gray-500 whitespace-nowrap">Opacity:</span>
                    <input
                      type="range"
                      min="0.1"
                      max="0.9"
                      step="0.1"
                      value={heatmapOpacity}
                      onChange={(e) => setHeatmapOpacity(parseFloat(e.target.value))}
                      className="flex-1 sm:w-20 accent-indigo-600"
                    />
                    <span className="text-[10px] sm:text-xs text-gray-600 w-8 text-right px-1">{Math.round(heatmapOpacity * 100)}%</span>
                  </div>
                )}
              </div>

              {showHeatmap && (
                <div className="mt-2 pt-2 border-t border-gray-100">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-gray-400 uppercase tracking-wide">Activation:</span>
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
      <div className={`fixed inset-y-0 right-0 lg:relative z-40 lg:z-0 w-full sm:w-[500px] bg-gray-50 border-l border-gray-200 overflow-y-auto p-4 sm:p-6 flex flex-col gap-4 sm:gap-6 transition-transform duration-300 shadow-2xl lg:shadow-none ${isSidebarOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'}`}>
        <div className="flex lg:hidden items-center justify-between mb-2">
           <h2 className="text-lg font-bold text-gray-900">Analysis Data</h2>
           <button 
             onClick={() => setIsSidebarOpen(false)}
             className="p-2 rounded-lg bg-white border border-gray-200 text-gray-400"
            >
             <X className="w-5 h-5" />
           </button>
        </div>
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
                <button
                  onClick={() => setShowDeleteConfirm(true)}
                  className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                  title="Delete AI Results"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
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
                            return formatClasses(task.classes) || task.task_name || task.task_type;
                         })()}
                      </span>
                      {(() => {
                        const task = availableHeatmaps.find(h => h.task_id === selectedTaskId);
                        if (task?.feature_extractor) {
                          return (
                            <Badge variant="secondary" className="bg-purple-50 text-purple-700 hover:bg-purple-100 text-[10px] uppercase tracking-wider font-bold px-1.5 py-0">
                              {task.feature_extractor}
                            </Badge>
                          );
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
                                setSelectedTaskId(hm.task_id ?? undefined)
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
                                <div className="flex flex-col gap-1">
                                  <span className={`text-[13px] font-semibold tracking-tight transition-colors duration-200 ${
                                    selectedTaskId === (hm.task_id || '') ? 'text-white' : 'text-gray-700'
                                  }`}>
                                    {formatClasses(hm.classes) || hm.task_name || hm.task_type}
                                  </span>
                                  {hm.feature_extractor && (
                                    <span className={`text-[10px] uppercase tracking-wider font-bold px-1.5 py-0.5 rounded-full w-fit transition-colors duration-200 ${
                                      selectedTaskId === (hm.task_id || '')
                                        ? 'bg-white/20 text-white'
                                        : 'bg-purple-50 text-purple-700'
                                    }`}>
                                      {hm.feature_extractor}
                                    </span>
                                  )}
                                </div>
                                {selectedTaskId === (hm.task_id || '') && (
                                    <CheckCircle2 className="w-3.5 h-3.5 text-white" />
                                )}
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

                {/* Selected task prediction info - supports both WSI heatmap and patch heatmap */}
                {(heatmapData || patchCAMData) && (
                  <div className="mt-3 p-3 bg-gradient-to-br from-indigo-50 to-blue-50 rounded-lg border border-indigo-200">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-indigo-700 font-semibold uppercase tracking-wider">Prediction</span>
                      {isPatchLevel ? (
                        <Badge variant="secondary" className="bg-orange-50 text-orange-700 text-[10px]">
                          Patch Heatmap
                        </Badge>
                      ) : (
                        <span className="text-xs text-gray-500">{heatmapData?.num_patches?.toLocaleString()} patches</span>
                      )}
                    </div>
                    <div className="text-lg font-bold text-indigo-700">
                      {(isPatchLevel ? patchCAMData?.prediction : heatmapData?.prediction) || 'N/A'}
                    </div>
                    {(() => {
                      const probs = isPatchLevel ? patchCAMData?.probs : heatmapData?.probs
                      if (probs && Object.keys(probs).length > 0) {
                        return (
                          <div className="mt-2 flex flex-wrap gap-1.5">
                            {Object.entries(probs)
                              .sort(([, a], [, b]) => (b as number) - (a as number))
                              .slice(0, 3)
                              .map(([cls, prob]) => (
                                <span key={cls} className="text-xs bg-white/70 px-2 py-0.5 rounded border border-indigo-100">
                                  {cls}: {((prob as number) * 100).toFixed(1)}%
                                </span>
                              ))}
                          </div>
                        )
                      }
                      return null
                    })()}
                  </div>
                )}
              </div>
            </Card>

            {/* Patch Heatmap Info Card - only for patch-level tasks */}
            {isPatchLevel && patchCAMData && (
              <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
                <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-orange-50/50 to-white">
                  <div className="p-1.5 bg-orange-100/50 rounded-md">
                    <Layers className="w-4 h-4 text-orange-600" />
                  </div>
                  <h3 className="text-sm font-semibold text-gray-900 tracking-tight">Class Activation Map</h3>
                </div>
                <div className="p-5">
                  <p className="text-sm text-gray-600 mb-3">
                    The heatmap overlay shows which regions of the patch contributed most to the classification decision.
                  </p>
                  <div className="flex items-center gap-2 text-xs text-gray-500">
                    <span className="font-medium">Heatmap Size:</span>
                    <span>{patchCAMData.cam_size?.[0]} × {patchCAMData.cam_size?.[1]}</span>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <span className="text-[10px] text-gray-400 uppercase tracking-wide">Activation:</span>
                    <div className="flex-1 h-2 rounded-full bg-gradient-to-r from-blue-500 via-green-500 via-yellow-500 to-red-500"></div>
                    <span className="text-[10px] text-gray-500">Low → High</span>
                  </div>
                </div>
              </Card>
            )}

            {/* Top Attention Patches Card - only for WSI-level tasks */}
            {!isPatchLevel && heatmapData?.top_patches && heatmapData.top_patches.length > 0 && (
              <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
                <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-red-50/50 to-white">
                  <div className="p-1.5 bg-red-100/50 rounded-md">
                    <TrendingUp className="w-4 h-4 text-red-600" />
                  </div>
                  <h3 className="text-sm font-semibold text-gray-900 tracking-tight">High Attention Regions</h3>
                  <div className="ml-auto flex items-center gap-2 sm:gap-3">
                    <Badge variant="secondary" className="bg-red-50 text-red-700 hover:bg-red-100 px-2 sm:px-2.5 font-semibold text-[10px] sm:text-xs">
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
                <div className="p-3 sm:p-5">
                  <div className="grid grid-cols-3 xs:grid-cols-4 sm:grid-cols-5 gap-2 sm:gap-3">
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

            {/* Bottom Attention Patches Card - only for WSI-level tasks */}
            {!isPatchLevel && heatmapData?.bottom_patches && heatmapData.bottom_patches.length > 0 && (
              <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
                <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-blue-50/50 to-white">
                  <div className="p-1.5 bg-blue-100/50 rounded-md">
                    <TrendingDown className="w-4 h-4 text-blue-600" />
                  </div>
                  <h3 className="text-sm font-semibold text-gray-900 tracking-tight">Low Attention Regions</h3>
                  <div className="ml-auto flex items-center gap-2 sm:gap-3">
                    <Badge variant="secondary" className="bg-blue-50 text-blue-700 hover:bg-blue-100 px-2 sm:px-2.5 font-semibold text-[10px] sm:text-xs">
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
                <div className="p-3 sm:p-5">
                  <div className="grid grid-cols-3 xs:grid-cols-4 sm:grid-cols-5 gap-2 sm:gap-3">
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

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[200]">
          <div className="bg-white rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
            <div className="p-6">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 bg-red-100 rounded-lg">
                  <Trash2 className="w-5 h-5 text-red-600" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900">Delete AI Results</h3>
              </div>

              <p className="text-gray-600 mb-4">
                Choose what to delete for this slide:
              </p>

              <div className="space-y-2 mb-6">
                <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50 transition-colors">
                  <input
                    type="radio"
                    name="deleteMode"
                    checked={deleteMode === 'task'}
                    onChange={() => setDeleteMode('task')}
                    className="w-4 h-4 text-red-600"
                  />
                  <div>
                    <div className="font-medium text-gray-900">Delete selected task only</div>
                    <div className="text-sm text-gray-500">
                      Remove results for: {availableHeatmaps.find(h => h.task_id === selectedTaskId)?.task_name || selectedTaskId || 'N/A'}
                    </div>
                  </div>
                </label>

                <label className="flex items-center gap-3 p-3 border rounded-lg cursor-pointer hover:bg-gray-50 transition-colors">
                  <input
                    type="radio"
                    name="deleteMode"
                    checked={deleteMode === 'all'}
                    onChange={() => setDeleteMode('all')}
                    className="w-4 h-4 text-red-600"
                  />
                  <div>
                    <div className="font-medium text-gray-900">Delete all results</div>
                    <div className="text-sm text-gray-500">
                      Remove all {availableHeatmaps.length} analysis results for this slide
                    </div>
                  </div>
                </label>
              </div>

              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 mb-6">
                <p className="text-sm text-amber-800">
                  <strong>Warning:</strong> This will permanently delete the attention weights and prediction data. This action cannot be undone.
                </p>
              </div>
            </div>

            <div className="flex gap-3 px-6 py-4 bg-gray-50 border-t">
              <button
                onClick={() => setShowDeleteConfirm(false)}
                disabled={deletingResults}
                className="flex-1 px-4 py-2 text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteResults}
                disabled={deletingResults}
                className="flex-1 px-4 py-2 text-white bg-red-600 rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
              >
                {deletingResults ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-4 h-4" />
                    Delete
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
