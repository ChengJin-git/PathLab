import { AnnotationRegion } from '../../api/annotation'

interface PatchAnnotationOverlayProps {
  regions: AnnotationRegion[]
  labelColors: Record<string, string>
  highlightedRegionId?: string | null
  slideWidth: number
  slideHeight: number
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

export function PatchAnnotationOverlay({
  regions,
  labelColors,
  highlightedRegionId = null,
  slideWidth,
  slideHeight,
}: PatchAnnotationOverlayProps) {
  if (slideWidth <= 0 || slideHeight <= 0 || regions.length === 0) {
    return null
  }

  const hasHighlightedRegion = !!highlightedRegionId && regions.some(region => region.id === highlightedRegionId)
  const minDimension = Math.min(slideWidth, slideHeight)
  const fontSize = clamp(minDimension * 0.036, 10, 28)

  return (
    <svg
      className="absolute inset-0 z-10 w-full h-full pointer-events-none"
      viewBox={`0 0 ${slideWidth} ${slideHeight}`}
      preserveAspectRatio="xMidYMid meet"
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
    </svg>
  )
}