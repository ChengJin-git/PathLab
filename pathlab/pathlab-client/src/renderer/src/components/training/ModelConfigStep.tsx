/**
 * ModelConfigStep Component
 *
 * Step 4: Aggregator/feature extractor selection and training parameters.
 */

import React, { useEffect, useState, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { CheckCircle2, Settings, Search } from 'lucide-react'
import { Select } from '../ui/select'
import {
  DataLevel,
  TaskType,
  ExtractorOption,
  AGGREGATORS,
  OPTIMIZERS,
  PATCH_CLASSIFIERS,
  FEATURE_EXTRACTORS,
  SEGMENTATION_ARCHITECTURES,
  SEGMENTATION_BACKBONES,
  SEGMENTATION_LOSSES,
  BACKBONE_GROUPS,
  DEFAULT_SEG_BACKBONE,
  isSegFmEncoder,
  FmDecoderType,
  FM_DECODER_TYPES,
  isSegmentationTask,
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

  // Classifier head (Patch-level classification)
  classifier: string
  setClassifier: (id: string) => void

  // Segmentation-specific (Patch-level segmentation)
  segArchitecture: string
  setSegArchitecture: (arch: string) => void
  segBackbone: string
  setSegBackbone: (backbone: string) => void
  segFmDecoderType: FmDecoderType
  setSegFmDecoderType: (decoder: FmDecoderType) => void
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
  classifier,
  setClassifier,
  segArchitecture,
  setSegArchitecture,
  segBackbone,
  setSegBackbone,
  segFmDecoderType,
  setSegFmDecoderType,
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

  const isSegmentation = isSegmentationTask(taskType)

  // Backbone search & group filter state
  const [backboneSearch, setBackboneSearch] = useState('')
  const [backboneGroup, setBackboneGroup] = useState<string | null>(null)

  const filteredBackbones = useMemo(() => {
    let list = [...SEGMENTATION_BACKBONES]
    if (backboneGroup) {
      list = list.filter((b) => b.group === backboneGroup)
    }
    if (backboneSearch.trim()) {
      const q = backboneSearch.trim().toLowerCase()
      list = list.filter(
        (b) =>
          b.id.toLowerCase().includes(q) ||
          b.name.toLowerCase().includes(q) ||
          b.group.toLowerCase().includes(q)
      )
    }
    return list
  }, [backboneSearch, backboneGroup])

  const allSegmentationFmExtractors = useMemo(
    () => FEATURE_EXTRACTORS.filter((extractor) => extractor.supports_spatial && isSegFmEncoder(extractor.id)),
    []
  )

  const filteredSegmentationFmExtractors = useMemo(
    () => filteredExtractors.filter((extractor) => extractor.supports_spatial && isSegFmEncoder(extractor.id)),
    [filteredExtractors]
  )

  const isFmSegmentation = isSegFmEncoder(segBackbone)
  const [lastStandardBackbone, setLastStandardBackbone] = useState(
    isFmSegmentation ? DEFAULT_SEG_BACKBONE : segBackbone || DEFAULT_SEG_BACKBONE
  )
  const [lastFmExtractor, setLastFmExtractor] = useState(
    isFmSegmentation ? segBackbone : (allSegmentationFmExtractors[0]?.id ?? 'uni')
  )

  useEffect(() => {
    if (isSegFmEncoder(segBackbone)) {
      setLastFmExtractor(segBackbone)
    } else if (segBackbone) {
      setLastStandardBackbone(segBackbone)
    }
  }, [segBackbone])

  const switchSegmentationModelType = (mode: 'standard' | 'fm') => {
    setBackboneSearch('')
    setBackboneGroup(null)
    setExtractorSearch('')

    if (mode === 'fm') {
      const nextExtractor = isSegFmEncoder(segBackbone)
        ? segBackbone
        : (lastFmExtractor || allSegmentationFmExtractors[0]?.id)
      if (nextExtractor) {
        setSegBackbone(nextExtractor)
      }
      return
    }

    setSegBackbone(isSegFmEncoder(segBackbone) ? lastStandardBackbone || DEFAULT_SEG_BACKBONE : segBackbone)
  }

  const selectSegmentationBackbone = (backboneId: string) => {
    setLastStandardBackbone(backboneId)
    setSegBackbone(backboneId)
  }

  const selectSegmentationFmExtractor = (extractorId: string) => {
    setLastFmExtractor(extractorId)
    setSegBackbone(extractorId)
  }

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
      <div className="flex flex-col lg:flex-row lg:items-start gap-4 sm:gap-6 mb-6">
        {/* Left Column: Model Architecture */}
        <Card className="min-w-0 flex-1 flex flex-col bg-gray-50/50 overflow-hidden min-h-[350px] lg:h-[640px] xl:h-[680px]">
          <div className="p-4 sm:p-5 pb-0 flex-shrink-0">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <h3 className="text-sm sm:text-base font-bold text-gray-900 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-primary-600" />
                {isSegmentation
                  ? t('training.modelConfig.segmentationModel')
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
              <div className="space-y-3">
                <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm space-y-2.5">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">
                      {t('training.modelConfig.modelType')}
                    </label>
                    <div className="inline-flex w-full sm:w-auto rounded-xl bg-gray-100 p-1">
                    <button
                      type="button"
                      onClick={() => switchSegmentationModelType('standard')}
                      className={`flex-1 sm:flex-none px-3 py-1.5 rounded-lg text-xs sm:text-sm font-semibold transition-all ${
                        !isFmSegmentation ? 'bg-white text-primary-700 shadow-sm border border-primary-200' : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      {t('training.modelConfig.standardSegmentation')}
                    </button>
                    <button
                      type="button"
                      onClick={() => switchSegmentationModelType('fm')}
                      className={`flex-1 sm:flex-none px-3 py-1.5 rounded-lg text-xs sm:text-sm font-semibold transition-all ${
                        isFmSegmentation ? 'bg-white text-primary-700 shadow-sm border border-primary-200' : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      {t('training.modelConfig.foundationSegmentation')}
                    </button>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] sm:text-xs text-gray-500 leading-snug">
                    <CheckCircle2 className="w-3.5 h-3.5 text-primary-500 flex-shrink-0" />
                    <span>
                      {isFmSegmentation
                        ? t('training.modelConfig.foundationSegmentationDesc')
                        : t('training.modelConfig.standardSegmentationDesc')}
                    </span>
                  </div>
                </div>

                {isFmSegmentation && (
                  <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm space-y-2.5">
                    <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">
                      {t('training.modelConfig.decoderType')}
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      {FM_DECODER_TYPES.map((type) => (
                        <div
                          key={type}
                          onClick={() => setSegFmDecoderType(type)}
                          className={`p-2.5 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                            segFmDecoderType === type
                              ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm'
                              : 'bg-white border-gray-100 hover:border-gray-200'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="font-bold text-gray-900 text-xs sm:text-sm capitalize">
                              {t(`training.modelConfig.decoder.${type}`, type)}
                            </div>
                            {segFmDecoderType === type && (
                              <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!isFmSegmentation && (
                  <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm space-y-2.5">
                    <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">
                      {t('training.modelConfig.architecture')}
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
                      {SEGMENTATION_ARCHITECTURES.map((arch) => (
                        <div
                          key={arch.id}
                          onClick={() => setSegArchitecture(arch.id)}
                          className={`group relative p-2.5 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                            segArchitecture === arch.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                          }`}
                        >
                          <div className="flex items-start justify-between mb-0.5 gap-2">
                            <div className="font-bold text-gray-900 text-xs sm:text-sm">{arch.name}</div>
                            {segArchitecture === arch.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />}
                          </div>
                          <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 leading-snug line-clamp-1">{arch.description}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {!isFmSegmentation ? (
                  <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm space-y-2.5">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">
                        {t('training.modelConfig.backbone')}
                      </label>
                      <div className="relative w-full sm:max-w-xs">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                        <input
                          type="text"
                          placeholder={t('training.modelConfig.searchBackbone')}
                          className="w-full pl-8 pr-3 py-1.5 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 transition-all bg-white"
                          value={backboneSearch}
                          onChange={(e) => setBackboneSearch(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      <button
                        type="button"
                        onClick={() => setBackboneGroup(null)}
                        className={`px-2.5 py-1 text-[10px] sm:text-xs rounded-full border transition-all ${
                          backboneGroup === null
                            ? 'bg-primary-50 border-primary-300 text-primary-700 font-semibold'
                            : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300'
                        }`}
                      >
                        {t('training.modelConfig.allGroups')}
                      </button>
                      {BACKBONE_GROUPS.map((group) => (
                        <button
                          key={group}
                          type="button"
                          onClick={() => setBackboneGroup(backboneGroup === group ? null : group)}
                          className={`px-2.5 py-1 text-[10px] sm:text-xs rounded-full border transition-all ${
                            backboneGroup === group
                              ? 'bg-primary-50 border-primary-300 text-primary-700 font-semibold'
                              : 'bg-white border-gray-200 text-gray-500 hover:border-gray-300'
                          }`}
                        >
                          {group}
                        </button>
                      ))}
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[300px] lg:max-h-[320px] overflow-y-auto custom-scrollbar pr-1">
                      {filteredBackbones.map((bb) => (
                        <div
                          key={bb.id}
                          onClick={() => selectSegmentationBackbone(bb.id)}
                          className={`p-2.5 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                            segBackbone === bb.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <div className="font-bold text-gray-900 text-xs sm:text-sm">{bb.name}</div>
                              <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 line-clamp-1">{bb.description}</div>
                            </div>
                            <div className="flex items-center gap-1.5 flex-shrink-0">
                              <span className="text-[9px] sm:text-[10px] text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded">{bb.group}</span>
                              {segBackbone === bb.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600" />}
                            </div>
                          </div>
                        </div>
                      ))}
                      {filteredBackbones.length === 0 && (
                        <div className="col-span-full text-center text-sm text-gray-400 py-6">
                          {t('training.modelConfig.noBackboneResults')}
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm space-y-2.5">
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                      <div className="min-w-0">
                        <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">
                          {t('training.modelConfig.featureExtractor')}
                        </label>
                      </div>
                      <div className="relative w-full sm:max-w-xs">
                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                        <input
                          type="text"
                          placeholder={t('training.modelConfig.search')}
                          className="w-full pl-8 pr-3 py-1.5 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 transition-all bg-white"
                          value={extractorSearch}
                          onChange={(e) => setExtractorSearch(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-[300px] lg:max-h-[320px] overflow-y-auto custom-scrollbar pr-1">
                      {filteredSegmentationFmExtractors.map((extractor) => (
                        <div
                          key={extractor.id}
                          onClick={() => selectSegmentationFmExtractor(extractor.id)}
                          className={`p-2.5 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                            segBackbone === extractor.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <div className="font-bold text-gray-900 text-xs sm:text-sm">{extractor.name}</div>
                              <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 line-clamp-1">{extractor.description}</div>
                            </div>
                            {segBackbone === extractor.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />}
                          </div>
                        </div>
                      ))}
                      {filteredSegmentationFmExtractors.length === 0 && (
                        <div className="col-span-full text-center text-sm text-gray-400 py-6">
                          {t('training.modelConfig.noFeatureExtractorResults')}
                        </div>
                      )}
                    </div>
                  </div>
                )}

                <div className="rounded-2xl border border-gray-200 bg-white p-3 shadow-sm space-y-2.5">
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest">
                    {t('training.modelConfig.lossFunction')}
                  </label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
                    {SEGMENTATION_LOSSES.map((loss) => {
                      const isSelected = segLossNames.includes(loss.id)
                      return (
                        <div
                          key={loss.id}
                          onClick={() => toggleLoss(loss.id)}
                          className={`p-2.5 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                            isSelected ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <div className="font-bold text-gray-900 text-xs sm:text-sm">{loss.name}</div>
                              <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 line-clamp-1">{loss.description}</div>
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 max-h-[340px] overflow-y-auto custom-scrollbar pr-1">
                {AGGREGATORS.map((agg) => (
                  <div
                    key={agg.id}
                    onClick={() => setAggregator(agg.id)}
                    className={`group relative p-2.5 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                      aggregator === agg.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                    }`}
                  >
                    <div className="flex items-start justify-between mb-0.5">
                      <div className="font-bold text-gray-900 text-xs sm:text-sm">{agg.name}</div>
                      {aggregator === agg.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600" />}
                    </div>
                    <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 leading-snug line-clamp-1">{agg.detail}</div>
                  </div>
                ))}
              </div>
            )}

            {/* Feature Extractor (Patch-level classification) */}
            {!isSegmentation && dataLevel === 'patch' && (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 sm:gap-3 max-h-[300px] overflow-y-auto custom-scrollbar pr-1">
                {filteredExtractors.map((extractor) => (
                  <div
                    key={extractor.id}
                    onClick={() => setFeatureExtractor(extractor.id)}
                    className={`p-2.5 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                      featureExtractor === extractor.id ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                    }`}
                  >
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="font-bold text-gray-900 text-xs sm:text-sm truncate">{extractor.name}</div>
                        <div className="text-[10px] sm:text-xs text-gray-500 mt-0.5 line-clamp-1">{extractor.description}</div>
                      </div>
                      {featureExtractor === extractor.id && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />}
                    </div>
                  </div>
                ))}
                {filteredExtractors.length === 0 && (
                  <div className="col-span-2 text-center text-sm text-gray-400 py-6">
                    {t('training.modelConfig.noResults', 'No matching extractors')}
                  </div>
                )}
              </div>
            )}

            {/* Classifier Head (Patch-level classification) */}
            {!isSegmentation && dataLevel === 'patch' && (
              <>
                <h4 className="text-xs sm:text-sm font-bold text-gray-700 mt-4 mb-2">{t('training.modelConfig.classifierHead', 'Classifier Head')}</h4>
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 sm:gap-3 pb-2">
                  {PATCH_CLASSIFIERS.map((cls) => (
                    <div
                      key={cls.value}
                      onClick={() => setClassifier(cls.value)}
                      className={`p-3 rounded-xl border transition-all cursor-pointer hover:shadow-sm ${
                        classifier === cls.value ? 'bg-white border-primary-500 ring-1 ring-primary-500 shadow-sm' : 'bg-white border-gray-100 hover:border-gray-200'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-0.5">
                        <div className="font-bold text-gray-900 text-xs sm:text-sm">{cls.label}</div>
                        {classifier === cls.value && <CheckCircle2 className="w-3.5 h-3.5 sm:w-4 sm:h-4 text-primary-600 flex-shrink-0" />}
                      </div>
                      <div className="text-[10px] sm:text-xs text-gray-500 mt-1 leading-relaxed line-clamp-2">{cls.description}</div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </Card>

        {/* Right Column: Training Parameters */}
        <Card className="w-full lg:w-[320px] xl:w-[340px] lg:flex-none lg:sticky lg:top-4 self-start p-4 sm:p-5 flex flex-col bg-white overflow-hidden shadow-sm border-gray-100">
          <h3 className="text-sm sm:text-base font-bold text-gray-900 mb-4 flex items-center gap-2">
            <Settings className="w-4 h-4 text-primary-600" />
            {t('training.modelConfig.trainingParams')}
          </h3>

          <div className="space-y-3">
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
              <Select
                value={optimizer}
                onChange={setOptimizer}
                options={OPTIMIZERS}
              />
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
