/**
 * TaskSetupStep Component
 *
 * Step 1: Task name, type, data level, and description configuration.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { Card } from '../ui/card'
import { Button } from '../ui/button'
import { TaskType, DataLevel, TASK_TYPES, getTaskMetadata } from '../../constants/training'

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
  const { t } = useTranslation()
  const navigate = useNavigate()

  return (
    <>
      <Card className="p-4 sm:p-8 border-gray-100 shadow-sm">
        <h3 className="text-lg sm:text-xl font-bold text-gray-900 mb-4 sm:mb-6">{t('training.taskSetup.taskConfiguration')}</h3>

        <div className="space-y-4 sm:space-y-6">
          {/* Task Name */}
          <div>
            <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">{t('training.taskSetup.taskName')}</label>
            <input
              type="text"
              className="w-full px-3 sm:px-4 py-2 sm:py-3 text-sm sm:text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
              value={taskName}
              onChange={(e) => setTaskName(e.target.value)}
              placeholder={t('training.taskSetup.taskNamePlaceholder')}
            />
          </div>

          <div className="space-y-4 sm:space-y-6">
            <div>
              <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">{t('training.taskSetup.patchLevel')}</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                {TASK_TYPES.filter((option) => getTaskMetadata(option.value).dataType === 'patch').map((option) => {
                  const metadata = getTaskMetadata(option.value)
                  const title = metadata.taskFamily === 'segmentation'
                    ? t('training.taskSetup.segmentation')
                    : t('training.taskSetup.classification')
                  const subtitle = metadata.taskFamily === 'segmentation'
                    ? t('training.taskSetup.segmentationMasks')
                    : t('training.taskSetup.categoricalLabels')
                  return (
                    <RadioOption
                      key={option.value}
                      selected={taskType === option.value}
                      onClick={() => {
                        setTaskType(option.value)
                        setDataLevel(metadata.dataType)
                      }}
                      title={title}
                      subtitle={subtitle}
                    />
                  )
                })}
              </div>
            </div>

            <div>
              <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">{t('training.taskSetup.wsiLevel')}</label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                {TASK_TYPES.filter((option) => getTaskMetadata(option.value).dataType === 'wsi').map((option) => {
                  const metadata = getTaskMetadata(option.value)
                  const title = metadata.taskFamily === 'survival'
                    ? t('training.taskSetup.survivalPrediction')
                    : t('training.taskSetup.classification')
                  const subtitle = metadata.taskFamily === 'survival'
                    ? t('training.taskSetup.timeToEvent')
                    : t('training.taskSetup.categoricalLabels')
                  return (
                    <RadioOption
                      key={option.value}
                      selected={taskType === option.value}
                      onClick={() => {
                        setTaskType(option.value)
                        setDataLevel(metadata.dataType)
                      }}
                      title={title}
                      subtitle={subtitle}
                    />
                  )
                })}
              </div>
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-xs sm:text-sm font-semibold text-gray-800 mb-2">{t('training.taskSetup.descriptionLabel')}</label>
            <textarea
              className="w-full px-3 sm:px-4 py-2 sm:py-3 text-sm sm:text-base border-gray-200 bg-gray-50/50 rounded-xl focus:ring-4 focus:ring-primary-500/10 focus:border-primary-500 focus:bg-white transition-all shadow-sm"
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              placeholder={t('training.taskSetup.descriptionPlaceholder')}
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
          {t('training.taskSetup.cancel')}
        </Button>
        <Button
          onClick={onNext}
          disabled={!canProceed}
          className="w-full sm:w-auto px-6 py-2 sm:py-2.5 text-sm sm:text-base order-1 sm:order-2"
        >
          {t('training.taskSetup.nextSelectData')}
        </Button>
      </div>
    </>
  )
}
