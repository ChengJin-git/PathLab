import type { CSSProperties, SyntheticEvent } from 'react'
import { getPatchFileImageUrl } from '../../api/heatmap'
import type { AnnotationRegion } from '../../api/annotation'
import { PatchAnnotationOverlay } from './PatchAnnotationOverlay'

export interface PatchOverlayLayer {
  key: string
  src: string
  alt: string
  opacity?: number
}

interface PatchOverlayStackProps {
  wsiId: string
  baseImageAlt: string
  overlayLayers: PatchOverlayLayer[]
  containerStyle?: CSSProperties
  onBaseImageLoad: (event: SyntheticEvent<HTMLImageElement>) => void
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
}

export function PatchOverlayStack({
  wsiId,
  baseImageAlt,
  overlayLayers,
  containerStyle,
  onBaseImageLoad,
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
}: PatchOverlayStackProps) {
  return (
    <div
      className="relative max-w-[600px] max-h-full aspect-square transition-transform duration-100"
      style={containerStyle}
    >
      <img
        src={getPatchFileImageUrl(wsiId)}
        alt={baseImageAlt}
        className="w-full h-full object-contain rounded-xl shadow-lg select-none"
        onLoad={onBaseImageLoad}
        decoding="async"
        draggable={false}
      />

      {overlayLayers.map((layer) => (
        <img
          key={layer.key}
          src={layer.src}
          alt={layer.alt}
          className="absolute inset-0 w-full h-full object-contain rounded-xl pointer-events-none select-none"
          style={{ opacity: layer.opacity ?? 1 }}
          decoding="async"
          draggable={false}
        />
      ))}

      <PatchAnnotationOverlay
        regions={regions}
        labelColors={labelColors}
        highlightedRegionId={highlightedRegionId}
        slideWidth={slideWidth}
        slideHeight={slideHeight}
        annotationMode={annotationMode}
        drawingTool={drawingTool}
        currentLabel={currentLabel}
        currentColor={currentColor}
        onRegionCreated={onRegionCreated}
        onRegionTooLarge={onRegionTooLarge}
        isLabelDropdownOpen={isLabelDropdownOpen}
      />
    </div>
  )
}