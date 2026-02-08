/**
 * DataSplitConfig Component
 *
 * Configures data split strategy: Random, K-Fold, or Manual.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { Layers, AlertCircle, CheckCircle2, UploadCloud } from 'lucide-react'
import { SplitStrategy } from '../../constants/training'
import { KFoldValidation, RandomSplitValidation } from '../../types/training'

export interface DataSplitConfigProps {
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
}

export function DataSplitConfig({
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
}: DataSplitConfigProps) {
  const navigate = useNavigate()

  return (
    <Card className="mt-6 p-6">
      <h3 className="text-md font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <Layers className="w-5 h-5 text-gray-500" />
        Data Split Configuration
      </h3>

      <div className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Random Split */}
          <SplitOption
            selected={splitStrategy === 'random'}
            onClick={() => setSplitStrategy('random')}
            title="Random Split"
            description="Standard 70/10/20 split (Train/Val/Test)."
          />

          {/* K-Fold */}
          <SplitOption
            selected={splitStrategy === 'k_fold'}
            onClick={() => setSplitStrategy('k_fold')}
            title="K-Fold CV"
            description="Cross-validation with K folds."
          />

          {/* Manual Split */}
          {hasPreDefinedSplits ? (
            <SplitOption
              selected={splitStrategy === 'manual'}
              onClick={() => setSplitStrategy('manual')}
              title="Custom Split"
              description="Use existing defined splits."
            />
          ) : (
            <div
              onClick={() => navigate('/register', { state: { datasetId: selectedDatasetId, datasetName: selectedDatasetName } })}
              className="p-4 rounded-xl border border-gray-200 bg-gray-50 hover:bg-gray-100 hover:border-gray-300 cursor-pointer transition-all flex flex-col justify-center"
            >
              <div className="flex items-center gap-2 mb-1">
                <UploadCloud className="w-4 h-4 text-gray-500" />
                <span className="font-medium text-sm text-gray-600">Upload Splits</span>
              </div>
              <p className="text-xs text-blue-600">No splits found. Click to upload CSV.</p>
            </div>
          )}
        </div>

        {/* Conditional Inputs */}
        <div className="mt-4 pl-1">
          {splitStrategy === 'random' && <RandomSplitDetails validation={randomSplitValidation} />}

          {splitStrategy === 'k_fold' && (
            <KFoldDetails kFoldSplits={kFoldSplits} setKFoldSplits={setKFoldSplits} validation={kFoldValidation} />
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
function RandomSplitDetails({ validation }: { validation: RandomSplitValidation }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 text-sm text-gray-600 bg-gray-50 p-3 rounded-lg border border-gray-100">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-green-500"></span>
          <span>Train: 70%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-blue-500"></span>
          <span>Val: 10%</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-amber-500"></span>
          <span>Test: 20%</span>
        </div>
      </div>

      {!validation.isValid && (
        <div className="p-3 bg-red-50 border border-red-100 rounded-lg">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
            <div className="text-sm text-red-700">
              <p className="font-medium">Cannot use Random 7:1:2 split</p>
              <p className="text-xs mt-1">{validation.message}</p>
            </div>
          </div>
        </div>
      )}

      {validation.isValid && (
        <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
          <div className="text-xs text-blue-700">
            <p className="font-medium mb-1">
              {validation.numClasses} classes, {validation.totalLabeled} labeled samples
            </p>
            <p className="text-blue-600">
              Expected: ~{Math.floor(validation.totalLabeled * 0.7)} train, ~{Math.floor(validation.totalLabeled * 0.1)} val, ~
              {Math.floor(validation.totalLabeled * 0.2)} test
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
  const maxAllowed = Math.min(10, validation.maxK || 10)

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4">
        <label className="text-sm font-medium text-gray-700">Number of Folds (K):</label>
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
        {validation.isValid && validation.maxK < 10 && (
          <span className="text-xs text-amber-600">(max {validation.maxK} based on class distribution)</span>
        )}
      </div>

      {!validation.isValid && (
        <div className="p-3 bg-red-50 border border-red-100 rounded-lg">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
            <div className="text-sm text-red-700">
              <p className="font-medium">Cannot use K-Fold cross-validation</p>
              <p className="text-xs mt-1">{validation.message}</p>
            </div>
          </div>
        </div>
      )}

      {validation.isValid && (
        <div className="p-3 bg-blue-50 border border-blue-100 rounded-lg">
          <div className="text-xs text-blue-700">
            <p className="font-medium mb-1">
              {kFoldSplits}-Fold CV: {validation.numClasses} classes, {validation.totalLabeled} labeled samples
            </p>
            <p className="text-blue-600">Each fold will have ~{Math.floor(validation.totalLabeled / kFoldSplits)} samples for validation</p>
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
  const navigate = useNavigate()

  return (
    <div className="space-y-3">
      {hasPreDefinedSplits ? (
        <div className="p-3 bg-green-50 border border-green-100 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle2 className="w-4 h-4 text-green-600" />
            <span className="text-sm font-medium text-green-800">Ready to use pre-defined splits</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-xs">
            <div className="bg-white p-2 rounded border border-green-100">
              <span className="text-gray-500 block">Train</span>
              <span className="font-semibold text-gray-900">{predefinedSplitCounts.train}</span>
            </div>
            <div className="bg-white p-2 rounded border border-green-100">
              <span className="text-gray-500 block">Val</span>
              <span className="font-semibold text-gray-900">{predefinedSplitCounts.val}</span>
            </div>
            <div className="bg-white p-2 rounded border border-green-100">
              <span className="text-gray-500 block">Test</span>
              <span className="font-semibold text-gray-900">{predefinedSplitCounts.test}</span>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-sm text-amber-600 bg-amber-50 p-4 rounded-lg border border-amber-100 flex flex-col gap-3">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <span>
              No split configuration found for this dataset. You can upload a CSV file with split assignments (train/val/test) in the
              Registration page.
            </span>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate('/register', { state: { datasetId: selectedDatasetId, datasetName: selectedDatasetName } })}
            className="self-start ml-6 bg-white hover:bg-amber-50 border-amber-200 text-amber-700"
          >
            Go to Registration & Upload Splits
          </Button>
        </div>
      )}
    </div>
  )
}

