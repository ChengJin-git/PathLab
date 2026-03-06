import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import type { DatasetSummary } from '../../api'

export interface ExportLabelsOptions {
  generateSplit?: boolean
  seed?: number
  stratified?: boolean
  trainRatio?: number
  valRatio?: number
  testRatio?: number
}

interface ExportLabelsModalProps {
  dataset: DatasetSummary
  onConfirm: (options: ExportLabelsOptions) => void
  onCancel: () => void
}

export function ExportLabelsModal({ dataset, onConfirm, onCancel }: ExportLabelsModalProps) {
  const { t } = useTranslation()
  const [seed, setSeed] = useState(42)
  const [stratified, setStratified] = useState(true)
  const [trainRatio, setTrainRatio] = useState(0.7)
  const [valRatio, setValRatio] = useState(0.1)
  const [testRatio, setTestRatio] = useState(0.2)

  const handleExport = () => {
    onConfirm({
      generateSplit: true,
      seed,
      stratified,
      trainRatio,
      valRatio,
      testRatio
    })
  }

  const totalRatio = trainRatio + valRatio + testRatio
  const ratioValid = Math.abs(totalRatio - 1.0) < 0.01

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between p-4 sm:p-6 border-b">
          <h2 className="text-lg sm:text-xl font-semibold text-gray-900">
            {t('listPage.exportLabelsWithSplit')}
          </h2>
          <button
            onClick={onCancel}
            className="text-gray-400 hover:text-gray-600 transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 sm:p-6 space-y-4 sm:space-y-6">
          {/* Dataset Info */}
          <div className="bg-gray-50 rounded-lg p-3 sm:p-4 space-y-1 sm:space-y-2">
            <p className="text-xs sm:text-sm text-gray-600">
              <span className="font-medium">{t('listPage.dataset')}:</span>{' '}
              <span className="font-semibold text-gray-900">{dataset.dataset_name}</span>
            </p>
            <p className="text-xs sm:text-sm text-gray-600">
              <span className="font-medium">{t('listPage.type')}:</span>{' '}
              {dataset.task_type === 'survival' ? t('listPage.survival') : 
               dataset.task_type === 'segmentation' ? t('listPage.segmentation') : 
               t('listPage.classification')}
              {' '}({dataset.aggregation_level === 'case' ? t('listPage.caseLevel') : t('listPage.fileLevel')})
            </p>
            <p className="text-xs sm:text-sm text-gray-600">
              <span className="font-medium">{t('listPage.files')}:</span> {dataset.file_count}
            </p>
          </div>

          {/* Split Ratios */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2 sm:mb-3">
              {t('listPage.splitRatios')}
            </label>
            <div className="grid grid-cols-3 gap-2 sm:gap-3">
              <div>
                <label className="block text-xs text-gray-600 mb-1">
                  {t('listPage.train')}
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={trainRatio}
                  onChange={(e) => setTrainRatio(parseFloat(e.target.value) || 0)}
                  className="w-full px-2 sm:px-3 py-1.5 sm:py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">
                  {t('listPage.val')}
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={valRatio}
                  onChange={(e) => setValRatio(parseFloat(e.target.value) || 0)}
                  className="w-full px-2 sm:px-3 py-1.5 sm:py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">
                  {t('listPage.test')}
                </label>
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={testRatio}
                  onChange={(e) => setTestRatio(parseFloat(e.target.value) || 0)}
                  className="w-full px-2 sm:px-3 py-1.5 sm:py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                />
              </div>
            </div>
            {!ratioValid && (
              <div className="flex items-center gap-1 sm:gap-2 mt-2 text-xs sm:text-sm text-red-600">
                <AlertCircle className="w-3 h-3 sm:w-4 sm:h-4 flex-shrink-0" />
                <span>{t('listPage.ratiosMustSumToOne')} ({totalRatio.toFixed(2)})</span>
              </div>
            )}
          </div>

          {/* Random Seed */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('listPage.randomSeed')}
            </label>
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(parseInt(e.target.value) || 42)}
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Stratified Split */}
          <div className="flex items-start gap-2 sm:gap-3">
            <input
              type="checkbox"
              id="stratified"
              checked={stratified}
              onChange={(e) => setStratified(e.target.checked)}
              className="mt-0.5 w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-2 focus:ring-blue-500"
            />
            <label htmlFor="stratified" className="text-xs sm:text-sm text-gray-700 cursor-pointer">
              {t('listPage.stratifiedSplit')}
            </label>
          </div>
        </div>

        {/* Footer */}
        <div className="flex flex-col-reverse sm:flex-row gap-2 sm:gap-3 p-4 sm:p-6 border-t bg-gray-50">
          <Button
            variant="outline"
            onClick={onCancel}
            className="w-full sm:w-auto"
          >
            {t('common.cancel')}
          </Button>
          <Button
            onClick={handleExport}
            disabled={!ratioValid}
            className="w-full sm:w-auto"
          >
            {t('listPage.exportWithSplit')}
          </Button>
        </div>
      </div>
    </div>
  )
}

