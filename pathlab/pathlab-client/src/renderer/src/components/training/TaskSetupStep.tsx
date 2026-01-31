/**
 * TaskSetupStep Component
 *
 * Step 1: Task name, type, data level, and description configuration.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { TaskType, DataLevel } from '../../types/training'

export interface TaskSetupStepProps {
  taskName: string
  setTaskName: (name: string) => void
  taskType: TaskType
  setTaskType: (type: TaskType) => void
  dataLevel: DataLevel
  setDataLevel: (level: DataLevel) => void
  taskDescription: string
  setTaskDescription: (desc: string) => void
  canProceed: boolean
  onNext: () => void
}

// Radio button option component
interface RadioOptionProps {
  selected: boolean
  disabled?: boolean
  onClick: () => void
  title: string
  subtitle: string
}

function RadioOption({ selected, disabled, onClick, title, subtitle }: RadioOptionProps) {
  return (
    <div
      onClick={disabled ? undefined : onClick}
      className={`relative p-3 sm:p-4 border rounded-xl transition-all duration-200 group ${
        disabled
          ? 'border-gray-100 bg-gray-50/50 cursor-not-allowed opacity-60'
          : selected
          ? 'border-primary-500 bg-primary-50/50 shadow-md ring-1 ring-primary-500/20 cursor-pointer'
          : 'border-gray-200 hover:border-primary-300 hover:bg-gray-50/50 hover:shadow-sm cursor-pointer'
      }`}
    >
      <div className="flex items-center justify-between">
        <div>
          <div
            className={`font-semibold text-xs sm:text-sm ${
              disabled
                ? 'text-gray-400'
                : selected
                ? 'text-primary-700'
                : 'text-gray-900 group-hover:text-primary-600'
            }`}
          >
            {title}
          </div>
          <div
            className={`text-[10px] sm:text-xs mt-0.5 sm:mt-1 ${
              disabled ? 'text-primary-500 font-medium' : 'text-gray-500'
            }`}
          >
            {subtitle}
          </div>
        </div>
        <div
          className={`w-4 h-4 sm:w-5 sm:h-5 rounded-full border flex items-center justify-center transition-colors ${
            disabled
              ? 'border-gray-200 bg-gray-50'
              : selected
              ? 'border-primary-500 bg-primary-500'
              : 'border-gray-300'
          }`}
        >
          {!disabled && selected && (
            <svg className="w-2.5 h-2.5 sm:w-3 sm:h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
              <path
                fillRule="evenodd"
                d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                clipRule="evenodd"
              />
            </svg>
          )}
        </div>
      </div>
    </div>
  )
}

export function TaskSetupStep({
  taskName,
  setTaskName,
  taskType,
  setTaskType,
  dataLevel,
  setDataLevel,
  taskDescription,
  setTaskDescription,
  canProceed,
  onNext,
}: TaskSetupStepProps) {
  const navigate = useNavigate()

  return (
    <>
      <Card className="p-4 sm:p-8 border-gray-100 shadow-sm">
        <h3 className="text-lg sm:text-xl font-bold text-gray-900 mb-4 sm:mb-6">Task Configuration</h3>

        <div className="space-y-4 sm:space-y-6">
          {/* Task Name */}
          <div>
            <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">Task Name *</label>
            <input
              type="text"
              className="w-full px-3 sm:px-4 py-2 sm:py-3 text-sm sm:text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              placeholder="e.g., Lung Cancer Survival Prediction"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 sm:gap-8">
            {/* Task Type */}
            <div>
              <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">Task Type *</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                <RadioOption
                  selected={taskType === 'classification'}
                  onClick={() => setTaskType('classification')}
                  title="Classification"
                  subtitle="Categorical labels"
                />
                <RadioOption
                  selected={taskType === 'survival_prediction'}
                  disabled={dataLevel === 'patch'}
                  onClick={() => setTaskType('survival_prediction')}
                  title={dataLevel === 'patch' ? 'Segmentation' : 'Survival Prediction'}
                  subtitle={dataLevel === 'patch' ? 'Coming soon' : 'Time-to-event outcomes'}
                />
              </div>
            </div>

            {/* Data Level */}
            <div>
              <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">Data Level *</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                <RadioOption
                  selected={dataLevel === 'wsi'}
                  onClick={() => setDataLevel('wsi')}
                  title="WSI-level"
                  subtitle="Whole slides"
                />
                <RadioOption
                  selected={dataLevel === 'patch'}
                  onClick={() => setDataLevel('patch')}
                  title="Patch-level"
                  subtitle="Image patches"
                />
              </div>
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">Description *</label>
            <textarea
              className="w-full px-3 sm:px-4 py-2 sm:py-3 text-sm sm:text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              placeholder="e.g., Classify lung cancer pathology slides into LUAD, LUSC, and Normal tissue..."
              rows={3}
            />
          </div>
        </div>
      </Card>

      {/* Navigation */}
      <div className="flex flex-col sm:flex-row justify-between items-center gap-3 mt-4 sm:mt-6">
        <Button
          variant="outline"
          onClick={() => navigate(-1)}
          className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-sm sm:text-base order-2 sm:order-1"
        >
          Cancel
        </Button>
        <Button
          onClick={onNext}
          disabled={!canProceed}
          className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-sm sm:text-base order-1 sm:order-2"
        >
          Next: Select Data →
        </Button>
      </div>
    </>
  )
}

