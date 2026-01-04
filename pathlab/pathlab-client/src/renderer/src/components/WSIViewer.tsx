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
        // Use Mock Tile Server
        const tileSource = {
            width: 10000,
            height: 10000,
            tileSize: 256,
            tileOverlap: 0,
            getTileUrl: function(level: number, x: number, y: number) {
                return `http://127.0.0.1:8000/tile/${level}/${x}/${y}`;
            }
        }
        
        const osdViewer = window.OpenSeadragon({
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
          timeout: 60000
        })

        osdViewer.addHandler('open', () => {
          setLoading(false)
          setError(undefined)
        })

        osdViewer.addHandler('open-failed', (event: any) => {
          setLoading(false)
          setError('Failed to load tiles')
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

  const handleAnalyze = async () => {
    if (!viewer) return
    const bounds = viewer.viewport.getBounds()
    
    try {
        const response = await fetch('http://127.0.0.1:8000/inference', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ x: 0, y: 0, w: 512, h: 512 })
        })
        
        if (!response.ok) throw new Error('Inference failed')

        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        
        const img = document.createElement('img')
        img.src = url
        img.style.opacity = '0.5'
        
        viewer.addOverlay({
            element: img,
            location: bounds
        })
    } catch (e) {
        console.error(e)
        alert('Mock inference failed')
    }
  }

  return (
    <div style={styles.container}>
      {loading && <div style={styles.overlay}>Loading WSI...</div>}
      {error && <div style={styles.error}>{error}</div>}
      <div ref={viewerRef} style={styles.viewer} />
      <button 
        onClick={handleAnalyze}
        style={{
            position: 'absolute',
            top: 20,
            right: 20,
            zIndex: 100,
            padding: '10px 20px',
            background: '#2563eb',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: 'bold'
        }}
      >
        Mock Analyze Region
      </button>
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

