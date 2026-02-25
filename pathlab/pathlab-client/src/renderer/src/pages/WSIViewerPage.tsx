import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  fetchWSIDetail,
  fetchAvailableHeatmaps,
  fetchWSIList,
  deleteWSIResults,
  HeatmapData,
  AvailableHeatmap,
  WSISummary,
  PatchCAMData,
  fetchPatchCAMData,
  getPatchCAMImageUrl,
  getPatchFileImageUrl,
} from '../api'
import WSIViewer from '../components/WSIViewer'
import { Card } from '../components/common'
import { ArrowLeft, Microscope, Layers, Loader2, ChevronLeft, ChevronRight, Plus, Minus, RotateCcw, Maximize2, X } from 'lucide-react'
import { exportPatchesAsZip } from '../components/wsiViewer/utils'
import { TaskSelectorCard } from '../components/wsiViewer/TaskSelectorCard'
import { AttentionClassSelector } from '../components/wsiViewer/AttentionClassSelector'
import { AttentionPatchesPanel } from '../components/wsiViewer/AttentionPatchesPanel'
import { DeleteResultsModal } from '../components/wsiViewer/DeleteResultsModal'
import { AnnotationToolbar, getColorForLabel } from '../components/wsiViewer/AnnotationToolbar'
import { AnnotationOverlay } from '../components/wsiViewer/AnnotationOverlay'
import { AnnotationListPanel } from '../components/wsiViewer/AnnotationListPanel'
import { CreateDatasetDialog } from '../components/wsiViewer/CreateDatasetDialog'
import { AnnotationRegion, AnnotationsMap, saveDraft, listDrafts, deleteDraft } from '../api/annotation'
import { useToast } from '../contexts/ToastContext'

