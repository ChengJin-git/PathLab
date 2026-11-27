import React, { useState } from 'react'
import { Checkbox } from '../ui/checkbox'
import { useTranslation } from 'react-i18next'
import { X, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Select } from '../ui/select'
import { ModalShell } from '../ui/modal-shell'
import type { DatasetSummary, ExportLabelsOptions } from '../../api/wsi'
import { isSegmentationTask, isSurvivalTask } from '../../constants/training'

export type { ExportLabelsOptions } from '../../api/wsi'

interface ExportLabelsModalProps {
  dataset: DatasetSummary
  onConfirm: (options: ExportLabelsOptions) => void
  onCancel: () => void
}

export function ExportLabelsModal({ dataset, onConfirm, onCancel }: ExportLabelsModalProps) {
  const { t } = useTranslation()
  const [strategy, setStrategy] = useState<'random' | 'k_fold'>('random')
  const [nSplits, setNSplits] = useState(5)
  const [seed, setSeed] = useState(42)
  const [stratified, setStratified] = useState(true)
  const [trainRatio, setTrainRatio] = useState(0.7)
  const [valRatio, setValRatio] = useState(0.1)
  const [testRatio, setTestRatio] = useState(0.2)
  const isKFold = strategy === 'k_fold'

  const handleExport = () => {
    onConfirm({
      generateSplit: true,
      strategy,
      ...(isKFold
        ? { nSplits }
        : {
            trainRatio,
            valRatio,
            testRatio
          }),
      seed,
      stratified,
    })
  }

  const totalRatio = trainRatio + valRatio + testRatio
  const ratioValid = Math.abs(totalRatio - 1.0) < 0.01
  const kFoldValid = nSplits >= 2
  const exportDisabled = isKFold ? !kFoldValid : !ratioValid

  return (
    <ModalShell isOpen={true} onClose={onCancel} maxWidth="md">
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
              {dataset.task_types.map(task => t(`training.taskSetup.${task}`)).join(' · ')}
              {' '}({dataset.aggregation_level === 'case' ? t('listPage.patientLevel') : t('listPage.fileLevel')})
            </p>
            <p className="text-xs sm:text-sm text-gray-600">
              <span className="font-medium">{t('listPage.files')}:</span> {dataset.file_count}
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              {t('chatComponents.taskConfig.splitStrategy')}
            </label>
            <Select
              value={strategy}
              onChange={(v) => setStrategy(v as 'random' | 'k_fold')}
              options={[
                { value: 'random', label: t('chatComponents.taskConfig.splitRandom') },
                { value: 'k_fold', label: t('chatComponents.taskConfig.splitKFold') },
              ]}
            />
          </div>

          {isKFold ? (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                {t('chatComponents.taskConfig.foldsK')}
              </label>
              <input
                type="number"
                min="2"
                max="50"
                value={nSplits}
                onChange={(e) => setNSplits(parseInt(e.target.value) || 2)}
                className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
          ) : (
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
          )}

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

          <div className="flex items-start gap-2 sm:gap-3">
            <Checkbox
              id="stratified"
              checked={stratified}
              onChange={(e) => setStratified(e.target.checked)}
              className="mt-0.5"
            />
            <label htmlFor="stratified" className="text-xs sm:text-sm text-gray-700 cursor-pointer">
              {t('training.dataSplit.stratifiedSplit')}
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
            disabled={exportDisabled}
            className="w-full sm:w-auto"
          >
            {t('listPage.exportWithSplit')}
          </Button>
        </div>
    </ModalShell>
  )
}
