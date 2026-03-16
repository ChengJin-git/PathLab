import { useTranslation } from 'react-i18next'
import { Layers } from 'lucide-react'
import { SEGMENTATION_MASK_COLORS } from '../../api'

interface ViewerOverlayControlsProps {
  canShowHeatmapOverlay: boolean
  showHeatmap: boolean
  onToggleHeatmap: () => void
  heatmapOpacity: number
  onHeatmapOpacityChange: (value: number) => void
  canShowSegMaskOverlay: boolean
  showSegMask: boolean
  onToggleSegMask: () => void
  segmentationClasses: string[]
  canShowGT: boolean
  showGT: boolean
  onToggleGT: () => void
}

export function ViewerOverlayControls({
  canShowHeatmapOverlay,
  showHeatmap,
  onToggleHeatmap,
  heatmapOpacity,
  onHeatmapOpacityChange,
  canShowSegMaskOverlay,
  showSegMask,
  onToggleSegMask,
  segmentationClasses,
  canShowGT,
  showGT,
  onToggleGT,
}: ViewerOverlayControlsProps) {
  const { t } = useTranslation()

  const toggles = [
    canShowHeatmapOverlay
      ? {
        key: 'heatmap',
        active: showHeatmap,
        onClick: onToggleHeatmap,
        label: showHeatmap ? t('wsiViewer.hideHeatmap') : t('wsiViewer.showHeatmap'),
        activeClassName: 'bg-indigo-100 text-indigo-700 border border-indigo-300',
      }
      : null,
    canShowSegMaskOverlay
      ? {
        key: 'seg-mask',
        active: showSegMask,
        onClick: onToggleSegMask,
        label: showSegMask ? t('wsiViewer.hidePredictionMask') : t('wsiViewer.showPredictionMask'),
        activeClassName: 'bg-emerald-100 text-emerald-700 border border-emerald-300',
      }
      : null,
    canShowGT
      ? {
        key: 'gt',
        active: showGT,
        onClick: onToggleGT,
        label: showGT ? t('wsiViewer.hideGT') : t('wsiViewer.showGT'),
        activeClassName: 'bg-amber-100 text-amber-700 border border-amber-300',
      }
      : null,
  ].filter((toggle): toggle is NonNullable<typeof toggle> => toggle !== null)

  return (
    <div className="absolute bottom-4 left-4 right-4 sm:right-auto bg-white/95 backdrop-blur-sm rounded-xl shadow-lg border border-gray-200 p-2 sm:p-3 z-20">
      <div className="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-3">
        {toggles.map((toggle) => (
          <button
            key={toggle.key}
            onClick={toggle.onClick}
            className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-xs sm:text-sm font-medium transition-all ${toggle.active
              ? toggle.activeClassName
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200'
              }`}
          >
            <Layers className="w-4 h-4" />
            {toggle.label}
          </button>
        ))}

        {showHeatmap && (
          <div className="flex items-center gap-2 px-2 sm:px-0 sm:pl-3 border-t sm:border-t-0 sm:border-l border-gray-200 pt-2 sm:pt-0">
            <span className="text-[10px] sm:text-xs text-gray-500 whitespace-nowrap">{t('wsiViewer.opacity')}:</span>
            <input
              type="range"
              min="0.1"
              max="0.9"
              step="0.1"
              value={heatmapOpacity}
              onChange={(event) => onHeatmapOpacityChange(parseFloat(event.target.value))}
              className="flex-1 sm:w-20 accent-indigo-600"
            />
            <span className="text-[10px] sm:text-xs text-gray-600 w-8 text-right px-1">{Math.round(heatmapOpacity * 100)}%</span>
          </div>
        )}
      </div>

      {showHeatmap && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-400 uppercase tracking-wide">{t('wsiViewer.activation')}:</span>
            <div className="flex-1 h-2 rounded-full bg-gradient-to-r from-blue-500 via-green-500 via-yellow-500 to-red-500" />
            <span className="text-[10px] text-gray-500">{t('wsiViewer.lowToHigh')}</span>
          </div>
        </div>
      )}

      {showSegMask && segmentationClasses.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          <div className="text-[10px] text-gray-400 uppercase tracking-wide mb-2">
            {t('wsiViewerComponents.taskSelector.classes')}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {segmentationClasses.map((label, index) => (
              <div
                key={`${label}-${index}`}
                className="flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-2 py-1 text-[11px] text-gray-700"
              >
                <span
                  className="h-2.5 w-2.5 rounded-full border border-gray-200"
                  style={{ backgroundColor: SEGMENTATION_MASK_COLORS[index % SEGMENTATION_MASK_COLORS.length] }}
                />
                <span>{label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}