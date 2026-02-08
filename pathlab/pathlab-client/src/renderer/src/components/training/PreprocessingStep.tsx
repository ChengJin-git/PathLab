/**
 * PreprocessingStep Component
 *
 * Step 3: Tiling parameters and feature extractor selection (WSI-level only).
 *
 * NOTE: Tile size (patch_size) is no longer user-configurable.
 * PrePATH-style tiling automatically determines patch_size based on WSI magnification
 * to ensure consistent physical coverage (~128μm) across different resolution WSIs.
 */

import React from 'react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Settings, Search, CheckCircle2 } from 'lucide-react'
import { ExtractorOption } from '../../constants/training'

export interface PreprocessingStepProps {
  // Tiling parameters (tile_size and stride removed - auto-determined by PrePATH-style)
  pyramidLevel: number
  setPyramidLevel: (level: number) => void
  featureBatchSize: number
  setFeatureBatchSize: (size: number) => void

  // Segmentation parameters
  segSthresh: number
  setSegSthresh: (val: number) => void
  segMthresh: number
  setSegMthresh: (val: number) => void
  segUseOtsu: boolean
  setSegUseOtsu: (val: boolean) => void

  // Feature extractor
  featureExtractor: string
  setFeatureExtractor: (id: string) => void
  extractorSearch: string
  setExtractorSearch: (search: string) => void
  filteredExtractors: ExtractorOption[]

  // Navigation
  canProceed: boolean
  onBack: () => void
  onNext: () => void
}

export function PreprocessingStep({
  pyramidLevel,
  setPyramidLevel,
  featureBatchSize,
  setFeatureBatchSize,
  segSthresh,
  setSegSthresh,
  segMthresh,
  setSegMthresh,
  segUseOtsu,
  setSegUseOtsu,
  featureExtractor,
  setFeatureExtractor,
  extractorSearch,
  setExtractorSearch,
  filteredExtractors,
  canProceed,
  onBack,
  onNext,
}: PreprocessingStepProps) {
  return (
    <>
      <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 mb-6">
        {/* Left Column: Configuration Parameters */}
        <Card className="flex-1 p-3 sm:p-6 border-gray-100 shadow-sm">
          <div className="flex items-center gap-2 sm:gap-3 mb-4 sm:mb-6">
            <div className="p-1.5 sm:p-2 bg-blue-50 rounded-xl">
              <Settings className="w-4 h-4 sm:w-5 sm:h-5 text-blue-600" />
            </div>
            <div>
              <h4 className="text-xs sm:text-base font-bold text-gray-900">Tiling Parameters</h4>
              <p className="text-[10px] sm:text-xs text-gray-400 mt-0.5">Configure patch extraction and filtering</p>
            </div>
          </div>

          <div className="space-y-4 sm:space-y-5">
            {/* Pyramid Level */}
            <div>
              <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-2">Pyramid Level</label>
              <select
                value={pyramidLevel}
                onChange={(e) => setPyramidLevel(Number(e.target.value))}
                className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm bg-gray-50 border-gray-100 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-bold outline-none"
              >
                <option value={0}>L0 (Max Resolution)</option>
                <option value={1}>L1 (1/4 Resolution)</option>
                <option value={2}>L2 (1/16 Resolution)</option>
              </select>
            </div>

            <div className="pt-2 border-t border-gray-50">
              <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-2 mt-3">Feature Batch Size</label>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  className="flex-1 px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm bg-gray-50 border-gray-100 rounded-xl focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-bold"
                  value={featureBatchSize}
                  onChange={(e) => setFeatureBatchSize(Number(e.target.value))}
                  min={1}
                />
                <span className="text-[9px] sm:text-xs text-gray-400 font-medium whitespace-nowrap">GPU patches</span>
              </div>
            </div>

            <div className="pt-4 border-t border-gray-50">
              <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">Tissue Segmentation</label>
              <div className="grid grid-cols-2 gap-x-3 gap-y-2">
                <div className="flex flex-col gap-1">
                  <label className="text-[9px] sm:text-xs text-gray-500 font-medium">Saturation Threshold</label>
                  <input
                    type="number"
                    className="px-3 py-1.5 text-[11px] bg-gray-50 border-gray-100 rounded-lg focus:border-primary-400 transition-all font-bold"
                    value={segSthresh}
                    onChange={(e) => setSegSthresh(Number(e.target.value))}
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[9px] sm:text-xs text-gray-500 font-medium">Mask Threshold</label>
                  <input
                    type="number"
                    className="px-3 py-1.5 text-[11px] bg-gray-50 border-gray-100 rounded-lg focus:border-primary-400 transition-all font-bold"
                    value={segMthresh}
                    onChange={(e) => setSegMthresh(Number(e.target.value))}
                  />
                </div>
              </div>
              <div className="flex items-center gap-2 mt-4">
                <input
                  type="checkbox"
                  id="use_otsu"
                  checked={segUseOtsu}
                  onChange={(e) => setSegUseOtsu(e.target.checked)}
                  className="w-3.5 h-3.5 text-primary-600 rounded border-gray-300 focus:ring-primary-500 cursor-pointer"
                />
                <label htmlFor="use_otsu" className="text-[10px] sm:text-xs text-gray-600 font-bold cursor-pointer select-none">
                  Use Otsu Thresholding
                </label>
              </div>
            </div>
          </div>
        </Card>

        {/* Right Column: Feature Extractor Selection */}
        <Card className="lg:col-span-8 flex flex-col min-h-[400px] h-full overflow-hidden border-0 shadow-sm ring-1 ring-gray-200">
          <div className="p-3 sm:p-4 border-b border-gray-100 bg-white flex-shrink-0 z-10">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 sm:gap-4">
              <div>
                <h4 className="text-sm sm:text-base font-bold text-gray-900">Feature Extractor</h4>
                <p className="text-[10px] sm:text-xs text-gray-500">Select model architecture</p>
              </div>
              <div className="relative w-full sm:w-48">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search..."
                  className="w-full pl-8 pr-3 py-1.5 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-2 focus:ring-primary-500/20 focus:border-primary-500 transition-all font-light"
                  value={extractorSearch}
                  onChange={(e) => setExtractorSearch(e.target.value)}
                />
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3 sm:p-4 bg-gray-50/50">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3">
              {filteredExtractors.length > 0 ? (
                filteredExtractors.map((extractor) => (
                  <div
                    key={extractor.id}
                    onClick={() => setFeatureExtractor(extractor.id)}
                    className={`group relative p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                      featureExtractor === extractor.id
                        ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                        : 'bg-white border-gray-100 hover:border-gray-200'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-0.5">
                      <div className="font-bold text-gray-900 text-xs sm:text-sm">{extractor.name}</div>
                      {featureExtractor === extractor.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600" />}
                    </div>
                    <p className="text-[10px] sm:text-xs text-gray-500 line-clamp-1 leading-relaxed">{extractor.description}</p>
                  </div>
                ))
              ) : (
                <div className="col-span-full py-12 text-center text-[10px] sm:text-xs text-gray-400 font-medium">No models found</div>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Navigation */}
      <div className="flex flex-col sm:flex-row justify-between items-center gap-3">
        <Button variant="outline" onClick={onBack} className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-2 sm:order-1">
          ← Back to Data
        </Button>
        <Button onClick={onNext} disabled={!canProceed} className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-1 sm:order-2">
          Next: Model Config →
        </Button>
      </div>
    </>
  )
}

