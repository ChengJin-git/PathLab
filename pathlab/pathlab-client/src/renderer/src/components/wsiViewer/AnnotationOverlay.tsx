import { useEffect, useRef, useCallback, useState } from 'react'
import { AnnotationRegion } from '../../api/annotation'

interface AnnotationOverlayProps {
  viewer: any                    // OSD viewer instance
  annotationMode: boolean
  drawingTool: 'rect' | 'polygon'
  currentLabel: string
  currentColor: string
  regions: AnnotationRegion[]    // current slide's annotations
  labelColors: Record<string, string>
  slideWidth: number
  slideHeight: number
  onRegionCreated: (region: Omit<AnnotationRegion, 'id'>) => void
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

export function AnnotationOverlay({
  viewer,
  annotationMode,
  drawingTool,
  currentLabel,
  currentColor,
  regions,
  labelColors,
  slideWidth,
  slideHeight,
  onRegionCreated,
}: AnnotationOverlayProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const [rectStart, setRectStart] = useState<{ x: number; y: number } | null>(null)
  const [rectEnd, setRectEnd] = useState<{ x: number; y: number } | null>(null)
  const [polygonPoints, setPolygonPoints] = useState<number[][]>([])
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null)
  const [spaceHeld, setSpaceHeld] = useState(false)

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

    ctx.strokeStyle = color
    ctx.lineWidth = highlight ? 3 : 2
    ctx.fillStyle = color + '20' // 12% opacity fill

    if (region.type === 'polygon' && region.points && region.points.length >= 3) {
      ctx.beginPath()
      const first = l0ToScreen(region.points[0][0], region.points[0][1])
      if (!first) return
      ctx.moveTo(first.x, first.y)
      for (let i = 1; i < region.points.length; i++) {
        const pt = l0ToScreen(region.points[i][0], region.points[i][1])
        if (pt) ctx.lineTo(pt.x, pt.y)
      }
      ctx.closePath()
      ctx.fill()
      ctx.stroke()
    } else {
      const w = bottomRight.x - topLeft.x
      const h = bottomRight.y - topLeft.y
      ctx.fillRect(topLeft.x, topLeft.y, w, h)
      ctx.strokeRect(topLeft.x, topLeft.y, w, h)
    }

    // Label text
    ctx.font = '11px system-ui, sans-serif'
    ctx.fillStyle = color
    const textY = topLeft.y - 4
    const metrics = ctx.measureText(region.label)
    ctx.fillStyle = 'rgba(255,255,255,0.85)'
    ctx.fillRect(topLeft.x, textY - 12, metrics.width + 6, 15)
    ctx.fillStyle = color
    ctx.fillText(region.label, topLeft.x + 3, textY)
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

    // Draw existing regions
    regions.forEach(r => drawRegion(ctx, r))

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
  }, [viewer, regions, isDrawing, drawingTool, rectStart, rectEnd, polygonPoints, mousePos, currentColor, drawRegion, l0ToScreen, resizeCanvas])

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

  // Toggle OSD mouse navigation based on annotation mode & space key
  useEffect(() => {
    if (!viewer) return
    if (annotationMode && !spaceHeld) {
      viewer.setMouseNavEnabled(false)
    } else {
      viewer.setMouseNavEnabled(true)
    }
    return () => { try { viewer.setMouseNavEnabled(true) } catch { /* */ } }
  }, [viewer, annotationMode, spaceHeld])

  // Space key handler for temporary navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
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
        if (width > 10 && height > 10 && width <= MAX_ROI_SIZE && height <= MAX_ROI_SIZE) {
          onRegionCreated({ type: 'rect', x, y, width, height, label: currentLabel, color: currentColor })
        }
      }
      setIsDrawing(false)
      setRectStart(null)
      setRectEnd(null)
    }
  }, [annotationMode, spaceHeld, drawingTool, isDrawing, rectStart, currentLabel, currentColor, screenToL0, onRegionCreated])

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
      }
    }
    setPolygonPoints([])
    setMousePos(null)
  }, [annotationMode, spaceHeld, drawingTool, polygonPoints, currentLabel, currentColor, onRegionCreated])

  // Wheel pass-through for zooming
  const handleWheel = useCallback((e: React.WheelEvent) => {
    if (!annotationMode || !viewer || !viewer.viewport) return
    e.stopPropagation()
    const factor = e.deltaY < 0 ? 1.2 : 0.8
    viewer.viewport.zoomBy(factor)
    viewer.viewport.applyConstraints()
  }, [annotationMode, viewer])

  const pointerEvents = annotationMode && !spaceHeld ? 'auto' : 'none'
  const cursor = annotationMode && !spaceHeld ? 'crosshair' : 'default'

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

