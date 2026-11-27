import React from 'react'
import { act, render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AnalysisConfigCard, type AgentAnalysisConfig } from '@renderer/components/chat/AnalysisConfigCard'
import { getTrainingTask, runTaskAnalysis } from '@renderer/api'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: vi.fn() },
  useTranslation: () => ({ t: (key: string) => key }),
}))
vi.mock('@renderer/contexts/ToastContext', () => ({ useToast: () => ({ warning: vi.fn() }) }))
vi.mock('@renderer/api', () => ({
  getTrainingTask: vi.fn(), runTaskAnalysis: vi.fn(), getTrainedModel: vi.fn(),
  startExternalValidation: vi.fn(), fetchValidationDataset: vi.fn(),
  ApiError: class extends Error { status = 500; isNotFound() { return false } },
}))

const config: AgentAnalysisConfig = {
  analysis_type: 'internal', task_id: 'train_1', task_name: 'Gastric Baseline',
  metrics: ['auc'], charts: ['roc_curve'],
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(getTrainingTask).mockResolvedValue({ status: 'completed' } as Awaited<ReturnType<typeof getTrainingTask>>)
  vi.mocked(runTaskAnalysis).mockResolvedValue({ task_id: 'train_1', analysis_id: 'analysis_1' } as Awaited<ReturnType<typeof runTaskAnalysis>>)
})

describe('confirmed analysis submission', () => {
  it('waits for validation, submits once on a new confirmation, never on mounting history', async () => {
    let resolve!: (task: Awaited<ReturnType<typeof getTrainingTask>>) => void
    vi.mocked(getTrainingTask).mockReturnValue(new Promise(done => { resolve = done }))
    const onSuccess = vi.fn()
    const view = render(<React.StrictMode><AnalysisConfigCard config={config} submitTrigger={3} onSubmitSuccess={onSuccess} /></React.StrictMode>)
    expect(runTaskAnalysis).not.toHaveBeenCalled()
    view.rerender(<React.StrictMode><AnalysisConfigCard config={config} submitTrigger={4} onSubmitSuccess={onSuccess} /></React.StrictMode>)
    expect(runTaskAnalysis).not.toHaveBeenCalled()
    await act(async () => resolve({ status: 'completed' } as Awaited<ReturnType<typeof getTrainingTask>>))
    await waitFor(() => expect(runTaskAnalysis).toHaveBeenCalledTimes(1))
    expect(runTaskAnalysis).toHaveBeenCalledWith('train_1', ['auc'], ['roc_curve'], undefined, undefined)
    view.rerender(<React.StrictMode><AnalysisConfigCard config={config} submitTrigger={5} onSubmitSuccess={onSuccess} /></React.StrictMode>)
    expect(runTaskAnalysis).toHaveBeenCalledTimes(1)
    expect(onSuccess).toHaveBeenCalledWith('train_1', 'analysis_1')
  })

  it('does not submit when the task is invalid', async () => {
    vi.mocked(getTrainingTask).mockResolvedValue({ status: 'running' } as Awaited<ReturnType<typeof getTrainingTask>>)
    const view = render(<AnalysisConfigCard config={config} submitTrigger={0} />)
    await waitFor(() => expect(getTrainingTask).toHaveBeenCalled())
    view.rerender(<AnalysisConfigCard config={config} submitTrigger={1} />)
    expect(runTaskAnalysis).not.toHaveBeenCalled()
  })
})
