import { useEffect, useRef, useState } from 'react'
import { PREPROCESSING_BASE } from '../config'
import { HeatmapData } from '../api'

interface WSIViewerProps {
  wsi_id: string
  showHeatmap?: boolean
  heatmapOpacity?: number
  taskId?: string  // Optional task ID for specific heatmap
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
 * Apply Gaussian blur to ImageData
 * Uses a simple box blur approximation (3 passes = good Gaussian approximation)
 */
function applyGaussianBlur(imageData: ImageData, radius: number): ImageData {
  const { width, height, data } = imageData
  const result = new Uint8ClampedArray(data)

  // Box blur approximation - 3 passes
  for (let pass = 0; pass < 3; pass++) {
    // Horizontal pass
    const temp = new Uint8ClampedArray(result)
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        let r = 0, g = 0, b = 0, a = 0, count = 0
        for (let dx = -radius; dx <= radius; dx++) {
          const nx = Math.min(Math.max(x + dx, 0), width - 1)
          const idx = (y * width + nx) * 4
          r += temp[idx]
          g += temp[idx + 1]
          b += temp[idx + 2]
          a += temp[idx + 3]
          count++
        }
        const idx = (y * width + x) * 4
        result[idx] = r / count
        result[idx + 1] = g / count
        result[idx + 2] = b / count
        result[idx + 3] = a / count
      }
    }

    // Vertical pass
    const temp2 = new Uint8ClampedArray(result)
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        let r = 0, g = 0, b = 0, a = 0, count = 0
        for (let dy = -radius; dy <= radius; dy++) {
          const ny = Math.min(Math.max(y + dy, 0), height - 1)
          const idx = (ny * width + x) * 4
          r += temp2[idx]
          g += temp2[idx + 1]
          b += temp2[idx + 2]
          a += temp2[idx + 3]
          count++
        }
        const idx = (y * width + x) * 4
        result[idx] = r / count
        result[idx + 1] = g / count
        result[idx + 2] = b / count
        result[idx + 3] = a / count
      }
    }
  }

  return new ImageData(result, width, height)
}

/**
 * Create a blended heatmap canvas (CLAM-style)
 * This creates a smooth, blurred heatmap overlay
 */
function createBlendedHeatmapCanvas(
  heatmapData: HeatmapData,
  canvasWidth: number,
  canvasHeight: number,
  opacity: number
): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = canvasWidth
  canvas.height = canvasHeight
  const ctx = canvas.getContext('2d')!

  // Calculate scale factor from slide coordinates to canvas coordinates
  const scaleX = canvasWidth / heatmapData.slide_width
  const scaleY = canvasHeight / heatmapData.slide_height
  const patchW = Math.ceil(heatmapData.patch_size * scaleX)
  const patchH = Math.ceil(heatmapData.patch_size * scaleY)

  // Create ImageData for the heatmap
  const imageData = ctx.createImageData(canvasWidth, canvasHeight)
  const data = imageData.data

  // Fill with transparent
  for (let i = 0; i < data.length; i += 4) {
    data[i] = 0
    data[i + 1] = 0
    data[i + 2] = 0
    data[i + 3] = 0
  }

  // Draw each patch
  heatmapData.heatmap.forEach((point) => {
    const x = Math.floor(point.x * scaleX)
    const y = Math.floor(point.y * scaleY)
    const [r, g, b] = weightToRGBA(point.weight)

    // Fill the patch area
    for (let py = 0; py < patchH; py++) {
      for (let px = 0; px < patchW; px++) {
        const cx = x + px
        const cy = y + py
        if (cx >= 0 && cx < canvasWidth && cy >= 0 && cy < canvasHeight) {
          const idx = (cy * canvasWidth + cx) * 4
          data[idx] = r
          data[idx + 1] = g
          data[idx + 2] = b
          data[idx + 3] = Math.round(255 * opacity)
        }
      }
    }
  })

  // Apply Gaussian blur for smooth blending (blur radius based on patch size)
  const blurRadius = Math.max(2, Math.floor(patchW / 4))
  const blurredData = applyGaussianBlur(imageData, blurRadius)

  ctx.putImageData(blurredData, 0, 0)

  return canvas
}

export default function WSIViewer({
  wsi_id,
  showHeatmap = false,
  heatmapOpacity = 0.5,
  taskId,
  onHeatmapLoaded
}: WSIViewerProps) {
  const viewerRef = useRef<HTMLDivElement>(null)
  const [viewer, setViewer] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null)
  const [heatmapLoading, setHeatmapLoading] = useState(false)

  useEffect(() => {
    if (!viewerRef.current || !wsi_id) return

    let osdViewer: any = null
    let cancelled = false

    const initViewer = async () => {
      // Wait for OpenSeadragon to load
      while (!window.OpenSeadragon && !cancelled) {
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
      if (cancelled) return

      try {
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
          showHomeControl: true,
          showZoomControl: true,
          showFullPageControl: true,
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

  // Load heatmap data when showHeatmap is enabled or taskId changes
  useEffect(() => {
    if (!showHeatmap || !wsi_id) {
      setHeatmapData(null)
      onHeatmapLoaded?.(null)
      return
    }

    const loadHeatmap = async () => {
      setHeatmapLoading(true)
      try {
        // Build URL with optional task_id parameter
        let url = `${PREPROCESSING_BASE}/wsi/${wsi_id}/heatmap`
        if (taskId) {
          url += `?task_id=${encodeURIComponent(taskId)}`
        }
        const response = await fetch(url)
        if (response.ok) {
          const data: HeatmapData = await response.json()
          setHeatmapData(data)
          onHeatmapLoaded?.(data)
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
  }, [showHeatmap, wsi_id, taskId, onHeatmapLoaded])

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

  return (
    <div style={styles.container}>
      {loading && <div style={styles.overlay}>Loading WSI...</div>}
      {heatmapLoading && showHeatmap && (
        <div style={styles.heatmapLoading}>Loading heatmap...</div>
      )}
      {error && <div style={styles.error}>{error}</div>}
      <div ref={viewerRef} style={styles.viewer} />
    </div>
  )
}

const styles = {
  container: { width: '100%', height: '100%', position: 'relative' as const, background: '#f3f4f6' },
  viewer: { width: '100%', height: '100%' },
  overlay: {
    position: 'absolute' as const,
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    color: '#374151',
    fontSize: 18,
    zIndex: 10
  },
  heatmapLoading: {
    position: 'absolute' as const,
    top: 16,
    left: 16,
    color: '#6366f1',
    fontSize: 14,
    background: 'rgba(255,255,255,0.9)',
    padding: '8px 16px',
    borderRadius: 8,
    zIndex: 20,
    boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)'
  },
  error: {
    position: 'absolute' as const,
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    color: '#dc2626',
    fontSize: 16,
    background: 'rgba(255,255,255,0.95)',
    padding: 20,
    borderRadius: 8,
    zIndex: 10,
    boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)'
  }
}

