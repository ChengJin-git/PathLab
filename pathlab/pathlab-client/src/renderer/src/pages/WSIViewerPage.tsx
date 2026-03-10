import { useEffect, useState, useCallback, useRef, useMemo, type SyntheticEvent } from 'react'
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
  getSegMaskImageUrl,
} from '../api'
import WSIViewer from '../components/WSIViewer'
import { Card } from '../components/common'
import { ArrowLeft, Microscope, Layers, Loader2, ChevronLeft, ChevronRight, Plus, Minus, RotateCcw, Maximize2, X, Save, AlertTriangle } from 'lucide-react'
import { exportPatchesAsZip } from '../components/wsiViewer/utils'
import { TaskSelectorCard } from '../components/wsiViewer/TaskSelectorCard'
import { AttentionClassSelector } from '../components/wsiViewer/AttentionClassSelector'
import { AttentionPatchesPanel } from '../components/wsiViewer/AttentionPatchesPanel'
import { DeleteResultsModal } from '../components/wsiViewer/DeleteResultsModal'
import { AnnotationToolbar, getColorForLabel } from '../components/wsiViewer/AnnotationToolbar'
import { AnnotationOverlay } from '../components/wsiViewer/AnnotationOverlay'
import { PatchOverlayStack, type PatchOverlayLayer } from '../components/wsiViewer/PatchOverlayStack'
import { AnnotationListPanel } from '../components/wsiViewer/AnnotationListPanel'
import { CreateDatasetDialog } from '../components/wsiViewer/CreateDatasetDialog'
import { ViewerOverlayControls } from '../components/wsiViewer/ViewerOverlayControls'
import {
  AnnotationRegion,
  AnnotationsMap,
  DatasetAnnotationSummaryResponse,
  saveAnnotation,
  listAnnotations,
  deleteAnnotation,
  getWSIGroundTruth,
  getDatasetAnnotationSummary,
  deleteDatasetAnnotationsByLabels,
  extractRegions,
} from '../api/annotation'
import { useToast } from '../contexts/ToastContext'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { getFileType } from '../constants/fileTypes'

const PATCH_OVERLAY_PREVIEW_SIZE = 768

const FOCUS_REGION_PADDING_MULTIPLIER = 1.8
const FOCUS_REGION_MIN_SIZE = 512

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

interface ViewerNavigationState {
  fromAIChat?: boolean
  fromDataset?: boolean
  datasetId?: string
  datasetName?: string
  conversationId?: string
  selectedTaskId?: string
  selectedFoldKey?: string
  initialShowHeatmap?: boolean
}

