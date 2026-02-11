/**
 * useTaskWizard Hook
 *
 * Manages the wizard step navigation and basic task configuration state.
 */

import { useState, useCallback, useMemo } from 'react'
import { TaskType, DataLevel, TrainingStatus } from '../constants/training'

export interface UseTaskWizardReturn {
  // Step navigation
  currentStep: number
  setCurrentStep: (step: number) => void
  goToNextStep: () => void
  goToPreviousStep: () => void

  // Task configuration (Step 1)
  taskName: string
  setTaskName: (name: string) => void
  taskType: TaskType
  setTaskType: (type: TaskType) => void
  dataLevel: DataLevel
  setDataLevel: (level: DataLevel) => void
  taskDescription: string
  setTaskDescription: (desc: string) => void

  // Training status (Step 5-6)
  trainingStatus: TrainingStatus
  setTrainingStatus: (status: TrainingStatus) => void
  submittedTaskId: string
  setSubmittedTaskId: (id: string) => void
  submitError: string
  setSubmitError: (error: string) => void

  // Validation
  canProceedStep1: boolean

  // Total steps (depends on dataLevel)
  totalSteps: number
}

export function useTaskWizard(): UseTaskWizardReturn {
  // Step navigation
  const [currentStep, setCurrentStep] = useState(1)

  // Step 1: Task Configuration
  const [taskName, setTaskName] = useState('')
  const [taskType, setTaskType] = useState<TaskType>('classification')
  const [dataLevel, setDataLevel] = useState<DataLevel>('wsi')
  const [taskDescription, setTaskDescription] = useState('')

  // Step 5-6: Training status
  const [trainingStatus, setTrainingStatus] = useState<TrainingStatus>('idle')
  const [submittedTaskId, setSubmittedTaskId] = useState('')
  const [submitError, setSubmitError] = useState('')

  // Total steps depends on data level (patch skips preprocessing step)
  const totalSteps = dataLevel === 'wsi' ? 6 : 5

  // Navigation helpers
  const goToNextStep = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, totalSteps))
  }, [totalSteps])

  const goToPreviousStep = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 1))
  }, [])

  // Step 1 validation
  const canProceedStep1 = useMemo(() => {
    return taskName.trim().length > 0 && taskDescription.trim().length > 0
  }, [taskName, taskDescription])

  // Handle dataLevel change - reset taskType if needed
  const handleSetDataLevel = useCallback((level: DataLevel) => {
    setDataLevel(level)
    // If switching to patch and taskType is survival, reset to classification
    if (level === 'patch' && taskType === 'survival') {
      setTaskType('classification')
    }
  }, [taskType])

  // Handle taskType change
  const handleSetTaskType = useCallback((type: TaskType) => {
    // Survival prediction is only available for WSI level
    if (type === 'survival' && dataLevel === 'patch') {
      return
    }
    setTaskType(type)
  }, [dataLevel])

  return {
    // Step navigation
    currentStep,
    setCurrentStep,
    goToNextStep,
    goToPreviousStep,

    // Task configuration
    taskName,
    setTaskName,
    taskType,
    setTaskType: handleSetTaskType,
    dataLevel,
    setDataLevel: handleSetDataLevel,
    taskDescription,
    setTaskDescription,

    // Training status
    trainingStatus,
    setTrainingStatus,
    submittedTaskId,
    setSubmittedTaskId,
    submitError,
    setSubmitError,

    // Validation
    canProceedStep1,

    // Total steps
    totalSteps,
  }
}

