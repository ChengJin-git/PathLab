import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { PREPROCESSING_BASE, API_BASE } from '../config'
import type { HeatmapData } from '../api/heatmap'
import { getPatchFileImageUrl, getThumbnailUrl } from '../api/heatmap'
import { buildSearchParams, withAuthTokenQuery } from '../api/client'
import { Plus, Minus, RotateCcw, Maximize, Minimize, Loader2, Move, Keyboard } from 'lucide-react'
import { Tooltip } from './ui/tooltip'

const PATCH_PREVIEW_SIZE = 512

let openSeadragonPromise: Promise<any> | null = null

async function loadOpenSeadragon(): Promise<any> {
  if (typeof window !== 'undefined' && window.OpenSeadragon) {
    return window.OpenSeadragon
  }

  openSeadragonPromise ??= import('openseadragon').then((module) => {
    const OpenSeadragon = module.default ?? module
    if (typeof window !== 'undefined') {
      window.OpenSeadragon = OpenSeadragon
    }
    return OpenSeadragon
  })

  return openSeadragonPromise
}

function isInputFocused(): boolean {
  const el = document.activeElement as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable
}

interface WSIViewerProps {
  wsi_id: string
  showHeatmap?: boolean
  heatmapOpacity?: number
  taskId?: string  // Optional task ID for specific heatmap
  foldKey?: string  // Optional fold key for k-fold results (e.g., 'fold_0')
  classIdx?: number  // Optional class index for multi-class attention (e.g., CLAM_MB)
  dataLevel?: 'wsi' | 'patch'  // Data level: 'wsi' uses heatmap, 'patch' uses patch_cam
  onHeatmapLoaded?: (data: HeatmapData | null) => void
  onViewerReady?: (viewer: any) => void  // Expose OSD viewer instance to parent (for annotation overlay)
  onSlideInfo?: (info: { width: number; height: number }) => void
  availability?: { status: 'unknown' | 'available' | 'unavailable' | 'stale'; reason?: string | null } | null
}

interface DZIInfo {
  width: number
  height: number
  tileSize: number
  overlap: number
  format: string
}

/**
 * Parse DZI XML and extract image info
 */
function parseDZI(xmlString: string): DZIInfo {
  const parser = new DOMParser()
  const doc = parser.parseFromString(xmlString, 'application/xml')
  const image = doc.getElementsByTagName('Image')[0]
  const size = doc.getElementsByTagName('Size')[0]

  return {
    width: parseInt(size.getAttribute('Width') || '0', 10),
    height: parseInt(size.getAttribute('Height') || '0', 10),
    tileSize: parseInt(image.getAttribute('TileSize') || '254', 10),
    overlap: parseInt(image.getAttribute('Overlap') || '1', 10),
    format: image.getAttribute('Format') || 'jpeg'
  }
}

/**
 * Convert attention weight to RGBA values (coolwarm colormap like CLAM)
 * Returns [r, g, b, a] where values are 0-255
 */
function weightToRGBA(weight: number): [number, number, number, number] {
  // Clamp weight to [0, 1]
  const w = Math.max(0, Math.min(1, weight))

  // Coolwarm colormap: blue (low) -> white (mid) -> red (high)
  let r: number, g: number, b: number

  if (w < 0.5) {
    // Blue to White
    const t = w / 0.5
    r = Math.round(59 + (255 - 59) * t)
    g = Math.round(76 + (255 - 76) * t)
    b = Math.round(192 + (255 - 192) * t)
  } else {
    // White to Red
    const t = (w - 0.5) / 0.5
    r = 255
    g = Math.round(255 * (1 - t))
    b = Math.round(255 * (1 - t * 0.8))
  }

  return [r, g, b, 255]
}

/**
 * Create a heatmap canvas
 * Optimized version using native Canvas API (GPU accelerated where possible)
 */
