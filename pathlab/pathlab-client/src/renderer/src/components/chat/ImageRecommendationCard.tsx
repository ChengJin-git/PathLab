import { useState, useEffect, useMemo, useRef, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2, Image as ImageIcon, ExternalLink, AlertCircle, ImageOff, Layers } from 'lucide-react'
import {
  fetchWSIList,
  fetchWSIIds,
  fetchWSIDetail,
  fetchAllResults,
  getRecommendationThumbnailUrl as getThumbnailUrl,
  fetchAvailableHeatmaps,
  getRecommendationPatchCAMImageUrl as getPatchCAMImageUrl,
  getRecommendationHeatmapThumbnailUrl as getHeatmapThumbnailUrl,
  getRecommendationSegMaskImageUrl as getSegMaskImageUrl,
  getLabelThumbnailUrl,
  getWSILabels,
  type WSISummary,
  type ResultWithWSI,
  type AvailableHeatmap
} from '../../api'
import { getFileType } from '../../constants/fileTypes'
import { isSegmentationTask } from '../../constants/training'
import { parseLastChatBlockJson, stripChatBlocks } from './chatBlockParsing'

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
    correct_prediction?: boolean  // Filter images where AI prediction matches ground truth label
    segmentation_class?: string  // Filter segmentation results containing a specific class
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
  resultPrediction: string | null
}

interface ViewerNavigationState {
  fromAIChat: boolean
  conversationId?: string
  chatScrollPosition?: string
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
  return parseLastChatBlockJson<ImageRecommendation>(content, 'IMAGE_RECOMMENDATION', { allowIncompleteLast: true })
}

/**
 * Remove [IMAGE_RECOMMENDATION] block from content for display
 */
export function removeImageRecommendationBlock(content: string): string {
  return stripChatBlocks(content, 'IMAGE_RECOMMENDATION').trim()
}

// Global cache for loaded images with heatmap info (persists across component remounts)
const RECOMMENDATION_CACHE_TTL_MS = 5 * 60 * 1000
const RECOMMENDATION_ERROR_CACHE_TTL_MS = 20 * 1000
const RECOMMENDATION_CACHE_MAX_ENTRIES = 120

interface RecommendationCacheSnapshot {
  images: ImageWithOverlays[]
  error: string | null
}

interface RecommendationCacheEntry {
  value: RecommendationCacheSnapshot
  timestamp: number
}

type RecommendationFilterSignature = {
  query: string
  label: string | null
  pred: string | null
  has_predictions: boolean
  correct_prediction: boolean | null
  segmentation_class: string | null
  dataset_id: string | null
  data_type: 'wsi' | 'patch' | 'all' | null
  event_status: number | null
  max_count: number
  show_heatmap: boolean
  heatmap_filter_feature_extractor: string | null
  heatmap_filter_aggregator: string | null
  segmentation_mask_source: SegmentationMaskSource | null
  segmentation_mask_task_id: string | null
}

function buildRecommendationFilterSignature(
  recommendation: ImageRecommendation,
  maxCount: number,
): RecommendationFilterSignature {
  return {
    query: recommendation.query,
    label: recommendation.filters?.label ?? null,
    pred: recommendation.filters?.pred ?? null,
    has_predictions: recommendation.filters?.has_predictions === true,
    correct_prediction: recommendation.filters?.correct_prediction ?? null,
    segmentation_class: recommendation.filters?.segmentation_class ?? null,
    dataset_id: recommendation.filters?.dataset_id ?? null,
    data_type: recommendation.filters?.data_type ?? null,
    event_status: recommendation.filters?.event_status ?? null,
    max_count: maxCount,
    show_heatmap: recommendation.show_heatmap === true,
    heatmap_filter_feature_extractor: recommendation.heatmap_filter?.feature_extractor ?? null,
    heatmap_filter_aggregator: recommendation.heatmap_filter?.aggregator ?? null,
    segmentation_mask_source: recommendation.segmentation_mask?.source ?? null,
    segmentation_mask_task_id: recommendation.segmentation_mask?.task_id ?? null,
  }
}

