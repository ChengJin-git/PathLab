import { useEffect, useState, useCallback, useRef, useMemo, type SyntheticEvent } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  fetchWSIDetail,
  fetchAvailableHeatmaps,
  fetchWSIList,
  fetchWSIIds,
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
import { Tooltip } from '../components/ui/tooltip'
import { ArrowLeft, Microscope, Layers, Loader2, ChevronLeft, ChevronRight, Plus, Minus, RotateCcw, Maximize2, X, Save, AlertTriangle, Keyboard, Move, Users } from 'lucide-react'
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
import { ShareAnnotationDialog } from '../components/wsiViewer/ShareAnnotationDialog'
import { ViewerOverlayControls } from '../components/wsiViewer/ViewerOverlayControls'
import { buildSlideNavigationTooltip, getAdjacentSlideIds, shouldPersistAnnotationsBeforeSlideNavigation } from '../lib/wsiViewerNavigation'
import { deriveAnnotationLabels, isMissingCurrentLabel } from '../lib/annotationLabels'
import { getLabelFromDigitShortcut, isEditableTarget } from '../lib/wsiViewerAnnotationShortcuts'
import {
  AnnotationRegion,
  AnnotationsMap,
  DatasetAnnotationSummaryResponse,
  saveAnnotation,
  listAnnotations,
  deleteAnnotation,
  getWSILabels,
  getDatasetAnnotationSummary,
  deleteDatasetAnnotationsByLabels,
  extractRegions,
  getSharedAnnotation,
  saveSharedAnnotation,
  getSharedAnnotationSSEUrl,
  SharedAnnotationEvent,
  listCollaborators,
  getMyAnnotationAccess,
} from '../api/annotation'
import { useToast } from '../contexts/ToastContext'
import { useAuth } from '../contexts/AuthContext'
import { useBackgroundTask } from '../contexts/BackgroundTaskContext'
import { getFileType } from '../constants/fileTypes'
import { isSegmentationTask, type TaskType } from '../constants/training'
import { ApiError, getAuthToken } from '../api/client'
import { API_BASE } from '../config'

import { usePresence, type AnnotationPatchEvent } from '../lib/usePresence'
import { PresenceCursorOverlay } from '../components/wsiViewer/PresenceCursorOverlay'

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
  chatScrollPosition?: string
  selectedTaskId?: string
  selectedFoldKey?: string
  initialShowHeatmap?: boolean
}

