import { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Image as ImageIcon, ExternalLink, AlertCircle, ImageOff } from 'lucide-react'
import { fetchWSIList, fetchAllResults, getThumbnailUrl, getFileType, type WSISummary } from '../../api'

export interface ImageRecommendation {
  query: string
  filters?: {
    label?: string
    has_predictions?: boolean
    dataset_id?: string
    data_type?: 'wsi' | 'patch' | 'all'
  }
  reason?: string
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

// Global cache for loaded images (persists across component remounts)
const imageCache = new Map<string, { images: WSISummary[]; error: string | null }>()

export function ImageRecommendationCard({ recommendation }: ImageRecommendationCardProps) {
  const navigate = useNavigate()
  const [images, setImages] = useState<WSISummary[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Memoize filter key to prevent unnecessary re-fetches
  const filterKey = useMemo(
    () =>
      JSON.stringify({
        label: recommendation.filters?.label,
        has_predictions: recommendation.filters?.has_predictions,
        dataset_id: recommendation.filters?.dataset_id,
        data_type: recommendation.filters?.data_type
      }),
    [recommendation.filters]
  )

  useEffect(() => {
    // Check cache first
    const cached = imageCache.get(filterKey)
    if (cached) {
      setImages(cached.images)
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
        const resultsWithWsi = resultsData.items

        // We need to get full WSI info, so fetch WSI list and merge
        const wsiResult = await fetchWSIList(recommendation.filters?.dataset_id)

        // Filter to only WSIs that have predictions
        const wsiIdsWithPredictions = new Set(resultsWithWsi.map(r => r.wsi_id))
        let filtered = wsiResult.items.filter(w => wsiIdsWithPredictions.has(w.wsi_id))

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

      // Limit to 3 images for faster loading
      const limitedImages = displayImages.slice(0, 3)
      setImages(limitedImages)
      // Cache the result
      imageCache.set(filterKey, { images: limitedImages, error: null })
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

  return (
    <div className="mt-4 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-4 bg-gradient-to-r from-orange-50 to-amber-50 border-b border-gray-100">
        <h3 className="font-semibold text-gray-900 flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-orange-600" />
          Recommended Images
        </h3>
        {recommendation.reason && (
          <p className="text-sm text-gray-500 mt-1">{recommendation.reason}</p>
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
        ) : images.length === 0 ? (
          <p className="text-sm text-gray-500 py-4 text-center">
            No images found matching your criteria. Try adjusting your search.
          </p>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {images.map(image => {
              const fileType = getFileType(image.wsi_path, image.file_size)
              return (
                <button
                  key={image.wsi_id}
                  onClick={() => handleImageClick(image.wsi_id)}
                  className="group p-3 bg-gray-50 hover:bg-orange-50 rounded-xl border border-gray-200
                             hover:border-orange-300 transition-all text-left"
                >
                  {/* Thumbnail preview */}
                  <div className="w-full h-28 bg-gray-100 rounded-lg mb-2 overflow-hidden relative">
                    <img
                      src={getThumbnailUrl(image.wsi_id, 256)}
                      alt={image.original_filename}
                      className="w-full h-full object-cover"
                      onError={(e) => {
                        // Hide broken image and show placeholder
                        e.currentTarget.style.display = 'none'
                        const placeholder = e.currentTarget.nextElementSibling as HTMLElement
                        if (placeholder) placeholder.style.display = 'flex'
                      }}
                    />
                    <div className="hidden absolute inset-0 items-center justify-center bg-gray-100">
                      <ImageOff className="w-8 h-8 text-gray-300" />
                    </div>
                    {/* File type badge */}
                    <span className={`absolute top-1.5 right-1.5 px-1.5 py-0.5 text-[10px] font-medium rounded ${
                      fileType === 'WSI'
                        ? 'bg-purple-100 text-purple-700 border border-purple-200'
                        : 'bg-green-100 text-green-700 border border-green-200'
                    }`}>
                      {fileType}
                    </span>
                  </div>

                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {image.original_filename}
                      </p>
                      {image.label && (
                        <span className="inline-block mt-1 px-2 py-0.5 bg-orange-100 text-orange-700
                                         text-xs rounded-full">
                          {image.label}
                        </span>
                      )}
                      {image.dataset_name && (
                        <p className="text-xs text-gray-500 mt-1 truncate">
                          {image.dataset_name}
                        </p>
                      )}
                    </div>
                    <ExternalLink className="w-4 h-4 text-gray-400 group-hover:text-orange-600
                                             flex-shrink-0 ml-2" />
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      {images.length > 0 && (
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

