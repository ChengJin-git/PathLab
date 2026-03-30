/**
 * DataSplitConfig Component
 *
 * Configures data split strategy: Random, K-Fold, or Manual.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Layers, AlertCircle, CheckCircle2, UploadCloud } from 'lucide-react'
import { SplitStrategy, TaskType, KFOLD_MAX_SPLITS } from '../../constants/training'
import { KFoldValidation, RandomSplitValidation } from '../../types/training'

export interface DataSplitConfigProps {
  taskType: TaskType
  splitStrategy: SplitStrategy
  setSplitStrategy: (strategy: SplitStrategy) => void
  kFoldSplits: number
  setKFoldSplits: (k: number) => void
  kFoldValidation: KFoldValidation
  randomSplitValidation: RandomSplitValidation
  hasPreDefinedSplits: boolean
  predefinedSplitCounts: { train: number; val: number; test: number }
  selectedDatasetId: string | null
  selectedDatasetName: string
  isWholeDatasetSelected?: boolean
}

export function DataSplitConfig({
  taskType,
  splitStrategy,
  setSplitStrategy,
  kFoldSplits,
  setKFoldSplits,
  kFoldValidation,
  randomSplitValidation,
  hasPreDefinedSplits,
  predefinedSplitCounts,
  selectedDatasetId,
  selectedDatasetName,
  isWholeDatasetSelected = false,
}: DataSplitConfigProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const isSegmentation = taskType === 'segmentation'

  return (
    <Card className="mt-6 p-6">
      <h3 className="text-md font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <Layers className="w-5 h-5 text-gray-500" />
        {t('training.dataSplit.title')}
      </h3>

      <div className="space-y-4">
        <div className={`grid grid-cols-1 gap-4 ${isSegmentation ? 'md:grid-cols-2' : 'md:grid-cols-3'}`}>
          {/* Random Split */}
          <SplitOption
            selected={splitStrategy === 'random'}
            onClick={() => setSplitStrategy('random')}
            title={t('training.dataSplit.randomSplit')}
            description={t('training.dataSplit.randomSplitDesc')}
          />

          {!isSegmentation && (
            <SplitOption
              selected={splitStrategy === 'k_fold'}
              onClick={() => setSplitStrategy('k_fold')}
              title={t('training.dataSplit.kFoldCV')}
              description={t('training.dataSplit.kFoldCVDesc')}
            />
          )}

          {hasPreDefinedSplits ? (
            <SplitOption
              selected={splitStrategy === 'manual'}
              onClick={() => setSplitStrategy('manual')}
              title={t('training.dataSplit.customSplit')}
              description={t('training.dataSplit.customSplitDesc')}
            />
          ) : (
            <div
              onClick={() => navigate('/register', { state: { datasetId: selectedDatasetId, datasetName: selectedDatasetName } })}
              className="p-4 rounded-xl border border-gray-200 bg-gray-50 hover:bg-gray-100 hover:border-gray-300 cursor-pointer transition-all flex flex-col justify-center"
            >
              <div className="flex items-center gap-2 mb-1">
                <UploadCloud className="w-4 h-4 text-gray-500" />
                <span className="font-medium text-sm text-gray-600">{t('training.dataSplit.uploadSplits')}</span>
              </div>
              <p className="text-xs text-blue-600">{t('training.dataSplit.noSplitsFound')}</p>
            </div>
          )}
        </div>

        {/* Conditional Inputs */}
        <div className="mt-4 pl-1">
          {splitStrategy === 'random' && (
            isWholeDatasetSelected ? (
              <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
                <div className="text-xs text-blue-700">
                  <p className="font-medium">{t('training.dataSplit.wholeDatasetSplitNote')}</p>
                </div>
              </div>
            ) : (
              <RandomSplitDetails taskType={taskType} validation={randomSplitValidation} />
            )
          )}

          {splitStrategy === 'k_fold' && (
            isWholeDatasetSelected ? (
              <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
                <div className="text-xs text-blue-700">
                  <p className="font-medium">{t('training.dataSplit.wholeDatasetSplitNote')}</p>
                </div>
              </div>
            ) : (
              <KFoldDetails kFoldSplits={kFoldSplits} setKFoldSplits={setKFoldSplits} validation={kFoldValidation} />
            )
          )}

          {splitStrategy === 'manual' && (
            <ManualSplitDetails
              hasPreDefinedSplits={hasPreDefinedSplits}
              predefinedSplitCounts={predefinedSplitCounts}
              selectedDatasetId={selectedDatasetId}
              selectedDatasetName={selectedDatasetName}
            />
          )}
        </div>
      </div>
    </Card>
  )
}

/** Split strategy option card */
function SplitOption({
  selected,
  onClick,
  title,
  description,
}: {
  selected: boolean
  onClick: () => void
  title: string
  description: string
}) {
  return (
    <div
      onClick={onClick}
      className={`p-4 rounded-xl border cursor-pointer transition-all ${
        selected ? 'bg-primary-50 border-primary-500 ring-1 ring-primary-500' : 'bg-white border-gray-200 hover:border-primary-300'
      }`}
    >
      <div className="flex items-center gap-2 mb-2">
        <div className={`w-4 h-4 rounded-full border flex items-center justify-center ${selected ? 'border-primary-600' : 'border-gray-400'}`}>
          {selected && <div className="w-2 h-2 rounded-full bg-primary-600" />}
        </div>
        <span className="font-medium text-sm text-gray-900">{title}</span>
      </div>
      <p className="text-xs text-gray-500 ml-6">{description}</p>
    </div>
  )
}