export default function WSIViewerPage() {
  const { t } = useTranslation()
  const { user } = useAuth()
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
  const chatScrollPosition = navigationState?.chatScrollPosition
  const preferredTaskId = navigationState?.selectedTaskId
  const preferredFoldKey = navigationState?.selectedFoldKey
  const initialShowHeatmap = navigationState?.initialShowHeatmap === true
  const [detail, setDetail] = useState<any>()
  const [showHeatmap, setShowHeatmap] = useState(false)
  const [showSegMask, setShowSegMask] = useState(false)
  const [heatmapOpacity, setHeatmapOpacity] = useState(0.5)
  const [segMaskOpacity, setSegMaskOpacity] = useState(0.5)

  // Navigation state
  const [allWSIs, setAllWSIs] = useState<WSISummary[]>([])
  const [orderedWsiIds, setOrderedWsiIds] = useState<string[]>([])

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
  const [showShortcuts, setShowShortcuts] = useState(false)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Shift' && !e.repeat) setShowShortcuts(prev => !prev)
    }
    const handleBlur = () => setShowShortcuts(false)

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('blur', handleBlur)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('blur', handleBlur)
    }
  }, [])

  // Annotation state
  const [annotationMode, setAnnotationMode] = useState(false)
  const [canAnnotate, setCanAnnotate] = useState(true)
  const [showGT, setShowGT] = useState(false)
  const [gtRegions, setGtRegions] = useState<AnnotationRegion[]>([])
  const [hasGTAnnotations, setHasGTAnnotations] = useState(false)
  const [drawingTool, setDrawingTool] = useState<'rect' | 'polygon'>('rect')
  const [currentLabel, setCurrentLabel] = useState('')
  const [rememberedLabelsByMode, setRememberedLabelsByMode] = useState<Record<'personal' | 'shared', string[]>>({
    personal: [],
    shared: [],
  })
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
  const immediateSharedSaveRef = useRef(false)
  const immediatePersonalSaveRef = useRef(false)
  const remoteAnnotationChangeRef = useRef(false)
  const locallyModifiedWsiIdsRef = useRef<Set<string>>(new Set())
  const keepaliveSaveRef = useRef({
    annotationMode: false,
    hasUnsavedChanges: false,
    editingMode: 'personal' as 'personal' | 'shared',
    allAnnotations: {} as AnnotationsMap,
    effectiveDatasetId: null as string | null | undefined,
    annotationId: null as string | null,
    sharedVersion: 0,
  })
  const [autoSeedConfirm, setAutoSeedConfirm] = useState<{
    draft: AnnotationsMap
    version: number
    sharedHasContent: boolean
  } | null>(null)
  const preloadedSharedAnnotationRef = useRef<{
    annotations: AnnotationsMap
    version: number
  } | null>(null)
  const [modeTransitioning, setModeTransitioning] = useState(false)
  const [showSharedExitDialog, setShowSharedExitDialog] = useState(false)
  const annotationIdRef = useRef<string | null>(null)
  const saveRequestRef = useRef<Promise<boolean> | null>(null)
  const slideNavRef = useRef({
    prevWsiId: null as string | null,
    nextWsiId: null as string | null,
    annotationMode: false,
    hasUnsavedChanges: false,
    persistAnnotations: null as ((opts?: { showToast?: boolean }) => Promise<boolean>) | null,
    isPatchLevel: false,
    handleManualSave: null as (() => Promise<boolean | undefined>) | null,
  })
  const patchKeysRef = useRef<Set<string>>(new Set())
  const patchRafRef = useRef<number | null>(null)
  const effectiveDatasetId = datasetId ?? detail?.meta?.dataset_id
  const draftCacheKey = effectiveDatasetId ?? '__NO_DATASET__'
  const draftCacheRef = useRef<{
    key: string
    draft: { annotation_id: string; annotations: AnnotationsMap } | null
  } | null>(null)
  const [datasetAnnotationSummary, setDatasetAnnotationSummary] = useState<DatasetAnnotationSummaryResponse | null>(null)
  const [loadingDatasetAnnotationSummary, setLoadingDatasetAnnotationSummary] = useState(false)

  // Collaborative Annotation State
  const [editingMode, setEditingMode] = useState<'personal' | 'shared'>('personal')
  const [sharedVersion, setSharedVersion] = useState(0)
  const [sharedSaving, setSharedSaving] = useState(false)
  const sharedVersionRef = useRef(0)
  const [isDatasetOwnerOrAdmin, setIsDatasetOwnerOrAdmin] = useState(false)
  const [showShareDialog, setShowShareDialog] = useState(false)
  useEffect(() => { sharedVersionRef.current = sharedVersion }, [sharedVersion])

  useEffect(() => {
    keepaliveSaveRef.current = {
      annotationMode,
      hasUnsavedChanges,
      editingMode,
      allAnnotations,
      effectiveDatasetId,
      annotationId,
      sharedVersion,
    }
  })

  // Manual save & unsaved-changes tracking
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [savingAnnotations, setSavingAnnotations] = useState(false)
  // Pending navigation when user tries to leave with unsaved changes
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null)
  const [annotationCancelToken, setAnnotationCancelToken] = useState(0)

  const handleRemoteAnnotationPatch = useCallback((event: AnnotationPatchEvent) => {
    if (editingMode !== 'shared') return
    remoteAnnotationChangeRef.current = true
    setAllAnnotations(prev => {
      const wsiRegions = prev[event.wsi_id] || []
      if (event.op === 'add' && event.region) {
        if (wsiRegions.some(r => r.id === event.region!.id)) return prev
        return { ...prev, [event.wsi_id]: [...wsiRegions, event.region] }
      } else if (event.op === 'update' && event.region_id && event.region_updates) {
        return { ...prev, [event.wsi_id]: wsiRegions.map(r => r.id === event.region_id ? { ...r, ...event.region_updates! } : r) }
      } else if (event.op === 'delete' && event.region_id) {
        return { ...prev, [event.wsi_id]: wsiRegions.filter(r => r.id !== event.region_id) }
      }
      return prev
    })
  }, [editingMode])

  const { cursors, sendCursor, sendAnnotationPatch } = usePresence(
    editingMode === 'shared' ? effectiveDatasetId : null,
    handleRemoteAnnotationPatch,
  )

  useEffect(() => {
    annotationIdRef.current = annotationId
  }, [annotationId])

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

  useEffect(() => {
    if (!effectiveDatasetId) {
      setCanAnnotate(true)
      return
    }
    getMyAnnotationAccess(effectiveDatasetId)
      .then(r => setCanAnnotate(r.can_annotate))
      .catch(() => setCanAnnotate(true))
  }, [effectiveDatasetId])

  useEffect(() => {
    let cancelled = false

    if (!fromDataset || !datasetId) {
      setOrderedWsiIds([])
      return () => {
        cancelled = true
      }
    }

    fetchWSIIds(datasetId)
      .then((res) => {
        if (!cancelled) {
          setOrderedWsiIds(res.items ?? [])
        }
      })
      .catch(() => {
        if (!cancelled) {
          setOrderedWsiIds([])
        }
      })

    return () => {
      cancelled = true
    }
  }, [fromDataset, datasetId])

  useEffect(() => {
    let cancelled = false
    const shouldLoadSummaryList = !fromDataset || (editingMode === 'shared' && showCreateDatasetDialog && !!datasetId)

    if (!shouldLoadSummaryList) {
      setAllWSIs([])
      return () => {
        cancelled = true
      }
    }

    fetchWSIList(fromDataset ? datasetId : undefined)
      .then((res) => {
        if (!cancelled) {
          setAllWSIs(res?.items ?? [])
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAllWSIs([])
        }
      })

    return () => {
      cancelled = true
    }
  }, [datasetId, editingMode, fromDataset, showCreateDatasetDialog])

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

  const isSelectedSegmentationTask = selectedTaskGroup.some(
    h => isSegmentationTask(h.task_type)
  )

  const effectiveFoldKey = isSelectedSegmentationTask ? undefined : selectedFoldKey

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
    h => isSegmentationTask(h.task_type)
  )
  const selectedTaskIsSegmentation = isSegmentationTask(selectedTask?.task_type)
  const hasPatchHeatmap = selectedTaskEntries.some(h => h.data_type === 'patch')
  const isPatchLevel = selectedTaskEntries.some(h => h.data_type === 'patch')
  const canShowHeatmapOverlay = selectedTaskEntries.some(h => h.data_type === 'wsi' || h.data_type === 'patch')
  const canShowSegMaskOverlay = selectedTaskEntries.some(h => isSegmentationTask(h.task_type))
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
    if (selectedTaskGroup.length === 0 || selectedTaskIsSegmentation) return []
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
  }, [selectedTaskGroup, selectedTaskIsSegmentation])

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

  useEffect(() => {
    if (!showGT || !wsi_id) {
      setGtRegions([])
      return
    }
    let cancelled = false
    getWSILabels(wsi_id).then(gt => {
      if (cancelled) return
      setGtRegions(gt.annotations[wsi_id] ?? [])
    }).catch(err => console.error('Failed to load GT:', err))
    return () => { cancelled = true }
  }, [showGT, wsi_id])

  useEffect(() => {
    setHasGTAnnotations(false)
    if (!wsi_id) return
    let cancelled = false
    getWSILabels(wsi_id).then(gt => {
      if (cancelled) return
      const regions = gt?.annotations?.[wsi_id] ?? []
      setHasGTAnnotations(regions.length > 0)
    }).catch(() => { if (!cancelled) setHasGTAnnotations(false) })
    return () => { cancelled = true }
  }, [wsi_id])

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
        opacity: segMaskOpacity,
      })
    }

    return layers
  }, [heatmapOpacity, segMaskOpacity, patchHeatmapPreviewUrl, patchSegMaskPreviewUrl, showHeatmap, showSegMask, t])

  const handleToggleHeatmap = useCallback(() => {
      setShowHeatmap(prev => {
      if (!prev) {
        setShowSegMask(false)
        setShowGT(false)
      }
      return !prev
    })
  }, [])

  const handleToggleSegMask = useCallback(() => {
      setShowSegMask(prev => {
      if (!prev) {
        setShowHeatmap(false)
        setShowGT(false)
      }
      return !prev
    })
  }, [])

  const handleToggleGT = useCallback(() => {
    setShowGT(prev => {
      if (!prev) {
        setShowHeatmap(false)
        setShowSegMask(false)
      }
      return !prev
    })
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

  const orderedNavigationIds = useMemo(() => {
    if (fromDataset) {
      return orderedWsiIds
    }

    return allWSIs.map((wsi) => wsi.wsi_id)
  }, [allWSIs, fromDataset, orderedWsiIds])

  const { previousId: prevWsiId, nextId: nextWsiId } = useMemo(
    () => getAdjacentSlideIds(orderedNavigationIds, wsi_id),
    [orderedNavigationIds, wsi_id],
  )

  // Annotation: computed values
  const currentRegions = useMemo(() => allAnnotations[wsi_id] || [], [allAnnotations, wsi_id])

  const overlayRegions = useMemo(
    () => (annotationMode ? currentRegions : showGT ? gtRegions : []),
    [annotationMode, currentRegions, showGT, gtRegions]
  )

  const overlayLabelColors = useMemo(() => {
    if (annotationMode) return labelColors
    if (!showGT || gtRegions.length === 0) return {}
    const colors: Record<string, string> = {}
    for (const r of gtRegions) {
      if (r.label && r.color && !colors[r.label]) colors[r.label] = r.color
    }
    return colors
  }, [annotationMode, labelColors, showGT, gtRegions])

  useEffect(() => {
    setFocusedRegionId(prev => prev && currentRegions.some(region => region.id === prev) ? prev : null)
  }, [currentRegions])

  const visibleLabels = useMemo(() => {
    return deriveAnnotationLabels(allAnnotations, rememberedLabelsByMode[editingMode] ?? [])
  }, [allAnnotations, editingMode, rememberedLabelsByMode])

  const allLabels = visibleLabels

  const missingCurrentLabel = useMemo(() => {
    return isMissingCurrentLabel(currentLabel, visibleLabels)
  }, [currentLabel, visibleLabels])

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

  const focusPatchRegion = useCallback((region: AnnotationRegion) => {
    if (slideWidth <= 0 || slideHeight <= 0) {
      return
    }

    const container = patchContainerRef.current
    if (!container) {
      return
    }

    const stackSide = Math.min(container.clientWidth, container.clientHeight, 600)
    if (stackSide <= 0) {
      return
    }

    const regionCenterX = region.x + region.width / 2
    const regionCenterY = region.y + region.height / 2
    const targetWidth = Math.max(region.width * FOCUS_REGION_PADDING_MULTIPLIER, slideWidth * 0.15)
    const targetHeight = Math.max(region.height * FOCUS_REGION_PADDING_MULTIPLIER, slideHeight * 0.15)
    const nextZoom = clamp(Math.min(slideWidth / targetWidth, slideHeight / targetHeight), 1, 10)

    const baseScale = Math.min(stackSide / slideWidth, stackSide / slideHeight)
    const renderedWidth = slideWidth * baseScale
    const renderedHeight = slideHeight * baseScale
    const renderedLeft = (stackSide - renderedWidth) / 2
    const renderedTop = (stackSide - renderedHeight) / 2
    const baseX = renderedLeft + regionCenterX * baseScale
    const baseY = renderedTop + regionCenterY * baseScale
    const centerX = stackSide / 2
    const centerY = stackSide / 2

    setPatchZoom(nextZoom)
    setPatchPan({
      x: -nextZoom * (baseX - centerX),
      y: -nextZoom * (baseY - centerY),
    })
  }, [slideHeight, slideWidth])

  const handleFocusRegion = useCallback((regionId: string) => {
    setFocusedRegionId(regionId)

    const region = currentRegions.find(item => item.id === regionId)
    if (!region || slideWidth <= 0 || slideHeight <= 0) {
      return
    }

    if (isPatchLevel) {
      focusPatchRegion(region)
      return
    }

    if (!osdViewer?.viewport || !window.OpenSeadragon) {
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
  }, [currentRegions, focusPatchRegion, isPatchLevel, osdViewer, slideHeight, slideWidth])

  const handleRegionCreated = useCallback((region: Omit<AnnotationRegion, 'id'>) => {
    const newRegion: AnnotationRegion = {
      ...region,
      id: crypto.randomUUID(),
      created_by: editingMode === 'shared' ? user?.id : undefined,
    }
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: [...(prev[wsi_id] || []), newRegion],
    }))
    setHasUnsavedChanges(true)
    if (editingMode === 'shared') {
      locallyModifiedWsiIdsRef.current.add(wsi_id)
      sendAnnotationPatch('add', wsi_id, { region: newRegion })
    }
    if (region.label) {
      setLabelColors(prev => {
        if (prev[region.label]) return prev
        return {
          ...prev,
          [region.label]: getColorForLabel(region.label, prev),
        }
      })
    }
  }, [wsi_id, editingMode, user?.id, sendAnnotationPatch])

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
    if (editingMode === 'shared') {
      locallyModifiedWsiIdsRef.current.add(wsi_id)
      sendAnnotationPatch('update', wsi_id, { region_id: regionId, region_updates: updates })
    }
  }, [wsi_id, editingMode, sendAnnotationPatch])

  const handleDeleteRegion = useCallback((regionId: string) => {
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: (prev[wsi_id] || []).filter(r => r.id !== regionId),
    }))
    if (editingMode === 'shared') {
      locallyModifiedWsiIdsRef.current.add(wsi_id)
      sendAnnotationPatch('delete', wsi_id, { region_id: regionId })
    } else {
      immediatePersonalSaveRef.current = true
    }
    setHasUnsavedChanges(true)
  }, [wsi_id, editingMode, sendAnnotationPatch])

  const handleDeleteRegions = useCallback((regionIds: string[]) => {
    const idSet = new Set(regionIds)
    setAllAnnotations(prev => ({
      ...prev,
      [wsi_id]: (prev[wsi_id] || []).filter(r => !idSet.has(r.id)),
    }))
    if (editingMode === 'shared') {
      locallyModifiedWsiIdsRef.current.add(wsi_id)
      for (const id of regionIds) {
        sendAnnotationPatch('delete', wsi_id, { region_id: id })
      }
    } else {
      immediatePersonalSaveRef.current = true
    }
    setHasUnsavedChanges(true)
  }, [wsi_id, editingMode, sendAnnotationPatch])

  const handleLabelChange = useCallback((label: string) => {
    setCurrentLabel(label)
    const trimmedLabel = label.trim()
    if (trimmedLabel) {
      setRememberedLabelsByMode(prev => {
        const labelsInMode = prev[editingMode]
        if (labelsInMode.includes(trimmedLabel)) return prev
        return {
          ...prev,
          [editingMode]: [...labelsInMode, trimmedLabel],
        }
      })
      setLabelColors(prev => {
        if (prev[trimmedLabel]) return prev
        return {
          ...prev,
          [trimmedLabel]: getColorForLabel(trimmedLabel, prev),
        }
      })
    }
  }, [editingMode])

  const handleCreateCurrentLabelInMode = useCallback(() => {
    const trimmed = currentLabel.trim()
    if (!trimmed) return
    setRememberedLabelsByMode(prev => {
      const labelsInMode = prev[editingMode]
      if (labelsInMode.includes(trimmed)) return prev
      return {
        ...prev,
        [editingMode]: [...labelsInMode, trimmed],
      }
    })
    setLabelColors(prev => {
      if (prev[trimmed]) return prev
      return {
        ...prev,
        [trimmed]: getColorForLabel(trimmed, prev),
      }
    })
  }, [currentLabel, editingMode])

  const requestAnnotationCancel = useCallback(() => {
    setAnnotationCancelToken(prev => prev + 1)
  }, [])

  const buildEmptyDatasetDraftAnnotations = useCallback((): AnnotationsMap => {
    if (Object.keys(allAnnotations).length > 0) {
      return allAnnotations
    }
    return wsi_id ? { [wsi_id]: [] } : {}
  }, [allAnnotations, wsi_id])

  const clearPendingSaveTimer = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
  }, [])

  const exitSharedMode = useCallback(() => {
    clearPendingSaveTimer()
    locallyModifiedWsiIdsRef.current.clear()
    setEditingMode('personal')
    setAllAnnotations({})
    setHasUnsavedChanges(false)
  }, [clearPendingSaveTimer])

  const saveShared = useCallback(async () => {
    if (!effectiveDatasetId) return false
    setSharedSaving(true)
    try {
      const response = await saveSharedAnnotation(effectiveDatasetId, {
        annotations: allAnnotations,
        version: sharedVersionRef.current,
      })
      setSharedVersion(response.version)
      setHasUnsavedChanges(false)
      locallyModifiedWsiIdsRef.current.clear()
      refreshDatasetAnnotationSummary()
      toast.success(t('annotation.saved'))
      return true
    } catch (err: any) {
      // 409 Conflict
      if (err instanceof ApiError && err.status === 409) {
        toast.warning(t('annotation.collab.versionConflict'))
        // Reload shared annotations
        try {
          const fresh = await getSharedAnnotation(effectiveDatasetId)
          if (fresh.annotations) {
            setAllAnnotations(fresh.annotations)
            mergeLabelColorsFromAnnotations(fresh.annotations)
          }
          setSharedVersion(fresh.version)
          // Conflict implies we lost our local changes unless we merge, but here we just reload for simplicity as per spec
          // "reloading and showing toast, updates sharedVersion"
          setHasUnsavedChanges(false)
        } catch (reloadErr) {
          console.error('Failed to reload after conflict:', reloadErr)
          toast.error(t('annotation.collab.reloadFailed'))
        }
      } else if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        console.error('Failed to save shared annotation (no permission):', err)
        toast.error(t('annotation.collab.saveFailedNoPermission'))
      } else {
        console.error('Failed to save shared annotation:', err)
        toast.error(t('annotation.collab.saveFailed'))
      }
      return false
    } finally {
      setSharedSaving(false)
    }
  }, [allAnnotations, effectiveDatasetId, refreshDatasetAnnotationSummary, t, toast, mergeLabelColorsFromAnnotations])

  const persistAnnotations = useCallback(async ({
    showToast = true,
  }: {
    showToast?: boolean
  } = {}) => {
    clearPendingSaveTimer()

    if (saveRequestRef.current) {
      const saved = await saveRequestRef.current
      if (showToast) {
        if (saved) {
          toast.success(t('annotation.saved'))
        } else {
          toast.error(t('annotation.saveFailed'))
        }
      }
      return saved
    }

    const savePromise = (async () => {
      setSavingAnnotations(true)
      try {
        const totalRegions = Object.values(allAnnotations).reduce((sum, r) => sum + r.length, 0)
        const currentAnnotationId = annotationIdRef.current

        if (totalRegions === 0) {
          if (effectiveDatasetId) {
            const id = currentAnnotationId || crypto.randomUUID()
            const emptyDatasetDraft = buildEmptyDatasetDraftAnnotations()
            if (!currentAnnotationId) {
              annotationIdRef.current = id
              setAnnotationId(id)
            }
            await saveAnnotation({
              annotation_id: id,
              source_dataset_id: effectiveDatasetId,
              annotations: emptyDatasetDraft,
            })
            updateDraftCache(id, emptyDatasetDraft)
          } else if (currentAnnotationId) {
            annotationIdRef.current = null
            setAnnotationId(null)
            await deleteAnnotation(currentAnnotationId)
            updateDraftCache(null, null)
          } else {
            setHasUnsavedChanges(false)
            return true
          }
        } else {
          const id = currentAnnotationId || crypto.randomUUID()
          if (!currentAnnotationId) {
            annotationIdRef.current = id
            setAnnotationId(id)
          }
          await saveAnnotation({
            annotation_id: id,
            source_dataset_id: effectiveDatasetId,
            annotations: allAnnotations,
          })
          updateDraftCache(id, allAnnotations)
        }

        setHasUnsavedChanges(false)
        if (effectiveDatasetId) {
          void refreshDatasetAnnotationSummary()
        }
        if (showToast) {
          toast.success(t('annotation.saved'))
        }
        return true
      } catch (err) {
        console.error('Failed to save annotation:', err)
        if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
          setHasUnsavedChanges(false)
        }
        if (showToast) {
          toast.error(t('annotation.saveFailed'))
        }
        return false
      } finally {
        saveRequestRef.current = null
        setSavingAnnotations(false)
      }
    })()

    saveRequestRef.current = savePromise
    return await savePromise
  }, [allAnnotations, buildEmptyDatasetDraftAnnotations, clearPendingSaveTimer, effectiveDatasetId, refreshDatasetAnnotationSummary, t, toast, updateDraftCache])

  // Manual save handler
  const handleManualSave = useCallback(async () => {
    if (editingMode === 'shared') {
      return await saveShared()
    }
    return await persistAnnotations({ showToast: true })
  }, [editingMode, persistAnnotations, saveShared])

  const handleToggleEditingMode = useCallback(async () => {
    if (editingMode === 'personal') {
      if (hasUnsavedChanges) {
        const saved = await persistAnnotations({ showToast: false })
        if (!saved) return
      }
      if (!effectiveDatasetId) {
        setEditingMode('shared')
        return
      }
      setModeTransitioning(true)
      let sharedRes: Awaited<ReturnType<typeof getSharedAnnotation>>
      try {
        sharedRes = await getSharedAnnotation(effectiveDatasetId)
      } catch (err) {
        console.error('Failed to pre-check shared annotations:', err)
        setModeTransitioning(false)
        setEditingMode('shared')
        return
      }
      const personalHasContent = Object.values(allAnnotations).some(
        (v) => Array.isArray(v) && v.length > 0
      )
      const sharedHasContent =
        !!sharedRes.annotations &&
        Object.values(sharedRes.annotations).some((v) => Array.isArray(v) && v.length > 0)
      preloadedSharedAnnotationRef.current = {
        annotations: sharedRes.annotations ?? {},
        version: sharedRes.version,
      }
      setModeTransitioning(false)
      if (personalHasContent) {
        setAutoSeedConfirm({ draft: allAnnotations, version: sharedRes.version, sharedHasContent })
        return
      }
      setEditingMode('shared')
    } else {
      const sharedHasContent = Object.values(allAnnotations).some(
        (v) => Array.isArray(v) && v.length > 0
      )
      if (!sharedHasContent) {
        exitSharedMode()
        return
      }
      setShowSharedExitDialog(true)
    }
  }, [editingMode, hasUnsavedChanges, persistAnnotations, allAnnotations, effectiveDatasetId, exitSharedMode])

  const handleAutoSeedConfirm = useCallback(async (usePersonalDraft: boolean) => {
    if (!autoSeedConfirm || !effectiveDatasetId) { setAutoSeedConfirm(null); return }
    const { draft, version } = autoSeedConfirm
    setAutoSeedConfirm(null)

    if (usePersonalDraft) {
      preloadedSharedAnnotationRef.current = null
      setSharedSaving(true)
      try {
        const saved = await saveSharedAnnotation(effectiveDatasetId, { version, annotations: draft })
        preloadedSharedAnnotationRef.current = { annotations: draft, version: saved.version }
        toast.info(t('annotation.collab.autoSeeded'))
      } catch (err: any) {
        if (err instanceof ApiError && err.status === 409) {
          const fresh = await getSharedAnnotation(effectiveDatasetId)
          preloadedSharedAnnotationRef.current = { annotations: fresh.annotations, version: fresh.version }
        }
      } finally {
        setSharedSaving(false)
      }
    }
    setEditingMode('shared')
  }, [autoSeedConfirm, effectiveDatasetId, t, toast])

  const handleSharedExitChoice = useCallback((importToPersonal: boolean) => {
    setShowSharedExitDialog(false)
    if (importToPersonal && isDatasetOwnerOrAdmin) {
      clearPendingSaveTimer()
      locallyModifiedWsiIdsRef.current.clear()
      draftCacheRef.current = null
      setEditingMode('personal')
      setHasUnsavedChanges(true)
    } else {
      exitSharedMode()
    }
  }, [clearPendingSaveTimer, exitSharedMode, isDatasetOwnerOrAdmin])

  const handleDeleteCrossSlideByLabel = useCallback(async (labels: string[]) => {
    const labelSet = new Set(labels)

    if (editingMode === 'shared') {
      for (const slideId of Object.keys(allAnnotations)) {
        locallyModifiedWsiIdsRef.current.add(slideId)
      }
      setAllAnnotations(prev => {
        const next: typeof prev = {}
        for (const [key, regions] of Object.entries(prev)) {
          next[key] = regions.filter(r => !labelSet.has(r.label))
        }
        return next
      })
      immediateSharedSaveRef.current = true
      setHasUnsavedChanges(true)
      return
    }

    if (!effectiveDatasetId) {
      setAllAnnotations(prev => {
        const next: typeof prev = {}
        for (const [key, regions] of Object.entries(prev)) {
          next[key] = regions.filter(r => !labelSet.has(r.label))
        }
        return next
      })
      immediatePersonalSaveRef.current = true
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
      const filteredAnnotations: AnnotationsMap = {}
      for (const [key, regions] of Object.entries(allAnnotations)) {
        filteredAnnotations[key] = regions.filter(r => !labelSet.has(r.label))
      }
      updateDraftCache(result.annotation_id, filteredAnnotations)
      setDatasetAnnotationSummary(result.summary)
      setAllAnnotations(filteredAnnotations)
      setHasUnsavedChanges(false)
      toast.success(t('annotation.saved'))
    } catch (err) {
      console.error('Failed to delete dataset annotations by labels:', err)
      toast.error(t('annotation.saveFailed'))
    }
  }, [allAnnotations, editingMode, effectiveDatasetId, handleManualSave, hasUnsavedChanges, t, toast, updateDraftCache])

  const handleCreateDatasetFromAnnotations = useCallback(async ({
    datasetName,
    taskType,
    sourceOrgan,
  }: {
    datasetName: string
    taskType: TaskType
    sourceOrgan: string
  }) => {
    try {
      if (effectiveDatasetId && hasUnsavedChanges) {
        const saved = await handleManualSave()
        if (!saved) return
      }

      const result = await extractRegions({
        annotation_id: annotationId || undefined,
        annotations: effectiveDatasetId ? undefined : allAnnotations,
        dataset_name: datasetName,
        task_type: taskType,
        source_organ: sourceOrgan || undefined,
        ...(effectiveDatasetId ? { source_dataset_id: effectiveDatasetId, dataset_scope: true, annotation_mode: editingMode } : {}),
      })

      addExtractionTask(result.task_id, datasetName)
      toast.success(t('annotation.extractSubmitted'))
    } catch (err: any) {
      toast.error(err?.message || t('annotation.extractFailed'))
      throw err
    }
  }, [addExtractionTask, allAnnotations, annotationId, editingMode, effectiveDatasetId, handleManualSave, hasUnsavedChanges, t, toast])

  useEffect(() => {
    if (editingMode !== 'shared' || !effectiveDatasetId) return

    let cancelled = false

    const preloaded = preloadedSharedAnnotationRef.current
    preloadedSharedAnnotationRef.current = null

    if (preloaded) {
      setAllAnnotations(preloaded.annotations)
      if (Object.keys(preloaded.annotations).length > 0) {
        mergeLabelColorsFromAnnotations(preloaded.annotations)
      }
      setSharedVersion(preloaded.version)
      setHasUnsavedChanges(false)

      listCollaborators(effectiveDatasetId).catch(() => null).then(collabRes => {
        if (cancelled) return
        if (collabRes) {
          const isAdmin = user?.role === 'admin'
          const isOwner = collabRes.members.some(m => m.role === 'owner' && m.user_id === user?.id)
          setIsDatasetOwnerOrAdmin(isAdmin || isOwner)
        } else {
          setIsDatasetOwnerOrAdmin(user?.role === 'admin')
        }
      })

      return () => { cancelled = true }
    }

    setSharedSaving(true)

    Promise.all([
      getSharedAnnotation(effectiveDatasetId),
      listCollaborators(effectiveDatasetId).catch(() => null),
    ]).then(([res, collabRes]) => {
      if (cancelled) return

      const sharedContent = res.annotations ?? {}
      setAllAnnotations(sharedContent)
      if (Object.keys(sharedContent).length > 0) {
        mergeLabelColorsFromAnnotations(sharedContent)
      }
      setSharedVersion(res.version)
      setHasUnsavedChanges(false)

      if (collabRes) {
        const isAdmin = user?.role === 'admin'
        const isOwner = collabRes.members.some(m => m.role === 'owner' && m.user_id === user?.id)
        setIsDatasetOwnerOrAdmin(isAdmin || isOwner)
      } else {
        setIsDatasetOwnerOrAdmin(user?.role === 'admin')
      }
    }).catch(err => {
      if (cancelled) return
      console.error('Failed to load shared annotations:', err)
      if (err instanceof ApiError && (err.status === 403 || err.status === 401)) {
        toast.error(t('annotation.collab.sharedLoadFailedNoPermission'))
      } else {
        toast.error(t('annotation.collab.sharedLoadFailed'))
      }
      exitSharedMode()
    }).finally(() => {
      if (!cancelled) setSharedSaving(false)
    })

    return () => { cancelled = true }
  }, [editingMode, effectiveDatasetId, exitSharedMode, mergeLabelColorsFromAnnotations, t, toast, user?.id, user?.role])

  // Collaborative Mode: SSE
  useEffect(() => {
    if (editingMode !== 'shared' || !effectiveDatasetId) return

    const url = getSharedAnnotationSSEUrl(effectiveDatasetId)
    if (!url) return

    const es = new EventSource(url)

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as SharedAnnotationEvent
        if (data.type === 'updated') {
          if (data.version > sharedVersionRef.current) {
            if (data.annotations) {
              if (locallyModifiedWsiIdsRef.current.size > 0) {
                const localModified = new Set(locallyModifiedWsiIdsRef.current)
                setAllAnnotations(prev => {
                  const merged = { ...data.annotations }
                  for (const wsiId of localModified) {
                    if (Object.prototype.hasOwnProperty.call(prev, wsiId)) {
                      merged[wsiId] = prev[wsiId]
                    }
                  }
                  return merged
                })
              } else {
                setAllAnnotations(data.annotations)
              }
              mergeLabelColorsFromAnnotations(data.annotations)
              setSharedVersion(data.version)
            } else {
              getSharedAnnotation(effectiveDatasetId).then(res => {
                if (locallyModifiedWsiIdsRef.current.size > 0) {
                  const localModified = new Set(locallyModifiedWsiIdsRef.current)
                  setAllAnnotations(prev => {
                    const merged = { ...res.annotations }
                    for (const wsiId of localModified) {
                      if (Object.prototype.hasOwnProperty.call(prev, wsiId)) {
                        merged[wsiId] = prev[wsiId]
                      }
                    }
                    return merged
                  })
                } else {
                  setAllAnnotations(res.annotations)
                }
                mergeLabelColorsFromAnnotations(res.annotations)
                setSharedVersion(res.version)
              })
            }
          }
        } else if (data.type === 'finalized') {
           toast.success(t('annotation.collab.submitted'))
           exitSharedMode()
           setShowGT(true)
        } else if (data.type === 'collaborator_removed') {
           if (data.user_id === user?.id) {
             if (hasUnsavedChanges) {
               toast.warning(t('annotation.collab.removedUnsavedLost'))
             } else {
               toast.warning(t('annotation.collab.removedFromCollaborators'))
             }
             exitSharedMode()
             setAnnotationMode(false)
             setCanAnnotate(false)
           }
        } else if (data.type === 'shared_deleted') {
           toast.warning(t('annotation.collab.sharedDeletedRemote'))
           exitSharedMode()
        } else if (data.type === 'gt_updated') {
           toast.info(t('annotation.collab.gtUpdated'))
        } else if (data.type === 'gt_deleted') {
           toast.info(t('annotation.collab.gtDeleted'))
        }
      } catch (e) {
        console.error('SSE Parse Error', e)
      }
    }

    return () => {
      es.close()
    }
  }, [editingMode, effectiveDatasetId, exitSharedMode, hasUnsavedChanges, user?.id, mergeLabelColorsFromAnnotations, t, toast])

  useEffect(() => {
    slideNavRef.current.prevWsiId = prevWsiId
    slideNavRef.current.nextWsiId = nextWsiId
    slideNavRef.current.annotationMode = annotationMode
    slideNavRef.current.hasUnsavedChanges = hasUnsavedChanges
    slideNavRef.current.persistAnnotations = persistAnnotations
    slideNavRef.current.isPatchLevel = isPatchLevel
    slideNavRef.current.handleManualSave = handleManualSave
  })

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.code !== 'KeyS') return
      e.preventDefault()
      if (slideNavRef.current.annotationMode) {
        slideNavRef.current.handleManualSave?.()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  useEffect(() => {
    const PAN_STEP = 5

    const animatePatchPan = () => {
      const keys = patchKeysRef.current
      let dx = 0, dy = 0
      if (keys.has('KeyW')) dy -= PAN_STEP
      if (keys.has('KeyS')) dy += PAN_STEP
      if (keys.has('KeyA')) dx -= PAN_STEP
      if (keys.has('KeyD')) dx += PAN_STEP
      if (dx !== 0 || dy !== 0) {
        setPatchPan(prev => ({ x: prev.x + dx, y: prev.y + dy }))
        patchRafRef.current = requestAnimationFrame(animatePatchPan)
      } else {
        patchRafRef.current = null
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (!slideNavRef.current.isPatchLevel) return
      if (isEditableTarget(document.activeElement)) return
      if (e.ctrlKey || e.metaKey || e.altKey) return

      const wasdCodes = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD'])
      if (wasdCodes.has(e.code)) {
        e.preventDefault()
        patchKeysRef.current.add(e.code)
        if (patchRafRef.current === null) {
          patchRafRef.current = requestAnimationFrame(animatePatchPan)
        }
        return
      }

      if (e.code === 'Equal') {
        e.preventDefault()
        setPatchZoom(prev => Math.min(prev * 1.3, 10))
      } else if (e.code === 'Minus') {
        e.preventDefault()
        setPatchZoom(prev => Math.max(prev / 1.3, 0.5))
      } else if (e.code === 'KeyR') {
        e.preventDefault()
        setPatchZoom(1)
        setPatchPan({ x: 0, y: 0 })
      } else if (e.code === 'KeyF') {
        e.preventDefault()
        if (document.fullscreenElement) {
          document.exitFullscreen()
        } else {
          patchContainerRef.current?.requestFullscreen()
        }
      }
    }

    const handleKeyUp = (e: KeyboardEvent) => {
      patchKeysRef.current.delete(e.code)
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
      if (patchRafRef.current !== null) {
        cancelAnimationFrame(patchRafRef.current)
        patchRafRef.current = null
      }
      patchKeysRef.current.clear()
    }
  }, [])

  useEffect(() => {
    const handleKeyDown = async (e: KeyboardEvent) => {
      if (isEditableTarget(document.activeElement)) return
      if (e.ctrlKey || e.metaKey || e.altKey) return

      const { prevWsiId: prev, nextWsiId: next, annotationMode: inAnnotation, hasUnsavedChanges: unsaved, persistAnnotations: persist } = slideNavRef.current

      if (e.code === 'KeyQ' && prev) {
        e.preventDefault()
        if (shouldPersistAnnotationsBeforeSlideNavigation(inAnnotation, unsaved) && persist) {
          await persist({ showToast: false })
        }
        navigate(`/wsi/${prev}`, {
          state: { fromAIChat, fromDataset, datasetId, datasetName, conversationId, chatScrollPosition },
        })
      } else if (e.code === 'KeyE' && next) {
        e.preventDefault()
        if (shouldPersistAnnotationsBeforeSlideNavigation(inAnnotation, unsaved) && persist) {
          await persist({ showToast: false })
        }
        navigate(`/wsi/${next}`, {
          state: { fromAIChat, fromDataset, datasetId, datasetName, conversationId, chatScrollPosition },
        })
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [navigate, fromAIChat, fromDataset, datasetId, datasetName, conversationId, chatScrollPosition])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!annotationMode) return
      if (e.ctrlKey || e.metaKey || e.altKey || e.shiftKey) return
      if (isEditableTarget(document.activeElement)) return

      if (e.code === 'Escape') {
        e.preventDefault()
        requestAnnotationCancel()
        return
      }

      const nextLabel = getLabelFromDigitShortcut(e.code, visibleLabels, e.key)
      if (nextLabel) {
        e.preventDefault()
        handleLabelChange(nextLabel)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [annotationMode, handleLabelChange, requestAnnotationCancel, visibleLabels])

  const guardedNavigate = useCallback((navigateFn: () => void) => {
    if (shouldPersistAnnotationsBeforeSlideNavigation(annotationMode, hasUnsavedChanges)) {
      setPendingNavigation(() => navigateFn)
    } else {
      navigateFn()
    }
  }, [hasUnsavedChanges, annotationMode])

  useEffect(() => {
    if (!annotationMode) return
    if (!hasUnsavedChanges) return
    if (editingMode === 'shared' ? sharedSaving : savingAnnotations) return
    if (remoteAnnotationChangeRef.current) {
      remoteAnnotationChangeRef.current = false
      return
    }

    clearPendingSaveTimer()

    if (editingMode === 'shared') {
      const isImmediate = immediateSharedSaveRef.current
      immediateSharedSaveRef.current = false
      saveTimerRef.current = setTimeout(async () => {
        saveTimerRef.current = null
        await saveShared()
      }, isImmediate ? 0 : 2000)
    } else {
      const isImmediatePersonal = immediatePersonalSaveRef.current
      immediatePersonalSaveRef.current = false
      const totalRegions = Object.values(allAnnotations).reduce((sum, r) => sum + r.length, 0)

      if (totalRegions === 0) {
        if (effectiveDatasetId || annotationIdRef.current) {
          saveTimerRef.current = setTimeout(async () => {
            saveTimerRef.current = null
            await persistAnnotations({ showToast: false })
          }, isImmediatePersonal ? 0 : 2000)
        } else {
          setHasUnsavedChanges(false)
        }
        return
      }

      saveTimerRef.current = setTimeout(async () => {
        saveTimerRef.current = null
        await persistAnnotations({ showToast: false })
      }, isImmediatePersonal ? 0 : 2000)
    }

    return () => {
      clearPendingSaveTimer()
    }
  }, [allAnnotations, annotationMode, clearPendingSaveTimer, effectiveDatasetId, hasUnsavedChanges, persistAnnotations, savingAnnotations, editingMode, sharedSaving, saveShared])

  // Annotation: recovery when entering annotation mode
  useEffect(() => {
    if (!annotationMode) return
    if (editingMode === 'shared') return
    if (!datasetId && !detail) return
    // Recover per current WSI instead of blocking on any previously loaded slide.
    // If the current key exists (even with an empty array), treat it as already loaded.
    if (Object.prototype.hasOwnProperty.call(allAnnotations, wsi_id)) return

    let cancelled = false

    const recoverAnnotations = async () => {
      try {
        let matching = draftCacheRef.current?.key === draftCacheKey
          ? draftCacheRef.current?.draft ?? null
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
      } catch (err) {
        console.error('Failed to recover annotation:', err)
      }
    }

    recoverAnnotations()

    return () => {
      cancelled = true
    }
  }, [annotationMode, editingMode, allAnnotations, datasetId, detail, draftCacheKey, effectiveDatasetId, mergeLabelColorsFromAnnotations, wsi_id])

  useEffect(() => {
    const handler = () => {
      const s = keepaliveSaveRef.current
      if (!s.annotationMode || !s.hasUnsavedChanges) return
      const token = getAuthToken()
      if (!token) return

      if (s.editingMode === 'shared' && s.effectiveDatasetId) {
        fetch(`${API_BASE}/annotation/datasets/${encodeURIComponent(s.effectiveDatasetId)}/shared`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({ annotations: s.allAnnotations, version: s.sharedVersion }),
          keepalive: true,
        }).catch(() => {})
      } else {
        const totalRegions = Object.values(s.allAnnotations).reduce((sum, r) => sum + r.length, 0)
        if (totalRegions === 0) return
        const id = s.annotationId || crypto.randomUUID()
        fetch(`${API_BASE}/annotation/drafts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
          body: JSON.stringify({
            annotation_id: id,
            annotations: s.allAnnotations,
            ...(s.effectiveDatasetId ? { source_dataset_id: s.effectiveDatasetId } : {}),
          }),
          keepalive: true,
        }).catch(() => {})
      }
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

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
            type="button"
            onClick={() => guardedNavigate(() => {
              if (fromAIChat) {
                if (conversationId) {
                  sessionStorage.setItem('ai-chat-conversation-id', conversationId)
                }
                if (chatScrollPosition) {
                  sessionStorage.setItem('ai-chat-scroll-position', chatScrollPosition)
                }
                navigate(conversationId ? `/dashboard/${conversationId}` : '/dashboard')
              } else if (fromDataset && datasetId) {
                navigate('/wsi-list', { state: { dataset_id: datasetId } })
              } else {
                navigate('/wsi-list')
              }
            })}
            className="flex items-center gap-1 sm:gap-2 rounded-full border border-transparent px-2.5 py-1.5 text-xs font-medium text-slate-500 transition-all hover:border-white/10 hover:bg-white/6 hover:text-white sm:px-3 sm:py-2 sm:text-sm"
          >
            <ArrowLeft className="w-4 h-4" />
            <span className="hidden sm:inline">
              {fromAIChat ? t('wsiViewer.backToChat') : fromDataset && datasetName ? t('wsiViewer.backToDataset', { name: datasetName }) : t('common.back')}
            </span>
          </button>
          <div className="h-6 w-px bg-white/10"></div>

          <div className="flex items-center gap-2 flex-1 min-w-0">
            <h3 className="flex items-center gap-2 truncate text-sm font-semibold tracking-[-0.02em] text-white sm:text-base" title={`UUID: ${wsi_id}`}>
              <Microscope className="h-3.5 w-3.5 text-secondary-300 sm:h-4 sm:w-4" />
              <span className="truncate">{meta?.original_filename || wsi_id}</span>
            </h3>
          </div>

          <div className="flex items-center gap-1 sm:gap-2">
            <div className="flex items-center gap-1 rounded-[1rem] border border-white/10 p-1">
              <Tooltip content={buildSlideNavigationTooltip({
                direction: 'previous',
                hasTarget: !!prevWsiId,
                shortcut: 'Q',
                labels: {
                  previousSlide: t('wsiViewer.previousSlide'),
                  nextSlide: t('wsiViewer.nextSlide'),
                  noPreviousSlide: t('wsiViewer.noPreviousSlide'),
                  noNextSlide: t('wsiViewer.noNextSlide'),
                },
              })}>
              <button
                type="button"
                onClick={() => prevWsiId && guardedNavigate(() => navigate(`/wsi/${prevWsiId}`, {
                  state: {
                    fromAIChat,
                    fromDataset,
                    datasetId,
                    datasetName,
                    conversationId,
                    chatScrollPosition,
                  }
                }))}
                disabled={!prevWsiId}
                className="relative flex items-center justify-center rounded-[0.85rem] p-1.5 text-slate-300 outline-none transition-all hover:bg-white/8 hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent sm:p-2"
              >
                <ChevronLeft className="w-4 h-4 sm:w-5 sm:h-5" />
                {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">Q</kbd>}
              </button>
              </Tooltip>
              <div className="mx-0.5 h-5 w-px bg-white/10"></div>
              <Tooltip content={buildSlideNavigationTooltip({
                direction: 'next',
                hasTarget: !!nextWsiId,
                shortcut: 'E',
                labels: {
                  previousSlide: t('wsiViewer.previousSlide'),
                  nextSlide: t('wsiViewer.nextSlide'),
                  noPreviousSlide: t('wsiViewer.noPreviousSlide'),
                  noNextSlide: t('wsiViewer.noNextSlide'),
                },
              })}>
              <button
                type="button"
                onClick={() => nextWsiId && guardedNavigate(() => navigate(`/wsi/${nextWsiId}`, {
                  state: {
                    fromAIChat,
                    fromDataset,
                    datasetId,
                    datasetName,
                    conversationId,
                    chatScrollPosition,
                  }
                }))}
                disabled={!nextWsiId}
                className="relative flex items-center justify-center rounded-[0.85rem] p-1.5 text-slate-300 outline-none transition-all hover:bg-white/8 hover:text-white disabled:cursor-not-allowed disabled:opacity-30 disabled:hover:bg-transparent sm:p-2"
              >
                <ChevronRight className="w-4 h-4 sm:w-5 sm:h-5" />
                {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">E</kbd>}
              </button>
              </Tooltip>
            </div>

            {canAnnotate && (
              <>
                <div className="h-5 w-px bg-white/10" />
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
                  visibleLabels={visibleLabels}
                  missingCurrentLabel={missingCurrentLabel}
                  onCreateCurrentLabelInMode={handleCreateCurrentLabelInMode}
                  onDropdownOpenChange={setIsLabelDropdownOpen}
                  editingMode={editingMode}
                  onToggleEditingMode={handleToggleEditingMode}
                  modeTransitioning={modeTransitioning}
                  sharedSaving={sharedSaving}
                  hasDatasetContext={!!effectiveDatasetId}
                  isDatasetOwnerOrAdmin={isDatasetOwnerOrAdmin}
                  onShareManage={() => setShowShareDialog(true)}
                />

                {/* Save Annotations Button — visible only in annotation mode */}
                {annotationMode && (
                  <Tooltip content={t('annotation.saveAnnotations')}>
                  <button
                    type="button"
                    onClick={handleManualSave}
                    disabled={savingAnnotations || !hasUnsavedChanges}
                    className={`flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs font-medium transition-all sm:px-3 sm:py-2 sm:text-sm ${
                      hasUnsavedChanges
                        ? 'border border-primary-400/80 bg-primary-500 text-white shadow-[0_18px_32px_rgba(59,130,246,0.35)] hover:bg-primary-400'
                        : 'border border-white/10 bg-white/6 text-slate-400 cursor-default'
                    }`}
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
                  </Tooltip>
                )}
              </>
            )}

            <button
              type="button"
              onClick={() => setIsSidebarOpen(!isSidebarOpen)}
              className={`lg:hidden rounded-full border p-2 ${isSidebarOpen ? 'border-primary-400/60 bg-primary-500/15 text-primary-100' : 'border-white/10 bg-white/6 text-slate-300 shadow-[0_16px_32px_rgba(15,23,42,0.28)]'}`}
            >
              <Layers className="w-4 h-4" />
            </button>
          </div>
        </div>
        <div
          className="relative flex-1 overflow-hidden bg-[#050814]"
          role="application"
          tabIndex={-1}
          onMouseMove={(e) => {
            if (editingMode !== 'shared' || !osdViewer?.viewport || !wsi_id) return
            const canvas = osdViewer.canvas?.element || osdViewer.canvas
            if (!canvas) return
            const rect = (canvas as HTMLElement).getBoundingClientRect?.()
            if (!rect) return
            const pt = osdViewer.viewport.pointFromPixel(
              new (window as any).OpenSeadragon.Point(e.clientX - rect.left, e.clientY - rect.top)
            )
            if (pt) sendCursor(wsi_id, pt.x, pt.y)
          }}
        >
          {/* Conditional Viewer: WSI Viewer for WSI-level, Patch Viewer for patch-level results */}
          {isPatchLevel ? (
            // Patch-level heatmap viewer with zoom/pan controls
            // Note: wheel event is handled via useEffect with { passive: false } to allow preventDefault
            <div
              ref={patchContainerRef}
              className="flex h-full w-full items-center justify-center overflow-hidden bg-[#050814]"
              role="application"
              tabIndex={-1}
              onMouseDown={handlePatchMouseDown}
              onMouseMove={handlePatchMouseMove}
              onMouseUp={handlePatchMouseUp}
              onMouseLeave={handlePatchMouseLeave}
              style={{ cursor: patchZoom > 1 ? (isPanning ? 'grabbing' : 'grab') : 'default' }}
            >
              <div
                className="absolute top-4 left-4 z-30 flex flex-col items-start gap-2"
              >
                <div role="presentation" className="flex items-center rounded-[1rem] border border-white/10 bg-slate-950/78 p-1 shadow-[0_20px_44px_rgba(2,6,23,0.55)] backdrop-blur-2xl">
                  <Tooltip content={`${t('wsiViewerComponents.viewer.zoomIn')} (=)`}>
                  <button
                    type="button"
                    onClick={handlePatchZoomIn}
                    className="relative flex h-9 w-9 items-center justify-center rounded-[0.85rem] text-slate-300 outline-none transition-all active:scale-95 hover:bg-white/8 hover:text-white"
                  >
                    <Plus className="w-4 h-4" />
                    {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">=</kbd>}
                  </button>
                  </Tooltip>
                  <Tooltip content={`${t('wsiViewerComponents.viewer.zoomOut')} (-)`}>
                  <button
                    type="button"
                    onClick={handlePatchZoomOut}
                    className="relative flex h-9 w-9 items-center justify-center rounded-[0.85rem] text-slate-300 outline-none transition-all active:scale-95 hover:bg-white/8 hover:text-white"
                  >
                    <Minus className="w-4 h-4" />
                    {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">-</kbd>}
                  </button>
                  </Tooltip>
                  <div className="mx-0.5 h-5 w-px bg-white/10" />
                  <Tooltip content={`${t('wsiViewerComponents.viewer.resetView')} (R)`}>
                  <button
                    type="button"
                    onClick={handlePatchReset}
                    className="relative flex h-9 w-9 items-center justify-center rounded-[0.85rem] text-slate-300 outline-none transition-all active:scale-95 hover:bg-white/8 hover:text-white"
                  >
                    <RotateCcw className="w-4 h-4" />
                    {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">R</kbd>}
                  </button>
                  </Tooltip>
                  <Tooltip content={`${t('wsiViewerComponents.viewer.fullScreen')} (F)`}>
                  <button
                    type="button"
                    onClick={handlePatchFullscreen}
                    className="relative flex h-9 w-9 items-center justify-center rounded-[0.85rem] text-slate-300 outline-none transition-all active:scale-95 hover:bg-white/8 hover:text-white"
                  >
                    <Maximize2 className="w-4 h-4" />
                    {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">F</kbd>}
                  </button>
                  </Tooltip>
                  <div className="mx-0.5 h-5 w-px bg-white/10" />
                  <div
                    role="note"
                    className="hidden cursor-help items-center gap-1.5 px-2 py-1 text-slate-400 transition-colors hover:text-slate-200 sm:flex"
                    title={t('wsiViewerComponents.viewer.holdShiftHint')}
                  >
                    <Keyboard className="w-4 h-4" />
                    <span className="text-[10px] font-medium leading-none">Shift</span>
                  </div>
                </div>

                {showShortcuts && (
                  <div className="pointer-events-none flex select-none items-center gap-2 rounded-xl border border-white/10 bg-slate-950/78 px-2.5 py-1.5 shadow-[0_20px_44px_rgba(2,6,23,0.55)] backdrop-blur-2xl animate-in fade-in zoom-in-95 duration-200">
                    <Move className="h-3.5 w-3.5 flex-shrink-0 text-slate-400" />
                    <div className="flex items-center gap-1">
                      {['W', 'A', 'S', 'D'].map(k => (
                        <kbd key={k} className="flex min-w-[20px] items-center justify-center rounded border border-white/10 bg-white/8 text-[11px] font-mono font-bold text-slate-200 shadow-sm h-[20px]">{k}</kbd>
                      ))}
                    </div>
                    <span className="text-[11px] font-medium text-slate-400">{t('wsiViewerComponents.viewer.panHint')}</span>
                  </div>
                )}
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
                regions={overlayRegions}
                labelColors={overlayLabelColors}
                highlightedRegionId={focusedRegionId}
                slideWidth={slideWidth}
                slideHeight={slideHeight}
                annotationMode={annotationMode}
                drawingTool={drawingTool}
                currentLabel={currentLabel}
                currentColor={currentColor}
                onRegionCreated={handleRegionCreated}
                onRegionTooLarge={handleRegionTooLarge}
                isLabelDropdownOpen={isLabelDropdownOpen}
                cancelToken={annotationCancelToken}
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
                regions={overlayRegions}
                labelColors={overlayLabelColors}
                slideWidth={slideWidth}
                slideHeight={slideHeight}
                onRegionCreated={handleRegionCreated}
                onRegionTooLarge={handleRegionTooLarge}
                isLabelDropdownOpen={isLabelDropdownOpen}
                cancelToken={annotationCancelToken}
              />
              <PresenceCursorOverlay
                viewer={osdViewer}
                wsiId={wsi_id}
                cursors={cursors}
                enabled={editingMode === 'shared'}
              />
            </>
          )}

          {(availableHeatmaps.length > 0 && shouldShowOverlayControls || hasGTAnnotations) && (
            <ViewerOverlayControls
              canShowHeatmapOverlay={canShowHeatmapOverlay}
              showHeatmap={showHeatmap}
              onToggleHeatmap={handleToggleHeatmap}
              heatmapOpacity={heatmapOpacity}
              onHeatmapOpacityChange={setHeatmapOpacity}
              canShowSegMaskOverlay={canShowSegMaskOverlay}
              showSegMask={showSegMask}
              onToggleSegMask={handleToggleSegMask}
              segMaskOpacity={segMaskOpacity}
              onSegMaskOpacityChange={setSegMaskOpacity}
              segmentationClasses={segmentationClasses}
              canShowGT={selectedTaskIsSegmentation || hasGTAnnotations}
              showGT={showGT}
              onToggleGT={handleToggleGT}
            />
          )}
        </div>
      </div>

      {/* Right: Attention Analysis Panel */}
      <div className={`fixed inset-y-0 right-0 lg:relative z-40 lg:z-0 w-full sm:w-[500px] bg-gray-50 border-l border-gray-200 overflow-y-auto p-4 sm:p-6 flex flex-col gap-4 sm:gap-6 transition-transform duration-300 shadow-2xl lg:shadow-none ${isSidebarOpen ? 'translate-x-0' : 'translate-x-full lg:translate-x-0'}`}>
        <div className="flex lg:hidden items-center justify-between mb-2">
          <h2 className="text-lg font-bold text-gray-900">{t('wsiViewer.analysisData')}</h2>
          <button
            type="button"
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
            preferRemoteCrossSlideSummary={!!effectiveDatasetId && editingMode !== 'shared'}
            crossSlideSummary={effectiveDatasetId && editingMode !== 'shared' ? datasetAnnotationSummary : null}
            loadingCrossSlideSummary={effectiveDatasetId && editingMode !== 'shared' ? loadingDatasetAnnotationSummary : false}
            canCreateDataset={editingMode !== 'shared' || isDatasetOwnerOrAdmin}
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
                  supportsFoldSelection={!selectedTaskIsSegmentation}
                  uniqueTasks={uniqueTasks}
                  isTaskDropdownOpen={isTaskDropdownOpen}
                  setIsTaskDropdownOpen={setIsTaskDropdownOpen}
                  setShowDeleteConfirm={setShowDeleteConfirm}
                  heatmapData={heatmapData}
                  patchCAMData={patchCAMData}
                  isPatchLevel={isPatchLevel}
                  wsiLabel={detail?.meta?.label}
                  wsiEventStatus={detail?.meta?.event_status}
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

      {autoSeedConfirm && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3 px-6 pt-6 pb-2">
              <div className="p-2 bg-indigo-100 rounded-full">
                <Users className="w-5 h-5 text-indigo-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('annotation.collab.autoSeedConfirmTitle')}</h3>
            </div>
            <p className="px-6 py-3 text-sm text-gray-600 leading-relaxed">{t(autoSeedConfirm.sharedHasContent ? 'annotation.collab.autoSeedConfirmMessage' : 'annotation.collab.autoSeedConfirmMessageSharedEmpty')}</p>
            <div className="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 border-t border-gray-100">
              <button type="button" onClick={() => handleAutoSeedConfirm(false)} className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
                {t('annotation.collab.autoSeedConfirmSkip')}
              </button>
              <button type="button" onClick={() => handleAutoSeedConfirm(true)} className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors">
                {t('annotation.collab.autoSeedConfirmUse')}
              </button>
            </div>
          </div>
        </div>
      )}

      {showSharedExitDialog && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center gap-3 px-6 pt-6 pb-2">
              <div className="p-2 bg-indigo-100 rounded-full">
                <Users className="w-5 h-5 text-indigo-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900">{t('annotation.collab.exitSharedTitle')}</h3>
            </div>
            <p className="px-6 py-3 text-sm text-gray-600 leading-relaxed">{t('annotation.collab.exitSharedMessage')}</p>
            <div className="flex items-center justify-end gap-3 px-6 py-4 bg-gray-50 border-t border-gray-100">
              <button type="button" onClick={() => handleSharedExitChoice(false)} className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors">
                {t('annotation.collab.exitSharedDiscard')}
              </button>
              {isDatasetOwnerOrAdmin && (
                <button type="button" onClick={() => handleSharedExitChoice(true)} className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors">
                  {t('annotation.collab.exitSharedImport')}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Create Dataset from Annotations Dialog */}
      <CreateDatasetDialog
        show={showCreateDatasetDialog}
        onClose={() => setShowCreateDatasetDialog(false)}
        allAnnotations={allAnnotations}
        summary={effectiveDatasetId && editingMode !== 'shared' ? datasetAnnotationSummary : null}
        labelColors={labelColors}
        hasWsiSources={editingMode === 'shared' ? hasWsiSources : (datasetAnnotationSummary?.has_wsi_sources ?? hasWsiSources)}
        defaultSource={detail?.meta?.source ?? null}
        onSubmitCreateDataset={handleCreateDatasetFromAnnotations}
      />

      {effectiveDatasetId && (
        <ShareAnnotationDialog
          open={showShareDialog}
          onClose={() => setShowShareDialog(false)}
          datasetId={effectiveDatasetId}
        />
      )}

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
                type="button"
                onClick={() => setPendingNavigation(null)}
                className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                type="button"
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
                type="button"
                onClick={async () => {
                  const saved = await handleManualSave()
                  if (!saved) return
                  const nav = pendingNavigation
                  setPendingNavigation(null)
                  nav()
                }}
                disabled={savingAnnotations || sharedSaving}
                className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors disabled:opacity-50 flex items-center gap-1.5"
              >
                {(savingAnnotations || sharedSaving) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {t('annotation.saveAndLeave')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
