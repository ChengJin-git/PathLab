/**
 * ModelConfigStep Component
 *
 * Step 4: Aggregator/feature extractor selection and training parameters.
 */

import React from 'react'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { CheckCircle2, Settings, Search } from 'lucide-react'
import { DataLevel } from '../../types/training'
import { AGGREGATORS } from '../../constants/training'

export interface ExtractorInfo {
  id: string
  name: string
  description: string
}

export interface ModelConfigStepProps {
  dataLevel: DataLevel

  // Aggregator (WSI-level)
  aggregator: string
  setAggregator: (id: string) => void

  // Feature extractor (Patch-level)
  featureExtractor: string
  setFeatureExtractor: (id: string) => void
  extractorSearch: string
  setExtractorSearch: (search: string) => void
  filteredExtractors: ExtractorInfo[]

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
  aggregator,
  setAggregator,
  featureExtractor,
  setFeatureExtractor,
  extractorSearch,
  setExtractorSearch,
  filteredExtractors,
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
  return (
    <>
      <div className="flex flex-col lg:flex-row gap-4 sm:gap-6 mb-6">
        {/* Left Column: Model Architecture */}
        <Card className="flex-1 lg:max-w-3xl flex flex-col bg-gray-50/50 overflow-hidden min-h-[350px]">
          <div className="p-4 sm:p-5 pb-0 flex-shrink-0">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-4">
              <h3 className="text-sm sm:text-base font-bold text-gray-900 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-primary-600" />
                {dataLevel === 'wsi' ? 'Aggregation Method' : 'Feature Extractor'}
              </h3>
              {dataLevel === 'patch' && (
                <div className="relative w-full sm:w-48">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Search..."
                    className="w-full pl-8 pr-3 py-1.5 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 transition-all bg-white"
                    value={extractorSearch}
                    onChange={(e) => setExtractorSearch(e.target.value)}
                  />
                </div>
              )}
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-4 sm:p-5 pt-0 custom-scrollbar">
            {/* Aggregation Method (WSI-level only) */}
            {dataLevel === 'wsi' && (
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

            {/* Feature Extractor (Patch-level) */}
            {dataLevel === 'patch' && (
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
            Training Params
          </h3>

          <div className="space-y-4">
            <div>
              <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Learning Rate</label>
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
                <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Epochs</label>
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
                <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Training Batch Size</label>
                <input
                  type="number"
                  className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                  value={trainBatchSize}
                  onChange={(e) => setTrainBatchSize(Number(e.target.value))}
                  min={1}
                  max={dataLevel === 'wsi' ? 16 : 128}
                />
              </div>
            </div>

            <div>
              <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Optimizer</label>
              <select
                className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                value={optimizer}
                onChange={(e) => setOptimizer(e.target.value)}
              >
                <option value="adam">Adam</option>
                <option value="sgd">SGD</option>
                <option value="adamw">AdamW</option>
              </select>
            </div>

            <div className="pt-3 border-t border-gray-50 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Patience</label>
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
                  <label className="block text-[10px] sm:text-xs font-bold text-gray-400 uppercase tracking-widest mb-1.5">Random Seed</label>
                  <input
                    type="number"
                    className="w-full px-3 py-1.5 sm:py-2 text-[11px] sm:text-sm border border-gray-200 rounded-lg focus:ring-1 focus:ring-primary-500 outline-none"
                    value={randomSeed}
                    onChange={(e) => setRandomSeed(parseInt(e.target.value) || 0)}
                    min={0}
                  />
                </div>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="autoBalance"
                  checked={autoBalance}
                  onChange={(e) => setAutoBalance(e.target.checked)}
                  className="rounded border-gray-300 text-primary-600 focus:ring-primary-500 w-3.5 h-3.5 cursor-pointer"
                />
                <label htmlFor="autoBalance" className="text-[11px] sm:text-xs text-gray-600 font-bold cursor-pointer select-none">
                  Auto-balance classes
                </label>
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Navigation */}
      <div className="flex flex-col sm:flex-row justify-between items-center gap-3">
        <Button variant="outline" onClick={onBack} className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-xs sm:text-sm order-2 sm:order-1">
          ← Back
        </Button>
        <Button
          onClick={onNext}
          disabled={!canProceed}
          className="w-full sm:w-auto px-8 py-2 sm:py-2.5 bg-primary-600 hover:bg-primary-700 text-white shadow-lg shadow-primary-500/20 text-xs sm:text-sm order-1 sm:order-2"
        >
          Next: Review Task →
        </Button>
      </div>
    </>
  )
}

