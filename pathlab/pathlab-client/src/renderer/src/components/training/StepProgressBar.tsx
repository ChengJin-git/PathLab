/**
 * StepProgressBar Component
 *
 * Displays the wizard step progress indicator.
 */

import React from 'react'
import { Card } from '../ui/card'
import { CheckCircle2 } from 'lucide-react'
import { DataLevel } from '../../constants/training'

export interface StepProgressBarProps {
  currentStep: number
  dataLevel: DataLevel
}

interface StepConfig {
  number: number
  label: string
  displayNumber?: string // For patch-level where numbers shift
}

export function StepProgressBar({ currentStep, dataLevel }: StepProgressBarProps) {
  const isWSI = dataLevel === 'wsi'

  // Define steps based on data level
  const steps: StepConfig[] = isWSI
    ? [
        { number: 1, label: 'Task Setup' },
        { number: 2, label: 'Data' },
        { number: 3, label: 'Preprocess' },
        { number: 4, label: 'Model' },
        { number: 5, label: 'Submit' },
        { number: 6, label: 'Results' },
      ]
    : [
        { number: 1, label: 'Task Setup', displayNumber: '1' },
        { number: 2, label: 'Data', displayNumber: '2' },
        { number: 4, label: 'Model', displayNumber: '3' },
        { number: 5, label: 'Submit', displayNumber: '4' },
        { number: 6, label: 'Results', displayNumber: '5' },
      ]

  return (
    <Card className="p-3 sm:p-6 overflow-x-auto scrollbar-none">
      <div className="flex items-center justify-between min-w-[500px] px-1">
        {steps.map((step, index) => (
          <React.Fragment key={step.number}>
            {/* Step indicator */}
            <div className="flex items-center space-x-2 sm:space-x-3">
              <div
                className={`w-7 h-7 sm:w-8 sm:h-8 rounded-full flex shrink-0 items-center justify-center font-bold text-[10px] sm:text-sm shadow-sm transition-all duration-300 ${
                  currentStep >= step.number
                    ? 'bg-primary-600 text-white ring-2 ring-primary-100'
                    : 'bg-gray-100 text-gray-400'
                }`}
              >
                {currentStep > step.number ? (
                  <CheckCircle2 className="w-4 h-4 sm:w-5 sm:h-5" />
                ) : (
                  step.displayNumber || step.number
                )}
              </div>
              <span
                className={`font-semibold text-[11px] sm:text-sm transition-colors duration-300 whitespace-nowrap ${
                  currentStep >= step.number ? 'text-gray-900' : 'text-gray-400'
                }`}
              >
                {step.label}
              </span>
            </div>

            {/* Connector line (not after last step) */}
            {index < steps.length - 1 && (
              <div
                className={`flex-1 h-0.5 mx-2 sm:mx-4 rounded-full transition-colors duration-500 ${
                  currentStep > step.number ? 'bg-primary-600' : 'bg-gray-200'
                }`}
              />
            )}
          </React.Fragment>
        ))}
      </div>
    </Card>
  )
}

