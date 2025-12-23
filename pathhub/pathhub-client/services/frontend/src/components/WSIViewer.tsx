import React, { useEffect, useRef, useState } from 'react'
import { PREPROCESSING_BASE } from '../config'

interface WSIViewerProps {
  wsi_id: string
}

export default function WSIViewer({ wsi_id }: WSIViewerProps) {
  const viewerRef = useRef<HTMLDivElement>(null)
  const [viewer, setViewer] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()

  useEffect(() => {
    if (!viewerRef.current || !wsi_id) return

    // Wait for OpenSeadragon to load
    const initViewer = () => {
      if (!window.OpenSeadragon) {
        setTimeout(initViewer, 100)
        return
      }

      try {
        const dziUrl = `${PREPROCESSING_BASE}/wsi/${encodeURIComponent(wsi_id)}/dzi`
        
        const osdViewer = window.OpenSeadragon({
          element: viewerRef.current,
          prefixUrl: 'https://cdnjs.cloudflare.com/ajax/libs/openseadragon/5.0.1/images/',
          tileSources: dziUrl,
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
          timeout: 60000
        })

        osdViewer.addHandler('open', () => {
          setLoading(false)
          setError(undefined)
        })

        osdViewer.addHandler('open-failed', (event: any) => {
          setLoading(false)
          setError('WSI file not available (placeholder mode)')
        })

        setViewer(osdViewer)
      } catch (err: any) {
        setLoading(false)
        setError(err.message || 'Failed to initialize viewer')
      }
    }

    initViewer()

    return () => {
      if (viewer) {
        viewer.destroy()
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
  container: { width: '100%', height: '100%', position: 'relative' as const, background: '#000' },
  viewer: { width: '100%', height: '100%' },
  overlay: { 
    position: 'absolute' as const, 
    top: '50%', 
    left: '50%', 
    transform: 'translate(-50%, -50%)',
    color: 'white',
    fontSize: 18,
    zIndex: 10
  },
  error: {
    position: 'absolute' as const,
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    color: '#ff4444',
    fontSize: 16,
    background: 'rgba(0,0,0,0.8)',
    padding: 20,
    borderRadius: 8,
    zIndex: 10
  }
}