/** Random split configuration details */
function RandomSplitDetails({
  taskType,
  validation,
}: {
  taskType: TaskType
  validation: RandomSplitValidation
}) {
  const { t } = useTranslation()
  const isSegmentation = taskType === 'segmentation'

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 text-sm text-gray-600 bg-gray-50 p-3 rounded-lg border border-gray-100">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500"></span>
          <span>{t('training.dataSplit.train70')}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-blue-500"></span>
          <span>{t('training.dataSplit.val10')}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-amber-500"></span>
          <span>{t('training.dataSplit.test20')}</span>
        </div>
      </div>

      {!validation.isValid && (
        <div className="p-3 bg-red-50 border border-red-100 rounded-lg">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
            <div className="text-sm text-red-700">
              <p className="font-medium">{t('training.dataSplit.cannotRandomSplit')}</p>
              <p className="text-xs mt-1">{validation.message}</p>
            </div>
          </div>
        </div>
      )}

      {validation.isValid && !isSegmentation && (
        <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
          <div className="text-xs text-blue-700">
            <p className="font-medium mb-1">
              {t('training.dataSplit.classesAndSamples', { classes: validation.numClasses, samples: validation.totalLabeled })}
            </p>
            <p className="text-blue-600">
              {t('training.dataSplit.expectedSplit', { train: Math.floor(validation.totalLabeled * 0.7), val: Math.floor(validation.totalLabeled * 0.1), test: Math.floor(validation.totalLabeled * 0.2) })}
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

/** K-Fold configuration details */
function KFoldDetails({
  kFoldSplits,
  setKFoldSplits,
  validation,
}: {
  kFoldSplits: number
  setKFoldSplits: (k: number) => void
  validation: KFoldValidation
}) {
  const { t } = useTranslation()
  const maxAllowed = Math.min(KFOLD_MAX_SPLITS, validation.maxK || KFOLD_MAX_SPLITS)

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4">
        <label className="text-sm font-medium text-gray-700">{t('training.dataSplit.numberOfFolds')}</label>
        <input
          type="number"
          min={2}
          max={maxAllowed}
          value={kFoldSplits}
          onChange={(e) => setKFoldSplits(Math.max(2, Math.min(maxAllowed, parseInt(e.target.value) || 5)))}
          disabled={!validation.isValid}
          className={`w-20 px-3 py-1.5 text-sm border rounded-md focus:ring-1 focus:ring-primary-500 ${
            !validation.isValid ? 'border-red-300 bg-red-50' : 'border-gray-300'
          }`}
        />
        {validation.isValid && validation.maxK < KFOLD_MAX_SPLITS && (
          <span className="text-xs text-amber-600">{t('training.dataSplit.maxKNote', { maxK: validation.maxK })}</span>
        )}
      </div>

      {!validation.isValid && (
        <div className="p-3 bg-red-50 border border-red-100 rounded-lg">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
            <div className="text-sm text-red-700">
              <p className="font-medium">{t('training.dataSplit.cannotKFold')}</p>
              <p className="text-xs mt-1">{validation.message}</p>
            </div>
          </div>
        </div>
      )}

      {validation.isValid && (
        <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
          <div className="text-xs text-blue-700">
            <p className="font-medium mb-1">
              {t('training.dataSplit.kFoldSummary', { k: kFoldSplits, classes: validation.numClasses, samples: validation.totalLabeled })}
            </p>
            <p className="text-blue-600">{t('training.dataSplit.kFoldEachFold', { count: Math.floor(validation.totalLabeled / kFoldSplits) })}</p>
          </div>
        </div>
      )}
    </div>
  )
}

/** Manual split configuration details */
function ManualSplitDetails({
  hasPreDefinedSplits,
  predefinedSplitCounts,
  selectedDatasetId,
  selectedDatasetName,
}: {
  hasPreDefinedSplits: boolean
  predefinedSplitCounts: { train: number; val: number; test: number }
  selectedDatasetId: string | null
  selectedDatasetName: string
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <div className="space-y-3">
      {hasPreDefinedSplits ? (
        <div className="p-3 bg-green-50 border border-green-100 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="w-4 h-4 text-green-600" />
            <span className="text-sm font-medium text-green-800">{t('training.dataSplit.readyPreDefined')}</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="bg-white p-2 rounded border border-green-100">
              <span className="text-gray-500 block">{t('training.dataSplit.train')}</span>
              <span className="font-semibold text-gray-900">{predefinedSplitCounts.train}</span>
            </div>
            <div className="bg-white p-2 rounded border border-green-100">
              <span className="text-gray-500 block">{t('training.dataSplit.val')}</span>
              <span className="font-semibold text-gray-900">{predefinedSplitCounts.val}</span>
            </div>
            <div className="bg-white p-2 rounded border border-green-100">
              <span className="text-gray-500 block">{t('training.dataSplit.test')}</span>
              <span className="font-semibold text-gray-900">{predefinedSplitCounts.test}</span>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-sm text-amber-600 bg-amber-50 p-4 rounded-lg border border-amber-100 flex flex-col gap-3">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>
              {t('training.dataSplit.noSplitConfig')}
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/register', { state: { datasetId: selectedDatasetId, datasetName: selectedDatasetName } })}
            className="self-start ml-6 bg-white hover:bg-amber-50 border-amber-200 text-amber-700"
          >
            {t('training.dataSplit.goToRegistration')}
          </Button>
        </div>
      )}
    </div>
  )
}