function createBlendedHeatmapCanvas(
  heatmapData: HeatmapData,
  canvasWidth: number,
  canvasHeight: number,
  opacity: number
): HTMLCanvasElement {
  // 1. Prepare offscreen canvas for drawing raw patches
  const tempCanvas = document.createElement('canvas')
  tempCanvas.width = canvasWidth
  tempCanvas.height = canvasHeight
  const tempCtx = tempCanvas.getContext('2d', { alpha: true })!

  // Calculate coordinates
  const scaleX = canvasWidth / heatmapData.slide_width
  const scaleY = canvasHeight / heatmapData.slide_height
  const patchW = heatmapData.patch_size * scaleX
  const patchH = heatmapData.patch_size * scaleY

  // 2. Draw sharp patches to temp canvas (Batch operation)
  heatmapData.heatmap.forEach((point) => {
    const x = point.x * scaleX
    const y = point.y * scaleY
    const [r, g, b] = weightToRGBA(point.weight)
    
    // We draw with full opacity on temp canvas, opacity is applied later
    tempCtx.fillStyle = `rgb(${r}, ${g}, ${b})` 
    tempCtx.fillRect(x, y, patchW + 0.5, patchH + 0.5) // +0.5 to prevent subpixel gaps
  })

  // 3. Draw to final canvas with Gaussian blur filter (GPU accelerated)
  const canvas = document.createElement('canvas')
  canvas.width = canvasWidth
  canvas.height = canvasHeight
  const ctx = canvas.getContext('2d', { alpha: true })!

  // Set opacity for the whole layer
  ctx.globalAlpha = opacity
  
  // Apply blur filter - simple yet effective blending
  // Radius relative to patch size ensures consistent look regardless of resolution
  const blurRadius = Math.max(2, patchW / 2) 
  ctx.filter = `blur(${blurRadius}px)`
  
  ctx.drawImage(tempCanvas, 0, 0)
  
  return canvas
}

