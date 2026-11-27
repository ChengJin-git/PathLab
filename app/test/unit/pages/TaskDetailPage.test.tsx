import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TaskDetailPage from '../../../src/renderer/src/pages/TaskDetailPage'
import * as apiModule from '../../../src/renderer/src/api'
import type { InferenceTaskResponse } from '../../../src/renderer/src/api/analysis'
import type { TrainingTaskDetail } from '../../../src/renderer/src/api/training'
import { markTrainingSubmissionCreated } from '../../../src/renderer/src/lib/utils/trainingSubmissionTracker'

const authState = {
  isAdmin: false,
  canUseGpu: true,
}

function LocationDisplay() {
  const location = useLocation()
  return <div data-testid="location-display">{location.pathname}</div>
}

vi.mock('react-i18next', async importOriginal => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string) => key,
    }),
  }
})

vi.mock('../../../src/renderer/src/contexts/AuthContext', () => ({
  useAuth: () => authState,
}))

vi.mock('../../../src/renderer/src/components/taskDetail/ProgressSection', () => ({
  ProgressSection: () => <div data-testid="progress-section" />,
}))

vi.mock('../../../src/renderer/src/components/taskDetail/ConfigurationPanel', () => ({
  ConfigurationPanel: () => <div data-testid="configuration-panel" />,
}))

vi.mock('../../../src/renderer/src/components/taskDetail/LogViewer', () => ({
  LogViewer: () => <div data-testid="log-viewer" />,
}))