function buildRecommendationFilterKey(signature: RecommendationFilterSignature): string {
  return JSON.stringify(signature)
}

const recommendationCache = new Map<string, RecommendationCacheEntry>()
const recommendationInFlightRequests = new Map<string, Promise<RecommendationCacheSnapshot>>()

function getCachedRecommendation(key: string): RecommendationCacheSnapshot | null {
  const cached = recommendationCache.get(key)
  if (!cached) return null

  const ttl = cached.value.error ? RECOMMENDATION_ERROR_CACHE_TTL_MS : RECOMMENDATION_CACHE_TTL_MS
  if (Date.now() - cached.timestamp >= ttl) {
    recommendationCache.delete(key)
    return null
  }

  return cached.value
}

function setCachedRecommendation(key: string, value: RecommendationCacheSnapshot): void {
  recommendationCache.set(key, {
    value,
    timestamp: Date.now(),
  })

  if (recommendationCache.size <= RECOMMENDATION_CACHE_MAX_ENTRIES) return

  let oldestKey: string | null = null
  let oldestTimestamp = Number.POSITIVE_INFINITY
  for (const [entryKey, entry] of recommendationCache.entries()) {
    if (entry.timestamp < oldestTimestamp) {
      oldestTimestamp = entry.timestamp
      oldestKey = entryKey
    }
  }

  if (oldestKey) {
    recommendationCache.delete(oldestKey)
  }
}

const CARD_THUMBNAIL_SIZE = 160
const OVERLAY_FETCH_CONCURRENCY = 4
const DETAIL_FETCH_CONCURRENCY = 3
const OVERLAY_THUMBNAIL_LOAD_CONCURRENCY = 4

interface QueueWaiter {
  cancelled: boolean
  resolve: (release: () => void) => void
}

function createImageLoadQueue(limit: number) {
  let active = 0
  const waiters: QueueWaiter[] = []

  const pump = () => {
    while (active < limit && waiters.length > 0) {
      const waiter = waiters.shift()
      if (!waiter || waiter.cancelled) continue

      active += 1
      let released = false
      waiter.resolve(() => {
        if (released) return
        released = true
        active = Math.max(0, active - 1)
        pump()
      })
    }
  }

  return {
    acquire() {
      let waiterRef: QueueWaiter | null = null
      const promise = new Promise<() => void>((resolve) => {
        waiterRef = { cancelled: false, resolve }
        waiters.push(waiterRef)
        pump()
      })

      return {
        promise,
        cancel: () => {
          if (waiterRef) waiterRef.cancelled = true
        }
      }
    }
  }
}

const overlayThumbnailLoadQueue = createImageLoadQueue(OVERLAY_THUMBNAIL_LOAD_CONCURRENCY)

async function mapWithConcurrencyLimit<T, R>(
  items: T[],
  limit: number,
  mapper: (item: T, index: number) => Promise<R>,
): Promise<R[]> {
  if (items.length === 0) return []

  const workerCount = Math.max(1, Math.min(limit, items.length))
  const results = new Array<R>(items.length)
  let nextIndex = 0

  const worker = async () => {
    while (nextIndex < items.length) {
      const currentIndex = nextIndex
      nextIndex += 1
      results[currentIndex] = await mapper(items[currentIndex], currentIndex)
    }
  }

  await Promise.all(Array.from({ length: workerCount }, () => worker()))
  return results
}

function getFileExtensionFromName(filename: string): string {
  const lastDot = filename.lastIndexOf('.')
  return lastDot >= 0 ? filename.slice(lastDot).toLowerCase() : ''
}

function inferResultDataType(result: ResultWithWSI, recommendation: ImageRecommendation): 'wsi' | 'patch' | null {
  if (recommendation.filters?.data_type === 'wsi' || recommendation.filters?.data_type === 'patch') {
    return recommendation.filters.data_type
  }
  return getFileType(getFileExtensionFromName(result.original_filename), 0) === 'Patch' ? 'patch' : 'wsi'
}

