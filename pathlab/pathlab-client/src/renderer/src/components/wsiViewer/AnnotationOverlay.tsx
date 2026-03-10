import { useEffect, useRef, useCallback, useState } from 'react'
import { AnnotationRegion } from '../../api/annotation'

interface AnnotationOverlayProps {
  viewer: any                    // OSD viewer instance
  annotationMode: boolean
  drawingTool: 'rect' | 'polygon'
  currentLabel: string
  currentColor: string
  highlightedRegionId?: string | null
  regions: AnnotationRegion[]    // current slide's annotations
  labelColors: Record<string, string>
  slideWidth: number
  slideHeight: number
  onRegionCreated: (region: Omit<AnnotationRegion, 'id'>) => void
  onRegionTooLarge?: () => void  // called when drawn region exceeds MAX_ROI_SIZE
  isLabelDropdownOpen?: boolean  // when true, disable canvas pointer-events so dropdown is interactive
}

/** Max ROI dimension in level-0 pixels */
const MAX_ROI_SIZE = 8192

/** Convert level-0 pixel coordinate to OSD viewport coordinate */
function l0ToViewport(x: number, y: number, slideWidth: number) {
  return { x: x / slideWidth, y: y / slideWidth }
}

/** Convert OSD viewport coordinate to level-0 pixel coordinate */
function viewportToL0(vx: number, vy: number, slideWidth: number) {
  return { x: vx * slideWidth, y: vy * slideWidth }
}

function withAlpha(color: string, alphaHex: string) {
  if (color.startsWith('#')) {
    if (color.length === 7) return `${color}${alphaHex}`
    if (color.length === 9) return `${color.slice(0, 7)}${alphaHex}`
  }
  return color
}