export default function WSIViewer({
  wsi_id,
  showHeatmap = false,
  heatmapOpacity = 0.5,
  taskId,
  foldKey,
  classIdx,
  dataLevel = 'wsi',
  onHeatmapLoaded,
  onViewerReady,
  onSlideInfo,
  availability,
}: WSIViewerProps) {
  const { t } = useTranslation()
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<HTMLDivElement>(null)
  const [viewer, setViewer] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null)
  const [heatmapLoading, setHeatmapLoading] = useState(false)
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [patchPreviewUrl, setPatchPreviewUrl] = useState<string | null>(null)

  const viewerInstanceRef = useRef<any>(null)
  const keysRef = useRef<Set<string>>(new Set())
  const rafRef = useRef<number | null>(null)

  useEffect(() => {
    if (!viewerRef.current || !wsi_id) return

    let osdViewer: any = null
    let cancelled = false

    const initViewer = async () => {
      try {
        setLoading(true)
        setError(undefined)
        setPatchPreviewUrl(null)

        if (availability?.status === 'unavailable') {
          setLoading(false)
          setError(t('wsiViewerComponents.viewer.externalStorageUnavailable', {
            reason: availability.reason ?? '',
          }))
          return
        }

        // First, check if this is a patch or WSI (via gateway with auth)
        const infoUrl = withAuthTokenQuery(`${API_BASE}/heatmap/wsi/${encodeURIComponent(wsi_id)}/info`)
        const infoResponse = await fetch(infoUrl)
        if (!infoResponse.ok) {
          throw new Error(`Failed to fetch file info: ${infoResponse.status}`)
        }
        const info = await infoResponse.json()

        if (cancelled) return

        const OpenSeadragon = await loadOpenSeadragon()
        if (cancelled) return

        // Determine tile source based on file type
        let tileSource: any
        const isImagePatch = info.is_patch

        if (isImagePatch) {
          setPatchPreviewUrl(getThumbnailUrl(wsi_id, PATCH_PREVIEW_SIZE))

          // Patch: use OSD simple image tile source (enables annotation + zoom/pan)
          tileSource = {
            type: 'image',
            url: getPatchFileImageUrl(wsi_id)
          }
        } else {
          // WSI: use DZI tile source
          const dziUrl = `${PREPROCESSING_BASE}/wsi/${wsi_id}/dzi`
          const response = await fetch(dziUrl)
          if (!response.ok) {
            throw new Error(`Failed to fetch DZI: ${response.status}`)
          }
          const dziXml = await response.text()
          const dzi = parseDZI(dziXml)

          if (cancelled) return

          // Expose slide dimensions to parent (for annotation coordinate conversion)
          onSlideInfo?.({ width: dzi.width, height: dzi.height })

          // Build tile URL using frontend's PREPROCESSING_BASE (not from DZI)
          const tileUrlBase = `${PREPROCESSING_BASE}/wsi/${wsi_id}/tiles`

          tileSource = {
            width: dzi.width,
            height: dzi.height,
            tileSize: dzi.tileSize,
            tileOverlap: dzi.overlap,
            getTileUrl: (level: number, x: number, y: number) => {
              return `${tileUrlBase}/${level}/${x}_${y}.${dzi.format}`
            }
          }
        }

        osdViewer = OpenSeadragon({
          element: viewerRef.current,
          prefixUrl: '/assets/openseadragon/images/',
          tileSources: tileSource,
          animationTime: 0.5,
          blendTime: 0.1,
          constrainDuringPan: true,
          maxZoomPixelRatio: isImagePatch ? 4 : 2,
          minZoomLevel: 0.5,
          visibilityRatio: 0.5,
          zoomPerScroll: 1.2,
          showNavigator: !isImagePatch,
          navigatorPosition: 'TOP_RIGHT',
          navigatorHeight: '120px',
          navigatorWidth: '180px',
          showRotationControl: false,
          showFlipControl: false,
          showHomeControl: false,
          showZoomControl: false,
          showFullPageControl: false,
          showNavigationControl: false,
          defaultZoomLevel: 0,
          timeout: 60000,
          crossOriginPolicy: 'Anonymous',
          keyboardShortcutsEnabled: false,
        })

        osdViewer.addHandler('open', () => {
          setLoading(false)
          setError(undefined)
          setPatchPreviewUrl(null)
          // For patches, get image dimensions from OSD after load
          if (isImagePatch) {
            const item = osdViewer.world.getItemAt(0)
            if (item) {
              const contentSize = item.getContentSize()
              onSlideInfo?.({ width: contentSize.x, height: contentSize.y })
            }
          }
        })

        osdViewer.addHandler('open-failed', (event: any) => {
          setLoading(false)
          setPatchPreviewUrl(null)
          setError(isImagePatch
            ? t('wsiViewerComponents.viewer.failedToLoadImage')
            : t('wsiViewerComponents.viewer.failedToLoadTiles'))
          console.error('OpenSeadragon failed to open:', event)
        })

        setViewer(osdViewer)
        onViewerReady?.(osdViewer)
      } catch (err: any) {
        if (!cancelled) {
          setLoading(false)
          setError(err.message || t('wsiViewerComponents.viewer.failedToInitialize'))
        }
      }
    }

    initViewer()

    return () => {
      cancelled = true
      if (osdViewer) {
        onViewerReady?.(null)
        osdViewer.destroy()
      }
    }
  }, [wsi_id, availability])

  // Load heatmap data when taskId, foldKey, classIdx, or dataLevel changes
  useEffect(() => {
    if (!wsi_id) {
      setHeatmapData(null)
      onHeatmapLoaded?.(null)
      return
    }

    const loadHeatmap = async () => {
      setHeatmapLoading(true)
      try {
        // Choose endpoint based on dataLevel: 'wsi' uses heatmap, 'patch' uses patch_cam
        const endpoint = dataLevel === 'patch' ? 'patch_cam' : 'heatmap'
        const params = buildSearchParams({
          task_id: taskId,
          fold_key: foldKey,
          class_idx: classIdx,
          format: dataLevel === 'patch' ? 'json' : undefined,
        })
        const queryString = params.toString()
        const url = `${PREPROCESSING_BASE}/wsi/${wsi_id}/${endpoint}${queryString ? '?' + queryString : ''}`

        const response = await fetch(url)
        if (response.ok) {
          const data = await response.json()
          // Check if the response has actual heatmap data (num_patches > 0 or heatmap array not empty)
          if (data.heatmap?.length > 0 || data.num_patches > 0 || data.cam?.length > 0) {
            setHeatmapData(data)
            onHeatmapLoaded?.(data)
          } else {
            // Empty response (no inference results) - treat as no heatmap
            // console.info('No heatmap data available for this WSI (no inference results)')
            setHeatmapData(null)
            onHeatmapLoaded?.(null)
          }
        } else {
          console.warn('Heatmap not available for this WSI')
          setHeatmapData(null)
          onHeatmapLoaded?.(null)
        }
      } catch (err) {
        console.error('Failed to load heatmap:', err)
        setHeatmapData(null)
        onHeatmapLoaded?.(null)
      } finally {
        setHeatmapLoading(false)
      }
    }

    loadHeatmap()
  }, [wsi_id, taskId, foldKey, classIdx, dataLevel, onHeatmapLoaded])

  // Render heatmap overlay when data is available (CLAM-style blended heatmap)
  useEffect(() => {
    if (!viewer || !heatmapData || !showHeatmap) {
      // Remove existing overlay if any
      if (viewer) {
        const existingOverlay = document.getElementById(`heatmap-overlay-${wsi_id}`)
        if (existingOverlay) {
          viewer.removeOverlay(existingOverlay)
        }
      }
      return
    }

    // Create Canvas overlay for heatmap (CLAM-style blended)
    const createHeatmapOverlay = () => {
      const existingOverlay = document.getElementById(`heatmap-overlay-${wsi_id}`)
      if (existingOverlay) {
        viewer.removeOverlay(existingOverlay)
      }

      // Calculate canvas size - use a reasonable resolution for performance
      // Scale down large slides to max 2048px on longest side
      const maxCanvasSize = 2048
      const aspectRatio = heatmapData.slide_height / heatmapData.slide_width
      let canvasWidth: number, canvasHeight: number

      if (heatmapData.slide_width > heatmapData.slide_height) {
        canvasWidth = Math.min(maxCanvasSize, heatmapData.slide_width)
        canvasHeight = Math.round(canvasWidth * aspectRatio)
      } else {
        canvasHeight = Math.min(maxCanvasSize, heatmapData.slide_height)
        canvasWidth = Math.round(canvasHeight / aspectRatio)
      }

      // Create blended heatmap canvas
      const heatmapCanvas = createBlendedHeatmapCanvas(
        heatmapData,
        canvasWidth,
        canvasHeight,
        heatmapOpacity
      )

      // Create container div for the canvas
      const container = document.createElement('div')
      container.id = `heatmap-overlay-${wsi_id}`
      container.style.pointerEvents = 'none'
      container.style.width = '100%'
      container.style.height = '100%'

      // Style the canvas to fill the container
      heatmapCanvas.style.width = '100%'
      heatmapCanvas.style.height = '100%'
      heatmapCanvas.style.imageRendering = 'auto' // Smooth scaling

      container.appendChild(heatmapCanvas)

      // Add overlay to viewer
      const rect = new window.OpenSeadragon.Rect(
        0,
        0,
        1,
        heatmapData.slide_height / heatmapData.slide_width
      )

      viewer.addOverlay({
        element: container,
        location: rect
      })
    }

    // Wait for viewer to be ready
    if (viewer.world.getItemCount() > 0) {
      createHeatmapOverlay()
    } else {
      viewer.addOnceHandler('open', createHeatmapOverlay)
    }

    return () => {
      const existingOverlay = document.getElementById(`heatmap-overlay-${wsi_id}`)
      if (existingOverlay && viewer) {
        try {
          viewer.removeOverlay(existingOverlay)
        } catch (e) {
          // Viewer might be destroyed
        }
      }
    }
  }, [viewer, heatmapData, showHeatmap, heatmapOpacity, wsi_id])

  // Custom Controls Handlers
  const handleZoomIn = () => {
    if (viewer && viewer.viewport) {
      viewer.viewport.zoomBy(1.2)
      viewer.viewport.applyConstraints()
    }
  }

  const handleZoomOut = () => {
    if (viewer && viewer.viewport) {
      viewer.viewport.zoomBy(0.8)
      viewer.viewport.applyConstraints()
    }
  }

  const handleReset = () => {
    if (viewer && viewer.viewport) {
      viewer.viewport.goHome()
    }
  }

  useEffect(() => {
    const handleFullScreenChange = () => {
      setIsFullScreen(!!document.fullscreenElement)
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Shift' && !e.repeat) setShowShortcuts(prev => !prev)
    }
    const handleBlur = () => setShowShortcuts(false)

    document.addEventListener('fullscreenchange', handleFullScreenChange)
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('blur', handleBlur)
    return () => {
      document.removeEventListener('fullscreenchange', handleFullScreenChange)
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('blur', handleBlur)
    }
  }, [])

  const handleFullScreen = () => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen().catch((err) => {
        console.error(`Error attempting to enable full-screen mode: ${err.message} (${err.name})`)
      })
    } else {
      document.exitFullscreen()
    }
  }

  useEffect(() => {
    viewerInstanceRef.current = viewer
  }, [viewer])

  useEffect(() => {
    const PAN_STEP = 0.004

    const animatePan = () => {
      const v = viewerInstanceRef.current
      if (!v?.viewport) { rafRef.current = null; return }
      const keys = keysRef.current
      let dx = 0, dy = 0
      if (keys.has('KeyW')) dy -= PAN_STEP
      if (keys.has('KeyS')) dy += PAN_STEP
      if (keys.has('KeyA')) dx -= PAN_STEP
      if (keys.has('KeyD')) dx += PAN_STEP
      if (dx !== 0 || dy !== 0) {
        v.viewport.panBy(new window.OpenSeadragon.Point(dx, dy), true)
        rafRef.current = requestAnimationFrame(animatePan)
      } else {
        rafRef.current = null
      }
    }

    const handleKeyDown = (e: KeyboardEvent) => {
      if (isInputFocused()) return
      if (e.ctrlKey || e.metaKey || e.altKey) return

      const wasdCodes = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD'])
      if (wasdCodes.has(e.code)) {
        e.preventDefault()
        keysRef.current.add(e.code)
        if (rafRef.current === null) {
          rafRef.current = requestAnimationFrame(animatePan)
        }
        return
      }

      const v = viewerInstanceRef.current
      if (!v?.viewport) return

      if (e.code === 'Equal') {
        e.preventDefault()
        v.viewport.zoomBy(1.2)
        v.viewport.applyConstraints()
      } else if (e.code === 'Minus') {
        e.preventDefault()
        v.viewport.zoomBy(0.8)
        v.viewport.applyConstraints()
      } else if (e.code === 'KeyR') {
        e.preventDefault()
        v.viewport.goHome()
      } else if (e.code === 'KeyF') {
        e.preventDefault()
        if (!document.fullscreenElement) {
          containerRef.current?.requestFullscreen().catch(console.error)
        } else {
          document.exitFullscreen()
        }
      }
    }

    const handleKeyUp = (e: KeyboardEvent) => {
      keysRef.current.delete(e.code)
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)

    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      keysRef.current.clear()
    }
  }, [])

  // Render OpenSeadragon viewer (used for both WSI and patch images)
  return (
    <div ref={containerRef} className="relative w-full h-full bg-gray-50 group">
      {patchPreviewUrl && (
        <div className="absolute inset-0 z-10 overflow-hidden bg-gray-100">
          <img
            src={patchPreviewUrl}
            alt={t('wsiViewerComponents.viewer.patchPreviewAlt')}
            className="h-full w-full object-contain"
          />
        </div>
      )}

      {loading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-50/55 backdrop-blur-sm z-50">
           <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mb-2" />
           <span className="text-gray-500 font-medium text-sm">{t('wsiViewerComponents.viewer.loadingPreview')}</span>
         </div>
      )}

      {error && (
        <div className="absolute inset-0 flex items-center justify-center z-50 pointer-events-none">
            <div className={`px-6 py-4 rounded-xl shadow-xl border font-medium ${
              availability?.status === 'unavailable'
                ? 'bg-amber-50/95 backdrop-blur-md border-amber-200 text-amber-700'
                : 'bg-white/90 backdrop-blur-md border-red-100 text-red-600'
            }`}>
                {error}
            </div>
        </div>
      )}

      {/* Custom Control Bar (Apple Style) */}
      <div className="absolute top-4 left-4 z-20 flex flex-col items-start gap-2 transition-opacity duration-200">
        <div className="bg-white/95 backdrop-blur-xl border border-gray-200/80 shadow-[0_4px_20px_rgb(0,0,0,0.08)] rounded-xl p-1 flex items-center">
          <Tooltip content={`${t('wsiViewerComponents.viewer.zoomIn')} (=)`}>
          <button
            type="button"
            onClick={handleZoomIn}
            className="relative flex items-center justify-center w-9 h-9 text-gray-700 hover:text-indigo-600 hover:bg-gray-50 rounded-lg transition-all active:scale-95 outline-none"
          >
            <Plus className="w-5 h-5" />
            {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">=</kbd>}
          </button>
          </Tooltip>
          <Tooltip content={`${t('wsiViewerComponents.viewer.zoomOut')} (-)`}>
          <button
            type="button"
            onClick={handleZoomOut}
            className="relative flex items-center justify-center w-9 h-9 text-gray-700 hover:text-indigo-600 hover:bg-gray-50 rounded-lg transition-all active:scale-95 outline-none"
          >
            <Minus className="w-5 h-5" />
            {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">-</kbd>}
          </button>
          </Tooltip>
          <div className="w-px h-5 bg-gray-200 mx-0.5"></div>
          <Tooltip content={`${t('wsiViewerComponents.viewer.resetView')} (R)`}>
          <button
            type="button"
            onClick={handleReset}
            className="relative flex items-center justify-center w-9 h-9 text-gray-700 hover:text-indigo-600 hover:bg-gray-50 rounded-lg transition-all active:scale-95 outline-none"
          >
            <RotateCcw className="w-4 h-4" />
            {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">R</kbd>}
          </button>
          </Tooltip>
          <Tooltip content={`${isFullScreen ? t('wsiViewerComponents.viewer.exitFullScreen') : t('wsiViewerComponents.viewer.fullScreen')} (F)`}>
          <button
            type="button"
            onClick={handleFullScreen}
            className="relative flex items-center justify-center w-9 h-9 text-gray-700 hover:text-indigo-600 hover:bg-gray-50 rounded-lg transition-all active:scale-95 outline-none"
          >
            {isFullScreen ? (
              <Minimize className="w-4 h-4" />
            ) : (
              <Maximize className="w-4 h-4" />
            )}
            {showShortcuts && <kbd className="absolute bottom-0.5 right-0.5 px-1 py-[1px] bg-white border border-gray-200 shadow-sm rounded text-[9px] font-mono font-semibold text-gray-500 z-10 pointer-events-none">F</kbd>}
          </button>
          </Tooltip>
          <div className="w-px h-5 bg-gray-200 mx-0.5"></div>
          <div 
            className="hidden sm:flex items-center gap-1.5 px-2 py-1 text-gray-400 cursor-help transition-colors hover:text-gray-600"
            title={t('wsiViewerComponents.viewer.holdShiftHint')}
          >
            <Keyboard className="w-4 h-4" />
            <span className="text-[10px] font-medium leading-none">Shift</span>
          </div>
        </div>

        {showShortcuts && (
          <div className="bg-white/95 backdrop-blur-xl border border-gray-200/80 shadow-[0_4px_20px_rgb(0,0,0,0.08)] rounded-xl px-2.5 py-1.5 flex items-center gap-2 select-none pointer-events-none mt-0 animate-in fade-in zoom-in-95 duration-200">
            <Move className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
            <div className="flex items-center gap-1">
              {['W', 'A', 'S', 'D'].map(k => (
                <kbd key={k} className="flex items-center justify-center min-w-[20px] h-[20px] bg-white border border-gray-200 border-b-[2px] shadow-sm rounded m-0 p-0 text-[11px] font-mono font-bold text-gray-600">
                  {k}
                </kbd>
              ))}
            </div>
            <span className="text-[11px] font-medium text-gray-500">{t('wsiViewerComponents.viewer.panHint')}</span>
          </div>
        )}

        {heatmapLoading && showHeatmap && (
           <div className="bg-white/90 backdrop-blur-xl border border-indigo-100 shadow-lg rounded-xl px-4 py-2.5 flex items-center gap-3 animate-in fade-in slide-in-from-top-2">
             <Loader2 className="w-4 h-4 text-indigo-600 animate-spin" />
             <span className="text-sm font-medium text-indigo-900">{t('wsiViewerComponents.viewer.loadingHeatmap')}</span>
           </div>
        )}
      </div>

      <div ref={viewerRef} className="w-full h-full" />
    </div>
  )
}

// Remove old styles object as we use Tailwind classes now
