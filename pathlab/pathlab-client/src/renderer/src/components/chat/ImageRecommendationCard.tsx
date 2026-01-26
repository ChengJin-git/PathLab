import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Image as ImageIcon, ExternalLink, AlertCircle, ImageOff, Layers } from 'lucide-react'
import {
  fetchWSIList,
  fetchAllResults,
  getThumbnailUrl,
  getFileType,
  fetchAvailableHeatmaps,
  getPatchCAMImageUrl,
  getHeatmapThumbnailUrl,
  type WSISummary,
  type AvailableHeatmap
} from '../../api'

export interface ImageRecommendation {
  query: string
  filters?: {
    label?: string
    pred?: string  // Filter by AI prediction result
    has_predictions?: boolean
    dataset_id?: string
    data_type?: 'wsi' | 'patch' | 'all'
  }
  max_count?: number  // Maximum number of images to display (default: 3)
  show_heatmap?: boolean  // Whether to show heatmaps alongside images
  heatmap_filter?: {
    feature_extractor?: string  // Filter heatmaps by feature extractor (e.g., 'uni', 'resnet50')
    aggregator?: string  // Filter heatmaps by aggregator (e.g., 'abmil', 'clam_sb') - WSI only
  }
  reason?: string
}

interface ImageWithHeatmap {
  image: WSISummary
  heatmaps: AvailableHeatmap[]
  hasHeatmap: boolean
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
const imageCache = new Map<string, { images: ImageWithHeatmap[]; error: string | null }>()

export function ImageRecommendationCard({ recommendation }: ImageRecommendationCardProps) {
  const navigate = useNavigate()
  const [imagesWithHeatmaps, setImagesWithHeatmaps] = useState<ImageWithHeatmap[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Determine max count (default 3)
  const maxCount = recommendation.max_count ?? 3

  // Memoize filter key to prevent unnecessary re-fetches
  const filterKey = useMemo(
    () =>
      JSON.stringify({
        label: recommendation.filters?.label,
        pred: recommendation.filters?.pred,
        has_predictions: recommendation.filters?.has_predictions,
        dataset_id: recommendation.filters?.dataset_id,
        data_type: recommendation.filters?.data_type,
        max_count: maxCount,
        show_heatmap: recommendation.show_heatmap
      }),
    [recommendation.filters, maxCount, recommendation.show_heatmap]
  )

  useEffect(() => {
    // Check cache first
    const cached = imageCache.get(filterKey)
    if (cached) {
      setImagesWithHeatmaps(cached.images)
      setError(cached.error)
      setIsLoading(false)
      return
    }

    loadImages()
  }, [filterKey])

  const loadImages = async () => {
    setIsLoading(true)
    setError(null)
    try {
      let displayImages: WSISummary[] = []

      // If has_predictions is true, fetch from results endpoint
      if (recommendation.filters?.has_predictions) {
        const resultsData = await fetchAllResults()
        // Convert ResultWithWSI to WSISummary-like objects
        let resultsWithWsi = resultsData.items

        // Apply pred filter (filter by AI prediction result)
        if (recommendation.filters?.pred) {
          resultsWithWsi = resultsWithWsi.filter(r =>
            r.pred?.toLowerCase().includes(recommendation.filters!.pred!.toLowerCase())
          )
        }

        // We need to get full WSI info, so fetch WSI list and merge
        const wsiResult = await fetchWSIList(recommendation.filters?.dataset_id)

        // Filter to only WSIs that have predictions (and match pred filter if specified)
        const wsiIdsWithPredictions = new Set(resultsWithWsi.map(r => r.wsi_id))
        let filtered = wsiResult.items.filter(w => wsiIdsWithPredictions.has(w.wsi_id))

        // Apply label filter (ground truth label)
        if (recommendation.filters?.label) {
          filtered = filtered.filter(s =>
            s.label?.toLowerCase().includes(recommendation.filters!.label!.toLowerCase())
          )
        }

        // Apply data_type filter
        if (recommendation.filters?.data_type && recommendation.filters.data_type !== 'all') {
          filtered = filtered.filter(s => {
            const fileType = getFileType(s.wsi_path, s.file_size)
            return recommendation.filters!.data_type === 'wsi'
              ? fileType === 'WSI'
              : fileType === 'Patch'
          })
        }

        displayImages = filtered
      } else {
        // Normal fetch without predictions filter
        const result = await fetchWSIList(recommendation.filters?.dataset_id)
        let filtered = result.items

        // Apply label filter
        if (recommendation.filters?.label) {
          filtered = filtered.filter(s =>
            s.label?.toLowerCase().includes(recommendation.filters!.label!.toLowerCase())
          )
        }

        // Apply data_type filter
        if (recommendation.filters?.data_type && recommendation.filters.data_type !== 'all') {
          filtered = filtered.filter(s => {
            const fileType = getFileType(s.wsi_path, s.file_size)
            return recommendation.filters!.data_type === 'wsi'
              ? fileType === 'WSI'
              : fileType === 'Patch'
          })
        }

        displayImages = filtered
      }

      // Limit to user-specified count (default 3)
      const limitedImages = displayImages.slice(0, maxCount)

      // Fetch heatmap availability for each image (if show_heatmap is enabled)
      let imagesWithHeatmapInfo: ImageWithHeatmap[]
      if (recommendation.show_heatmap) {
        // Fetch heatmaps in parallel for all images
        const heatmapPromises = limitedImages.map(async (img) => {
          try {
            let heatmaps = await fetchAvailableHeatmaps(img.wsi_id)

            // Apply heatmap_filter if specified
            if (recommendation.heatmap_filter) {
              const { feature_extractor, aggregator } = recommendation.heatmap_filter
              heatmaps = heatmaps.filter(h => {
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
              heatmaps,
              hasHeatmap: heatmaps.length > 0
            }
          } catch {
            return {
              image: img,
              heatmaps: [],
              hasHeatmap: false
            }
          }
        })
        imagesWithHeatmapInfo = await Promise.all(heatmapPromises)
      } else {
        // Don't fetch heatmaps, just wrap images
        imagesWithHeatmapInfo = limitedImages.map(img => ({
          image: img,
          heatmaps: [],
          hasHeatmap: false
        }))
      }

      setImagesWithHeatmaps(imagesWithHeatmapInfo)
      // Cache the result
      imageCache.set(filterKey, { images: imagesWithHeatmapInfo, error: null })
    } catch (err) {
      setError('Failed to load images')
      console.error('Failed to load images:', err)
      // Cache the error state too
      imageCache.set(filterKey, { images: [], error: 'Failed to load images' })
    } finally {
      setIsLoading(false)
    }
  }

  const handleImageClick = (wsiId: string) => {
    navigate(`/wsi/${wsiId}`)
  }

  // Count images with heatmaps for summary
  const imagesWithHeatmapCount = imagesWithHeatmaps.filter(i => i.hasHeatmap).length

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-orange-50 to-amber-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-orange-600" />
          Recommended Images
          {imagesWithHeatmaps.length > 0 && (
            <span className="text-xs font-normal text-gray-500">
              ({imagesWithHeatmaps.length} image{imagesWithHeatmaps.length > 1 ? 's' : ''})
            </span>
          )}
        </h3>
        {recommendation.reason && (
          <p className="text-sm text-gray-500 mt-1">{recommendation.reason}</p>
        )}
        {/* Heatmap availability summary */}
        {recommendation.show_heatmap && imagesWithHeatmaps.length > 0 && (
          <div className="flex items-center gap-3 mt-2 text-xs">
            {imagesWithHeatmapCount > 0 && (
              <span className="flex items-center gap-1 text-green-600">
                <Layers className="w-3 h-3" />
                {imagesWithHeatmapCount} with heatmap
              </span>
            )}
          </div>
        )}
        {/* Warning when heatmap_filter specified but no matching heatmaps found */}
        {recommendation.show_heatmap && recommendation.heatmap_filter && imagesWithHeatmapCount === 0 && imagesWithHeatmaps.length > 0 && (
          <div className="flex items-center gap-2 mt-2 text-xs text-amber-600 bg-amber-50 px-2 py-1.5 rounded-lg">
            <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
            <span>
              No heatmaps found for the specified model
              {recommendation.heatmap_filter.feature_extractor && ` (${recommendation.heatmap_filter.feature_extractor})`}
              {recommendation.heatmap_filter.aggregator && ` + ${recommendation.heatmap_filter.aggregator.toUpperCase()}`}
            </span>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="p-5">
        {isLoading ? (
          <div className="flex items-center justify-center py-8 text-gray-500">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            Loading images...
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 text-red-600 py-4">
            <AlertCircle className="w-4 h-4" />
            <span className="text-sm">{error}</span>
          </div>
        ) : imagesWithHeatmaps.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">
            No images found matching your criteria. Try adjusting your search.
          </p>
        ) : (
          <div className="space-y-4">
            {imagesWithHeatmaps.map(({ image, heatmaps, hasHeatmap }) => {
              const fileType = getFileType(image.wsi_path, image.file_size)
              const latestHeatmap = heatmaps[0] // Get the most recent heatmap
              return (
                <div
                  key={image.wsi_id}
                  className="group p-4 bg-gray-50 hover:bg-orange-50 rounded-xl border border-gray-200
                             hover:border-orange-300 transition-all"
                >
                  {/* Image row with optional heatmap */}
                  <div className="flex gap-4">
                    {/* Original image */}
                    <button
                      onClick={() => handleImageClick(image.wsi_id)}
                      className="relative flex-shrink-0"
                    >
                      <div className="w-32 h-32 bg-gray-100 rounded-lg overflow-hidden">
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
                      <span className={`absolute top-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded ${
                        fileType === 'WSI'
                          ? 'bg-purple-100 text-purple-700 border border-purple-200'
                          : 'bg-green-100 text-green-700 border border-green-200'
                      }`}>
                        {fileType}
                      </span>
                      <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded bg-white/80 text-gray-600">
                        Original
                      </span>
                    </button>

                    {/* Heatmap (if available and show_heatmap is true) */}
                    {recommendation.show_heatmap && hasHeatmap && latestHeatmap && (
                      <button
                        onClick={() => handleImageClick(image.wsi_id)}
                        className="relative flex-shrink-0"
                      >
                        <div className="w-32 h-32 bg-gray-100 rounded-lg overflow-hidden">
                          <img
                            src={
                              fileType === 'Patch'
                                ? getPatchCAMImageUrl(image.wsi_id, latestHeatmap.task_id || undefined)
                                : getHeatmapThumbnailUrl(image.wsi_id, latestHeatmap.task_id || undefined, 256)
                            }
                            alt={`Heatmap for ${image.original_filename}`}
                            className="w-full h-full object-cover"
                            onError={(e) => {
                              e.currentTarget.style.display = 'none'
                              const placeholder = e.currentTarget.nextElementSibling as HTMLElement
                              if (placeholder) placeholder.style.display = 'flex'
                            }}
                          />
                          <div className="hidden absolute inset-0 items-center justify-center bg-gray-100">
                            <Layers className="w-8 h-8 text-gray-300" />
                          </div>
                        </div>
                        <span className="absolute bottom-1.5 left-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded bg-green-100 text-green-700 border border-green-200">
                          Heatmap
                        </span>
                      </button>
                    )}

                    {/* No heatmap - don't show placeholder, just show original image only */}

                    {/* Image info */}
                    <div className="flex-1 min-w-0 flex flex-col justify-between">
                      <div>
                        <p className="text-sm font-medium text-gray-900 break-all">
                          {image.original_filename}
                        </p>
                        <div className="flex flex-wrap gap-1 mt-2">
                          {image.label && (
                            <span className="px-2 py-0.5 bg-orange-100 text-orange-700 text-xs rounded-full">
                              Label: {image.label}
                            </span>
                          )}
                          {hasHeatmap && latestHeatmap?.prediction && (
                            <span className="px-2 py-0.5 bg-blue-100 text-blue-700 text-xs rounded-full">
                              Pred: {latestHeatmap.prediction}
                            </span>
                          )}
                        </div>
                        {image.dataset_name && (
                          <p className="text-xs text-gray-500 mt-2 truncate">
                            Dataset: {image.dataset_name}
                          </p>
                        )}
                      </div>
                      <button
                        onClick={() => handleImageClick(image.wsi_id)}
                        className="self-start mt-2 text-xs text-orange-600 hover:text-orange-700 font-medium flex items-center gap-1"
                      >
                        View details <ExternalLink className="w-3 h-3" />
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      {imagesWithHeatmaps.length > 0 && (
        <div className="px-5 py-3 bg-gray-50 border-t border-gray-100">
          <button
            onClick={() => navigate('/wsi-list')}
            className="text-sm text-orange-600 hover:text-orange-700 font-medium"
          >
            View all images →
          </button>
        </div>
      )}
    </div>
  )
}

