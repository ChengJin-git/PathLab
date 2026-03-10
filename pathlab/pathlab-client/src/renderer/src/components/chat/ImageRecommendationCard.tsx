import { useState, useEffect, useMemo, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2, Image as ImageIcon, ExternalLink, AlertCircle, ImageOff, Layers } from 'lucide-react'
import {
  fetchWSIList,
  fetchWSIDetail,
  fetchAllResults,
  getThumbnailUrl,
  fetchAvailableHeatmaps,
  getRecommendationPatchCAMImageUrl as getPatchCAMImageUrl,
  getRecommendationHeatmapThumbnailUrl as getHeatmapThumbnailUrl,
  getSegMaskImageUrl,
  getWSIGroundTruth,
  type WSISummary,
  type AvailableHeatmap,
  type AnnotationRegion
} from '../../api'
import { getFileType } from '../../constants/fileTypes'

type SegmentationMaskSource = 'gt' | 'model_pred' | 'both'

interface SegmentationMaskConfig {
  source: SegmentationMaskSource
  task_id?: string
}

export interface ImageRecommendation {
  query: string
  filters?: {
    label?: string
    pred?: string  // Filter by AI prediction result
    has_predictions?: boolean
    dataset_id?: string
    data_type?: 'wsi' | 'patch' | 'all'
    event_status?: number  // Filter by survival event status: 1 = event occurred, 0 = censored
  }
  max_count?: number  // Maximum number of images to display (default: 3)
  show_heatmap?: boolean  // Whether to show heatmaps alongside images
  heatmap_filter?: {
    feature_extractor?: string  // Filter heatmaps by feature extractor (e.g., 'uni', 'resnet50')
    aggregator?: string  // Filter heatmaps by aggregator (e.g., 'abmil', 'clam_sb') - WSI only
  }
  segmentation_mask?: SegmentationMaskConfig
  reason?: string
}

interface ImageWithOverlays {
  image: WSISummary
  overlays: AvailableHeatmap[]
}

interface ViewerNavigationState {
  fromAIChat: boolean
  conversationId?: string
  selectedTaskId?: string
  selectedFoldKey?: string
  initialShowHeatmap?: boolean
}

interface ImageRecommendationCardProps {
  recommendation: ImageRecommendation
}

/**
 * Parse [IMAGE_RECOMMENDATION] block from message content
 */
export function parseImageRecommendation(content: string): ImageRecommendation | null {
  const match = content.match(/\[IMAGE_RECOMMENDATION\]([\s\S]*?)\[\/IMAGE_RECOMMENDATION\]/)
  if (!match) return null

  try {
    const jsonStr = match[1].trim()
    return JSON.parse(jsonStr)
  } catch {
    return null
  }
}

/**
 * Remove [IMAGE_RECOMMENDATION] block from content for display
 */
export function removeImageRecommendationBlock(content: string): string {
  return content.replace(/\[IMAGE_RECOMMENDATION\][\s\S]*?\[\/IMAGE_RECOMMENDATION\]/g, '').trim()
}

// Global cache for loaded images with heatmap info (persists across component remounts)
const imageCache = new Map<string, { images: ImageWithOverlays[]; error: string | null }>()
const groundTruthMaskCache = new Map<string, AnnotationRegion[]>()
const wsiDimensionCache = new Map<string, { width: number; height: number }>()
const CARD_THUMBNAIL_SIZE = 160