export function AnnotationOverlay({
  viewer,
  annotationMode,
  drawingTool,
  currentLabel,
  currentColor,
  highlightedRegionId = null,
  regions,
  labelColors,
  slideWidth,
  slideHeight,
  onRegionCreated,
  onRegionTooLarge,
  isLabelDropdownOpen = false,
}: AnnotationOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const [rectStart, setRectStart] = useState<{ x: number; y: number } | null>(null)
  const [rectEnd, setRectEnd] = useState<{ x: number; y: number } | null>(null)
  const [polygonPoints, setPolygonPoints] = useState<number[][]>([])
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null)
  const [spaceHeld, setSpaceHeld] = useState(false)
  const [viewerReady, setViewerReady] = useState(false)

  // Resize canvas to match container
  const resizeCanvas = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const parent = canvas.parentElement
    if (!parent) return
    const rect = parent.getBoundingClientRect()
    if (canvas.width !== rect.width || canvas.height !== rect.height) {
      canvas.width = rect.width
      canvas.height = rect.height
    }
  }, [])

  // Convert screen pixel to level-0 coordinate
  const screenToL0 = useCallback((screenX: number, screenY: number) => {
    if (!viewer || !viewer.viewport) return null
    const canvas = canvasRef.current
    if (!canvas) return null
    const rect = canvas.getBoundingClientRect()
    const canvasX = screenX - rect.left
    const canvasY = screenY - rect.top
    const viewportPoint = viewer.viewport.pointFromPixel(
      new window.OpenSeadragon.Point(canvasX, canvasY)
    )
    return viewportToL0(viewportPoint.x, viewportPoint.y, slideWidth)
  }, [viewer, slideWidth])

  // Convert level-0 coordinate to screen pixel (relative to canvas)
  const l0ToScreen = useCallback((x: number, y: number) => {
    if (!viewer || !viewer.viewport) return null
    const vp = l0ToViewport(x, y, slideWidth)
    const pixel = viewer.viewport.pixelFromPoint(
      new window.OpenSeadragon.Point(vp.x, vp.y)
    )
    return { x: pixel.x, y: pixel.y }
  }, [viewer, slideWidth])

  // ─── Drawing logic ──────────────────────────────────────────────────────
  const drawRegion = useCallback((ctx: CanvasRenderingContext2D, region: AnnotationRegion, highlight = false) => {
    const color = labelColors[region.label] || region.color || '#3b82f6'
    const topLeft = l0ToScreen(region.x, region.y)
    const bottomRight = l0ToScreen(region.x + region.width, region.y + region.height)
    if (!topLeft || !bottomRight) return

    const baseLineWidth = highlight ? 4 : 2
    const highlightStrokeColor = 'rgba(255, 255, 255, 0.98)'
    ctx.strokeStyle = color
    ctx.lineWidth = baseLineWidth
    ctx.fillStyle = withAlpha(color, highlight ? '2E' : '20')

    if (region.type === 'polygon' && region.points && region.points.length >= 3) {
      const screenPoints = region.points
        .map(point => l0ToScreen(point[0], point[1]))
        .filter((point): point is { x: number; y: number } => point !== null)
      if (screenPoints.length < 3) return

      const drawPolygonPath = () => {
        ctx.beginPath()
        ctx.moveTo(screenPoints[0].x, screenPoints[0].y)
        for (let i = 1; i < screenPoints.length; i++) {
          ctx.lineTo(screenPoints[i].x, screenPoints[i].y)
        }
        ctx.closePath()
      }

      if (highlight) {
        drawPolygonPath()
        ctx.save()
        ctx.strokeStyle = highlightStrokeColor
        ctx.lineWidth = 10
        ctx.shadowColor = 'rgba(0, 0, 0, 0.35)'
        ctx.shadowBlur = 10
        ctx.stroke()
        ctx.restore()
      }

      drawPolygonPath()
      ctx.fill()
      ctx.strokeStyle = color
      ctx.lineWidth = baseLineWidth
      ctx.stroke()

      if (highlight) {
        screenPoints.forEach(point => {
          ctx.save()
          ctx.fillStyle = highlightStrokeColor
          ctx.shadowColor = 'rgba(0, 0, 0, 0.28)'
          ctx.shadowBlur = 6
          ctx.beginPath()
          ctx.arc(point.x, point.y, 4.5, 0, Math.PI * 2)
          ctx.fill()
          ctx.restore()

          ctx.fillStyle = color
          ctx.beginPath()
          ctx.arc(point.x, point.y, 2.5, 0, Math.PI * 2)
          ctx.fill()
        })
      }
    } else {
      const w = bottomRight.x - topLeft.x
      const h = bottomRight.y - topLeft.y

      if (highlight) {
        ctx.save()
        ctx.strokeStyle = highlightStrokeColor
        ctx.lineWidth = 10
        ctx.shadowColor = 'rgba(0, 0, 0, 0.35)'
        ctx.shadowBlur = 10
        ctx.strokeRect(topLeft.x, topLeft.y, w, h)
        ctx.restore()
      }

      ctx.fillRect(topLeft.x, topLeft.y, w, h)
      ctx.strokeStyle = color
      ctx.lineWidth = baseLineWidth
      ctx.strokeRect(topLeft.x, topLeft.y, w, h)

      if (highlight) {
        const corners = [
          [topLeft.x, topLeft.y],
          [bottomRight.x, topLeft.y],
          [topLeft.x, bottomRight.y],
          [bottomRight.x, bottomRight.y],
        ]
        corners.forEach(([x, y]) => {
          ctx.save()
          ctx.fillStyle = highlightStrokeColor
          ctx.shadowColor = 'rgba(0, 0, 0, 0.28)'
          ctx.shadowBlur = 6
          ctx.beginPath()
          ctx.arc(x, y, 4.5, 0, Math.PI * 2)
          ctx.fill()
          ctx.restore()

          ctx.fillStyle = color
          ctx.beginPath()
          ctx.arc(x, y, 2.5, 0, Math.PI * 2)
          ctx.fill()
        })
      }
    }

    // Label text
    ctx.font = 'bold 14px system-ui, -apple-system, sans-serif'
    ctx.fillStyle = color
    const textY = topLeft.y - 6
    const metrics = ctx.measureText(region.label)
    // Background pill
    const pillPadX = 6
    const pillPadY = 3
    const pillH = 18
    ctx.fillStyle = 'rgba(255,255,255,0.92)'
    ctx.beginPath()
    const rx = topLeft.x
    const ry = textY - pillH + pillPadY + 2
    const rw = metrics.width + pillPadX * 2
    const rh = pillH
    const radius = 4
    ctx.moveTo(rx + radius, ry)
    ctx.lineTo(rx + rw - radius, ry)
    ctx.quadraticCurveTo(rx + rw, ry, rx + rw, ry + radius)
    ctx.lineTo(rx + rw, ry + rh - radius)
    ctx.quadraticCurveTo(rx + rw, ry + rh, rx + rw - radius, ry + rh)
    ctx.lineTo(rx + radius, ry + rh)
    ctx.quadraticCurveTo(rx, ry + rh, rx, ry + rh - radius)
    ctx.lineTo(rx, ry + radius)
    ctx.quadraticCurveTo(rx, ry, rx + radius, ry)
    ctx.closePath()
    ctx.fill()
    if (highlight) {
      ctx.save()
      ctx.strokeStyle = highlightStrokeColor
      ctx.lineWidth = 3
      ctx.shadowColor = 'rgba(0, 0, 0, 0.25)'
      ctx.shadowBlur = 6
      ctx.stroke()
      ctx.restore()

      ctx.strokeStyle = color
      ctx.lineWidth = 1.25
      ctx.stroke()
    }
    // Shadow
    ctx.shadowColor = 'rgba(0,0,0,0.1)'
    ctx.shadowBlur = 4
    ctx.shadowOffsetY = 1
    ctx.fill()
    ctx.shadowColor = 'transparent'
    ctx.shadowBlur = 0
    ctx.shadowOffsetY = 0
    // Text
    ctx.fillStyle = color
    ctx.fillText(region.label, topLeft.x + pillPadX, textY)
  }, [l0ToScreen, labelColors])

  // Render all annotations + in-progress drawing
  const render = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    resizeCanvas()
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.clearRect(0, 0, canvas.width, canvas.height)
    if (!viewer || !viewer.viewport) return

    const hasHighlightedRegion = !!highlightedRegionId && regions.some(r => r.id === highlightedRegionId)

    // Draw existing regions
    regions.forEach(r => {
      const isHighlighted = r.id === highlightedRegionId
      ctx.save()
      if (hasHighlightedRegion && !isHighlighted) {
        ctx.globalAlpha = 0.4
      }
      drawRegion(ctx, r, isHighlighted)
      ctx.restore()
    })

    // Draw in-progress rectangle
    if (isDrawing && drawingTool === 'rect' && rectStart && rectEnd) {
      const s = l0ToScreen(rectStart.x, rectStart.y)
      const e = l0ToScreen(rectEnd.x, rectEnd.y)
      if (s && e) {
        ctx.strokeStyle = currentColor
        ctx.lineWidth = 2
        ctx.setLineDash([6, 3])
        ctx.fillStyle = currentColor + '15'
        const w = e.x - s.x
        const h = e.y - s.y
        ctx.fillRect(s.x, s.y, w, h)
        ctx.strokeRect(s.x, s.y, w, h)
        ctx.setLineDash([])
      }
    }

    // Draw in-progress polygon
    if (drawingTool === 'polygon' && polygonPoints.length > 0) {
      ctx.strokeStyle = currentColor
      ctx.lineWidth = 2
      ctx.setLineDash([6, 3])
      ctx.beginPath()
      const first = l0ToScreen(polygonPoints[0][0], polygonPoints[0][1])
      if (first) {
        ctx.moveTo(first.x, first.y)
        for (let i = 1; i < polygonPoints.length; i++) {
          const pt = l0ToScreen(polygonPoints[i][0], polygonPoints[i][1])
          if (pt) ctx.lineTo(pt.x, pt.y)
        }
        // Line to mouse cursor
        if (mousePos) {
          const mp = l0ToScreen(mousePos.x, mousePos.y)
          if (mp) ctx.lineTo(mp.x, mp.y)
        }
        ctx.stroke()
        // Draw points
        polygonPoints.forEach(pt => {
          const sp = l0ToScreen(pt[0], pt[1])
          if (sp) {
            ctx.fillStyle = currentColor
            ctx.beginPath()
            ctx.arc(sp.x, sp.y, 4, 0, Math.PI * 2)
            ctx.fill()
          }
        })
      }
      ctx.setLineDash([])
    }
  }, [viewer, regions, highlightedRegionId, isDrawing, drawingTool, rectStart, rectEnd, polygonPoints, mousePos, currentColor, drawRegion, l0ToScreen, resizeCanvas])

  // Re-render on viewport change (zoom/pan)
  useEffect(() => {
    if (!viewer) return
    const handler = () => render()
    viewer.addHandler('animation', handler)
    viewer.addHandler('animation-finish', handler)
    viewer.addHandler('resize', handler)
    render()
    return () => {
      try {
        viewer.removeHandler('animation', handler)
        viewer.removeHandler('animation-finish', handler)
        viewer.removeHandler('resize', handler)
      } catch { /* viewer may be destroyed */ }
    }
  }, [viewer, render])

  // Re-render when regions change
  useEffect(() => { render() }, [regions, render])

  // Wait until the OSD viewer has actually opened before taking over pointer input.
  useEffect(() => {
    if (!viewer) {
      setViewerReady(false)
      return
    }

    const hasOpenItem = typeof viewer.world?.getItemCount === 'function' && viewer.world.getItemCount() > 0
    setViewerReady(hasOpenItem)

    if (hasOpenItem) return

    const handleOpen = () => setViewerReady(true)
    viewer.addHandler('open', handleOpen)

    return () => {
      try {
        viewer.removeHandler('open', handleOpen)
      } catch { /* viewer may be destroyed */ }
    }
  }, [viewer])

  // Toggle OSD mouse navigation based on annotation mode & space key
  useEffect(() => {
    if (!viewer) return
    if (annotationMode && viewerReady && !spaceHeld) {
      viewer.setMouseNavEnabled(false)
    } else {
      viewer.setMouseNavEnabled(true)
    }
    return () => { try { viewer.setMouseNavEnabled(true) } catch { /* */ } }
  }, [viewer, annotationMode, viewerReady, spaceHeld])

  // Space key handler for temporary navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Skip if user is typing in an input/textarea element
      const tag = (e.target as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable) return
      if (e.code === 'Space' && annotationMode) {
        e.preventDefault()
        setSpaceHeld(true)
      }
    }
    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === 'Space') {
        setSpaceHeld(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [annotationMode])

  // ─── Mouse event handlers ───────────────────────────────────────────────
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!annotationMode || spaceHeld) return
    if (drawingTool === 'rect') {
      const pt = screenToL0(e.clientX, e.clientY)
      if (pt) {
        setIsDrawing(true)
        setRectStart(pt)
        setRectEnd(pt)
      }
    }
  }, [annotationMode, spaceHeld, drawingTool, screenToL0])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!annotationMode || spaceHeld) return
    const pt = screenToL0(e.clientX, e.clientY)
    if (!pt) return
    if (drawingTool === 'rect' && isDrawing) {
      setRectEnd(pt)
    }
    if (drawingTool === 'polygon' && polygonPoints.length > 0) {
      setMousePos(pt)
    }
  }, [annotationMode, spaceHeld, drawingTool, isDrawing, polygonPoints.length, screenToL0])

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    if (!annotationMode || spaceHeld) return
    if (drawingTool === 'rect' && isDrawing && rectStart) {
      const pt = screenToL0(e.clientX, e.clientY)
      if (pt) {
        const x = Math.min(rectStart.x, pt.x)
        const y = Math.min(rectStart.y, pt.y)
        const width = Math.abs(pt.x - rectStart.x)
        const height = Math.abs(pt.y - rectStart.y)
        if (width > 10 && height > 10) {
          if (width <= MAX_ROI_SIZE && height <= MAX_ROI_SIZE) {
            onRegionCreated({ type: 'rect', x, y, width, height, label: currentLabel, color: currentColor })
          } else {
            onRegionTooLarge?.()
          }
        }
      }
      setIsDrawing(false)
      setRectStart(null)
      setRectEnd(null)
    }
  }, [annotationMode, spaceHeld, drawingTool, isDrawing, rectStart, currentLabel, currentColor, screenToL0, onRegionCreated, onRegionTooLarge])

  const handleClick = useCallback((e: React.MouseEvent) => {
    if (!annotationMode || spaceHeld || drawingTool !== 'polygon') return
    const pt = screenToL0(e.clientX, e.clientY)
    if (pt) {
      setPolygonPoints(prev => [...prev, [pt.x, pt.y]])
    }
  }, [annotationMode, spaceHeld, drawingTool, screenToL0])

  const handleDoubleClick = useCallback((_e: React.MouseEvent) => {
    if (!annotationMode || spaceHeld || drawingTool !== 'polygon') return
    if (polygonPoints.length >= 3) {
      const xs = polygonPoints.map(p => p[0])
      const ys = polygonPoints.map(p => p[1])
      const x = Math.min(...xs)
      const y = Math.min(...ys)
      const width = Math.max(...xs) - x
      const height = Math.max(...ys) - y
      if (width <= MAX_ROI_SIZE && height <= MAX_ROI_SIZE) {
        onRegionCreated({ type: 'polygon', x, y, width, height, label: currentLabel, color: currentColor, points: polygonPoints })
      } else {
        onRegionTooLarge?.()
      }
    }
    setPolygonPoints([])
    setMousePos(null)
  }, [annotationMode, spaceHeld, drawingTool, polygonPoints, currentLabel, currentColor, onRegionCreated, onRegionTooLarge])

  // Wheel pass-through for zooming (zoom towards mouse position)
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (!annotationMode || !viewerReady || !viewer || !viewer.viewport) return
    e.preventDefault()
    e.stopPropagation()
    const canvas = canvasRef.current
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const canvasX = e.clientX - rect.left
    const canvasY = e.clientY - rect.top
    const refPoint = viewer.viewport.pointFromPixel(
      new window.OpenSeadragon.Point(canvasX, canvasY)
    )
    const factor = e.deltaY < 0 ? 1.2 : 0.8
    viewer.viewport.zoomBy(factor, refPoint)
    viewer.viewport.applyConstraints()
  }, [annotationMode, viewerReady, viewer])

  const interactionEnabled = annotationMode && viewerReady && !spaceHeld && !isLabelDropdownOpen
  const pointerEvents = interactionEnabled ? 'auto' : 'none'
  const cursor = interactionEnabled ? 'crosshair' : 'default'

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 z-10"
      style={{ pointerEvents, cursor }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
      onWheel={handleWheel}
    />
  )
}