export default function WSIViewerPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const { wsi_id = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const fromAIChat = (location.state as { fromAIChat?: boolean } | null)?.fromAIChat === true
  const fromDataset = (location.state as { fromDataset?: boolean } | null)?.fromDataset === true
  const datasetId = (location.state as { datasetId?: string } | null)?.datasetId
  const datasetName = (location.state as { datasetName?: string } | null)?.datasetName
  const [detail, setDetail] = useState<any>()
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.5)

  // Navigation state
  const [allWSIs, setAllWSIs] = useState<WSISummary[]>([])

  // Multi-task heatmap state
  const [availableHeatmaps, setAvailableHeatmaps] = useState<AvailableHeatmap[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | undefined>()
  const [selectedFoldKey, setSelectedFoldKey] = useState<string | undefined>()  // K-fold: selected fold
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null)
  const [loadingHeatmaps, setLoadingHeatmaps] = useState(true)

  // Multi-class attention state
  const [selectedClassIdx, setSelectedClassIdx] = useState<number | undefined>()
  const [isClassDropdownOpen, setIsClassDropdownOpen] = useState(false)

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

  // Mouse wheel zoom for patch viewer - use non-passive event listener to allow preventDefault
  useEffect(() => {
    const container = patchContainerRef.current
    if (!container) return

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (e.deltaY < 0) {
        setPatchZoom(prev => Math.min(prev * 1.1, 10))
      } else {
        setPatchZoom(prev => Math.max(prev / 1.1, 0.5))
      }
    }

    // Use { passive: false } to allow preventDefault
    container.addEventListener('wheel', handleWheel, { passive: false })
    return () => {
      container.removeEventListener('wheel', handleWheel)
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
      alert(t('wsiViewer.deleteResultsFailed', { error: String(err) }))
    } finally {
      setDeletingResults(false)
    }
  }

  const [isSidebarOpen, setIsSidebarOpen] = useState(false)

  // Annotation state
  const [annotationMode, setAnnotationMode] = useState(false)
  const [drawingTool, setDrawingTool] = useState<'rect' | 'polygon'>('rect')
  const [currentLabel, setCurrentLabel] = useState('')
  const [labelColors, setLabelColors] = useState<Record<string, string>>({})
  const [allAnnotations, setAllAnnotations] = useState<AnnotationsMap>({})
  const [draftId, setDraftId] = useState<string | null>(null)
  const [osdViewer, setOsdViewer] = useState<any>(null)
  const [slideWidth, setSlideWidth] = useState(0)
  const [slideHeight, setSlideHeight] = useState(0)
  const [showCreateDatasetDialog, setShowCreateDatasetDialog] = useState(false)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Load WSI list for navigation
  // If coming from a dataset, load only that dataset's WSIs; otherwise load all
  useEffect(() => {
    fetchWSIList(fromDataset ? datasetId : undefined).then(res => {
      if (res && res.items) {
        setAllWSIs(res.items)
      }
    })
  }, [fromDataset, datasetId])

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
    // Auto-select class for multi-class attention
    if (data?.attention_type === 'multi_class' && data.selected_class_idx !== null) {
      setSelectedClassIdx(data.selected_class_idx ?? 0)
    } else {
      setSelectedClassIdx(undefined)
    }
  }, [])

  // Get selected task and check if it's patch-level
  const selectedTask = availableHeatmaps.find(h => h.task_id === selectedTaskId && (!h.fold_key || h.fold_key === selectedFoldKey))
  const isPatchLevel = selectedTask?.data_type === 'patch'

  // Get available folds for the selected task (K-fold support)
  const availableFolds = useMemo(() => {
    if (!selectedTaskId) return []
    const folds = availableHeatmaps
      .filter(h => h.task_id === selectedTaskId && h.fold_key)
      .map(h => h.fold_key!)
      .filter((v, i, a) => a.indexOf(v) === i)  // unique
      .sort((a, b) => {
        // Sort fold_0, fold_1, ... numerically
        const numA = parseInt(a.replace('fold_', ''), 10)
        const numB = parseInt(b.replace('fold_', ''), 10)
        return numA - numB
      })
    return folds
  }, [availableHeatmaps, selectedTaskId])

  // Get unique tasks for dropdown (deduplicate K-fold entries)
  const uniqueTasks = useMemo(() => {
    const seen = new Set<string>()
    const result: (AvailableHeatmap & { isKFold?: boolean; numFolds?: number })[] = []
    for (const hm of availableHeatmaps) {
      const key = hm.task_id || hm.attention_file
      if (!seen.has(key)) {
        seen.add(key)
        // Use is_kfold and num_folds from backend instead of counting folds
        // In K-Fold training, each WSI only has one fold result (the fold where it was in validation set)
        result.push({
          ...hm,
          isKFold: hm.is_kfold === true,
          numFolds: hm.num_folds ?? undefined
        })
      }
    }
    return result
  }, [availableHeatmaps])

  // Auto-select first fold when task changes or when folds become available
  useEffect(() => {
    if (availableFolds.length > 0 && !availableFolds.includes(selectedFoldKey || '')) {
      setSelectedFoldKey(availableFolds[0])
    } else if (availableFolds.length === 0) {
      setSelectedFoldKey(undefined)
    }
  }, [availableFolds, selectedFoldKey])

  // Load patch CAM data when selecting a patch-level task
  useEffect(() => {
    if (isPatchLevel && selectedTaskId) {
      fetchPatchCAMData(wsi_id, selectedTaskId, selectedFoldKey).then(setPatchCAMData)
    } else {
      setPatchCAMData(null)
    }
  }, [wsi_id, selectedTaskId, selectedFoldKey, isPatchLevel])

  const currentIndex = allWSIs.findIndex(w => w.wsi_id === wsi_id)
  const prevWSI = currentIndex > 0 ? allWSIs[currentIndex - 1] : null
  const nextWSI = currentIndex >= 0 && currentIndex < allWSIs.length - 1 ? allWSIs[currentIndex + 1] : null

  // Annotation: computed values
  const currentRegions = useMemo(() => allAnnotations[wsi_id] || [], [allAnnotations, wsi_id])

  const allLabels = useMemo(() => {
    const labels = new Set<string>()
    for (const regions of Object.values(allAnnotations)) {
      for (const r of regions) {
        if (r.label) labels.add(r.label)
      }
    }
    return Array.from(labels)
  }, [allAnnotations])

  const currentColor = useMemo(() => {
    if (!currentLabel) return '#3b82f6'
    return getColorForLabel(currentLabel, labelColors)
  }, [currentLabel, labelColors])

  // Annotation: handlers
  const handleViewerReady = useCallback((viewer: any) => {
    setOsdViewer(viewer)
  }, [])

  const handleSlideInfo = useCallback((info: { width: number; height: number }) => {
    setSlideWidth(info.width)
    setSlideHeight(info.height)
  }, [])

  const handleRegionCreated = useCallback((region: Omit<AnnotationRegion, 'id'>) => {
    const newRegion: AnnotationRegion = {
      ...region,
      id: crypto.randomUUID(),
    }
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: [...(prev[wsi_id] || []), newRegion],
    }))
    // Auto-assign color to label
    if (region.label && !labelColors[region.label]) {
      const color = getColorForLabel(region.label, labelColors)
      setLabelColors(prev => ({ ...prev, [region.label]: color }))
    }
  }, [wsi_id, labelColors])

  const handleRegionTooLarge = useCallback(() => {
    toast.warning(t('annotation.regionTooLarge'))
  }, [t, toast])

  const handleUpdateRegion = useCallback((regionId: string, updates: Partial<AnnotationRegion>) => {
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: (prev[wsi_id] || []).map(r => r.id === regionId ? { ...r, ...updates } : r),
    }))
  }, [wsi_id])

  const handleDeleteRegion = useCallback((regionId: string) => {
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: (prev[wsi_id] || []).filter(r => r.id !== regionId),
    }))
  }, [wsi_id])

  const handleLabelChange = useCallback((label: string) => {
    setCurrentLabel(label)
    if (label && !labelColors[label]) {
      const color = getColorForLabel(label, labelColors)
      setLabelColors(prev => ({ ...prev, [label]: color }))
    }
  }, [labelColors])

  // Annotation: auto-save draft (debounced 2s)
  useEffect(() => {
    if (!annotationMode) return
    const totalRegions = Object.values(allAnnotations).reduce((sum, r) => sum + r.length, 0)

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)

    // If all regions are deleted and a draft exists, delete it from server immediately
    // (no debounce — the user's intent is clear, and delaying risks the timer being
    // cancelled by an annotation-mode toggle, leaving a stale draft on the server)
    if (totalRegions === 0) {
      if (draftId) {
        const idToDelete = draftId
        setDraftId(null)
        deleteDraft(idToDelete).catch(err => {
          console.error('Failed to delete empty annotation draft:', err)
        })
      }
      return
    }

    saveTimerRef.current = setTimeout(async () => {
      try {
        const id = draftId || crypto.randomUUID()
        if (!draftId) setDraftId(id)
        await saveDraft({
          draft_id: id,
          source_dataset_id: datasetId,
          annotations: allAnnotations,
        })
      } catch (err) {
        console.error('Failed to auto-save annotation draft:', err)
      }
    }, 2000)

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [annotationMode, allAnnotations, draftId, datasetId])

  // Annotation: draft recovery when entering annotation mode
  useEffect(() => {
    if (!annotationMode) return
    // Only recover if annotations state is pristine (empty object).
    // If keys exist (even with empty arrays), the user explicitly cleared them —
    // don't restore the old draft.
    if (Object.keys(allAnnotations).length > 0) return

    listDrafts().then(drafts => {
      // Find a draft matching this dataset
      const matching = drafts.find(d => d.source_dataset_id === datasetId)
      if (matching && Object.keys(matching.annotations).length > 0) {
        setAllAnnotations(matching.annotations)
        setDraftId(matching.draft_id)
        // Recover label colors
        const colors: Record<string, string> = {}
        for (const regions of Object.values(matching.annotations)) {
          for (const r of regions) {
            if (r.label && r.color) colors[r.label] = r.color
          }
        }
        setLabelColors(prev => ({ ...prev, ...colors }))
      }
    }).catch(err => {
      console.error('Failed to recover annotation draft:', err)
    })
  }, [annotationMode]) // eslint-disable-line react-hooks/exhaustive-deps

  // Annotation: beforeunload warning
  useEffect(() => {
    const totalRegions = Object.values(allAnnotations).reduce((sum, r) => sum + r.length, 0)
    if (totalRegions === 0) return

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [allAnnotations])

  if (!detail) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-8 h-8 animate-spin text-blue-500" />
          <p className="text-gray-500 font-medium">{t('wsiViewer.loadingFileInfo')}</p>
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
          <button
            onClick={() => {
              if (fromAIChat) {
                navigate('/dashboard')
              } else if (fromDataset && datasetId) {
                // Return to the same dataset in ListPage
                navigate('/wsi-list', { state: { dataset_id: datasetId } })
              } else {
                // Return to all datasets list
                navigate('/wsi-list')
              }
            }}
            className="flex items-center gap-1 sm:gap-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100/80 text-xs sm:text-sm font-medium px-2 sm:px-3 py-1.5 sm:py-2 rounded-lg transition-all"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">
              {fromAIChat ? t('wsiViewer.backToChat') : fromDataset && datasetName ? t('wsiViewer.backToDataset', { name: datasetName }) : t('common.back')}
            </span>
          </button>
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
                onClick={() => prevWSI && navigate(`/wsi/${prevWSI.wsi_id}`, {
                  state: {
                    fromAIChat,
                    fromDataset,
                    datasetId,
                    datasetName
                  }
                })}
                disabled={!prevWSI}
                className="p-1 sm:p-1.5 rounded-md hover:bg-white hover:shadow-sm text-gray-500 hover:text-indigo-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:shadow-none disabled:cursor-not-allowed transition-all"
                title={prevWSI ? t('common.previous') : t('wsiViewer.noPreviousSlide')}
              >
                <ChevronLeft className="w-4 h-4 sm:w-5 sm:h-5" />
              </button>
              <div className="w-px h-4 bg-gray-200"></div>
              <button
                onClick={() => nextWSI && navigate(`/wsi/${nextWSI.wsi_id}`, {
                  state: {
                    fromAIChat,
                    fromDataset,
                    datasetId,
                    datasetName
                  }
                })}
                disabled={!nextWSI}
                className="p-1 sm:p-1.5 rounded-md hover:bg-white hover:shadow-sm text-gray-500 hover:text-indigo-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:shadow-none disabled:cursor-not-allowed transition-all"
                title={nextWSI ? t('common.next') : t('wsiViewer.noNextSlide')}
              >
                <ChevronRight className="w-4 h-4 sm:w-5 sm:h-5" />
              </button>
            </div>

            <div className="w-px h-5 bg-gray-200" />
            <AnnotationToolbar
              annotationMode={annotationMode}
              onToggleMode={() => setAnnotationMode(m => !m)}
              drawingTool={drawingTool}
              onToolChange={setDrawingTool}
              currentLabel={currentLabel}
              onLabelChange={handleLabelChange}
              labelColors={labelColors}
              allLabels={allLabels}
            />

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
            // Note: wheel event is handled via useEffect with { passive: false } to allow preventDefault
            <div
              ref={patchContainerRef}
              className="w-full h-full flex items-center justify-center overflow-hidden bg-gray-100"
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
                  title={t('wsiViewer.zoomIn')}
                >
                  <Plus className="w-4 h-4" />
                </button>
                <button
                  onClick={handlePatchZoomOut}
                  className="p-2 hover:bg-gray-100 rounded transition-colors text-gray-600 hover:text-gray-900"
                  title={t('wsiViewer.zoomOut')}
                >
                  <Minus className="w-4 h-4" />
                </button>
                <div className="h-5 w-px bg-gray-200 mx-0.5" />
                <button
                  onClick={handlePatchReset}
                  className="p-2 hover:bg-gray-100 rounded transition-colors text-gray-600 hover:text-gray-900"
                  title={t('wsiViewer.resetView')}
                >
                  <RotateCcw className="w-4 h-4" />
                </button>
                <button
                  onClick={handlePatchFullscreen}
                  className="p-2 hover:bg-gray-100 rounded transition-colors text-gray-600 hover:text-gray-900"
                  title={t('wsiViewer.fullscreen')}
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
                  alt={t('wsiViewer.patchAlt')}
                  className="w-full h-full object-contain rounded-xl shadow-lg select-none"
                  draggable={false}
                />
                {/* Heatmap overlay */}
                {showHeatmap && selectedTaskId && (
                  <img
                    src={getPatchCAMImageUrl(wsi_id, selectedTaskId, selectedFoldKey)}
                    alt={t('wsiViewer.heatmapOverlayAlt')}
                    className="absolute inset-0 w-full h-full object-contain rounded-xl pointer-events-none select-none"
                    style={{ opacity: heatmapOpacity }}
                    draggable={false}
                  />
                )}
              </div>
            </div>
          ) : (
            // WSI-level viewer
            <>
              <WSIViewer
                wsi_id={wsi_id}
                showHeatmap={showHeatmap}
                heatmapOpacity={heatmapOpacity}
                taskId={selectedTaskId}
                foldKey={selectedFoldKey}
                classIdx={selectedClassIdx}
                dataLevel={selectedTask?.data_type || 'wsi'}
                onHeatmapLoaded={handleHeatmapLoaded}
                onViewerReady={handleViewerReady}
                onSlideInfo={handleSlideInfo}
              />
              <AnnotationOverlay
                viewer={osdViewer}
                annotationMode={annotationMode}
                drawingTool={drawingTool}
                currentLabel={currentLabel}
                currentColor={currentColor}
                regions={currentRegions}
                labelColors={labelColors}
                slideWidth={slideWidth}
                slideHeight={slideHeight}
                onRegionCreated={handleRegionCreated}
                onRegionTooLarge={handleRegionTooLarge}
              />
            </>
          )}

          {/* Heatmap Controls Overlay */}
          {availableHeatmaps.length > 0 && (
            <div className="absolute bottom-4 left-4 right-4 sm:right-auto bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200 p-2 sm:p-3 z-20">
              <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
                <button
                  onClick={() => setShowHeatmap(!showHeatmap)}
                  className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs sm:text-sm font-medium transition-all ${showHeatmap
                    ? 'bg-indigo-100 text-indigo-700 border border-indigo-300'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'
                    }`}
                >
                  <Layers className="w-4 h-4" />
                  {showHeatmap ? t('wsiViewer.hideHeatmap') : t('wsiViewer.showHeatmap')}
                </button>

                {showHeatmap && (
                  <div className="flex items-center gap-2 px-2 sm:px-0 sm:pl-3 border-t sm:border-t-0 sm:border-l border-gray-200 pt-2 sm:pt-0">
                    <span className="text-[10px] sm:text-xs text-gray-500 whitespace-nowrap">{t('wsiViewer.opacity')}:</span>
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
                    <span className="text-[10px] text-gray-400 uppercase tracking-wide">{t('wsiViewer.activation')}:</span>
                    <div className="flex-1 h-2 rounded-full bg-gradient-to-r from-blue-500 via-green-500 via-yellow-500 to-red-500"></div>
                    <span className="text-[10px] text-gray-500">{t('wsiViewer.lowToHigh')}</span>
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
          <h2 className="text-lg font-bold text-gray-900">{t('wsiViewer.analysisData')}</h2>
          <button
            onClick={() => setIsSidebarOpen(false)}
            className="p-2 rounded-lg bg-white border border-gray-200 text-gray-400"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        {/* Conditionally show annotation panel or analysis panels */}
        {annotationMode ? (
          <AnnotationListPanel
            currentWsiId={wsi_id}
            regions={currentRegions}
            allAnnotations={allAnnotations}
            labelColors={labelColors}
            onUpdateRegion={handleUpdateRegion}
            onDeleteRegion={handleDeleteRegion}
            onCreateDataset={() => setShowCreateDatasetDialog(true)}
          />
        ) : (
          <>
            {/* Loading state */}
            {loadingHeatmaps && (
              <div className="flex items-center justify-center py-12">
                <div className="flex flex-col items-center gap-3">
                  <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
                  <p className="text-sm text-gray-500">{t('wsiViewer.loadingAnalysisData')}</p>
                </div>
              </div>
            )}

            {/* No heatmaps available */}
            {!loadingHeatmaps && availableHeatmaps.length === 0 && (
              <Card className="overflow-hidden">
                <div className="p-8 text-center">
                  <Layers className="w-12 h-12 text-gray-300 mx-auto mb-3" />
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">{t('wsiViewer.noAttentionData')}</h3>
                  <p className="text-xs text-gray-500">
                    {t('wsiViewer.noAttentionDataDesc')}
                  </p>
                </div>
              </Card>
            )}

            {/* Heatmaps available */}
            {!loadingHeatmaps && availableHeatmaps.length > 0 && (
              <>
                <TaskSelectorCard
                  availableHeatmaps={availableHeatmaps}
                  selectedTaskId={selectedTaskId}
                  setSelectedTaskId={setSelectedTaskId}
                  selectedFoldKey={selectedFoldKey}
                  setSelectedFoldKey={setSelectedFoldKey}
                  availableFolds={availableFolds}
                  uniqueTasks={uniqueTasks}
                  isTaskDropdownOpen={isTaskDropdownOpen}
                  setIsTaskDropdownOpen={setIsTaskDropdownOpen}
                  setShowDeleteConfirm={setShowDeleteConfirm}
                  heatmapData={heatmapData}
                  patchCAMData={patchCAMData}
                  isPatchLevel={isPatchLevel}
                />

                {/* Multi-class Attention Selector - only for CLAM_MB and similar aggregators */}
                {heatmapData?.attention_type === 'multi_class' && heatmapData.classes && heatmapData.classes.length > 0 && (
                  <AttentionClassSelector
                    heatmapData={heatmapData}
                    selectedClassIdx={selectedClassIdx}
                    setSelectedClassIdx={setSelectedClassIdx}
                    isClassDropdownOpen={isClassDropdownOpen}
                    setIsClassDropdownOpen={setIsClassDropdownOpen}
                  />
                )}

                <AttentionPatchesPanel
                  heatmapData={heatmapData}
                  wsi_id={wsi_id}
                  exportingTop={exportingTop}
                  exportingBottom={exportingBottom}
                  handleExportTop={handleExportTop}
                  handleExportBottom={handleExportBottom}
                  patchCAMData={patchCAMData}
                  isPatchLevel={isPatchLevel}
                />
              </>
            )}
          </>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <DeleteResultsModal
        showDeleteConfirm={showDeleteConfirm}
        setShowDeleteConfirm={setShowDeleteConfirm}
        deleteMode={deleteMode}
        setDeleteMode={setDeleteMode}
        deletingResults={deletingResults}
        handleDeleteResults={handleDeleteResults}
        availableHeatmaps={availableHeatmaps}
        selectedTaskId={selectedTaskId}
      />

      {/* Create Dataset from Annotations Dialog */}
      <CreateDatasetDialog
        show={showCreateDatasetDialog}
        onClose={() => setShowCreateDatasetDialog(false)}
        allAnnotations={allAnnotations}
        labelColors={labelColors}
        sourceDatasetId={datasetId}
        draftId={draftId || undefined}
      />
    </div>
  )
}