function hexToRgba(color: string, alpha: number): string {
  const normalized = color.replace('#', '')
  const expanded = normalized.length === 3
    ? normalized.split('').map(ch => ch + ch).join('')
    : normalized

  if (expanded.length !== 6) return `rgba(59, 130, 246, ${alpha})`

  const r = Number.parseInt(expanded.slice(0, 2), 16)
  const g = Number.parseInt(expanded.slice(2, 4), 16)
  const b = Number.parseInt(expanded.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function inferDimensionsFromRegions(regions: AnnotationRegion[]): { width: number; height: number } | null {
  if (regions.length === 0) return null

  let maxX = 0
  let maxY = 0

  for (const region of regions) {
    maxX = Math.max(maxX, region.x + region.width)
    maxY = Math.max(maxY, region.y + region.height)

    if (region.type === 'polygon' && region.points) {
      for (const [x, y] of region.points) {
        maxX = Math.max(maxX, x)
        maxY = Math.max(maxY, y)
      }
    }
  }

  if (maxX <= 0 || maxY <= 0) return null
  return { width: Math.ceil(maxX), height: Math.ceil(maxY) }
}

function getLatestSegmentationMaskOverlay(overlays: AvailableHeatmap[], taskId?: string): AvailableHeatmap | undefined {
  const segmentationOverlays = overlays.filter(o => o.data_type === 'patch_segmentation')
  if (segmentationOverlays.length === 0) return undefined
  return taskId
    ? segmentationOverlays.find(o => o.task_id === taskId) ?? segmentationOverlays[0]
    : segmentationOverlays[0]
}

function getPreferredHeatmapOverlay(overlays: AvailableHeatmap[], preferredTaskId?: string): AvailableHeatmap | undefined {
  const heatmapOverlays = overlays.filter(o => o.data_type === 'wsi' || o.data_type === 'patch')
  if (heatmapOverlays.length === 0) return undefined
  return preferredTaskId
    ? heatmapOverlays.find(o => o.task_id === preferredTaskId) ?? heatmapOverlays[0]
    : heatmapOverlays[0]
}

function OverlayThumbnailButton({
  src,
  alt,
  onClick,
  title,
  badgeLabel,
  badgeClassName,
  fallback,
  loadingColorClass,
}: {
  src: string
  alt: string
  onClick: () => void
  title: string
  badgeLabel: string
  badgeClassName: string
  fallback: ReactNode
  loadingColorClass: string
}) {
  const [loadState, setLoadState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    setLoadState('loading')
  }, [src])

  return (
    <button
      onClick={onClick}
      className="relative flex-shrink-0 snap-start group/img w-32 h-32"
      title={title}
    >
      <div className="relative w-full h-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200 group-hover/img:border-orange-300 shadow-sm transition-colors">
        {loadState !== 'error' && (
          <img
            src={src}
            alt={alt}
            className={`w-full h-full object-cover ${loadState === 'ready' ? 'opacity-100' : 'opacity-0'}`}
            loading="lazy"
            decoding="async"
            onLoad={() => setLoadState('ready')}
            onError={() => setLoadState('error')}
          />
        )}

        {loadState === 'error' && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-100">
            {fallback}
          </div>
        )}

        {loadState === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70">
            <Loader2 className={`w-5 h-5 animate-spin ${loadingColorClass}`} />
          </div>
        )}
      </div>

      <span className={`absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded shadow-sm backdrop-blur-[2px] ${badgeClassName}`}>
        {badgeLabel}
      </span>
    </button>
  )
}

function PendingThumbnailSlot({
  title,
  badgeLabel,
  badgeClassName,
  loadingColorClass,
}: {
  title: string
  badgeLabel: string
  badgeClassName: string
  loadingColorClass: string
}) {
  return (
    <div
      className="relative flex-shrink-0 snap-start w-32 h-32"
      title={title}
      aria-label={title}
    >
      <div className="relative w-full h-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200 shadow-sm">
        <div className="absolute inset-0 flex items-center justify-center bg-white/70">
          <Loader2 className={`w-5 h-5 animate-spin ${loadingColorClass}`} />
        </div>
      </div>

      <span className={`absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded shadow-sm backdrop-blur-[2px] ${badgeClassName}`}>
        {badgeLabel}
      </span>
    </div>
  )
}

