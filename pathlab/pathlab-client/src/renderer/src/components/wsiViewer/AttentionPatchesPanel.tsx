import { useTranslation } from 'react-i18next'
import { HeatmapData, PatchCAMData, getPatchImageUrl } from '../../api'
import { Card } from '../common'
import { Badge } from '../ui/badge'
import { Layers, TrendingUp, TrendingDown, Download, Loader2 } from 'lucide-react'

interface AttentionPatchesPanelProps {
  heatmapData: HeatmapData | null
  patchCAMData: PatchCAMData | null
  wsi_id: string
  isPatchLevel: boolean
  exportingTop: boolean
  exportingBottom: boolean
  handleExportTop: () => void
  handleExportBottom: () => void
}

export function AttentionPatchesPanel({
  heatmapData,
  patchCAMData,
  wsi_id,
  isPatchLevel,
  exportingTop,
  exportingBottom,
  handleExportTop,
  handleExportBottom
}: AttentionPatchesPanelProps) {
  const { t } = useTranslation()
  return (
    <>
      {/* Patch Heatmap Info Card - only for patch-level tasks */}
      {isPatchLevel && patchCAMData && (
        <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200 shrink-0" noPadding>
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-orange-50/50 to-white">
            <div className="p-1.5 bg-orange-100/50 rounded-md">
              <Layers className="w-4 h-4 text-orange-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900 tracking-tight">{t('wsiViewerComponents.attentionPatchesPanel.classActivationMap')}</h3>
          </div>
          <div className="p-5">
            <p className="text-sm text-gray-600 mb-3">
              {t('wsiViewerComponents.attentionPatchesPanel.heatmapDescription')}
            </p>
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span className="font-medium">{t('wsiViewerComponents.attentionPatchesPanel.heatmapSize')}:</span>
              <span>{patchCAMData.cam_size?.[0]} × {patchCAMData.cam_size?.[1]}</span>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-[10px] text-gray-400 uppercase tracking-wide">{t('wsiViewerComponents.attentionPatchesPanel.activation')}:</span>
              <div className="flex-1 h-2 rounded-full bg-gradient-to-r from-blue-500 via-green-500 via-yellow-500 to-red-500"></div>
              <span className="text-[10px] text-gray-500">{t('wsiViewerComponents.attentionPatchesPanel.lowToHigh')}</span>
            </div>
          </div>
        </Card>
      )}

      {/* Top Attention Patches Card - only for WSI-level tasks */}
      {!isPatchLevel && heatmapData?.top_patches && heatmapData.top_patches.length > 0 && (
        <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200 shrink-0" noPadding>
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-red-50/50 to-white">
            <div className="p-1.5 bg-red-100/50 rounded-md">
              <TrendingUp className="w-4 h-4 text-red-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900 tracking-tight">{t('wsiViewerComponents.attentionPatchesPanel.highAttentionRegions')}</h3>
            <div className="ml-auto flex items-center gap-2 sm:gap-3">
              <Badge variant="secondary" className="bg-red-50 text-red-700 hover:bg-red-100 px-2 sm:px-2.5 font-semibold text-[10px] sm:text-xs">
                {t('wsiViewerComponents.attentionPatchesPanel.top10')}
              </Badge>
              <button
                onClick={handleExportTop}
                disabled={exportingTop}
                className="text-gray-400 hover:text-red-600 transition-colors"
                title={t('wsiViewerComponents.attentionPatchesPanel.exportTopPatches')}
              >
                {exportingTop ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Download className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
          <div className="p-3 sm:p-5">
            <div className="grid grid-cols-3 xs:grid-cols-4 sm:grid-cols-5 gap-2 sm:gap-3">
              {heatmapData.top_patches.map((patch, idx) => (
                <div
                  key={`top-${idx}`}
                  className="relative aspect-square rounded-xl overflow-hidden border border-gray-100 shadow-sm hover:ring-2 hover:ring-red-500 hover:shadow-lg transition-all duration-300 cursor-pointer group"
                  title={`Attention: ${(patch.weight * 100).toFixed(1)}%\nPosition: (${patch.x}, ${patch.y})`}
                >
                  <img
                    src={getPatchImageUrl(wsi_id, patch.x, patch.y, 256)}
                    alt={`Top ${idx + 1}`}
                    className="w-full h-full object-cover transform group-hover:scale-110 transition-transform duration-500"
                    loading="lazy"
                  />
                  <div className="absolute top-1 left-1 bg-red-600/90 backdrop-blur-sm text-white text-[10px] font-bold w-5 h-5 flex items-center justify-center rounded-lg shadow-sm">
                    {idx + 1}
                  </div>
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-1.5 opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-2 group-hover:translate-y-0">
                    <span className="text-[10px] text-white font-medium flex justify-center">
                      {(patch.weight * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Bottom Attention Patches Card - only for WSI-level tasks */}
      {!isPatchLevel && heatmapData?.bottom_patches && heatmapData.bottom_patches.length > 0 && (
        <Card className="overflow-hidden border-0 shadow-sm ring-1 ring-gray-200 shrink-0" noPadding>
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-blue-50/50 to-white">
            <div className="p-1.5 bg-blue-100/50 rounded-md">
              <TrendingDown className="w-4 h-4 text-blue-600" />
            </div>
            <h3 className="text-sm font-semibold text-gray-900 tracking-tight">{t('wsiViewerComponents.attentionPatchesPanel.lowAttentionRegions')}</h3>
            <div className="ml-auto flex items-center gap-2 sm:gap-3">
              <Badge variant="secondary" className="bg-blue-50 text-blue-700 hover:bg-blue-100 px-2 sm:px-2.5 font-semibold text-[10px] sm:text-xs">
                {t('wsiViewerComponents.attentionPatchesPanel.bottom10')}
              </Badge>
              <button
                onClick={handleExportBottom}
                disabled={exportingBottom}
                className="text-gray-400 hover:text-blue-600 transition-colors"
                title={t('wsiViewerComponents.attentionPatchesPanel.exportBottomPatches')}
              >
                {exportingBottom ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Download className="w-4 h-4" />
                )}
              </button>
            </div>
          </div>
          <div className="p-3 sm:p-5">
            <div className="grid grid-cols-3 xs:grid-cols-4 sm:grid-cols-5 gap-2 sm:gap-3">
              {heatmapData.bottom_patches.map((patch, idx) => (
                <div
                  key={`bottom-${idx}`}
                  className="relative aspect-square rounded-xl overflow-hidden border border-gray-100 shadow-sm hover:ring-2 hover:ring-blue-500 hover:shadow-lg transition-all duration-300 cursor-pointer group"
                  title={`Attention: ${(patch.weight * 100).toFixed(1)}%\nPosition: (${patch.x}, ${patch.y})`}
                >
                  <img
                    src={getPatchImageUrl(wsi_id, patch.x, patch.y, 256)}
                    alt={`Bottom ${idx + 1}`}
                    className="w-full h-full object-cover transform group-hover:scale-110 transition-transform duration-500"
                    loading="lazy"
                  />
                  <div className="absolute top-1 left-1 bg-blue-600/90 backdrop-blur-sm text-white text-[10px] font-bold w-5 h-5 flex items-center justify-center rounded-lg shadow-sm">
                    {idx + 1}
                  </div>
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 via-black/40 to-transparent p-1.5 opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-2 group-hover:translate-y-0">
                    <span className="text-[10px] text-white font-medium flex justify-center">
                      {(patch.weight * 100).toFixed(1)}%
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </>
  )
}