function buildPreviewSummaryFromResult(result: ResultWithWSI, recommendation: ImageRecommendation): WSISummary {
  return {
    wsi_id: result.wsi_id,
    original_filename: result.original_filename,
    dataset_id: recommendation.filters?.dataset_id ?? null,
    dataset_name: null,
    case_id: result.case_id,
    label: result.label,
    file_extension: getFileExtensionFromName(result.original_filename),
    age: null,
    gender: null,
    source: null,
    event_time: null,
    event_status: null,
    split: null,
    file_size: null,
    data_type: inferResultDataType(result, recommendation),
    created_at: result.created_at,
  }
}

function dedupeLatestResultsByWsi(items: ResultWithWSI[]): ResultWithWSI[] {
  const seen = new Set<string>()
  const deduped: ResultWithWSI[] = []
  for (const item of items) {
    if (seen.has(item.wsi_id)) continue
    seen.add(item.wsi_id)
    deduped.push(item)
  }
  return deduped
}

function getLatestSegmentationMaskOverlay(overlays: AvailableHeatmap[], taskId?: string): AvailableHeatmap | undefined {
  const segmentationOverlays = overlays.filter(o => isSegmentationTask(o.task_type))
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
  className = 'relative flex-1 min-w-[60px] aspect-square md:flex-none md:flex-shrink-0 md:snap-start md:aspect-auto md:w-32 md:h-32 group/img',
}: {
  src: string
  alt: string
  onClick: () => void
  title: string
  badgeLabel: string
  badgeClassName: string
  fallback: ReactNode
  loadingColorClass: string
  className?: string
}) {
  const [loadState, setLoadState] = useState<'queued' | 'loading' | 'ready' | 'error'>('queued')
  const releaseLoadSlotRef = useRef<(() => void) | null>(null)

  const releaseLoadSlot = () => {
    releaseLoadSlotRef.current?.()
    releaseLoadSlotRef.current = null
  }

  useEffect(() => {
    releaseLoadSlot()
    setLoadState('queued')

    let active = true
    const ticket = overlayThumbnailLoadQueue.acquire()

    void ticket.promise.then((releaseSlot) => {
      if (!active) {
        releaseSlot()
        return
      }

      releaseLoadSlotRef.current = releaseSlot
      setLoadState('loading')
    })

    return () => {
      active = false
      ticket.cancel()
      releaseLoadSlot()
    }
  }, [src])

  return (
    <button
      onClick={onClick}
      className={className}
      title={title}
    >
      <div className="relative w-full h-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200 group-hover/img:border-orange-300 shadow-sm transition-colors">
        {loadState !== 'error' && loadState !== 'queued' && (
          <img
            src={src}
            alt={alt}
            className={`w-full h-full object-cover ${loadState === 'ready' ? 'opacity-100' : 'opacity-0'}`}
            loading="lazy"
            decoding="async"
            onLoad={() => {
              releaseLoadSlot()
              setLoadState('ready')
            }}
            onError={() => {
              releaseLoadSlot()
              setLoadState('error')
            }}
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
  className = 'relative flex-1 min-w-[60px] aspect-square md:flex-none md:flex-shrink-0 md:snap-start md:aspect-auto md:w-32 md:h-32',
}: {
  title: string
  badgeLabel: string
  badgeClassName: string
  loadingColorClass: string
  className?: string
}) {
  return (
    <div
      className={className}
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
  const [status, setStatus] = useState<'queued' | 'loading' | 'ready' | 'empty' | 'error'>('queued')
  const isActiveRef = useRef(true)
  const releaseLoadSlotRef = useRef<(() => void) | null>(null)
  const gtThumbnailUrl = useMemo(
    () => getLabelThumbnailUrl(image.wsi_id, CARD_THUMBNAIL_SIZE),
    [image.wsi_id]
  )

  const releaseLoadSlot = () => {
    releaseLoadSlotRef.current?.()
    releaseLoadSlotRef.current = null
  }

  useEffect(() => {
    let active = true
    isActiveRef.current = true

    releaseLoadSlot()
    setStatus('queued')
    const ticket = overlayThumbnailLoadQueue.acquire()

    void ticket.promise.then((releaseSlot) => {
      if (!active) {
        releaseSlot()
        return
      }

      releaseLoadSlotRef.current = releaseSlot
      setStatus('loading')
    })

    return () => {
      active = false
      isActiveRef.current = false
      ticket.cancel()
      releaseLoadSlot()
    }
  }, [gtThumbnailUrl])

  const handleLoadError = () => {
    releaseLoadSlot()
    void getWSILabels(image.wsi_id)
      .then((gtResult) => {
        if (!isActiveRef.current) return
        const nextRegions = gtResult.annotations?.[image.wsi_id] || []
        setStatus(nextRegions.length > 0 ? 'error' : 'empty')
      })
      .catch(() => {
        if (!isActiveRef.current) return
        setStatus('error')
      })
  }

  return (
    <button
      onClick={onClick}
      className="relative w-full h-full group/img"
      title={t('chatComponents.imageRecommendation.groundTruthMask')}
    >
      <div className="relative w-full h-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200 group-hover/img:border-orange-300 shadow-sm transition-colors">
        {status !== 'queued' && status !== 'empty' && status !== 'error' && (
          <img
            src={gtThumbnailUrl}
            alt={`${t('chatComponents.imageRecommendation.groundTruthMask')}: ${image.original_filename}`}
            className={`w-full h-full object-cover ${status === 'ready' ? 'opacity-100' : 'opacity-0'}`}
            loading="lazy"
            decoding="async"
            onLoad={() => {
              releaseLoadSlot()
              setStatus('ready')
            }}
            onError={handleLoadError}
          />
        )}

        {(status === 'queued' || status === 'loading') && (
          <div className="absolute inset-0 flex items-center justify-center bg-white/70">
            <Loader2 className="w-5 h-5 text-violet-500 animate-spin" />
          </div>
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

        {status === 'error' && (
          <div className="absolute inset-0 hidden items-center justify-center bg-gray-100">
            <ImageOff className="w-8 h-8 text-gray-300" />
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
  const filterSignature = useMemo(
    () => buildRecommendationFilterSignature(recommendation, maxCount),
    [
      recommendation.query,
      recommendation.filters?.label,
      recommendation.filters?.pred,
      recommendation.filters?.has_predictions,
      recommendation.filters?.dataset_id,
      recommendation.filters?.data_type,
      recommendation.filters?.event_status,
      recommendation.show_heatmap,
      recommendation.heatmap_filter?.feature_extractor,
      recommendation.heatmap_filter?.aggregator,
      recommendation.segmentation_mask?.source,
      recommendation.segmentation_mask?.task_id,
      maxCount,
    ]
  )

  const filterKey = useMemo(
    () => buildRecommendationFilterKey(filterSignature),
    [filterSignature]
  )

  useEffect(() => {
    let active = true

    // Check cache first
    const cached = getCachedRecommendation(filterKey)
    if (cached) {
      setImagesWithOverlays(cached.images)
      setError(cached.error)
      setIsOverlayInfoLoading(false)
      setIsLoading(false)
      return () => {
        active = false
      }
    }

    const inFlight = recommendationInFlightRequests.get(filterKey)
    if (inFlight) {
      void inFlight.then((result) => {
        if (!active || result == null) return
        setImagesWithOverlays(result.images)
        setError(result.error)
        setIsOverlayInfoLoading(false)
        setIsLoading(false)
      })
      return () => {
        active = false
      }
    }

    const requestPromise = loadImages(() => active)
      .finally(() => {
        if (recommendationInFlightRequests.get(filterKey) === requestPromise) {
          recommendationInFlightRequests.delete(filterKey)
        }
      })
    recommendationInFlightRequests.set(filterKey, requestPromise)

    return () => {
      active = false
    }
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

  const loadImages = async (isActive: () => boolean = () => true): Promise<RecommendationCacheSnapshot> => {
    if (isActive()) {
      setIsLoading(true)
      setIsOverlayInfoLoading(false)
      setError(null)
    }
    try {
      let displayImages: WSISummary[] = []
      let predictionByWsiId = new Map<string, string | null>()
      let shouldHydrateLimitedImages = false

      const needsPredictionsPath = !!(
        recommendation.filters?.has_predictions ||
        recommendation.filters?.pred ||
        recommendation.filters?.correct_prediction !== undefined ||
        recommendation.filters?.segmentation_class ||
        recommendation.segmentation_mask?.source === 'model_pred' ||
        recommendation.segmentation_mask?.source === 'both'
      )

      if (needsPredictionsPath) {
        const resultsData = await fetchAllResults()
        let resultsWithWsi = dedupeLatestResultsByWsi(resultsData.items)

        if (recommendation.filters?.pred) {
          resultsWithWsi = resultsWithWsi.filter(r =>
            r.pred?.toLowerCase() === recommendation.filters!.pred!.toLowerCase()
          )
        }

        if (recommendation.filters?.correct_prediction !== undefined) {
          const wantCorrect = recommendation.filters.correct_prediction
          resultsWithWsi = resultsWithWsi.filter(r => {
            const isCorrect = r.pred != null && r.label != null &&
              r.pred.toLowerCase() === r.label.toLowerCase()
            return wantCorrect ? isCorrect : !isCorrect
          })
        }

        if (recommendation.filters?.segmentation_class) {
          const targetClass = recommendation.filters.segmentation_class.toLowerCase()
          resultsWithWsi = resultsWithWsi.filter(r => {
            const classNames = (r as ResultWithWSI & { extra_metadata?: { class_names?: string[] } }).extra_metadata?.class_names
            return Array.isArray(classNames) && classNames.some(c => c.toLowerCase() === targetClass)
          })
        }

        if (recommendation.filters?.label) {
          resultsWithWsi = resultsWithWsi.filter(r =>
            r.label?.toLowerCase() === recommendation.filters!.label!.toLowerCase()
          )
        }

        if (recommendation.filters?.dataset_id) {
          const matchingWsiIds = await fetchWSIIds(
            recommendation.filters.dataset_id,
            recommendation.filters.data_type && recommendation.filters.data_type !== 'all'
              ? recommendation.filters.data_type
              : undefined,
          )
          const allowedIds = new Set(matchingWsiIds.items)
          resultsWithWsi = resultsWithWsi.filter(r => allowedIds.has(r.wsi_id))
        }

        if (recommendation.filters?.data_type && recommendation.filters.data_type !== 'all') {
          resultsWithWsi = resultsWithWsi.filter(r => inferResultDataType(r, recommendation) === recommendation.filters!.data_type)
        }

        predictionByWsiId = new Map(resultsWithWsi.map(r => [r.wsi_id, r.pred ?? null]))

        const requiresFullWsiScan = recommendation.filters?.event_status !== undefined && recommendation.filters?.event_status !== null
        if (requiresFullWsiScan) {
          const wsiResult = await fetchWSIList(recommendation.filters?.dataset_id)
          const wsiIdsWithPredictions = new Set(resultsWithWsi.map(r => r.wsi_id))
          let filtered = wsiResult.items.filter(w => wsiIdsWithPredictions.has(w.wsi_id))
          filtered = filtered.filter(s => s.event_status === recommendation.filters!.event_status)

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
          displayImages = resultsWithWsi.map(result => buildPreviewSummaryFromResult(result, recommendation))
          shouldHydrateLimitedImages = true
        }
      } else {
        displayImages = await fetchAndFilterWSIList(recommendation)
      }

      // Fallback: if predictions path returned nothing, retry with the WSI list.
      // This handles large datasets where the 1000-record limit in fetchAllResults
      // truncates results, as well as cases where AIResult records don't exist yet.
      if (needsPredictionsPath && displayImages.length === 0) {
        console.warn('[ImageRecommendation] No images found via predictions path, falling back to dataset images')
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
        resultPrediction: predictionByWsiId.get(img.wsi_id) ?? null,
      }))

      if (isActive()) {
        setImagesWithOverlays(baseImageInfo)
        setIsLoading(false)
      }

      const hydratedImagesPromise = shouldHydrateLimitedImages
        ? mapWithConcurrencyLimit(limitedImages, DETAIL_FETCH_CONCURRENCY, async (img) => {
          if (!isActive()) return null
          try {
            const detail = await fetchWSIDetail(img.wsi_id)
            return isActive() ? detail.meta : null
          } catch {
            return null
          }
        })
        : Promise.resolve<WSISummary[]>([])

      let imageOverlayInfo: ImageWithOverlays[]
      if (needsOverlayLookup) {
        if (isActive()) {
          setIsOverlayInfoLoading(true)
        }
        imageOverlayInfo = await mapWithConcurrencyLimit(limitedImages, OVERLAY_FETCH_CONCURRENCY, async (img) => {
          if (!isActive()) {
            return {
              image: img,
              overlays: [],
              resultPrediction: predictionByWsiId.get(img.wsi_id) ?? null,
            }
          }

          try {
            let overlays = await fetchAvailableHeatmaps(img.wsi_id)
            if (!isActive()) {
              return {
                image: img,
                overlays: [],
                resultPrediction: predictionByWsiId.get(img.wsi_id) ?? null,
              }
            }

            // Apply heatmap_filter if specified
            if (recommendation.heatmap_filter) {
              const { feature_extractor, aggregator } = recommendation.heatmap_filter
              overlays = overlays.filter(h => {
                if (isSegmentationTask(h.task_type)) {
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
                // Filter by aggregator if specified (WSI-level overlays only; patch CAM overlays have no aggregator)
                if (aggregator && h.data_type !== 'patch') {
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
              resultPrediction: predictionByWsiId.get(img.wsi_id) ?? null,
            }
          } catch {
            return {
              image: img,
              overlays: [],
              resultPrediction: predictionByWsiId.get(img.wsi_id) ?? null,
            }
          }
        })
      } else {
        imageOverlayInfo = baseImageInfo
      }

      const hydratedImages = await hydratedImagesPromise
      if (hydratedImages.length > 0) {
        const hydratedById = new Map(hydratedImages.filter((img): img is WSISummary => !!img).map(img => [img.wsi_id, img]))
        imageOverlayInfo = imageOverlayInfo.map(item => ({
          ...item,
          image: hydratedById.get(item.image.wsi_id)
            ? { ...item.image, ...hydratedById.get(item.image.wsi_id)! }
            : item.image,
        }))
      }

      // Cache the result
      const cacheValue = { images: imageOverlayInfo, error: null }
      if (isActive()) {
        setImagesWithOverlays(imageOverlayInfo)
      }
      setCachedRecommendation(filterKey, cacheValue)
      return cacheValue
    } catch (err) {
      const errorMessage = t('chatComponents.imageRecommendation.failedToLoad')
      if (isActive()) {
        setImagesWithOverlays([])
        setError(errorMessage)
      }
      console.error('Failed to load images:', err)
      // Cache the error state too
      const cacheValue = { images: [], error: errorMessage }
      setCachedRecommendation(filterKey, cacheValue)
      return cacheValue
    } finally {
      if (isActive()) {
        setIsOverlayInfoLoading(false)
        setIsLoading(false)
      }
    }
  }

  const handleImageClick = (wsiId: string, heatmapOverlay?: AvailableHeatmap) => {
    // Save scroll position and conversation ID before navigating
    const messagesContainer = document.querySelector('[data-chat-messages-container]')
    const scrollPosition = messagesContainer ? String(messagesContainer.scrollTop) : undefined
    if (messagesContainer) {
      sessionStorage.setItem('ai-chat-scroll-position', scrollPosition || '0')
    }
    const conversationId = document.querySelector('[data-current-conversation-id]')?.getAttribute('data-current-conversation-id')
    if (conversationId) {
      sessionStorage.setItem('ai-chat-conversation-id', conversationId)
    }
    const navigationState: ViewerNavigationState = {
      fromAIChat: true,
      conversationId: conversationId || undefined,
      chatScrollPosition: scrollPosition,
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
    overlays.some(o => isSegmentationTask(o.task_type))
  ).length

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-3 py-3 sm:px-5 sm:py-4 bg-gradient-to-r from-orange-50 to-amber-50 border-b border-gray-100">
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
      <div className="p-3 sm:p-4">
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
            {imagesWithOverlays.map(({ image, overlays, resultPrediction }) => {
              const fileType = getFileType(image.file_extension, image.file_size, image.data_type)
              const latestSegmentationMask = getLatestSegmentationMaskOverlay(overlays, segmentationMaskConfig?.task_id)
              const latestHeatmap = getPreferredHeatmapOverlay(
                overlays,
                isSegmentationCard ? (latestSegmentationMask?.task_id ?? segmentationMaskConfig?.task_id) : undefined,
              )
              const hasHeatmap = !!latestHeatmap
              const displayPrediction = resultPrediction ?? latestHeatmap?.prediction ?? null
              const showOverlayLoadingPlaceholder = needsOverlayLookup && isOverlayInfoLoading
              // Count thumbnails to decide mobile layout: ≤2 → flex row, >2 → 2×2 grid
              const thumbnailCount = 1
                + (recommendation.show_heatmap && (hasHeatmap || showOverlayLoadingPlaceholder) ? 1 : 0)
                + (wantsPredictionMask && fileType === 'Patch' ? 1 : 0)
                + (wantsGroundTruthMask && fileType === 'Patch' ? 1 : 0)
              const useDesktopSegmentationGridLayout = isSegmentationCard && fileType === 'Patch' && thumbnailCount === 4
              const thumbnailClassName = useDesktopSegmentationGridLayout
                ? 'relative flex-1 min-w-[60px] aspect-square md:w-full md:aspect-square group/img'
                : 'relative flex-1 min-w-[60px] aspect-square md:flex-none md:flex-shrink-0 md:snap-start md:aspect-auto md:w-32 md:h-32 group/img'
              const thumbnailSlotClassName = useDesktopSegmentationGridLayout
                ? 'relative flex-1 min-w-[60px] aspect-square md:w-full md:aspect-square'
                : 'relative flex-1 min-w-[60px] aspect-square md:flex-none md:flex-shrink-0 md:snap-start md:aspect-auto md:w-32 md:h-32'
              const thumbnailsContainerClassName = useDesktopSegmentationGridLayout
                ? `${thumbnailCount > 2 ? 'grid grid-cols-2' : 'flex'} gap-2 w-full md:grid md:grid-cols-4`
                : `${thumbnailCount > 2 ? 'grid grid-cols-2' : 'flex'} gap-2 w-full md:flex md:w-auto md:overflow-x-auto md:snap-x md:[&::-webkit-scrollbar]:hidden md:[-ms-overflow-style:none] md:[scrollbar-width:none] md:shrink-0`
              return (
                <div
                  key={image.wsi_id}
                  className="group p-3 sm:p-4 bg-gray-50 hover:bg-orange-50 rounded-xl border border-gray-200 hover:border-orange-300 transition-all"
                >
                  <div className={useDesktopSegmentationGridLayout ? 'flex flex-col gap-3' : 'flex flex-col md:flex-row md:flex-wrap md:items-start gap-3'}>
                    {/* Images Container - keep 2×2 grid for >2 thumbnails on mobile/small screens; switch to horizontal strip on desktop */}
                    <div className={thumbnailsContainerClassName}>
                      {/* Original image */}
                      <button
                        onClick={() => handleImageClick(image.wsi_id, latestHeatmap)}
                        className={thumbnailClassName}
                      >
                        <div className="w-full h-full bg-gray-100 rounded-lg overflow-hidden border border-gray-200 group-hover/img:border-orange-300 shadow-sm transition-colors">
                          <img
                            src={getThumbnailUrl(image.wsi_id, CARD_THUMBNAIL_SIZE)}
                            alt={image.original_filename}
                            className="w-full h-full object-cover"
                            loading="lazy"
                            decoding="async"
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
                            className={thumbnailClassName}
                          />
                        ) : showOverlayLoadingPlaceholder ? (
                          <PendingThumbnailSlot
                            title={t('chatComponents.imageRecommendation.heatmap')}
                            badgeLabel={t('chatComponents.imageRecommendation.heatmap')}
                            badgeClassName="bg-green-100/90 text-green-700"
                            loadingColorClass="text-green-500"
                            className={thumbnailSlotClassName}
                          />
                        ) : null
                      )}

                      {wantsPredictionMask && fileType === 'Patch' && (
                        latestSegmentationMask ? (
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
                            className={thumbnailClassName}
                          />
                        ) : showOverlayLoadingPlaceholder ? (
                          <PendingThumbnailSlot
                            title={t('chatComponents.imageRecommendation.modelPredictionMask')}
                            badgeLabel={t('chatComponents.imageRecommendation.modelPredictionMaskShort')}
                            badgeClassName="bg-indigo-100/90 text-indigo-700"
                            loadingColorClass="text-indigo-500"
                            className={thumbnailSlotClassName}
                          />
                        ) : (
                          <div className={thumbnailSlotClassName}>
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
                        <div className={`${thumbnailSlotClassName} shadow-sm rounded-lg`}>
                          <GroundTruthMaskThumbnail
                            image={image}
                            onClick={() => handleImageClick(image.wsi_id, latestHeatmap)}
                          />
                        </div>
                      )}
                    </div>

                    {/* Image info */}
                    <div className={`w-full md:min-w-0 flex flex-col pt-2 ${useDesktopSegmentationGridLayout ? 'md:pt-0' : 'md:flex-1 md:pt-1'}`}>
                      <div className={useDesktopSegmentationGridLayout ? 'flex flex-col sm:flex-row sm:justify-between sm:items-start gap-2' : 'flex justify-between items-start gap-2'}>
                        <p className="text-sm sm:text-base font-semibold text-gray-900 break-all leading-tight">
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
                        {displayPrediction && (
                          <div className="inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap px-2.5 py-1 bg-blue-50 text-blue-700 text-xs rounded-md font-medium border border-blue-100">
                            <span className="font-bold text-blue-500 uppercase tracking-wider text-[10px]">{t('chatComponents.imageRecommendation.pred')}</span>
                            <span className="text-blue-900">{displayPrediction}</span>
                          </div>
                        )}
                        {image.label && (
                          <div className="inline-flex shrink-0 items-center whitespace-nowrap px-2 py-1 bg-amber-50 text-amber-700 text-xs rounded-md font-medium border border-amber-100">
                            {t('chatComponents.imageRecommendation.label')}: <span className="text-amber-900 ml-1">{image.label}</span>
                          </div>
                        )}
                        {wantsPredictionMask && latestSegmentationMask?.task_name && (
                          <div className="inline-flex max-w-full flex-wrap items-center gap-1.5 px-2.5 py-1 bg-indigo-50 text-indigo-700 text-xs rounded-md font-medium border border-indigo-100">
                            <span className="shrink-0 font-bold text-indigo-500 uppercase tracking-wider text-[10px]">{t('chatComponents.imageRecommendation.maskModel')}</span>
                            <span className="min-w-0 whitespace-normal break-words text-indigo-900">{latestSegmentationMask.task_name}</span>
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
        <div className="px-3 py-2 sm:px-5 sm:py-3 bg-gray-50 border-t border-gray-100">
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
