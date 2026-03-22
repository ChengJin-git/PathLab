/**
 * useTaskWizard Hook
 *
 * Manages the wizard step navigation and basic task configuration state.
 */

import { useState, useCallback, useMemo } from 'react'
import { TaskType, DataLevel, TrainingStatus } from '../constants/training'
import { useDraftState } from './useDraftState'

const D = 'draft:wizard:'

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
  const [currentStep, setCurrentStep] = useDraftState(`${D}step`, 1)
  const [taskName, setTaskName] = useDraftState(`${D}taskName`, '')
  const [taskType, setTaskType] = useDraftState<TaskType>(`${D}taskType`, 'classification')
  const [dataLevel, setDataLevel] = useDraftState<DataLevel>(`${D}dataLevel`, 'wsi')
  const [taskDescription, setTaskDescription] = useDraftState(`${D}taskDescription`, '')

  const [trainingStatus, setTrainingStatus] = useState<TrainingStatus>('idle')
  const [submittedTaskId, setSubmittedTaskId] = useState('')
  const [submitError, setSubmitError] = useState('')

  // Total steps depends on data level (patch skips preprocessing step)
  const totalSteps = dataLevel === 'wsi' ? 6 : 5

  // Navigation helpers
  const goToNextStep = useCallback(() => {
    setCurrentStep((prev) => Math.min(prev + 1, totalSteps))
  }, [totalSteps, setCurrentStep])

  const goToPreviousStep = useCallback(() => {
    setCurrentStep((prev) => Math.max(prev - 1, 1))
  }, [setCurrentStep])

  // Step 1 validation
  const canProceedStep1 = useMemo(() => {
    return taskName.trim().length > 0 && taskDescription.trim().length > 0
  }, [taskName, taskDescription])

  // Handle dataLevel change - reset taskType if needed
  const handleSetDataLevel = useCallback((level: DataLevel) => {
    setDataLevel(level)
    if (level === 'wsi' && taskType === 'segmentation') {
      setTaskType('classification')
    }
    if (level === 'patch' && taskType === 'survival') {
      setTaskType('classification')
    }
  }, [taskType, setDataLevel, setTaskType])

  const handleSetTaskType = useCallback((type: TaskType) => {
    if (type === 'survival' && dataLevel === 'patch') {
      return
    }
    if (type === 'segmentation' && dataLevel === 'wsi') {
      return
    }
    setTaskType(type)
  }, [dataLevel, setTaskType])

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