describe('TaskDetailPage extval rerun', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    authState.isAdmin = false
    authState.canUseGpu = true

    vi.spyOn(apiModule, 'getAuthToken').mockReturnValue(null)
    vi.spyOn(apiModule, 'cancelQueueTask').mockResolvedValue({ cancelled: true, message: 'cancelled' })
    vi.spyOn(apiModule, 'getTrainingTask').mockImplementation(async taskId => {
      if (taskId !== 'extval_source') {
        throw new apiModule.ApiError('Task not found', 404, 'NOT_FOUND')
      }

      return {
      task_id: 'extval_source',
      task_name: 'Validation Task',
      task_type: 'external_validation',
      data_type: 'wsi',
      task_description: 'validation failed',
      status: 'failed',
      progress: 0,
      error_message: null,
      classes: null,
      created_at: '2026-05-13T00:00:00Z',
      updated_at: '2026-05-13T00:00:00Z',
      started_at: null,
      finished_at: null,
      wsi_count: 4,
      preprocessing_config: {},
      model_config: {
        model_id: 'model_1',
        dataset_id: 'dataset_1',
        analysis_metrics: ['accuracy'],
        analysis_charts: ['roc_curve'],
        bootstrap_ci_metrics: ['accuracy'],
      },
      } as TrainingTaskDetail
    })
  })

  it('renders i18n key for synthetic creating status on extval rerun', async () => {
    const originalCrypto = globalThis.crypto
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID: () => '11111111-2222-3333-4444-555555555555' },
      configurable: true,
    })

    vi.spyOn(apiModule, 'startExternalValidation').mockImplementation(
      () => new Promise(() => {})
    )

    render(
      <MemoryRouter initialEntries={['/task/extval_source']}>
        <Routes>
          <Route path="/task/:task_id" element={<><TaskDetailPage /><LocationDisplay /></>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByText('Validation Task')

    fireEvent.click(screen.getByRole('button', { name: 'taskDetail.rerun' }))

    await waitFor(() => {
      expect(screen.getByTestId('location-display').textContent).toBe('/task/extval_1111111122223333')
    })

    await waitFor(() => {
      expect(screen.getByText('taskList.progress.creatingTask')).toBeInTheDocument()
    })

    Object.defineProperty(globalThis, 'crypto', {
      value: originalCrypto,
      configurable: true,
    })
  })

  it('navigates immediately to a synthetic task page while extval rerun is still submitting', async () => {
    const originalCrypto = globalThis.crypto
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID: () => '11111111-2222-3333-4444-555555555555' },
      configurable: true,
    })

    let resolveRequest: ((value: InferenceTaskResponse) => void) | null = null
    vi.spyOn(apiModule, 'startExternalValidation').mockImplementation(
      () => new Promise(resolve => {
        resolveRequest = resolve
      })
    )

    render(
      <MemoryRouter initialEntries={['/task/extval_source']}>
        <Routes>
          <Route path="/task/:task_id" element={<><TaskDetailPage /><LocationDisplay /></>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByText('Validation Task')

    fireEvent.click(screen.getByRole('button', { name: 'taskDetail.rerun' }))

    await waitFor(() => {
      expect(screen.getByTestId('location-display').textContent).toBe('/task/extval_1111111122223333')
    })

    expect(apiModule.startExternalValidation).toHaveBeenCalledWith(
      'model_1',
      'dataset_1',
      ['accuracy'],
      ['roc_curve'],
      true,
      undefined
    )

    await act(async () => {
      resolveRequest?.({ task_id: 'extval_real123', status: 'pending', total_wsi: 4 })
      await Promise.resolve()
    })

    await waitFor(() => {
      expect(screen.getByTestId('location-display').textContent).toBe('/task/extval_real123')
    })

    Object.defineProperty(globalThis, 'crypto', {
      value: originalCrypto,
      configurable: true,
    })
  })

  it('does not call getTrainingTask for a pending synthetic extval ID before startExternalValidation resolves', async () => {
    const originalCrypto = globalThis.crypto
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID: () => '11111111-2222-3333-4444-555555555555' },
      configurable: true,
    })

    vi.spyOn(apiModule, 'startExternalValidation').mockImplementation(
      () => new Promise(() => {})
    )

    render(
      <MemoryRouter initialEntries={['/task/extval_source']}>
        <Routes>
          <Route path="/task/:task_id" element={<><TaskDetailPage /><LocationDisplay /></>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByText('Validation Task')

    fireEvent.click(screen.getByRole('button', { name: 'taskDetail.rerun' }))

    await waitFor(() => {
      expect(screen.getByTestId('location-display').textContent).toBe('/task/extval_1111111122223333')
    })

    const getTrainingTaskCalls = vi.mocked(apiModule.getTrainingTask).mock.calls
    const syntheticCalls = getTrainingTaskCalls.filter(([id]) => id === 'extval_1111111122223333')
    expect(syntheticCalls).toHaveLength(0)

    Object.defineProperty(globalThis, 'crypto', {
      value: originalCrypto,
      configurable: true,
    })
  })

  it('does not poll getTrainingTask for a pending synthetic extval ID after the interval fires', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    const originalCrypto = globalThis.crypto
    Object.defineProperty(globalThis, 'crypto', {
      value: { randomUUID: () => '11111111-2222-3333-4444-555555555555' },
      configurable: true,
    })

    vi.spyOn(apiModule, 'startExternalValidation').mockImplementation(
      () => new Promise(() => {})
    )

    render(
      <MemoryRouter initialEntries={['/task/extval_source']}>
        <Routes>
          <Route path="/task/:task_id" element={<><TaskDetailPage /><LocationDisplay /></>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByText('Validation Task')

    fireEvent.click(screen.getByRole('button', { name: 'taskDetail.rerun' }))

    await waitFor(() => {
      expect(screen.getByTestId('location-display').textContent).toBe('/task/extval_1111111122223333')
    })

    await act(async () => {
      vi.advanceTimersByTime(3000)
      await Promise.resolve()
    })

    const getTrainingTaskCalls = vi.mocked(apiModule.getTrainingTask).mock.calls
    const syntheticCalls = getTrainingTaskCalls.filter(([id]) => id === 'extval_1111111122223333')
    expect(syntheticCalls).toHaveLength(0)

    Object.defineProperty(globalThis, 'crypto', {
      value: originalCrypto,
      configurable: true,
    })

    vi.useRealTimers()
  })

  it('does not keep polling a stale created synthetic extval ID after restart', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    markTrainingSubmissionCreated('extval_stale11112222')

    render(
      <MemoryRouter initialEntries={['/task/extval_stale11112222']}>
        <Routes>
          <Route path="/task/:task_id" element={<><TaskDetailPage /><LocationDisplay /></>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByText('taskDetail.taskNotFound')

    await act(async () => {
      vi.advanceTimersByTime(5000)
      await Promise.resolve()
    })

    const getTrainingTaskCalls = vi.mocked(apiModule.getTrainingTask).mock.calls
    const staleCalls = getTrainingTaskCalls.filter(([id]) => id === 'extval_stale11112222')
    expect(staleCalls).toHaveLength(1)

    vi.useRealTimers()
  })
})
