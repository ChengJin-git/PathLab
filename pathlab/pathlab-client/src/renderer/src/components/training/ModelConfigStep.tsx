/**
 * ModelConfigStep Component
 *
 * Step 4: Aggregator/feature extractor selection and training parameters.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { CheckCircle2, Settings, Search } from 'lucide-react'
import {
  DataLevel,
  TaskType,
  ExtractorOption,
  BackboneOption,
  LossOption,
  AGGREGATORS,
  OPTIMIZERS,
  SEGMENTATION_ARCHITECTURES,
  SEGMENTATION_BACKBONES,
  SEGMENTATION_LOSSES,
} from '../../constants/training'

export interface ModelConfigStepProps {
  dataLevel: DataLevel
  taskType: TaskType

  // Aggregator (WSI-level)
  aggregator: string
  setAggregator: (id: string) => void

  // Feature extractor (Patch-level classification)
  featureExtractor: string
  setFeatureExtractor: (id: string) => void
  extractorSearch: string
  setExtractorSearch: (search: string) => void
  filteredExtractors: ExtractorOption[]

  // Segmentation-specific (Patch-level segmentation)
  segArchitecture: string
  setSegArchitecture: (arch: string) => void
  segBackbone: string
  setSegBackbone: (backbone: string) => void
  segLossNames: string[]
  setSegLossNames: (names: string[]) => void
  segLossWeights: number[]
  setSegLossWeights: (weights: number[]) => void

  // Training parameters
  learningRate: number
  setLearningRate: (val: number) => void
  epochs: number
  setEpochs: (val: number) => void
  trainBatchSize: number
  setTrainBatchSize: (val: number) => void
  optimizer: string
  setOptimizer: (val: string) => void
  earlyStoppingPatience: number
  setEarlyStoppingPatience: (val: number) => void
  randomSeed: number
  setRandomSeed: (val: number) => void
  autoBalance: boolean
  setAutoBalance: (val: boolean) => void

  // Navigation
  canProceed: boolean
  onBack: () => void
  onNext: () => void
}

export function ModelConfigStep({
  dataLevel,
  taskType,
  aggregator,
  setAggregator,
  featureExtractor,
  setFeatureExtractor,
  extractorSearch,
  setExtractorSearch,
  filteredExtractors,
  segArchitecture,
  setSegArchitecture,
  segBackbone,
  setSegBackbone,
  segLossNames,
  setSegLossNames,
  segLossWeights,
  setSegLossWeights,
  learningRate,
  setLearningRate,
  epochs,
  setEpochs,
  trainBatchSize,
  setTrainBatchSize,
  optimizer,
  setOptimizer,
  earlyStoppingPatience,
  setEarlyStoppingPatience,
  randomSeed,
  setRandomSeed,
  autoBalance,
  setAutoBalance,
  canProceed,
  onBack,
  onNext,
}: ModelConfigStepProps) {
  const { t } = useTranslation()

  const isSegmentation = taskType === 'segmentation'

  // Toggle a loss function on/off
  const toggleLoss = (lossId: string) => {
    const idx = segLossNames.indexOf(lossId)
    if (idx >= 0) {
      // Remove (but keep at least 1 loss)
      if (segLossNames.length <= 1) return
      const newNames = segLossNames.filter((_, i) => i !== idx)
      const newWeights = segLossWeights.filter((_, i) => i !== idx)
      // Re-normalize weights
      const total = newWeights.reduce((a, b) => a + b, 0)
      setSegLossNames(newNames)
      setSegLossWeights(newWeights.map((w) => Math.round((w / total) * 100) / 100))
    } else {
      // Add with equal weight
      const newNames = [...segLossNames, lossId]
      const equalWeight = Math.round((1 / newNames.length) * 100) / 100
      setSegLossNames(newNames)
      setSegLossWeights(newNames.map(() => equalWeight))
    }
  }

  return (
    <>
      <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 mb-6">
        {/* Left Column: Model Architecture */}
        <Card className="flex-1 lg:max-w-3xl flex flex-col bg-gray-50/50 overflow-hidden min-h-[350px]">
          <div className="p-4 sm:p-5 pb-0 flex-shrink-0">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <h3 className="text-sm sm:text-base font-bold text-gray-900 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-primary-600" />
                {isSegmentation
                  ? t('training.modelConfig.segArchitecture')
                  : dataLevel === 'wsi'
                  ? t('training.modelConfig.aggregationMethod')
                  : t('training.modelConfig.featureExtractor')}
              </h3>
              {dataLevel === 'patch' && !isSegmentation && (
                <div className="relative w-full sm:w-48">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                  <input
                    type="text"
                    placeholder={t('training.modelConfig.search')}
                    className="w-full pl-8 pr-3 py-1.5 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 transition-all bg-white"
                    value={extractorSearch}
                    onChange={(e) => setExtractorSearch(e.target.value)}
                  />
                </div>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4 sm:p-5 pt-0 custom-scrollbar">
            {/* Segmentation Architecture + Backbone + Loss */}
            {isSegmentation && (
              <div className="space-y-6">
                {/* Architecture Selection */}
                <div>
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">
                    {t('training.modelConfig.architecture')}
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3">
                    {SEGMENTATION_ARCHITECTURES.map((arch) => (
                      <div
                        key={arch.id}
                        onClick={() => setSegArchitecture(arch.id)}
                        className={`group relative p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                          segArchitecture === arch.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                        }`}
                      >
                        <div className="flex items-start justify-between mb-0.5">
                          <div className="font-bold text-gray-900 text-xs sm:text-sm">{arch.name}</div>
                          {segArchitecture === arch.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600" />}
                        </div>
                        <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed line-clamp-2">{arch.description}</div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Backbone Selection */}
                <div>
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">
                    {t('training.modelConfig.backbone')}
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3">
                    {SEGMENTATION_BACKBONES.map((bb) => (
                      <div
                        key={bb.id}
                        onClick={() => setSegBackbone(bb.id)}
                        className={`p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                          segBackbone === bb.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                        }`}
                      >
                        <div className="flex items-start justify-between">
                          <div className="flex-1 min-w-0">
                            <div className="font-bold text-gray-900 text-xs sm:text-sm">{bb.name}</div>
                            <div className="text-[10px] sm:text-xs text-gray-500 mt-1 line-clamp-1">{bb.description}</div>
                          </div>
                          {segBackbone === bb.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Loss Functions */}
                <div>
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">
                    {t('training.modelConfig.lossFunction')}
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3">
                    {SEGMENTATION_LOSSES.map((loss) => {
                      const isSelected = segLossNames.includes(loss.id)
                      return (
                        <div
                          key={loss.id}
                          onClick={() => toggleLoss(loss.id)}
                          className={`p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                            isSelected ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                          }`}
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex-1 min-w-0">
                              <div className="font-bold text-gray-900 text-xs sm:text-sm">{loss.name}</div>
                              <div className="text-[10px] sm:text-xs text-gray-500 mt-1 line-clamp-1">{loss.description}</div>
                            </div>
                            {isSelected && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Aggregation Method (WSI-level only) */}
            {!isSegmentation && dataLevel === 'wsi' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3">
                {AGGREGATORS.map((agg) => (
                  <div
                    key={agg.id}
                    onClick={() => setAggregator(agg.id)}
                    className={`group relative p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                      aggregator === agg.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-0.5">
                      <div className="font-bold text-gray-900 text-xs sm:text-sm">{agg.name}</div>
                      {aggregator === agg.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600" />}
                    </div>
                    <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed line-clamp-2">{agg.detail}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Feature Extractor (Patch-level classification) */}
            {!isSegmentation && dataLevel === 'patch' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 pb-2">
                {filteredExtractors.map((extractor) => (
                  <div
                    key={extractor.id}
                    onClick={() => setFeatureExtractor(extractor.id)}
                    className={`p-3 sm:p-4 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                      featureExtractor === extractor.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="font-bold text-gray-900 text-xs sm:text-sm truncate">{extractor.name}</div>
                        <div className="text-[10px] sm:text-xs text-gray-500 mt-1 line-clamp-1">{extractor.description}</div>
                      </div>
                      {featureExtractor === extractor.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>

        {/* Right Column: Training Parameters */}
        <Card className="flex-1 lg:max-w-md p-4 sm:p-5 flex flex-col bg-white overflow-hidden shadow-sm border-gray-100">
          <h3 className="text-sm sm:text-base font-bold text-gray-900 mb-4 flex items-center gap-2">
            <Settings className="w-4 h-4 text-primary-600" />
            {t('training.modelConfig.trainingParams')}
          </h3>

          <div className="space-y-4">
            <div>
              <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">{t('training.modelConfig.learningRate')}</label>
              <input
                type="number"
                className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none transition-all"
                value={learningRate}
                onChange={(e) => setLearningRate(Number(e.target.value))}
                step={0.0001}
                min={0.00001}
                max={0.01}
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">{t('training.modelConfig.epochs')}</label>
                <input
                  type="number"
                  className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                  value={epochs}
                  onChange={(e) => setEpochs(Number(e.target.value))}
                  min={1}
                  max={200}
                />
              </div>
              <div>
                <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">{t('training.modelConfig.trainBatchSize')}</label>
                <input
                  type="number"
                  className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                  value={trainBatchSize}
                  onChange={(e) => setTrainBatchSize(Number(e.target.value))}
                  min={1}
                  max={dataLevel === 'wsi' ? 16 : isSegmentation ? 64 : 128}
                />
              </div>
            </div>

            <div>
              <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">{t('training.modelConfig.optimizer')}</label>
              <select
                className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                value={optimizer}
                onChange={(e) => setOptimizer(e.target.value)}
              >
                {OPTIMIZERS.map(opt => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>

            <div className="pt-3 border-t border-gray-50 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">{t('training.modelConfig.patience')}</label>
                  <input
                    type="number"
                    className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                    value={earlyStoppingPatience}
                    onChange={(e) => setEarlyStoppingPatience(Number(e.target.value))}
                    min={1}
                    max={50}
                  />
                </div>
                <div>
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">{t('training.modelConfig.randomSeed')}</label>
                  <input
                    type="number"
                    className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                    value={randomSeed}
                    onChange={(e) => setRandomSeed(parseInt(e.target.value) || 0)}
                    min={0}
                  />
                </div>
              </div>

              {!isSegmentation && (
                <div className="flex items-center gap-2 pt-1">
                  <input
                    type="checkbox"
                    id="autoBalance"
                    checked={autoBalance}
                    onChange={(e) => setAutoBalance(e.target.checked)}
                    className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-3.5 h-3.5 cursor-pointer"
                  />
                  <label htmlFor="autoBalance" className="text-[11px] sm:text-xs text-gray-600 font-bold cursor-pointer select-none">
                    {t('training.modelConfig.autoBalance')}
                  </label>
                </div>
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Navigation */}
      <div className="flex flex-col sm:flex-row justify-between items-center gap-3">
        <Button variant="outline" onClick={onBack} className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-2 sm:order-1">
          {t('training.modelConfig.back')}
        </Button>
        <Button
          onClick={onNext}
          disabled={!canProceed}
          className="w-full sm:w-auto px-8 py-2 sm:py-2.5 bg-primary-600 hover:bg-primary-700 text-white shadow-lg shadow-primary-500/20 text-xs sm:text-sm order-1 sm:order-2"
        >
          {t('training.modelConfig.nextReview')}
        </Button>
      </div>
    </>
  )
}
