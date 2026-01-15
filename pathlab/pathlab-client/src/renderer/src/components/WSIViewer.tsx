import React, { useEffect, useRef, useState } from 'react'
import { PREPROCESSING_BASE } from '../config'

interface WSIViewerProps {
  wsi_id: string
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

export default function WSIViewer({ wsi_id }: WSIViewerProps) {
  const viewerRef = useRef<HTMLDivElement>(null)
  const [viewer, setViewer] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()

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

  return (
    <div style={styles.container}>
      {loading && <div style={styles.overlay}>Loading WSI...</div>}
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

