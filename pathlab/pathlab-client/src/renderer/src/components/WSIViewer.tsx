import { useEffect, useRef, useState } from 'react'
import { PREPROCESSING_BASE } from '../config'
import { HeatmapData } from '../api'
import { Plus, Minus, RotateCcw, Maximize, Minimize, Loader2 } from 'lucide-react'

interface WSIViewerProps {
  wsi_id: string
  showHeatmap?: boolean
  heatmapOpacity?: number
  taskId?: string  // Optional task ID for specific heatmap
  foldKey?: string  // Optional fold key for k-fold results (e.g., 'fold_0')
  classIdx?: number  // Optional class index for multi-class attention (e.g., CLAM_MB)
  dataLevel?: 'wsi' | 'patch'  // Data level: 'wsi' uses heatmap, 'patch' uses patch_cam
  onHeatmapLoaded?: (data: HeatmapData | null) => void
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
  onHeatmapLoaded
}: WSIViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<HTMLDivElement>(null)
  const patchImageRef = useRef<HTMLImageElement>(null)
  const [viewer, setViewer] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null)
  const [heatmapLoading, setHeatmapLoading] = useState(false)
  const [isFullScreen, setIsFullScreen] = useState(false)
  const [isPatch, setIsPatch] = useState(false)
  const [patchImageUrl, setPatchImageUrl] = useState<string>()
  const [patchZoom, setPatchZoom] = useState(1)

  useEffect(() => {
    if (!viewerRef.current || !wsi_id) return

    let osdViewer: any = null
    let cancelled = false

    const initViewer = async () => {
      try {
        // First, check if this is a patch or WSI
        const infoUrl = `${PREPROCESSING_BASE}/wsi/${wsi_id}/info`
        const infoResponse = await fetch(infoUrl)
        if (!infoResponse.ok) {
          throw new Error(`Failed to fetch file info: ${infoResponse.status}`)
        }
        const info = await infoResponse.json()

        if (cancelled) return

        // If it's a patch, just display the image directly
        if (info.is_patch) {
          setIsPatch(true)
          setPatchImageUrl(`${PREPROCESSING_BASE}/wsi/${wsi_id}/image`)
          setLoading(false)
          return
        }

        // For WSI, use OpenSeadragon with DZI
        setIsPatch(false)

        // Wait for OpenSeadragon to load
        while (!window.OpenSeadragon && !cancelled) {
          await new Promise((resolve) => setTimeout(resolve, 100))
        }
        if (cancelled) return

        // Fetch DZI info from preprocessing service
        const dziUrl = `${PREPROCESSING_BASE}/wsi/${wsi_id}/dzi`
        const response = await fetch(dziUrl)
        if (!response.ok) {
          throw new Error(`Failed to fetch DZI: ${response.status}`)
        }
        const dziXml = await response.text()
        const dzi = parseDZI(dziXml)

        if (cancelled) return

        // Build tile URL using frontend's PREPROCESSING_BASE (not from DZI)
        const tileUrlBase = `${PREPROCESSING_BASE}/wsi/${wsi_id}/tiles`

        // Create custom tile source with explicit getTileUrl
        const tileSource = {
          width: dzi.width,
          height: dzi.height,
          tileSize: dzi.tileSize,
          tileOverlap: dzi.overlap,
          getTileUrl: (level: number, x: number, y: number) => {
            return `${tileUrlBase}/${level}/${x}_${y}.${dzi.format}`
          }
        }

        osdViewer = window.OpenSeadragon({
          element: viewerRef.current,
          prefixUrl: 'https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/',
          tileSources: tileSource,
          animationTime: 0.5,
          blendTime: 0.1,
          constrainDuringPan: true,
          maxZoomPixelRatio: 2,
          minZoomLevel: 0.5,
          visibilityRatio: 0.5,
          zoomPerScroll: 1.2,
          showNavigator: true,
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
          crossOriginPolicy: 'Anonymous'
        })

        osdViewer.addHandler('open', () => {
          setLoading(false)
          setError(undefined)
        })

        osdViewer.addHandler('open-failed', (event: any) => {
          setLoading(false)
          setError('Failed to load tiles')
          console.error('OpenSeadragon failed to open:', event)
        })

        setViewer(osdViewer)
      } catch (err: any) {
        if (!cancelled) {
          setLoading(false)
          setError(err.message || 'Failed to initialize viewer')
        }
      }
    }

    initViewer()

    return () => {
      cancelled = true
      if (osdViewer) {
        osdViewer.destroy()
      }
    }
  }, [wsi_id])

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
        const params = new URLSearchParams()
        if (taskId) {
          params.set('task_id', taskId)
        }
        if (foldKey) {
          params.set('fold_key', foldKey)
        }
        if (classIdx !== undefined) {
          params.set('class_idx', classIdx.toString())
        }
        if (dataLevel === 'patch') {
          params.set('format', 'json')  // Request JSON format for patch CAM
        }
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

    document.addEventListener('fullscreenchange', handleFullScreenChange)
    return () => {
      document.removeEventListener('fullscreenchange', handleFullScreenChange)
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

  // Patch zoom handlers
  const handlePatchZoomIn = () => setPatchZoom((z) => Math.min(z * 1.25, 10))
  const handlePatchZoomOut = () => setPatchZoom((z) => Math.max(z / 1.25, 0.1))
  const handlePatchReset = () => setPatchZoom(1)

  // Add non-passive wheel event listener for patch image to allow preventDefault
  useEffect(() => {
    const patchImage = patchImageRef.current
    if (!patchImage || !isPatch) return

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (e.deltaY < 0) {
        setPatchZoom((z) => Math.min(z * 1.25, 10))
      } else {
        setPatchZoom((z) => Math.max(z / 1.25, 0.1))
      }
    }

    // Use { passive: false } to allow preventDefault
    patchImage.addEventListener('wheel', handleWheel, { passive: false })
    return () => {
      patchImage.removeEventListener('wheel', handleWheel)
    }
  }, [isPatch])

  // For patch images, render simple image viewer with zoom
  if (isPatch && patchImageUrl) {
    return (
      <div ref={containerRef} className="relative w-full h-full bg-gray-50 group overflow-hidden">
        {loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-50/80 backdrop-blur-sm z-50">
            <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mb-2" />
            <span className="text-gray-500 font-medium text-sm">Loading Image...</span>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center z-50 pointer-events-none">
            <div className="bg-white/90 backdrop-blur-md px-6 py-4 rounded-xl shadow-xl border border-red-100 text-red-600 font-medium">
              {error}
            </div>
          </div>
        )}

        {/* Control bar for patch images */}
        <div className="absolute top-4 left-4 z-[100] flex flex-col gap-2 transition-opacity duration-200">
          <div className="bg-white/90 backdrop-blur-xl border border-white/20 shadow-[0_8px_30px_rgb(0,0,0,0.12)] rounded-xl p-1.5 flex items-center gap-1">
            <button
              onClick={handlePatchZoomIn}
              className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
              title="Zoom In"
            >
              <Plus className="w-5 h-5" />
            </button>
            <button
              onClick={handlePatchZoomOut}
              className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
              title="Zoom Out"
            >
              <Minus className="w-5 h-5" />
            </button>
            <div className="w-px h-4 bg-gray-200 mx-1"></div>
            <button
              onClick={handlePatchReset}
              className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
              title="Reset View"
            >
              <RotateCcw className="w-4 h-4" />
            </button>
            <button
              onClick={handleFullScreen}
              className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
              title={isFullScreen ? "Exit Full Screen" : "Full Screen"}
            >
              {isFullScreen ? (
                <Minimize className="w-4 h-4" />
              ) : (
                <Maximize className="w-4 h-4" />
              )}
            </button>
          </div>
        </div>

        {/* Patch image display with zoom and pan */}
        <div className="w-full h-full overflow-hidden flex items-center justify-center">
          <img
            ref={patchImageRef}
            src={patchImageUrl}
            alt="Patch Image"
            className="transition-transform duration-200 max-w-full max-h-full object-contain"
            style={{
              cursor: patchZoom > 1 ? 'grab' : 'default',
              transform: `scale(${patchZoom})`,
              transformOrigin: 'center center'
            }}
            draggable={false}
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false)
              setError('Failed to load image')
            }}
          />
        </div>
      </div>
    )
  }

  // For WSI images, render OpenSeadragon viewer
  return (
    <div ref={containerRef} className="relative w-full h-full bg-gray-50 group">
      {loading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-gray-50/80 backdrop-blur-sm z-50">
           <Loader2 className="w-8 h-8 text-indigo-500 animate-spin mb-2" />
           <span className="text-gray-500 font-medium text-sm">Loading Preview...</span>
        </div>
      )}

      {error && (
        <div className="absolute inset-0 flex items-center justify-center z-50 pointer-events-none">
            <div className="bg-white/90 backdrop-blur-md px-6 py-4 rounded-xl shadow-xl border border-red-100 text-red-600 font-medium">
                {error}
            </div>
        </div>
      )}

      {/* Custom Control Bar (Apple Style) */}
      <div className="absolute top-4 left-4 z-[100] flex flex-col gap-2 transition-opacity duration-200">
        <div className="bg-white/90 backdrop-blur-xl border border-white/20 shadow-[0_8px_30px_rgb(0,0,0,0.12)] rounded-xl p-1.5 flex items-center gap-1">
          <button
            onClick={handleZoomIn}
            className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
            title="Zoom In"
          >
            <Plus className="w-5 h-5" />
          </button>
          <button
            onClick={handleZoomOut}
            className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
            title="Zoom Out"
          >
            <Minus className="w-5 h-5" />
          </button>
          <div className="w-px h-4 bg-gray-200 mx-1"></div>
          <button
            onClick={handleReset}
            className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
            title="Reset View"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
          <button
            onClick={handleFullScreen}
            className="p-2 text-gray-700 hover:text-indigo-600 hover:bg-black/5 rounded-lg transition-all active:scale-95 outline-none"
            title={isFullScreen ? "Exit Full Screen" : "Full Screen"}
          >
            {isFullScreen ? (
              <Minimize className="w-4 h-4" />
            ) : (
              <Maximize className="w-4 h-4" />
            )}
          </button>
        </div>

        {/* Heatmap Loading Indicator (Moved below controls) */}
        {heatmapLoading && showHeatmap && (
           <div className="bg-white/90 backdrop-blur-xl border border-indigo-100 shadow-lg rounded-xl px-4 py-2.5 flex items-center gap-3 animate-in fade-in slide-in-from-top-2">
             <Loader2 className="w-4 h-4 text-indigo-600 animate-spin" />
             <span className="text-sm font-medium text-indigo-900">Loading Heatmap...</span>
           </div>
        )}
      </div>

      <div ref={viewerRef} className="w-full h-full" />
    </div>
  )
}

// Remove old styles object as we use Tailwind classes now

