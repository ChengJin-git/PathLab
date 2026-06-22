import React from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { TaskSetupStep, TaskSetupStepProps } from '@renderer/components/training/TaskSetupStep'
import { useTaskWizard } from '@renderer/lib/useTaskWizard'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}))

function renderTaskSetupStep(props: Partial<TaskSetupStepProps> = {}) {
  const defaultProps: TaskSetupStepProps = {
    taskName: '',
    setTaskName: vi.fn(),
    taskType: 'patch_classification',
    setTaskType: vi.fn(),
    dataLevel: 'patch',
    setDataLevel: vi.fn(),
    taskDescription: '',
    setTaskDescription: vi.fn(),
    canProceed: true,
    onNext: vi.fn(),
  }
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TaskSetupStep {...defaultProps} {...props} />
    </MemoryRouter>
  )
}

function TaskSetupStepWizardHarness() {
  const wizard = useTaskWizard()

  return (
    <>
      <TaskSetupStep
        taskName="Test task"
        setTaskName={wizard.setTaskName}
        taskType={wizard.taskType}
        setTaskType={wizard.setTaskType}
        dataLevel={wizard.dataLevel}
        setDataLevel={wizard.setDataLevel}
        taskDescription="Test description"
        setTaskDescription={wizard.setTaskDescription}
        canProceed={wizard.canProceedStep1}
        onNext={vi.fn()}
      />
      <output data-testid="wizard-task-type">{wizard.taskType}</output>
      <output data-testid="wizard-data-level">{wizard.dataLevel}</output>
    </>
  )
}

function renderTaskSetupStepWithWizard() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TaskSetupStepWizardHarness />
    </MemoryRouter>
  )
}