function GroundTruthMaskThumbnail({
  image,
  onClick
}: {
  image: WSISummary
  onClick: () => void
}) {
  const { t } = useTranslation()
  const [regions, setRegions] = useState<AnnotationRegion[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading')
  const [imageDimensions, setImageDimensions] = useState<{ width: number; height: number } | null>(() => {
    if (image.width && image.height && image.width > 0 && image.height > 0) {
      return { width: image.width, height: image.height }
    }
    return wsiDimensionCache.get(image.wsi_id) || null
  })
  const renderDimensions = useMemo(
    () => imageDimensions ?? inferDimensionsFromRegions(regions),
    [imageDimensions, regions]
  )
  const isWaitingForDimensions = status === 'ready' && regions.length > 0 && !renderDimensions

  useEffect(() => {
    let active = true
    const loadGroundTruth = async () => {
      const cached = groundTruthMaskCache.get(image.wsi_id)
      if (cached) {
        if (!active) return
        setRegions(cached)
        setStatus(cached.length > 0 ? 'ready' : 'empty')
        return
      }

      try {
        const gtResult = await getWSIGroundTruth(image.wsi_id)

        if (!active) return

        const nextRegions = gtResult.annotations?.[image.wsi_id] || []
        const width = gtResult.width
        const height = gtResult.height

        if (typeof width === 'number' && typeof height === 'number' && width > 0 && height > 0) {
          const nextDimensions = { width, height }
          wsiDimensionCache.set(image.wsi_id, nextDimensions)
          setImageDimensions(nextDimensions)
        }

        groundTruthMaskCache.set(image.wsi_id, nextRegions)
        setRegions(nextRegions)
        setStatus(nextRegions.length > 0 ? 'ready' : 'empty')
      } catch {
        if (!active) return
        setStatus('error')
      }
    }

    loadGroundTruth()

    return () => {
      active = false
    }
  }, [image.wsi_id])

  useEffect(() => {
    let active = true

    if (imageDimensions) return

    const loadDimensions = async () => {
      try {
        const detail = await fetchWSIDetail(image.wsi_id)
        if (!active) return

        const width = detail.meta?.width
        const height = detail.meta?.height
        if (typeof width === 'number' && typeof height === 'number' && width > 0 && height > 0) {
          const nextDimensions = { width, height }
          wsiDimensionCache.set(image.wsi_id, nextDimensions)
          setImageDimensions(nextDimensions)
        }
      } catch {
        // Fallback to annotation bounds if metadata request fails.
      }
    }

    loadDimensions()

    return () => {
      active = false
    }
  }, [image.wsi_id, imageDimensions])

  return (
    <button
      onClick={onClick}
      className="relative w-full h-full group/img"
      title={t('chatComponents.imageRecommendation.groundTruthMask')}
    >
      <div className="relative w-full h-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200 group-hover/img:border-orange-300 shadow-sm transition-colors">
        <img
          src={getThumbnailUrl(image.wsi_id, CARD_THUMBNAIL_SIZE)}
          alt={`${t('chatComponents.imageRecommendation.groundTruthMask')}: ${image.original_filename}`}
          className="w-full h-full object-cover"
          loading="lazy"
          decoding="async"
          onError={(e) => {
            e.currentTarget.style.display = 'none'
            const placeholder = e.currentTarget.nextElementSibling as HTMLElement | null
            if (placeholder) placeholder.style.display = 'flex'
          }}
        />
        <div className="hidden absolute inset-0 items-center justify-center bg-gray-100">
          <ImageOff className="w-8 h-8 text-gray-300" />
        </div>

        {(status === 'loading' || isWaitingForDimensions) && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70">
            <Loader2 className="w-5 h-5 text-violet-500 animate-spin" />
          </div>
        )}

        {status === 'ready' && regions.length > 0 && renderDimensions && (
          <svg
            className="absolute inset-0 w-full h-full pointer-events-none"
            viewBox={`0 0 ${renderDimensions.width} ${renderDimensions.height}`}
            preserveAspectRatio="xMidYMid slice"
          >
            {regions.map((region) => {
              const stroke = region.color || '#8b5cf6'
              const fill = hexToRgba(stroke, 0.18)

              if (region.type === 'polygon' && region.points && region.points.length >= 3) {
                return (
                  <polygon
                    key={region.id}
                    points={region.points.map(([x, y]) => `${x},${y}`).join(' ')}
                    fill={fill}
                    stroke={stroke}
                    strokeWidth={3}
                    vectorEffect="non-scaling-stroke"
                  />
                )
              }

              return (
                <rect
                  key={region.id}
                  x={region.x}
                  y={region.y}
                  width={region.width}
                  height={region.height}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={3}
                  vectorEffect="non-scaling-stroke"
                />
              )
            })}
          </svg>
        )}

        {status === 'empty' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/10 px-2 text-center">
            <span className="px-2 py-1 text-[10px] font-medium rounded bg-black/60 text-white">
              {t('chatComponents.imageRecommendation.noGtMask')}
            </span>
          </div>
        )}

        {status === 'error' && (
          <div className="absolute inset-0 flex items-center justify-center bg-black/10 px-2 text-center">
            <span className="px-2 py-1 text-[10px] font-medium rounded bg-black/60 text-white">
              {t('chatComponents.imageRecommendation.gtMaskUnavailable')}
            </span>
          </div>
        )}
      </div>

      <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded bg-violet-100/90 text-violet-700 shadow-sm backdrop-blur-[2px]">
        {t('chatComponents.imageRecommendation.groundTruthMaskShort')}
      </span>
    </button>
  )
}