export default function WSIViewerPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const { addExtractionTask } = useBackgroundTask()
  const { wsi_id = '' } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const navigationState = (location.state as ViewerNavigationState | null) ?? null
  const fromAIChat = navigationState?.fromAIChat === true
  const fromDataset = navigationState?.fromDataset === true
  const datasetId = navigationState?.datasetId
  const datasetName = navigationState?.datasetName
  const conversationId = navigationState?.conversationId
  const preferredTaskId = navigationState?.selectedTaskId
  const preferredFoldKey = navigationState?.selectedFoldKey
  const initialShowHeatmap = navigationState?.initialShowHeatmap === true
  const [detail, setDetail] = useState<any>()
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [showSegMask, setShowSegMask] = useState(false)
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
          setSelectedFoldKey(undefined)
          setShowHeatmap(false)
          setShowSegMask(false)
        } else {
          setSelectedTaskId(undefined)
          setSelectedFoldKey(undefined)
          setHeatmapData(null)
          setShowHeatmap(false)
          setShowSegMask(false)
        }
      }

      setShowDeleteConfirm(false)
    } catch (err) {
      console.error('Failed to delete results:', err)
      toast.error(t('wsiViewer.deleteResultsFailed', { error: String(err) }))
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
  const [isLabelDropdownOpen, setIsLabelDropdownOpen] = useState(false)
  const [allAnnotations, setAllAnnotations] = useState<AnnotationsMap>({})
  const [annotationId, setAnnotationId] = useState<string | null>(null)
  const [osdViewer, setOsdViewer] = useState<any>(null)
  const [slideWidth, setSlideWidth] = useState(0)
  const [slideHeight, setSlideHeight] = useState(0)
  const [showCreateDatasetDialog, setShowCreateDatasetDialog] = useState(false)
  const [focusedRegionId, setFocusedRegionId] = useState<string | null>(null)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const effectiveDatasetId = datasetId ?? detail?.meta?.dataset_id
  const draftCacheKey = effectiveDatasetId ?? '__NO_DATASET__'
  const draftCacheRef = useRef<{
    key: string
    draft: { annotation_id: string; annotations: AnnotationsMap } | null
  } | null>(null)
  const [datasetAnnotationSummary, setDatasetAnnotationSummary] = useState<DatasetAnnotationSummaryResponse | null>(null)
  const [loadingDatasetAnnotationSummary, setLoadingDatasetAnnotationSummary] = useState(false)

  // Manual save & unsaved-changes tracking
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [savingAnnotations, setSavingAnnotations] = useState(false)
  // Pending navigation when user tries to leave with unsaved changes
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null)

  // Determine if any annotated source slide is a WSI (not a patch image)
  // Used to disable segmentation dataset creation for WSI data
  const hasWsiSources = useMemo(() => {
    const annotatedWsiIds = new Set(
      Object.keys(allAnnotations).filter(id => allAnnotations[id]?.length > 0)
    )
    if (annotatedWsiIds.size === 0) return false
    return allWSIs.some(wsi => {
      if (!annotatedWsiIds.has(wsi.wsi_id)) return false
      return getFileType(wsi.file_extension || null, wsi.file_size ?? null) === 'WSI'
    })
  }, [allAnnotations, allWSIs])

  const refreshDatasetAnnotationSummary = useCallback(async () => {
    if (!effectiveDatasetId) {
      setDatasetAnnotationSummary(null)
      return
    }

    setLoadingDatasetAnnotationSummary(true)
    try {
      const summary = await getDatasetAnnotationSummary(effectiveDatasetId)
      setDatasetAnnotationSummary(summary)
      if (summary.annotation_id && !annotationId) {
        setAnnotationId(summary.annotation_id)
      }
    } catch (err) {
      console.error('Failed to load dataset annotation summary:', err)
    } finally {
      setLoadingDatasetAnnotationSummary(false)
    }
  }, [annotationId, effectiveDatasetId])

  // Load WSI list for navigation
  // If coming from a dataset, load only that dataset's WSIs; otherwise load all
  useEffect(() => {
    fetchWSIList(fromDataset ? datasetId : undefined).then(res => {
      if (res && res.items) {
        setAllWSIs(res.items)
      }
    })
  }, [fromDataset, datasetId])

  useEffect(() => {
    if (!annotationMode || !effectiveDatasetId) {
      setDatasetAnnotationSummary(null)
      setLoadingDatasetAnnotationSummary(false)
      return
    }
    refreshDatasetAnnotationSummary()
  }, [annotationMode, effectiveDatasetId, refreshDatasetAnnotationSummary])

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
        const isHeatmapEntry = (entry: AvailableHeatmap) => entry.data_type === 'wsi' || entry.data_type === 'patch'
        const preferredExactEntry = preferredTaskId
          ? heatmaps.find(h => h.task_id === preferredTaskId && h.fold_key === preferredFoldKey && isHeatmapEntry(h))
          : undefined
        const preferredTaskEntry = preferredTaskId
          ? heatmaps.find(h => h.task_id === preferredTaskId && isHeatmapEntry(h))
          : undefined
        const fallbackEntry = heatmaps.find(isHeatmapEntry) ?? heatmaps[0]
        const initialEntry = preferredExactEntry ?? preferredTaskEntry ?? fallbackEntry

        if (initialEntry?.task_id) {
          setSelectedTaskId(initialEntry.task_id)
          setSelectedFoldKey(preferredExactEntry?.fold_key || undefined)
          setShowHeatmap(initialShowHeatmap && isHeatmapEntry(initialEntry))
          setShowSegMask(false)
        }
      } catch (err) {
        console.error('Failed to fetch available heatmaps:', err)
        setAvailableHeatmaps([])
      } finally {
        setLoadingHeatmaps(false)
      }
    }
    loadData()
  }, [initialShowHeatmap, preferredFoldKey, preferredTaskId, wsi_id])

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

  const handleSelectedTaskChange = useCallback((taskId: string | undefined) => {
    setSelectedTaskId(taskId)
    setSelectedFoldKey(undefined)
    setSelectedClassIdx(undefined)
    setShowHeatmap(false)
    setShowSegMask(false)
  }, [])

  const handleSelectedFoldChange = useCallback((foldKey: string) => {
    setSelectedFoldKey(foldKey)
    setSelectedClassIdx(undefined)
    setShowHeatmap(false)
    setShowSegMask(false)
  }, [])

  const selectedTaskGroup = useMemo(() => {
    if (!selectedTaskId) return []
    return availableHeatmaps.filter(h => h.task_id === selectedTaskId)
  }, [availableHeatmaps, selectedTaskId])

  const isSegmentationTask = selectedTaskGroup.some(
    h => h.task_type === 'segmentation' || h.task_type === 'patch_segmentation' || h.data_type === 'patch_segmentation'
  )

  const effectiveFoldKey = isSegmentationTask ? undefined : selectedFoldKey

  const selectedTaskEntries = useMemo(() => {
    if (selectedTaskGroup.length === 0) return []

    if (effectiveFoldKey) {
      const foldEntries = selectedTaskGroup.filter(h => h.fold_key === effectiveFoldKey)
      if (foldEntries.length > 0) return foldEntries
    }

    const nonFoldEntries = selectedTaskGroup.filter(h => !h.fold_key)
    return nonFoldEntries.length > 0 ? nonFoldEntries : selectedTaskGroup
  }, [effectiveFoldKey, selectedTaskGroup])

  const selectedTask = selectedTaskEntries.find(h => h.data_type === 'wsi' || h.data_type === 'patch') ?? selectedTaskEntries[0]
  const selectedSegmentationEntry = selectedTaskEntries.find(
    h => h.task_type === 'segmentation' || h.task_type === 'patch_segmentation' || h.data_type === 'patch_segmentation'
  )
  const hasPatchHeatmap = selectedTaskEntries.some(h => h.data_type === 'patch')
  const isPatchLevel = selectedTaskEntries.some(h => h.data_type === 'patch' || h.data_type === 'patch_segmentation')
  const canShowHeatmapOverlay = selectedTaskEntries.some(h => h.data_type === 'wsi' || h.data_type === 'patch')
  const canShowSegMaskOverlay = selectedTaskEntries.some(h => h.data_type === 'patch_segmentation')
  const shouldShowOverlayControls = canShowHeatmapOverlay || canShowSegMaskOverlay
  const segmentationClasses = selectedSegmentationEntry?.classes ?? []
  const viewerDataLevel: 'wsi' | 'patch' = selectedTask?.data_type === 'patch' ? 'patch' : 'wsi'

  // Mouse wheel zoom for patch viewer - wait until the conditional patch container is mounted
  useEffect(() => {
    if (!isPatchLevel) return

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

    container.addEventListener('wheel', handleWheel, { passive: false })
    return () => {
      container.removeEventListener('wheel', handleWheel)
    }
  }, [isPatchLevel])

  // Get available folds for the selected task (K-fold support)
  const availableFolds = useMemo(() => {
    if (selectedTaskGroup.length === 0 || isSegmentationTask) return []
    const folds = selectedTaskGroup
      .filter(h => h.fold_key)
      .map(h => h.fold_key!)
      .filter((v, i, a) => a.indexOf(v) === i)  // unique
      .sort((a, b) => {
        // Sort fold_0, fold_1, ... numerically
        const numA = parseInt(a.replace('fold_', ''), 10)
        const numB = parseInt(b.replace('fold_', ''), 10)
        return numA - numB
      })
    return folds
  }, [isSegmentationTask, selectedTaskGroup])

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

  useEffect(() => {
    if (!canShowHeatmapOverlay && showHeatmap) {
      setShowHeatmap(false)
    }
  }, [canShowHeatmapOverlay, showHeatmap])

  useEffect(() => {
    if (!canShowSegMaskOverlay && showSegMask) {
      setShowSegMask(false)
    }
  }, [canShowSegMaskOverlay, showSegMask])

  // Load patch CAM data when selecting a patch-level task
  useEffect(() => {
    if (hasPatchHeatmap && selectedTaskId) {
      fetchPatchCAMData(wsi_id, selectedTaskId, effectiveFoldKey).then(setPatchCAMData)
    } else {
      setPatchCAMData(null)
    }
  }, [wsi_id, selectedTaskId, effectiveFoldKey, hasPatchHeatmap])

  const patchHeatmapPreviewUrl = useMemo(() => {
    if (!selectedTaskId || !canShowHeatmapOverlay) return null
    return getPatchCAMImageUrl(wsi_id, selectedTaskId, effectiveFoldKey, PATCH_OVERLAY_PREVIEW_SIZE)
  }, [canShowHeatmapOverlay, effectiveFoldKey, selectedTaskId, wsi_id])

  const patchSegMaskPreviewUrl = useMemo(() => {
    if (!selectedTaskId || !canShowSegMaskOverlay) return null
    return getSegMaskImageUrl(wsi_id, selectedTaskId, effectiveFoldKey, PATCH_OVERLAY_PREVIEW_SIZE)
  }, [canShowSegMaskOverlay, effectiveFoldKey, selectedTaskId, wsi_id])

  const patchOverlayLayers = useMemo<PatchOverlayLayer[]>(() => {
    const layers: PatchOverlayLayer[] = []

    if (showHeatmap && patchHeatmapPreviewUrl) {
      layers.push({
        key: 'pred-heatmap',
        src: patchHeatmapPreviewUrl,
        alt: t('wsiViewer.heatmapOverlayAlt'),
        opacity: heatmapOpacity,
      })
    }

    if (showSegMask && patchSegMaskPreviewUrl) {
      layers.push({
        key: 'pred-mask',
        src: patchSegMaskPreviewUrl,
        alt: t('wsiViewer.showPredictionMask'),
      })
    }

    return layers
  }, [heatmapOpacity, patchHeatmapPreviewUrl, patchSegMaskPreviewUrl, showHeatmap, showSegMask, t])

  const handleToggleHeatmap = useCallback(() => {
    setShowHeatmap(prev => !prev)
  }, [])

  const handleToggleSegMask = useCallback(() => {
    setShowSegMask(prev => !prev)
  }, [])

  useEffect(() => {
    if (!isPatchLevel) return

    ;[patchHeatmapPreviewUrl, patchSegMaskPreviewUrl]
      .filter((url): url is string => !!url)
      .forEach((url) => {
        const img = new Image()
        img.decoding = 'async'
        img.src = url
      })
  }, [isPatchLevel, patchHeatmapPreviewUrl, patchSegMaskPreviewUrl])

  const currentIndex = allWSIs.findIndex(w => w.wsi_id === wsi_id)
  const prevWSI = currentIndex > 0 ? allWSIs[currentIndex - 1] : null
  const nextWSI = currentIndex >= 0 && currentIndex < allWSIs.length - 1 ? allWSIs[currentIndex + 1] : null

  // Annotation: computed values
  const currentRegions = useMemo(() => allAnnotations[wsi_id] || [], [allAnnotations, wsi_id])

  useEffect(() => {
    setFocusedRegionId(prev => prev && currentRegions.some(region => region.id === prev) ? prev : null)
  }, [currentRegions])

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

  const updateDraftCache = useCallback((nextAnnotationId: string | null, annotations: AnnotationsMap | null) => {
    draftCacheRef.current = {
      key: draftCacheKey,
      draft: nextAnnotationId
        ? {
            annotation_id: nextAnnotationId,
            annotations: annotations ?? {},
          }
        : null,
    }
  }, [draftCacheKey])

  const mergeLabelColorsFromAnnotations = useCallback((annotations: AnnotationsMap) => {
    setLabelColors(prev => {
      const next = { ...prev }
      for (const regions of Object.values(annotations)) {
        for (const region of regions) {
          if (!region.label) continue
          if (next[region.label]) continue

          const usedColors = new Set(Object.values(next))
          if (region.color && !usedColors.has(region.color)) {
            next[region.label] = region.color
          } else {
            next[region.label] = getColorForLabel(region.label, next)
          }
        }
      }
      return next
    })
  }, [])

  // Annotation: handlers
  const handleViewerReady = useCallback((viewer: any) => {
    setOsdViewer(viewer)
  }, [])

  const handleSlideInfo = useCallback((info: { width: number; height: number }) => {
    setSlideWidth(info.width)
    setSlideHeight(info.height)
  }, [])

  const handlePatchImageLoad = useCallback((event: SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget
    if (image.naturalWidth > 0 && image.naturalHeight > 0) {
      setSlideWidth(image.naturalWidth)
      setSlideHeight(image.naturalHeight)
    }
  }, [])

  const handleFocusRegion = useCallback((regionId: string) => {
    setFocusedRegionId(regionId)

    const region = currentRegions.find(item => item.id === regionId)
    if (!region || !osdViewer?.viewport || !window.OpenSeadragon || slideWidth <= 0 || slideHeight <= 0) {
      return
    }

    const viewportAspect = Math.max(osdViewer.viewport.getAspectRatio?.() || 1, 0.1)
    const regionCenterX = region.x + region.width / 2
    const regionCenterY = region.y + region.height / 2

    let targetWidth = Math.max(region.width * FOCUS_REGION_PADDING_MULTIPLIER, FOCUS_REGION_MIN_SIZE)
    let targetHeight = Math.max(region.height * FOCUS_REGION_PADDING_MULTIPLIER, FOCUS_REGION_MIN_SIZE)

    if (targetWidth / targetHeight > viewportAspect) {
      targetHeight = targetWidth / viewportAspect
    } else {
      targetWidth = targetHeight * viewportAspect
    }

    const scale = Math.min(1, slideWidth / targetWidth, slideHeight / targetHeight)
    targetWidth *= scale
    targetHeight *= scale

    const targetX = clamp(regionCenterX - targetWidth / 2, 0, Math.max(0, slideWidth - targetWidth))
    const targetY = clamp(regionCenterY - targetHeight / 2, 0, Math.max(0, slideHeight - targetHeight))

    const bounds = new window.OpenSeadragon.Rect(
      targetX / slideWidth,
      targetY / slideWidth,
      targetWidth / slideWidth,
      targetHeight / slideWidth,
    )

    if (typeof osdViewer.viewport.fitBoundsWithConstraints === 'function') {
      osdViewer.viewport.fitBoundsWithConstraints(bounds, false)
    } else {
      osdViewer.viewport.fitBounds(bounds, false)
      osdViewer.viewport.applyConstraints()
    }
  }, [currentRegions, osdViewer, slideHeight, slideWidth])

  const handleRegionCreated = useCallback((region: Omit<AnnotationRegion, 'id'>) => {
    const newRegion: AnnotationRegion = {
      ...region,
      id: crypto.randomUUID(),
    }
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: [...(prev[wsi_id] || []), newRegion],
    }))
    setHasUnsavedChanges(true)
    // Auto-assign color to label
    if (region.label) {
      setLabelColors(prev => {
        if (prev[region.label]) return prev
        return {
          ...prev,
          [region.label]: getColorForLabel(region.label, prev),
        }
      })
    }
  }, [wsi_id])

  const handleRegionTooLarge = useCallback(() => {
    toast.warning(t('annotation.regionTooLarge'))
  }, [t, toast])

  const handleUpdateRegion = useCallback((regionId: string, updates: Partial<AnnotationRegion>) => {
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: (prev[wsi_id] || []).map(r => r.id === regionId ? { ...r, ...updates } : r),
    }))
    if (updates.label) {
      setLabelColors(prev => {
        if (prev[updates.label!]) return prev
        return {
          ...prev,
          [updates.label!]: getColorForLabel(updates.label!, prev),
        }
      })
    }
    setHasUnsavedChanges(true)
  }, [wsi_id])

  const handleDeleteRegion = useCallback((regionId: string) => {
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: (prev[wsi_id] || []).filter(r => r.id !== regionId),
    }))
    setHasUnsavedChanges(true)
  }, [wsi_id])

  const handleDeleteRegions = useCallback((regionIds: string[]) => {
    const idSet = new Set(regionIds)
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: (prev[wsi_id] || []).filter(r => !idSet.has(r.id)),
    }))
    setHasUnsavedChanges(true)
  }, [wsi_id])

  const handleLabelChange = useCallback((label: string) => {
    const defaultLabel = t('annotation.defaultLabel')
    // When user sets a real label and there are regions with the default label,
    // replace all default-label regions with the new label and remove the default from colors
    if (label !== defaultLabel) {
      setAllAnnotations(prev => {
        const updated: typeof prev = {}
        let changed = false
        for (const [wsiId, regions] of Object.entries(prev)) {
          updated[wsiId] = regions.map(r => {
            if (r.label === defaultLabel) {
              changed = true
              return { ...r, label }
            }
            return r
          })
        }
        return changed ? updated : prev
      })
      setLabelColors(prev => {
        if (prev[defaultLabel]) {
          const { [defaultLabel]: _, ...rest } = prev
          return rest
        }
        return prev
      })
    }
    setCurrentLabel(label)
    if (label) {
      setLabelColors(prev => {
        if (prev[label]) return prev
        return {
          ...prev,
          [label]: getColorForLabel(label, prev),
        }
      })
    }
  }, [t])

  const buildEmptyDatasetDraftAnnotations = useCallback((): AnnotationsMap => {
    if (Object.keys(allAnnotations).length > 0) {
      return allAnnotations
    }
    return wsi_id ? { [wsi_id]: [] } : {}
  }, [allAnnotations, wsi_id])

  // Manual save handler
  const handleManualSave = useCallback(async () => {
    setSavingAnnotations(true)
    try {
      const totalRegions = Object.values(allAnnotations).reduce((sum, r) => sum + r.length, 0)
      if (totalRegions === 0) {
        if (effectiveDatasetId) {
          const id = annotationId || crypto.randomUUID()
          const emptyDatasetDraft = buildEmptyDatasetDraftAnnotations()
          if (!annotationId) setAnnotationId(id)
          await saveAnnotation({
            annotation_id: id,
            source_dataset_id: effectiveDatasetId,
            annotations: emptyDatasetDraft,
          })
          updateDraftCache(id, emptyDatasetDraft)
        } else if (annotationId) {
          // Nothing to save; if an annotation exists, delete it
          const idToDelete = annotationId
          setAnnotationId(null)
          await deleteAnnotation(idToDelete)
          updateDraftCache(null, null)
        }
      } else {
        const id = annotationId || crypto.randomUUID()
        if (!annotationId) setAnnotationId(id)
        await saveAnnotation({
          annotation_id: id,
          source_dataset_id: effectiveDatasetId,
          annotations: allAnnotations,
        })
        updateDraftCache(id, allAnnotations)
      }
      setHasUnsavedChanges(false)
      if (effectiveDatasetId) {
        await refreshDatasetAnnotationSummary()
      }
      toast.success(t('annotation.saved'))
      return true
    } catch (err) {
      console.error('Failed to save annotation:', err)
      toast.error(t('annotation.saveFailed'))
      return false
    } finally {
      setSavingAnnotations(false)
    }
  }, [allAnnotations, annotationId, buildEmptyDatasetDraftAnnotations, effectiveDatasetId, refreshDatasetAnnotationSummary, t, toast, updateDraftCache])

  const handleDeleteCrossSlideByLabel = useCallback(async (labels: string[]) => {
    const labelSet = new Set(labels)

    if (!effectiveDatasetId) {
      setAllAnnotations(prev => {
        const next: typeof prev = {}
        for (const [key, regions] of Object.entries(prev)) {
          next[key] = regions.filter(r => !labelSet.has(r.label))
        }
        return next
      })
      setHasUnsavedChanges(true)
      return
    }

    try {
      if (hasUnsavedChanges) {
        const saved = await handleManualSave()
        if (!saved) return
      }

      const result = await deleteDatasetAnnotationsByLabels(effectiveDatasetId, { labels })
      setAnnotationId(result.annotation_id)
      draftCacheRef.current = null
      setDatasetAnnotationSummary(result.summary)
      setAllAnnotations(prev => {
        const next: typeof prev = {}
        for (const [key, regions] of Object.entries(prev)) {
          next[key] = regions.filter(r => !labelSet.has(r.label))
        }
        return next
      })
      setHasUnsavedChanges(false)
      toast.success(t('annotation.saved'))
    } catch (err) {
      console.error('Failed to delete dataset annotations by labels:', err)
      toast.error(t('annotation.saveFailed'))
    }
  }, [effectiveDatasetId, handleManualSave, hasUnsavedChanges, t, toast])

  const handleCreateDatasetFromAnnotations = useCallback(async ({
    datasetName,
    taskType,
  }: {
    datasetName: string
    taskType: 'classification' | 'segmentation'
  }) => {
    try {
      if (effectiveDatasetId && hasUnsavedChanges) {
        const saved = await handleManualSave()
        if (!saved) return
      }

      const isSegReuse = taskType === 'segmentation' && !!effectiveDatasetId
      const result = await extractRegions({
        annotation_id: annotationId || undefined,
        annotations: effectiveDatasetId ? undefined : allAnnotations,
        dataset_name: isSegReuse ? '' : datasetName,
        task_type: taskType,
        ...(effectiveDatasetId ? { source_dataset_id: effectiveDatasetId, dataset_scope: true } : {}),
      })

      addExtractionTask(result.task_id, isSegReuse ? t('annotation.reuseDataset') : datasetName)
      toast.success(t('annotation.extractSubmitted'))
    } catch (err: any) {
      toast.error(err?.message || t('annotation.extractFailed'))
      throw err
    }
  }, [addExtractionTask, allAnnotations, annotationId, effectiveDatasetId, handleManualSave, hasUnsavedChanges, t, toast])

  // Navigation guard: wrap navigation in unsaved-changes check
  const guardedNavigate = useCallback((navigateFn: () => void) => {
    if (hasUnsavedChanges && annotationMode) {
      setPendingNavigation(() => navigateFn)
    } else {
      navigateFn()
    }
  }, [hasUnsavedChanges, annotationMode])

  // Annotation: auto-save (debounced 2s)
  useEffect(() => {
    if (!annotationMode) return
    if (!hasUnsavedChanges) return
    const totalRegions = Object.values(allAnnotations).reduce((sum, r) => sum + r.length, 0)

    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)

    // For dataset-scoped annotations, persist empty drafts so intentional GT clearing
    // does not resurrect the dataset GT on the next load.
    if (totalRegions === 0) {
      if (effectiveDatasetId) {
        const id = annotationId || crypto.randomUUID()
        const emptyDatasetDraft = buildEmptyDatasetDraftAnnotations()
        if (!annotationId) setAnnotationId(id)
        saveAnnotation({
          annotation_id: id,
          source_dataset_id: effectiveDatasetId,
          annotations: emptyDatasetDraft,
        }).then(() => {
          updateDraftCache(id, emptyDatasetDraft)
          setHasUnsavedChanges(false)
          refreshDatasetAnnotationSummary()
        }).catch(err => {
          console.error('Failed to save empty dataset annotation:', err)
        })
      } else if (annotationId) {
        const idToDelete = annotationId
        setAnnotationId(null)
        deleteAnnotation(idToDelete).then(() => {
          updateDraftCache(null, null)
          setHasUnsavedChanges(false)
        }).catch(err => {
          console.error('Failed to delete empty annotation:', err)
        })
      } else {
        setHasUnsavedChanges(false)
      }
      return
    }

    saveTimerRef.current = setTimeout(async () => {
      try {
        const id = annotationId || crypto.randomUUID()
        if (!annotationId) setAnnotationId(id)
        await saveAnnotation({
          annotation_id: id,
          source_dataset_id: effectiveDatasetId,
          annotations: allAnnotations,
        })
        updateDraftCache(id, allAnnotations)
        setHasUnsavedChanges(false)
        if (effectiveDatasetId) {
          await refreshDatasetAnnotationSummary()
        }
      } catch (err) {
        console.error('Failed to auto-save annotation:', err)
      }
    }, 2000)

    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [annotationMode, allAnnotations, annotationId, buildEmptyDatasetDraftAnnotations, effectiveDatasetId, hasUnsavedChanges, refreshDatasetAnnotationSummary, updateDraftCache])

  // Annotation: recovery when entering annotation mode
  useEffect(() => {
    if (!annotationMode) return
    if (!datasetId && !detail) return
    // Recover per current WSI instead of blocking on any previously loaded slide.
    // If the current key exists (even with an empty array), treat it as already loaded.
    if (Object.prototype.hasOwnProperty.call(allAnnotations, wsi_id)) return

    let cancelled = false

    const recoverAnnotations = async () => {
      try {
        let matching = draftCacheRef.current?.key === draftCacheKey
          ? draftCacheRef.current.draft
          : null

        if (draftCacheRef.current?.key !== draftCacheKey) {
          const annotations = await listAnnotations()
          if (cancelled) return

          const found = annotations.find(d => (d.source_dataset_id ?? undefined) === (effectiveDatasetId ?? undefined))
          matching = found
            ? {
                annotation_id: found.annotation_id,
                annotations: found.annotations,
              }
            : null
          draftCacheRef.current = {
            key: draftCacheKey,
            draft: matching,
          }
        }

        // Draft wins over GT fallback for the current WSI if it already has an entry.
        if (matching) {
          setAnnotationId(matching.annotation_id)
          if (Object.keys(matching.annotations).length > 0) {
            setAllAnnotations(prev => ({
              ...prev,
              ...matching.annotations,
            }))
            mergeLabelColorsFromAnnotations(matching.annotations)
          }
          if (Object.prototype.hasOwnProperty.call(matching.annotations, wsi_id)) return
        } else {
          setAnnotationId(null)
        }

        if (!wsi_id) return

        const gt = await getWSIGroundTruth(wsi_id)
        if (cancelled || Object.keys(gt.annotations).length === 0) return

        setAllAnnotations(prev => ({
          ...prev,
          ...gt.annotations,
        }))
        mergeLabelColorsFromAnnotations(gt.annotations)
      } catch (err) {
        console.error('Failed to recover annotation:', err)
      }
    }

    recoverAnnotations()

    return () => {
      cancelled = true
    }
  }, [annotationMode, allAnnotations, datasetId, detail, draftCacheKey, effectiveDatasetId, mergeLabelColorsFromAnnotations, wsi_id])

  // Annotation: beforeunload warning (only when there are unsaved changes)
  useEffect(() => {
    if (!hasUnsavedChanges || !annotationMode) return

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [hasUnsavedChanges, annotationMode])

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
            onClick={() => guardedNavigate(() => {
              if (fromAIChat) {
                navigate(conversationId ? `/dashboard/${conversationId}` : '/dashboard')
              } else if (fromDataset && datasetId) {
                navigate('/wsi-list', { state: { dataset_id: datasetId } })
              } else {
                navigate('/wsi-list')
              }
            })}
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
                onClick={() => prevWSI && guardedNavigate(() => navigate(`/wsi/${prevWSI.wsi_id}`, {
                  state: {
                    fromAIChat,
                    fromDataset,
                    datasetId,
                    datasetName,
                    conversationId
                  }
                }))}
                disabled={!prevWSI}
                className="p-1 sm:p-1.5 rounded-md hover:bg-white hover:shadow-sm text-gray-500 hover:text-indigo-600 disabled:opacity-30 disabled:hover:bg-transparent disabled:hover:shadow-none disabled:cursor-not-allowed transition-all"
                title={prevWSI ? t('common.previous') : t('wsiViewer.noPreviousSlide')}
              >
                <ChevronLeft className="w-4 h-4 sm:w-5 sm:h-5" />
              </button>
              <div className="w-px h-4 bg-gray-200"></div>
              <button
                onClick={() => nextWSI && guardedNavigate(() => navigate(`/wsi/${nextWSI.wsi_id}`, {
                  state: {
                    fromAIChat,
                    fromDataset,
                    datasetId,
                    datasetName,
                    conversationId
                  }
                }))}
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
              onToggleMode={() => {
                setAnnotationMode(m => {
                  if (!m && !currentLabel) {
                    // Entering annotation mode with no label — set default
                    const defaultLabel = t('annotation.defaultLabel')
                    handleLabelChange(defaultLabel)
                  }
                  return !m
                })
              }}
              drawingTool={drawingTool}
              onToolChange={setDrawingTool}
              currentLabel={currentLabel}
              onLabelChange={handleLabelChange}
              labelColors={labelColors}
              allLabels={allLabels}
              onDropdownOpenChange={setIsLabelDropdownOpen}
            />

            {/* Save Annotations Button — visible only in annotation mode */}
            {annotationMode && (
              <button
                onClick={handleManualSave}
                disabled={savingAnnotations || !hasUnsavedChanges}
                className={`flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 sm:py-2 rounded-lg text-xs sm:text-sm font-medium transition-all ${
                  hasUnsavedChanges
                    ? 'bg-indigo-600 text-white hover:bg-indigo-700 shadow-sm'
                    : 'bg-gray-100 text-gray-400 cursor-default'
                }`}
                title={t('annotation.saveAnnotations')}
              >
                {savingAnnotations ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <Save className="w-3.5 h-3.5" />
                )}
                <span className="hidden sm:inline">
                  {savingAnnotations ? t('annotation.saving') : t('annotation.saveAnnotations')}
                </span>
              </button>
            )}

            <button
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className={`lg:hidden p-2 rounded-lg ${isSidebarOpen ? 'bg-indigo-100 text-indigo-700' : 'bg-white text-gray-500 border border-gray-200 shadow-sm'}`}
            >
              <Layers className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 relative bg-gray-100 overflow-hidden">
          {/* Conditional Viewer: WSI Viewer for WSI-level, Patch Viewer for patch-level results */}
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

              <PatchOverlayStack
                wsiId={wsi_id}
                baseImageAlt={t('wsiViewer.patchAlt')}
                overlayLayers={patchOverlayLayers}
                containerStyle={{
                  transform: `scale(${patchZoom}) translate(${patchPan.x / patchZoom}px, ${patchPan.y / patchZoom}px)`,
                  transformOrigin: 'center center'
                }}
                onBaseImageLoad={handlePatchImageLoad}
                regions={currentRegions}
                labelColors={labelColors}
                highlightedRegionId={focusedRegionId}
                slideWidth={slideWidth}
                slideHeight={slideHeight}
              />
            </div>
          ) : (
            // WSI-level viewer
            <>
              <WSIViewer
                wsi_id={wsi_id}
                showHeatmap={showHeatmap}
                heatmapOpacity={heatmapOpacity}
                taskId={selectedTaskId}
                foldKey={effectiveFoldKey}
                classIdx={selectedClassIdx}
                dataLevel={viewerDataLevel}
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
                highlightedRegionId={focusedRegionId}
                regions={currentRegions}
                labelColors={labelColors}
                slideWidth={slideWidth}
                slideHeight={slideHeight}
                onRegionCreated={handleRegionCreated}
                onRegionTooLarge={handleRegionTooLarge}
                isLabelDropdownOpen={isLabelDropdownOpen}
              />
            </>
          )}

          {/* Heatmap Controls Overlay */}
          {availableHeatmaps.length > 0 && shouldShowOverlayControls && (
            <ViewerOverlayControls
              canShowHeatmapOverlay={canShowHeatmapOverlay}
              showHeatmap={showHeatmap}
              onToggleHeatmap={handleToggleHeatmap}
              heatmapOpacity={heatmapOpacity}
              onHeatmapOpacityChange={setHeatmapOpacity}
              canShowSegMaskOverlay={canShowSegMaskOverlay}
              showSegMask={showSegMask}
              onToggleSegMask={handleToggleSegMask}
              segmentationClasses={segmentationClasses}
            />
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
            preferRemoteCrossSlideSummary={!!effectiveDatasetId}
            crossSlideSummary={effectiveDatasetId ? datasetAnnotationSummary : null}
            loadingCrossSlideSummary={effectiveDatasetId ? loadingDatasetAnnotationSummary : false}
            labelColors={labelColors}
            focusedRegionId={focusedRegionId}
            onFocusRegion={handleFocusRegion}
            onUpdateRegion={handleUpdateRegion}
            onDeleteRegion={handleDeleteRegion}
            onDeleteRegions={handleDeleteRegions}
            onDeleteCrossSlideByLabel={handleDeleteCrossSlideByLabel}
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
                  selectedTaskEntries={selectedTaskEntries}
                  selectedTaskId={selectedTaskId}
                  setSelectedTaskId={handleSelectedTaskChange}
                  selectedFoldKey={effectiveFoldKey}
                  setSelectedFoldKey={handleSelectedFoldChange}
                  availableFolds={availableFolds}
                  supportsFoldSelection={!isSegmentationTask}
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
        summary={effectiveDatasetId ? datasetAnnotationSummary : null}
        labelColors={labelColors}
        sourceDatasetId={effectiveDatasetId}
        hasWsiSources={datasetAnnotationSummary?.has_wsi_sources ?? hasWsiSources}
        onSubmitCreateDataset={handleCreateDatasetFromAnnotations}
      />

      {/* Unsaved Annotations Confirmation Modal */}
      {pendingNavigation && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3 px-6 pt-6 pb-2">
              <div className="p-2 bg-amber-100 rounded-full">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('annotation.unsavedTitle')}</h3>
            </div>
            <p className="px-6 py-3 text-sm text-gray-600 leading-relaxed">
              {t('annotation.unsavedMessage')}
            </p>
            <div className="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 border-t border-gray-100">
              <button
                onClick={() => setPendingNavigation(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={() => {
                  const nav = pendingNavigation
                  setPendingNavigation(null)
                  setHasUnsavedChanges(false)
                  nav()
                }}
                className="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 border border-red-200 rounded-lg hover:bg-red-100 transition-colors"
              >
                {t('annotation.discardAndLeave')}
              </button>
              <button
                onClick={async () => {
                  const saved = await handleManualSave()
                  if (!saved) return
                  const nav = pendingNavigation
                  setPendingNavigation(null)
                  nav()
                }}
                disabled={savingAnnotations}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {savingAnnotations && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {t('annotation.saveAndLeave')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
