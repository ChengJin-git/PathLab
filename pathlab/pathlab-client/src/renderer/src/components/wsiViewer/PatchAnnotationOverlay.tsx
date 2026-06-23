import { useCallback, useEffect, useRef, useState } from 'react'
import { AnnotationRegion } from '../../api/annotation'

interface PatchAnnotationOverlayProps {
  regions: AnnotationRegion[]
  labelColors: Record<string, string>
  highlightedRegionId?: string | null
  slideWidth: number
  slideHeight: number
  annotationMode: boolean
  drawingTool: 'rect' | 'polygon'
  currentLabel: string
  currentColor: string
  onRegionCreated: (region: Omit<AnnotationRegion, 'id'>) => void
  onRegionTooLarge?: () => void
  isLabelDropdownOpen?: boolean
  cancelToken?: number
}

const MAX_ROI_SIZE = 8192

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

export function PatchAnnotationOverlay({
  regions,
  labelColors,
  highlightedRegionId = null,
  slideWidth,
  slideHeight,
  annotationMode,
  drawingTool,
  currentLabel,
  currentColor,
  onRegionCreated,
  onRegionTooLarge,
  isLabelDropdownOpen = false,
  cancelToken,
}: PatchAnnotationOverlayProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [isDrawing, setIsDrawing] = useState(false)
  const [rectStart, setRectStart] = useState<{ x: number; y: number } | null>(null)
  const [rectEnd, setRectEnd] = useState<{ x: number; y: number } | null>(null)
  const [polygonPoints, setPolygonPoints] = useState<number[][]>([])
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null)
  const [spaceHeld, setSpaceHeld] = useState(false)

  const interactionEnabled = annotationMode && !spaceHeld && !isLabelDropdownOpen

  const screenToImage = useCallback((screenX: number, screenY: number) => {
    const svg = svgRef.current
    if (!svg || !svg.getScreenCTM()) return null

    const point = svg.createSVGPoint()
    point.x = screenX
    point.y = screenY

    const transformed = point.matrixTransform(svg.getScreenCTM()!.inverse())
    return {
      x: clamp(transformed.x, 0, slideWidth),
      y: clamp(transformed.y, 0, slideHeight),
    }
  }, [slideHeight, slideWidth])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      const tag = target?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return
      if (e.code === 'Space' && annotationMode) {
        e.preventDefault()
        setSpaceHeld(true)
        return
      }
      if (!annotationMode) return

      if (e.code === 'Escape') {
        e.preventDefault()
        setIsDrawing(false)
        setRectStart(null)
        setRectEnd(null)
        setPolygonPoints([])
        setMousePos(null)
        return
      }

      if (drawingTool === 'polygon' && (e.code === 'Backspace' || e.code === 'Delete')) {
        e.preventDefault()
        setPolygonPoints(prev => prev.slice(0, -1))
        setMousePos(null)
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
  }, [annotationMode, drawingTool])

  useEffect(() => {
    if (!annotationMode) {
      setIsDrawing(false)
      setRectStart(null)
      setRectEnd(null)
      setPolygonPoints([])
      setMousePos(null)
    }
  }, [annotationMode])

  useEffect(() => {
    if (cancelToken === undefined) return
    setIsDrawing(false)
    setRectStart(null)
    setRectEnd(null)
    setPolygonPoints([])
    setMousePos(null)
  }, [cancelToken])

  const stopEvent = (event: React.MouseEvent<SVGSVGElement>) => {
    event.preventDefault()
    event.stopPropagation()
  }

  const handleMouseDown = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    if (!interactionEnabled) return
    stopEvent(event)

    if (drawingTool !== 'rect') return

    const pt = screenToImage(event.clientX, event.clientY)
    if (!pt) return

    setIsDrawing(true)
    setRectStart(pt)
    setRectEnd(pt)
  }, [drawingTool, interactionEnabled, screenToImage])

  const handleMouseMove = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    if (!interactionEnabled) return
    stopEvent(event)

    const pt = screenToImage(event.clientX, event.clientY)
    if (!pt) return

    if (drawingTool === 'rect' && isDrawing) {
      setRectEnd(pt)
    }
    if (drawingTool === 'polygon' && polygonPoints.length > 0) {
      setMousePos(pt)
    }
  }, [drawingTool, interactionEnabled, isDrawing, polygonPoints.length, screenToImage])

  const handleMouseUp = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    if (!interactionEnabled) return
    stopEvent(event)

    if (drawingTool !== 'rect' || !isDrawing || !rectStart) return

    const pt = screenToImage(event.clientX, event.clientY)
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
  }, [currentColor, currentLabel, drawingTool, interactionEnabled, isDrawing, onRegionCreated, onRegionTooLarge, rectStart, screenToImage])

  const handleClick = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    if (!interactionEnabled || drawingTool !== 'polygon') return
    stopEvent(event)

    const pt = screenToImage(event.clientX, event.clientY)
    if (!pt) return

    setPolygonPoints(prev => [...prev, [pt.x, pt.y]])
  }, [drawingTool, interactionEnabled, screenToImage])

  const handleDoubleClick = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    if (!interactionEnabled || drawingTool !== 'polygon') return
    stopEvent(event)

    if (polygonPoints.length >= 3) {
      const xs = polygonPoints.map(point => point[0])
      const ys = polygonPoints.map(point => point[1])
      const x = Math.min(...xs)
      const y = Math.min(...ys)
      const width = Math.max(...xs) - x
      const height = Math.max(...ys) - y

      if (width <= MAX_ROI_SIZE && height <= MAX_ROI_SIZE) {
        onRegionCreated({
          type: 'polygon',
          x,
          y,
          width,
          height,
          label: currentLabel,
          color: currentColor,
          points: polygonPoints,
        })
      } else {
        onRegionTooLarge?.()
      }
    }

    setPolygonPoints([])
    setMousePos(null)
  }, [currentColor, currentLabel, drawingTool, interactionEnabled, onRegionCreated, onRegionTooLarge, polygonPoints])

  if (slideWidth <= 0 || slideHeight <= 0) {
    return null
  }

  const hasHighlightedRegion = !!highlightedRegionId && regions.some(region => region.id === highlightedRegionId)
  const minDimension = Math.min(slideWidth, slideHeight)
  const fontSize = clamp(minDimension * 0.036, 10, 28)
  const shouldRender = regions.length > 0 || interactionEnabled || polygonPoints.length > 0 || (isDrawing && rectStart && rectEnd)

  if (!shouldRender) {
    return null
  }

  return (
    <svg
      ref={svgRef}
      className="absolute inset-0 z-20 w-full h-full pointer-events-none"
      style={{ pointerEvents: interactionEnabled ? 'auto' : 'none', cursor: interactionEnabled ? 'crosshair' : 'default' }}
      viewBox={`0 0 ${slideWidth} ${slideHeight}`}
      preserveAspectRatio="xMidYMid meet"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={() => setMousePos(null)}
      onClick={handleClick}
      onDoubleClick={handleDoubleClick}
    >
      {regions.map(region => {
        const isHighlighted = region.id === highlightedRegionId
        const color = labelColors[region.label] || region.color || '#3b82f6'
        const horizontalPadding = clamp(fontSize * 0.28, 4, 8)
        const verticalPadding = clamp(fontSize * 0.14, 2, 5)
        const estimatedTextWidth = Math.max(fontSize * 1.8, region.label.length * fontSize * 0.56)
        const labelX = region.x + 6
        const labelWidth = estimatedTextWidth + horizontalPadding * 2
        const labelHeight = fontSize + verticalPadding * 2
        const labelTop = Math.max(2, region.y - labelHeight - 4)
        const labelY = labelTop + verticalPadding + fontSize * 0.8
        const sharedOpacity = hasHighlightedRegion && !isHighlighted ? 0.45 : 1

        return (
          <g key={region.id} opacity={sharedOpacity}>
            {region.type === 'polygon' && region.points && region.points.length >= 3 ? (
              <>
                {isHighlighted && (
                  <polygon
                    points={region.points.map(([x, y]) => `${x},${y}`).join(' ')}
                    fill="none"
                    stroke="rgba(255,255,255,0.98)"
                    strokeWidth={10}
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                <polygon
                  points={region.points.map(([x, y]) => `${x},${y}`).join(' ')}
                  fill={color}
                  fillOpacity={isHighlighted ? 0.18 : 0.12}
                  stroke={color}
                  strokeWidth={isHighlighted ? 4 : 2}
                  vectorEffect="non-scaling-stroke"
                />
              </>
            ) : (
              <>
                {isHighlighted && (
                  <rect
                    x={region.x}
                    y={region.y}
                    width={region.width}
                    height={region.height}
                    fill="none"
                    stroke="rgba(255,255,255,0.98)"
                    strokeWidth={10}
                    vectorEffect="non-scaling-stroke"
                  />
                )}
                <rect
                  x={region.x}
                  y={region.y}
                  width={region.width}
                  height={region.height}
                  fill={color}
                  fillOpacity={isHighlighted ? 0.18 : 0.12}
                  stroke={color}
                  strokeWidth={isHighlighted ? 4 : 2}
                  vectorEffect="non-scaling-stroke"
                />
              </>
            )}

            <rect
              x={labelX - horizontalPadding}
              y={labelTop}
              width={labelWidth}
              height={labelHeight}
              rx={4}
              fill="rgba(255,255,255,0.97)"
              stroke={isHighlighted ? 'rgba(255,255,255,0.98)' : color}
              strokeWidth={isHighlighted ? 2.25 : 1}
              vectorEffect="non-scaling-stroke"
            />
            <text
              x={labelX}
              y={labelY}
              fill={color}
              fontSize={fontSize}
              fontWeight={800}
              stroke="rgba(255,255,255,0.95)"
              strokeWidth={1.2}
              paintOrder="stroke"
            >
              {region.label}
            </text>
          </g>
        )
      })}

      {isDrawing && drawingTool === 'rect' && rectStart && rectEnd && (
        <rect
          x={Math.min(rectStart.x, rectEnd.x)}
          y={Math.min(rectStart.y, rectEnd.y)}
          width={Math.abs(rectEnd.x - rectStart.x)}
          height={Math.abs(rectEnd.y - rectStart.y)}
          fill={currentColor}
          fillOpacity={0.08}
          stroke={currentColor}
          strokeWidth={2}
          strokeDasharray="8 4"
          vectorEffect="non-scaling-stroke"
        />
      )}

      {drawingTool === 'polygon' && polygonPoints.length > 0 && (
        <>
          <polyline
            points={[
              ...polygonPoints.map(([x, y]) => `${x},${y}`),
              ...(mousePos ? [`${mousePos.x},${mousePos.y}`] : []),
            ].join(' ')}
            fill="none"
            stroke={currentColor}
            strokeWidth={2}
            strokeDasharray="8 4"
            vectorEffect="non-scaling-stroke"
          />
          {polygonPoints.map(([x, y], idx) => (
            <circle
              key={`${x}-${y}-${idx}`}
              cx={x}
              cy={y}
              r={4}
              fill={currentColor}
              stroke="rgba(255,255,255,0.95)"
              strokeWidth={1.5}
              vectorEffect="non-scaling-stroke"
            />
          ))}
        </>
      )}
    </svg>
  )
}