export function ImageRecommendationCard({ recommendation }: ImageRecommendationCardProps) {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [imagesWithOverlays, setImagesWithOverlays] = useState<ImageWithOverlays[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isOverlayInfoLoading, setIsOverlayInfoLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const segmentationMaskConfig = recommendation.segmentation_mask
  const wantsGroundTruthMask = segmentationMaskConfig?.source === 'gt' || segmentationMaskConfig?.source === 'both'
  const wantsPredictionMask = segmentationMaskConfig?.source === 'model_pred' || segmentationMaskConfig?.source === 'both'
  const isSegmentationCard = !!segmentationMaskConfig
  const needsOverlayLookup = recommendation.show_heatmap || wantsPredictionMask

  // Determine max count (default 3)
  const maxCount = recommendation.max_count ?? 3

  // Memoize filter key to prevent unnecessary re-fetches
  // Include query in the key so each unique recommendation gets its own cache entry
  const filterKey = useMemo(
    () =>
      JSON.stringify({
        query: recommendation.query,
        label: recommendation.filters?.label,
        pred: recommendation.filters?.pred,
        has_predictions: recommendation.filters?.has_predictions,
        dataset_id: recommendation.filters?.dataset_id,
        data_type: recommendation.filters?.data_type,
        event_status: recommendation.filters?.event_status,
        max_count: maxCount,
        show_heatmap: recommendation.show_heatmap,
        segmentation_mask_source: recommendation.segmentation_mask?.source,
        segmentation_mask_task_id: recommendation.segmentation_mask?.task_id,
      }),
    [recommendation.query, recommendation.filters, maxCount, recommendation.show_heatmap, recommendation.segmentation_mask]
  )

  useEffect(() => {
    // Check cache first
    const cached = imageCache.get(filterKey)
    if (cached) {
      setImagesWithOverlays(cached.images)
      setError(cached.error)
      setIsOverlayInfoLoading(false)
      setIsLoading(false)
      return
    }

    loadImages()
  }, [filterKey])

  /**
   * Fetch WSI list by dataset and apply label/event_status/data_type filters.
   * Extracted to avoid duplication between the normal path and the fallback path.
   */
  const fetchAndFilterWSIList = async (rec: ImageRecommendation): Promise<WSISummary[]> => {
    const result = await fetchWSIList(rec.filters?.dataset_id)
    let filtered = result.items

    // Apply label filter - use exact match to avoid substring issues
    if (rec.filters?.label) {
      filtered = filtered.filter(s =>
        s.label?.toLowerCase() === rec.filters!.label!.toLowerCase()
      )
    }

    // Apply event_status filter (for survival datasets: 0=censored, 1=event)
    if (rec.filters?.event_status !== undefined && rec.filters?.event_status !== null) {
      filtered = filtered.filter(s => s.event_status === rec.filters!.event_status)
    }

    // Apply data_type filter
    if (rec.filters?.data_type && rec.filters.data_type !== 'all') {
      filtered = filtered.filter(s => {
        const fileType = getFileType(s.file_extension, s.file_size, s.data_type)
        return rec.filters!.data_type === 'wsi'
          ? fileType === 'WSI'
          : fileType === 'Patch'
      })
    }

    return filtered
  }

  const loadImages = async () => {
    setIsLoading(true)
    setIsOverlayInfoLoading(false)
    setError(null)
    try {
      let displayImages: WSISummary[] = []

      // If has_predictions is true, fetch from results endpoint
      if (recommendation.filters?.has_predictions) {
        const resultsData = await fetchAllResults()
        // Convert ResultWithWSI to WSISummary-like objects
        let resultsWithWsi = resultsData.items

        // Apply pred filter (filter by AI prediction result) - use exact match to avoid substring issues
        // e.g., "MSIH" should NOT match "nonMSIH"
        if (recommendation.filters?.pred) {
          resultsWithWsi = resultsWithWsi.filter(r =>
            r.pred?.toLowerCase() === recommendation.filters!.pred!.toLowerCase()
          )
        }

        // Apply label filter (ground truth label) on results BEFORE creating the wsi_id set
        // This is critical: we must filter by label here, not later on the WSI list
        // Use exact match to avoid substring issues (e.g., "MSIH" matching "nonMSIH")
        if (recommendation.filters?.label) {
          resultsWithWsi = resultsWithWsi.filter(r =>
            r.label?.toLowerCase() === recommendation.filters!.label!.toLowerCase()
          )
        }

        // We need to get full WSI info, so fetch WSI list and merge
        const wsiResult = await fetchWSIList(recommendation.filters?.dataset_id)

        // Filter to only WSIs that have predictions (and match both pred and label filters if specified)
        const wsiIdsWithPredictions = new Set(resultsWithWsi.map(r => r.wsi_id))
        let filtered = wsiResult.items.filter(w => wsiIdsWithPredictions.has(w.wsi_id))

        // Apply event_status filter (for survival datasets: 0=censored, 1=event)
        if (recommendation.filters?.event_status !== undefined && recommendation.filters?.event_status !== null) {
          filtered = filtered.filter(s => s.event_status === recommendation.filters!.event_status)
        }

        // Apply data_type filter
        if (recommendation.filters?.data_type && recommendation.filters.data_type !== 'all') {
          filtered = filtered.filter(s => {
            const fileType = getFileType(s.file_extension, s.file_size, s.data_type)
            return recommendation.filters!.data_type === 'wsi'
              ? fileType === 'WSI'
              : fileType === 'Patch'
          })
        }

        displayImages = filtered
      } else {
        // Normal fetch without predictions filter
        displayImages = await fetchAndFilterWSIList(recommendation)
      }

      // Fallback: if show_heatmap is true but no images found with has_predictions filter,
      // retry without the predictions constraint. This handles the case where heatmaps exist
      // on disk (from training) but no AIResult records exist in the database.
      if (needsOverlayLookup && displayImages.length === 0 && recommendation.filters?.has_predictions) {
        console.warn('[ImageRecommendation] No images found with has_predictions filter, falling back to dataset images for heatmap display')
        displayImages = await fetchAndFilterWSIList(recommendation)
      }

      // Shuffle the images randomly before limiting
      // This ensures different images are shown each time for the same filters
      const shuffled = [...displayImages].sort(() => Math.random() - 0.5)

      // Limit to user-specified count (default 3)
      const limitedImages = shuffled.slice(0, maxCount)
      const baseImageInfo = limitedImages.map(img => ({
        image: img,
        overlays: [],
      }))

      setImagesWithOverlays(baseImageInfo)
      setIsLoading(false)

      let imageOverlayInfo: ImageWithOverlays[]
      if (needsOverlayLookup) {
        setIsOverlayInfoLoading(true)
        const overlayPromises = limitedImages.map(async (img) => {
          try {
            let overlays = await fetchAvailableHeatmaps(img.wsi_id)

            // Apply heatmap_filter if specified
            if (recommendation.heatmap_filter) {
              const { feature_extractor, aggregator } = recommendation.heatmap_filter
              overlays = overlays.filter(h => {
                if (h.data_type === 'patch_segmentation') {
                  return true
                }
                // Filter by feature_extractor if specified
                if (feature_extractor) {
                  // If user specified feature_extractor but heatmap doesn't have it, reject
                  if (!h.feature_extractor) {
                    return false
                  }
                  if (h.feature_extractor.toLowerCase() !== feature_extractor.toLowerCase()) {
                    return false
                  }
                }
                // Filter by aggregator if specified (WSI only)
                if (aggregator) {
                  // If user specified aggregator but heatmap doesn't have it, reject
                  if (!h.aggregator) {
                    return false
                  }
                  if (h.aggregator.toLowerCase() !== aggregator.toLowerCase()) {
                    return false
                  }
                }
                return true
              })
            }

            return {
              image: img,
              overlays,
            }
          } catch {
            return {
              image: img,
              overlays: [],
            }
          }
        })
        imageOverlayInfo = await Promise.all(overlayPromises)
      } else {
        imageOverlayInfo = baseImageInfo
      }

      setImagesWithOverlays(imageOverlayInfo)
      // Cache the result
      imageCache.set(filterKey, { images: imageOverlayInfo, error: null })
    } catch (err) {
      setImagesWithOverlays([])
      setError(t('chatComponents.imageRecommendation.failedToLoad'))
      console.error('Failed to load images:', err)
      // Cache the error state too
      imageCache.set(filterKey, { images: [], error: t('chatComponents.imageRecommendation.failedToLoad') })
    } finally {
      setIsOverlayInfoLoading(false)
      setIsLoading(false)
    }
  }

  const handleImageClick = (wsiId: string, heatmapOverlay?: AvailableHeatmap) => {
    // Save scroll position and conversation ID before navigating
    const messagesContainer = document.querySelector('[data-chat-messages-container]')
    if (messagesContainer) {
      sessionStorage.setItem('ai-chat-scroll-position', String(messagesContainer.scrollTop))
    }
    const conversationId = document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
    if (conversationId) {
      sessionStorage.setItem('ai-chat-conversation-id', conversationId)
    }
    const navigationState: ViewerNavigationState = {
      fromAIChat: true,
      conversationId: conversationId || undefined,
    }

    if (heatmapOverlay?.task_id) {
      navigationState.selectedTaskId = heatmapOverlay.task_id
      navigationState.selectedFoldKey = heatmapOverlay.fold_key || undefined
      navigationState.initialShowHeatmap = recommendation.show_heatmap === true
    }

    navigate(`/wsi/${wsiId}`, { state: navigationState })
  }

  const imagesWithHeatmapCount = imagesWithOverlays.filter(({ overlays }) => {
    const latestSegmentationMask = getLatestSegmentationMaskOverlay(overlays, segmentationMaskConfig?.task_id)
    return !!getPreferredHeatmapOverlay(
      overlays,
      isSegmentationCard ? (latestSegmentationMask?.task_id ?? segmentationMaskConfig?.task_id) : undefined,
    )
  }).length

  const imagesWithPredictionMaskCount = imagesWithOverlays.filter(({ overlays }) =>
    overlays.some(o => o.data_type === 'patch_segmentation')
  ).length

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-orange-50 to-amber-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-orange-600" />
          {t(isSegmentationCard
            ? 'chatComponents.imageRecommendation.segmentationMasks'
            : 'chatComponents.imageRecommendation.recommendedImages')}
          {imagesWithOverlays.length > 0 && (
            <span className="text-xs font-normal text-gray-500">
              ({t('chatComponents.imageRecommendation.imageCount', { count: imagesWithOverlays.length })})
            </span>
          )}
        </h3>
        {recommendation.reason && (
          <p className="text-sm text-gray-500 mt-1">{recommendation.reason}</p>
        )}
        {/* Heatmap availability summary */}
        {recommendation.show_heatmap && imagesWithOverlays.length > 0 && (
          <div className="flex items-center gap-3 mt-2 text-xs">
            {imagesWithHeatmapCount > 0 && (
              <span className="flex items-center gap-1 text-green-600">
                <Layers className="w-3 h-3" />
                {t('chatComponents.imageRecommendation.withHeatmap', { count: imagesWithHeatmapCount })}
              </span>
            )}
          </div>
        )}
        {/* Warning when heatmap_filter specified but no matching heatmaps found */}
        {recommendation.show_heatmap && recommendation.heatmap_filter && !isOverlayInfoLoading && imagesWithHeatmapCount === 0 && imagesWithOverlays.length > 0 && (
          <div className="flex items-center gap-2 mt-2 text-xs text-amber-600 bg-amber-50 px-2 py-1.5 rounded-lg">
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>
              {t('chatComponents.imageRecommendation.noHeatmapsFound')}
              {recommendation.heatmap_filter.feature_extractor && ` (${recommendation.heatmap_filter.feature_extractor})`}
              {recommendation.heatmap_filter.aggregator && ` + ${recommendation.heatmap_filter.aggregator.toUpperCase()}`}
            </span>
          </div>
        )}
        {wantsPredictionMask && !isOverlayInfoLoading && imagesWithPredictionMaskCount === 0 && imagesWithOverlays.length > 0 && (
          <div className="flex items-center gap-2 mt-2 text-xs text-amber-600 bg-amber-50 px-2 py-1.5 rounded-lg">
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>{t('chatComponents.imageRecommendation.noModelPredMasksFound')}</span>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-gray-500">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            {t('chatComponents.imageRecommendation.loadingImages')}
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 text-red-600 py-4">
            <AlertCircle className="w-4 h-4" />
            <span className="text-sm">{error}</span>
          </div>
        ) : imagesWithOverlays.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">
            {t('chatComponents.imageRecommendation.noImagesFound')}
          </p>
        ) : (
          <div className="space-y-4">
            {imagesWithOverlays.map(({ image, overlays }) => {
              const fileType = getFileType(image.file_extension, image.file_size, image.data_type)
              const latestSegmentationMask = getLatestSegmentationMaskOverlay(overlays, segmentationMaskConfig?.task_id)
              const latestHeatmap = getPreferredHeatmapOverlay(
                overlays,
                isSegmentationCard ? (latestSegmentationMask?.task_id ?? segmentationMaskConfig?.task_id) : undefined,
              )
              const hasHeatmap = !!latestHeatmap
              const showOverlayLoadingPlaceholder = needsOverlayLookup && isOverlayInfoLoading
              return (
                <div
                  key={image.wsi_id}
                  className="group p-4 bg-gray-50 hover:bg-orange-50 rounded-xl border border-gray-200
                             hover:border-orange-300 transition-all"
                >
                  <div className="flex flex-wrap items-center gap-4">
                    {/* Images Container - Scrollable horizontal list */}
                    <div className="flex gap-2 overflow-x-auto pb-0 snap-x [&::-webkit-scrollbar]:hidden [-ms-overflow-style:none] [scrollbar-width:none] shrink-0 max-w-full">
                      {/* Original image */}
                      <button
                        onClick={() => handleImageClick(image.wsi_id, latestHeatmap)}
                        className="relative flex-shrink-0 snap-start group/img w-32 h-32"
                      >
                        <div className="w-full h-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200 group-hover/img:border-orange-300 shadow-sm transition-colors">
                          <img
                            src={getThumbnailUrl(image.wsi_id, 256)}
                            alt={image.original_filename}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              e.currentTarget.style.display = 'none'
                              const placeholder = e.currentTarget.nextElementSibling as HTMLElement
                              if (placeholder) placeholder.style.display = 'flex'
                            }}
                          />
                          <div className="hidden absolute inset-0 items-center justify-center bg-gray-100">
                            <ImageOff className="w-8 h-8 text-gray-300" />
                          </div>
                        </div>
                        {/* File type badge */}
                        <span className={`absolute top-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded shadow-sm ${fileType === 'WSI'
                          ? 'bg-purple-100/90 text-purple-700 backdrop-blur-[2px]'
                          : 'bg-green-100/90 text-green-700 backdrop-blur-[2px]'
                          }`}>
                          {fileType}
                        </span>
                        <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded bg-white/90 text-gray-700 shadow-sm backdrop-blur-[2px]">
                          {t('chatComponents.imageRecommendation.original')}
                        </span>
                      </button>

                      {/* Heatmap (if available and show_heatmap is true) */}
                      {recommendation.show_heatmap && (
                        hasHeatmap && latestHeatmap ? (
                          <OverlayThumbnailButton
                            src={
                              fileType === 'Patch'
                                ? getPatchCAMImageUrl(
                                  image.wsi_id,
                                  latestHeatmap.task_id || undefined,
                                  latestHeatmap.fold_key || undefined,
                                )
                                : getHeatmapThumbnailUrl(
                                  image.wsi_id,
                                  latestHeatmap.task_id || undefined,
                                  CARD_THUMBNAIL_SIZE,
                                  undefined,
                                  latestHeatmap.fold_key || undefined,
                                  latestHeatmap.patch_size,
                                )
                            }
                            alt={`Heatmap for ${image.original_filename}`}
                            onClick={() => handleImageClick(image.wsi_id, latestHeatmap)}
                            title={t('chatComponents.imageRecommendation.heatmap')}
                            badgeLabel={t('chatComponents.imageRecommendation.heatmap')}
                            badgeClassName="bg-green-100/90 text-green-700"
                            loadingColorClass="text-green-500"
                            fallback={<Layers className="w-8 h-8 text-gray-300" />}
                          />
                        ) : showOverlayLoadingPlaceholder ? (
                          <PendingThumbnailSlot
                            title={t('chatComponents.imageRecommendation.heatmap')}
                            badgeLabel={t('chatComponents.imageRecommendation.heatmap')}
                            badgeClassName="bg-green-100/90 text-green-700"
                            loadingColorClass="text-green-500"
                          />
                        ) : null
                      )}

                      {wantsPredictionMask && fileType === 'Patch' && (
                        latestSegmentationMask ? (
                          <div className="shadow-sm rounded-lg">
                            <OverlayThumbnailButton
                              src={getSegMaskImageUrl(
                                image.wsi_id,
                                latestSegmentationMask.task_id || segmentationMaskConfig?.task_id,
                                latestSegmentationMask.fold_key || undefined,
                                CARD_THUMBNAIL_SIZE,
                              )}
                              alt={`${t('chatComponents.imageRecommendation.modelPredictionMask')}: ${image.original_filename}`}
                              onClick={() => handleImageClick(image.wsi_id, latestHeatmap)}
                              title={t('chatComponents.imageRecommendation.modelPredictionMask')}
                              badgeLabel={t('chatComponents.imageRecommendation.modelPredictionMaskShort')}
                              badgeClassName="bg-indigo-100/90 text-indigo-700"
                              loadingColorClass="text-indigo-500"
                              fallback={<Layers className="w-8 h-8 text-gray-300" />}
                            />
                          </div>
                        ) : showOverlayLoadingPlaceholder ? (
                          <PendingThumbnailSlot
                            title={t('chatComponents.imageRecommendation.modelPredictionMask')}
                            badgeLabel={t('chatComponents.imageRecommendation.modelPredictionMaskShort')}
                            badgeClassName="bg-indigo-100/90 text-indigo-700"
                            loadingColorClass="text-indigo-500"
                          />
                        ) : (
                          <div className="relative flex-shrink-0 snap-start w-32 h-32">
                            <div className="w-full h-full bg-gray-100 rounded-lg border-2 border-dashed border-gray-300 flex items-center justify-center p-3 text-center">
                              <div className="flex flex-col items-center gap-2 text-gray-500">
                                <Layers className="w-6 h-6 opacity-50" />
                                <span className="text-[10px] font-medium leading-tight">
                                  {t('chatComponents.imageRecommendation.noModelPredMask')}
                                  <br />
                                  <span className="text-[9px] opacity-75">(Not processed)</span>
                                </span>
                              </div>
                            </div>
                            <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded bg-gray-100/90 text-gray-600 shadow-sm backdrop-blur-[2px]">
                              {t('chatComponents.imageRecommendation.modelPredictionMaskShort')}
                            </span>
                          </div>
                        )
                      )}

                      {wantsGroundTruthMask && fileType === 'Patch' && (
                        <div className="w-32 h-32 flex-shrink-0 snap-start shadow-sm rounded-lg">
                          <GroundTruthMaskThumbnail
                            image={image}
                            onClick={() => handleImageClick(image.wsi_id, latestHeatmap)}
                          />
                        </div>
                      )}
                    </div>

                    {/* Image info */}
                    <div className="flex-1 min-w-[240px] flex flex-col pt-1">
                      <div className="flex justify-between items-start gap-2">
                        <p className="text-base font-semibold text-gray-900 break-all leading-tight">
                          {image.original_filename}
                        </p>
                        <button
                          onClick={() => handleImageClick(image.wsi_id, latestHeatmap)}
                          className="shrink-0 text-xs text-orange-600 hover:text-orange-700 font-medium flex items-center gap-1.5 hover:underline"
                        >
                          {t('chatComponents.imageRecommendation.viewDetails')} <ExternalLink className="w-3.5 h-3.5" />
                        </button>
                      </div>

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        {image.dataset_name && (
                          <div className="inline-flex shrink-0 items-center whitespace-nowrap px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded-md font-medium border border-gray-200">
                            {t('chatComponents.imageRecommendation.dataset')}: <span className="text-gray-900 ml-1">{image.dataset_name}</span>
                          </div>
                        )}
                        {image.label && (
                          <div className="inline-flex shrink-0 items-center whitespace-nowrap px-2 py-1 bg-amber-50 text-amber-700 text-xs rounded-md font-medium border border-amber-100">
                            {t('chatComponents.imageRecommendation.label')}: <span className="text-amber-900 ml-1">{image.label}</span>
                          </div>
                        )}
                        {wantsPredictionMask && latestSegmentationMask?.task_name && (
                          <div className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-2.5 py-1 bg-indigo-50 text-indigo-700 text-xs rounded-md font-medium border border-indigo-100">
                            <span className="font-bold text-indigo-500 uppercase tracking-wider text-[10px]">{t('chatComponents.imageRecommendation.maskModel')}</span>
                            <span className="text-indigo-900">{latestSegmentationMask.task_name}</span>
                          </div>
                        )}
                        {recommendation.show_heatmap && hasHeatmap && latestHeatmap?.prediction && (
                          <div className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-2.5 py-1 bg-blue-50 text-blue-700 text-xs rounded-md font-medium border border-blue-100">
                            <span className="font-bold text-blue-500 uppercase tracking-wider text-[10px]">{t('chatComponents.imageRecommendation.pred')}</span>
                            <span className="text-blue-900">{latestHeatmap.prediction}</span>
                          </div>
                        )}
                        {image.event_status !== null && (
                          <span className={`shrink-0 whitespace-nowrap px-2 py-1 text-xs rounded-md font-medium border ${image.event_status === 1
                            ? 'bg-red-50 text-red-700 border-red-100'
                            : 'bg-teal-50 text-teal-700 border-teal-100'
                            }`}>
                            {image.event_status === 1 ? t('chatComponents.imageRecommendation.event') : t('chatComponents.imageRecommendation.censored')}
                          </span>
                        )}
                        {image.event_time !== null && image.event_time !== undefined && (
                          <span className="shrink-0 whitespace-nowrap px-2 py-1 text-xs bg-gray-50 text-gray-600 rounded-md border border-gray-100">
                            {t('chatComponents.imageRecommendation.survivalTimeMonths')}: {image.event_time}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      {imagesWithOverlays.length > 0 && (
        <div className="px-5 py-3 bg-gray-50 border-t border-gray-100">
          <button
            onClick={() => {
              // Save scroll position and conversation ID before navigating
              const messagesContainer = document.querySelector('[data-chat-messages-container]')
              if (messagesContainer) {
                sessionStorage.setItem('ai-chat-scroll-position', String(messagesContainer.scrollTop))
              }
              const conversationId = document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
              if (conversationId) {
                sessionStorage.setItem('ai-chat-conversation-id', conversationId)
              }
              // Navigate to the dataset if specified, otherwise to the general list
              navigate('/wsi-list', {
                state: {
                  fromAIChat: true,
                  dataset_id: recommendation.filters?.dataset_id
                }
              })
            }}
            className="text-sm text-orange-600 hover:text-orange-700 font-medium"
          >
            {t('chatComponents.imageRecommendation.viewAllImages')}
          </button>
        </div>
      )}
    </div>
  )
}
