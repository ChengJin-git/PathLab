/**
 * StepProgressBar Component
 *
 * Displays the wizard step progress indicator.
 */

import React from 'react'
import { useTranslation } from 'react-i18next'
import { Card } from '../ui/card'
import { CheckCircle2 } from 'lucide-react'
import { DataLevel } from '../../constants/training'

export interface StepProgressBarProps {
  currentStep: number
  dataLevel: DataLevel
  onStepClick?: (step: number) => void
}

interface StepConfig {
  number: number
  label: string
  displayNumber?: string
}

export function StepProgressBar({ currentStep, dataLevel, onStepClick }: StepProgressBarProps) {
  const { t } = useTranslation()
  const isWSI = dataLevel === 'wsi'

  const steps: StepConfig[] = isWSI
    ? [
        { number: 1, label: t('training.stepProgress.taskSetup') },
        { number: 2, label: t('training.stepProgress.data') },
        { number: 3, label: t('training.stepProgress.preprocess') },
        { number: 4, label: t('training.stepProgress.model') },
        { number: 5, label: t('training.stepProgress.submit') },
        { number: 6, label: t('training.stepProgress.results') },
      ]
    : [
        { number: 1, label: t('training.stepProgress.taskSetup'), displayNumber: '1' },
        { number: 2, label: t('training.stepProgress.data'), displayNumber: '2' },
        { number: 4, label: t('training.stepProgress.model'), displayNumber: '3' },
        { number: 5, label: t('training.stepProgress.submit'), displayNumber: '4' },
        { number: 6, label: t('training.stepProgress.results'), displayNumber: '5' },
      ]

  return (
    <Card surface="elevated" className="overflow-x-auto border-[color:var(--surface-border)] bg-[color:var(--surface-elevated)] p-4 shadow-[var(--shadow-elevated)] scrollbar-none sm:p-6">
      <div className="flex min-w-[500px] items-center justify-between px-1">
        {steps.map((step, index) => {
          const isClickable = !!onStepClick && currentStep >= step.number
          return (
            <React.Fragment key={step.number}>
              {isClickable ? (
                <button
                  type="button"
                  className="flex items-center space-x-2 sm:space-x-3 group cursor-pointer"
                  onClick={() => onStepClick(step.number)}
                >
                  <div
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold shadow-[var(--shadow-soft)] transition-all duration-300 sm:h-9 sm:w-9 sm:text-sm ${currentStep > step.number ? 'border-primary-600 bg-primary-600 text-white ring-4 ring-primary-500/15' : 'border-primary-200 bg-primary-50 text-primary-700'} group-hover:ring-4 group-hover:ring-primary-500/20`}
                  >
                    {currentStep > step.number ? (
                      <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" />
                    ) : (
                      step.displayNumber || step.number
                    )}
                  </div>
                  <span className="whitespace-nowrap text-[11px] font-semibold tracking-[-0.02em] text-slate-900 transition-colors duration-300 group-hover:text-primary-700 sm:text-sm">
                    {step.label}
                  </span>
                </button>
              ) : (
                <div className="flex items-center space-x-2 sm:space-x-3">
                  <div
                    className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-[10px] font-bold shadow-[var(--shadow-soft)] transition-all duration-300 sm:h-9 sm:w-9 sm:text-sm ${
                      currentStep >= step.number
                        ? 'border-primary-600 bg-primary-600 text-white ring-4 ring-primary-500/15'
                        : 'border-[color:var(--surface-border-strong)] bg-[color:var(--surface-muted)] text-slate-400'
                    }`}
                  >
                    {currentStep > step.number ? (
                      <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" />
                    ) : (
                      step.displayNumber || step.number
                    )}
                  </div>
                  <span
                    className={`whitespace-nowrap text-[11px] font-semibold tracking-[-0.02em] transition-colors duration-300 sm:text-sm ${
                      currentStep >= step.number ? 'text-slate-900' : 'text-slate-400'
                    }`}
                  >
                    {step.label}
                  </span>
                </div>
              )}

              {index < steps.length - 1 && (
                <div
                  className={`mx-2 h-0.5 flex-1 rounded-full transition-colors duration-500 sm:mx-4 ${
                    currentStep > step.number ? 'bg-primary-500' : 'bg-[color:var(--surface-border-strong)]'
                  }`}
                />
              )}
            </React.Fragment>
          )
        })}
      </div>
    </Card>
  )
}