describe('TaskSetupStep grouped task selection', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  it('renders grouped task choices by image level (patch and wsi)', () => {
    renderTaskSetupStep()
    expect(screen.getByText('training.taskSetup.patchLevel')).toBeInTheDocument()
    expect(screen.getByText('training.taskSetup.wsiLevel')).toBeInTheDocument()
  })

  it('shows classification and segmentation under patch level', () => {
    renderTaskSetupStep()
    const patchGroup = screen.getByText('training.taskSetup.patchLevel').closest('div')!
    const patchCards = patchGroup.querySelectorAll('div[class*="relative"]')
    expect(patchCards.length).toBe(2)
    expect(within(patchCards[0] as HTMLElement).getByText('training.taskSetup.classification')).toBeInTheDocument()
    expect(within(patchCards[1] as HTMLElement).getByText('training.taskSetup.segmentation')).toBeInTheDocument()
  })

  it('shows classification and survival prediction under wsi level', () => {
    renderTaskSetupStep()
    const wsiGroup = screen.getByText('training.taskSetup.wsiLevel').closest('div')!
    const wsiCards = wsiGroup.querySelectorAll('div[class*="relative"]')
    expect(wsiCards.length).toBe(2)
    expect(within(wsiCards[0] as HTMLElement).getByText('training.taskSetup.classification')).toBeInTheDocument()
    expect(within(wsiCards[1] as HTMLElement).getByText('training.taskSetup.survivalPrediction')).toBeInTheDocument()
  })

  it('does not render separate task type and data level columns', () => {
    renderTaskSetupStep()
    expect(screen.queryByText('training.taskSetup.taskTypeLabel')).not.toBeInTheDocument()
    expect(screen.queryByText('training.taskSetup.dataLevelLabel')).not.toBeInTheDocument()
  })

  it('selecting patch classification updates both taskType and dataLevel', () => {
    const setTaskType = vi.fn()
    const setDataLevel = vi.fn()
    renderTaskSetupStep({ setTaskType, setDataLevel })

    const patchGroup = screen.getByText('training.taskSetup.patchLevel').closest('div')!
    const patchCards = patchGroup.querySelectorAll('div[class*="relative"]')
    fireEvent.click(patchCards[0])

    expect(setTaskType).toHaveBeenCalledWith('patch_classification')
    expect(setDataLevel).toHaveBeenCalledWith('patch')
  })

  it('selecting patch segmentation updates both taskType and dataLevel', () => {
    const setTaskType = vi.fn()
    const setDataLevel = vi.fn()
    renderTaskSetupStep({ setTaskType, setDataLevel })

    const patchGroup = screen.getByText('training.taskSetup.patchLevel').closest('div')!
    const patchCards = patchGroup.querySelectorAll('div[class*="relative"]')
    fireEvent.click(patchCards[1])

    expect(setTaskType).toHaveBeenCalledWith('patch_segmentation')
    expect(setDataLevel).toHaveBeenCalledWith('patch')
  })

  it('selecting wsi classification updates both taskType and dataLevel', () => {
    const setTaskType = vi.fn()
    const setDataLevel = vi.fn()
    renderTaskSetupStep({ setTaskType, setDataLevel })

    const wsiGroup = screen.getByText('training.taskSetup.wsiLevel').closest('div')!
    const wsiCards = wsiGroup.querySelectorAll('div[class*="relative"]')
    fireEvent.click(wsiCards[0])

    expect(setTaskType).toHaveBeenCalledWith('wsi_classification')
    expect(setDataLevel).toHaveBeenCalledWith('wsi')
  })

  it('selecting wsi survival updates both taskType and dataLevel', () => {
    const setTaskType = vi.fn()
    const setDataLevel = vi.fn()
    renderTaskSetupStep({ setTaskType, setDataLevel })

    const wsiGroup = screen.getByText('training.taskSetup.wsiLevel').closest('div')!
    const wsiCards = wsiGroup.querySelectorAll('div[class*="relative"]')
    fireEvent.click(wsiCards[1])

    expect(setTaskType).toHaveBeenCalledWith('wsi_survival')
    expect(setDataLevel).toHaveBeenCalledWith('wsi')
  })

  it('keeps wsi survival selected when switching from patch-level task through the wizard state', () => {
    sessionStorage.setItem('draft:wizard:taskType', JSON.stringify('patch_classification'))
    sessionStorage.setItem('draft:wizard:dataLevel', JSON.stringify('patch'))
    renderTaskSetupStepWithWizard()

    const wsiGroup = screen.getByText('training.taskSetup.wsiLevel').closest('div')!
    const wsiCards = wsiGroup.querySelectorAll('div[class*="relative"]')
    fireEvent.click(wsiCards[1])

    expect(screen.getByTestId('wizard-task-type')).toHaveTextContent('wsi_survival')
    expect(screen.getByTestId('wizard-data-level')).toHaveTextContent('wsi')
  })

  it('marks the currently selected task as selected', () => {
    renderTaskSetupStep({ taskType: 'wsi_survival', dataLevel: 'wsi' })
    const wsiGroup = screen.getByText('training.taskSetup.wsiLevel').closest('div')!
    const wsiCards = wsiGroup.querySelectorAll('div[class*="relative"]')
    expect(wsiCards[1].querySelector('svg')).toBeInTheDocument()
  })

  it('preserves task name, description, cancel and next behavior', () => {
    const onNext = vi.fn()
    const setTaskName = vi.fn()
    const setTaskDescription = vi.fn()
    renderTaskSetupStep({ onNext, setTaskName, setTaskDescription, canProceed: true })

    const nameInput = screen.getByPlaceholderText('training.taskSetup.taskNamePlaceholder')
    fireEvent.change(nameInput, { target: { value: 'Test Task' } })
    expect(setTaskName).toHaveBeenCalledWith('Test Task')

    const descInput = screen.getByPlaceholderText('training.taskSetup.descriptionPlaceholder')
    fireEvent.change(descInput, { target: { value: 'A description' } })
    expect(setTaskDescription).toHaveBeenCalledWith('A description')

    const nextButton = screen.getByRole('button', { name: 'training.taskSetup.nextSelectData' })
    fireEvent.click(nextButton)
    expect(onNext).toHaveBeenCalled()
  })
})
