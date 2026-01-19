import { useEffect, useRef, useState } from 'react'
import { PREPROCESSING_BASE } from '../config'

interface HeatmapPoint {
  x: number
  y: number
  weight: number
  raw_weight: number
}

interface HeatmapData {
  wsi_id: string
  task_id?: string
  patch_size: number
  slide_width: number
  slide_height: number
  num_patches: number
  attention_min: number
  attention_max: number
  prediction?: string
  probs?: Record<string, number>
  heatmap: HeatmapPoint[]
}

interface WSIViewerProps {
  wsi_id: string
  showHeatmap?: boolean
  heatmapOpacity?: number
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
 * Convert attention weight to color (blue -> green -> yellow -> red)
 */
function weightToColor(weight: number, opacity: number): string {
  // Clamp weight to [0, 1]
  const w = Math.max(0, Math.min(1, weight))

  // Color gradient: blue (low) -> cyan -> green -> yellow -> red (high)
  let r: number, g: number, b: number

  if (w < 0.25) {
    // Blue to Cyan
    const t = w / 0.25
    r = 0
    g = Math.round(255 * t)
    b = 255
  } else if (w < 0.5) {
    // Cyan to Green
    const t = (w - 0.25) / 0.25
    r = 0
    g = 255
    b = Math.round(255 * (1 - t))
  } else if (w < 0.75) {
    // Green to Yellow
    const t = (w - 0.5) / 0.25
    r = Math.round(255 * t)
    g = 255
    b = 0
  } else {
    // Yellow to Red
    const t = (w - 0.75) / 0.25
    r = 255
    g = Math.round(255 * (1 - t))
    b = 0
  }

  return `rgba(${r}, ${g}, ${b}, ${opacity})`
}

export default function WSIViewer({
  wsi_id,
  showHeatmap = false,
  heatmapOpacity = 0.5,
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

  // Load heatmap data when showHeatmap is enabled
  useEffect(() => {
    if (!showHeatmap || !wsi_id) {
      setHeatmapData(null)
      onHeatmapLoaded?.(null)
      return
    }

    const loadHeatmap = async () => {
      setHeatmapLoading(true)
      try {
        const response = await fetch(`${PREPROCESSING_BASE}/wsi/${wsi_id}/heatmap`)
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
  }, [showHeatmap, wsi_id, onHeatmapLoaded])

  // Render heatmap overlay when data is available
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

    // Create SVG overlay for heatmap
    const createHeatmapOverlay = () => {
      const existingOverlay = document.getElementById(`heatmap-overlay-${wsi_id}`)
      if (existingOverlay) {
        viewer.removeOverlay(existingOverlay)
      }

      // Create SVG element
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
      svg.id = `heatmap-overlay-${wsi_id}`
      svg.setAttribute('viewBox', `0 0 ${heatmapData.slide_width} ${heatmapData.slide_height}`)
      svg.style.pointerEvents = 'none'

      // Add rectangles for each patch
      const patchSize = heatmapData.patch_size
      heatmapData.heatmap.forEach((point) => {
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect')
        rect.setAttribute('x', String(point.x))
        rect.setAttribute('y', String(point.y))
        rect.setAttribute('width', String(patchSize))
        rect.setAttribute('height', String(patchSize))
        rect.setAttribute('fill', weightToColor(point.weight, heatmapOpacity))
        svg.appendChild(rect)
      })

      // Add overlay to viewer
      const rect = new window.OpenSeadragon.Rect(
        0,
        0,
        1,
        heatmapData.slide_height / heatmapData.slide_width
      )

      viewer.addOverlay({
        element: svg,
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

