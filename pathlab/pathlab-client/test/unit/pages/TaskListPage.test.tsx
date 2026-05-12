import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TaskListPage from '../../../src/renderer/src/pages/TaskListPage'
import * as apiModule from '../../../src/renderer/src/api'
import { TooltipProvider } from '../../../src/renderer/src/components/ui/tooltip'

const authState = {
  isAdmin: false,
  user: { id: 'user-1' },
}

vi.mock('react-i18next', async importOriginal => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  return {
    ...actual,
    useTranslation: () => ({
      t: (key: string, options?: Record<string, unknown>) => {
        if (options?.count !== undefined) return `${key}:${String(options.count)}`
        return key
      },
    }),
  }
})

vi.mock('../../../src/renderer/src/contexts/AuthContext', () => ({
  useAuth: () => authState,
}))

vi.mock('../../../src/renderer/src/contexts/BackgroundTaskContext', () => ({
  useBackgroundTask: () => ({
    rawTrainingTasks: null,
    subscribeTrainingSSE: () => () => {},
  }),
}))

describe('TaskListPage delete modal', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
    authState.isAdmin = false
    authState.user = { id: 'user-1' }
  })

  it('shows mode-specific cleanup scope instead of exact zero totals for quick storage summaries', async () => {
    vi.spyOn(apiModule, 'getTrainingTasks').mockResolvedValue({
      items: [
        {
          task_id: 'task-1',
          task_name: 'Quick Summary Task',
          task_type: 'wsi_classification',
          data_type: 'wsi',
          task_description: null,
          status: 'completed',
          progress: 100,
          error_message: null,
          preprocessing_config: null,
          model_config: null,
          classes: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:05:00Z',
          started_at: '2026-01-01T00:00:00Z',
          finished_at: '2026-01-01T00:05:00Z',
          user_id: 'user-1',
        },
      ],
      total: 1,
      stats: { total: 1, running: 0, completed: 1, failed: 0, cancelled: 0 },
    })

    vi.spyOn(apiModule, 'getTrainingTaskStorageInfo').mockResolvedValue({
      task_id: 'task-1',
      quick: true,
      ai_results: { path: '', size: 0, exists: true, file_count: 0, wsi_dir_count: 0 },
      training_dir: { path: '', size: 0, exists: true, file_count: 0 },
      training_logs: { path: '', size: 0, exists: true, file_count: 0 },
      analysis_logs: { path: '', size: 0, exists: true, file_count: 0 },
      models: [{ path: '', size: 0, exists: true, file_count: 0 }],
      total_size: 0,
      total_size_mb: 0,
      total_size_gb: 0,
      total_files: 0,
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })

    const { container } = render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter>
            <TaskListPage />
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    )

    await screen.findByText('Quick Summary Task')

    const deleteButton = container.querySelector('button.group\\/delete')
    expect(deleteButton).toBeInstanceOf(HTMLButtonElement)
    fireEvent.click(deleteButton as HTMLButtonElement)

    await screen.findByText('taskList.deleteModal.singleTitle')
    await waitFor(() => {
      expect(apiModule.getTrainingTaskStorageInfo).toHaveBeenCalledWith('task-1', { quick: true })
    })

    const modalTitle = screen.getByText('taskList.deleteModal.singleTitle')
    const modalSubtitle = screen.getByText('taskList.deleteModal.cannotBeUndone')
    expect(modalTitle).toHaveClass('text-center')
    expect(modalSubtitle).toHaveClass('text-center')
    expect(screen.queryByText('taskList.deleteModal.quickScopeTitle')).not.toBeInTheDocument()
    expect(screen.getByText('taskList.deleteModal.trainingDataQuick')).toBeInTheDocument()
    expect(screen.getByText('taskList.deleteModal.aiResultsQuick')).toBeInTheDocument()
    expect(screen.getByText('taskList.deleteModal.logsQuick')).toBeInTheDocument()
    expect(screen.getByText('taskList.deleteModal.analysisLogsQuick')).toBeInTheDocument()
    expect(screen.getByText('taskList.deleteModal.modelsKeptQuick')).toBeInTheDocument()
    expect(screen.queryByText('taskList.deleteModal.modelsQuick')).not.toBeInTheDocument()
    expect(screen.queryByText('0 B')).not.toBeInTheDocument()
    expect(screen.queryByText('taskList.deleteModal.files:0')).not.toBeInTheDocument()
    expect(screen.queryByText(/不准确的 0 B/)).not.toBeInTheDocument()
    expect(screen.queryByText(/后台清理任务统计/)).not.toBeInTheDocument()

    fireEvent.click(screen.getByDisplayValue('complete'))

    expect(screen.getByText('taskList.deleteModal.modelsQuick')).toBeInTheDocument()
    expect(screen.queryByText('taskList.deleteModal.modelsKeptQuick')).not.toBeInTheDocument()
  })

  it('maps admin queue gpu stage details by task id from stage-keyed snapshots', async () => {
    authState.isAdmin = true

    vi.spyOn(apiModule, 'getTrainingTasks').mockResolvedValue({
      items: [
        {
          task_id: 'task-1',
          task_name: 'Queued Training Task',
          task_type: 'wsi_classification',
          data_type: 'wsi',
          task_description: null,
          status: 'training',
          progress: 40,
          error_message: null,
          preprocessing_config: null,
          model_config: null,
          classes: null,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:05:00Z',
          started_at: '2026-01-01T00:00:00Z',
          finished_at: null,
          user_id: 'user-1',
        },
      ],
      total: 1,
      stats: { total: 1, running: 1, completed: 0, failed: 0, cancelled: 0 },
    })

    vi.spyOn(apiModule, 'getQueueStatus').mockResolvedValue({
      max_concurrent: 2,
      gpu_count: 2,
      running_count: 1,
      pending_count: 0,
      queue_size: 0,
      running_task_ids: ['task-1'],
      running_tasks: [{ task_id: 'task-1', gpu: 1 }],
      pending_task_ids: [],
      is_running: true,
      gpu_stage_details: {
        'task-1:feature_extraction': {
          task_id: 'task-1',
          stage: 'feature_extraction',
          state: 'running',
          gpu: 1,
          device: 'cuda:1',
          required_vram_mb: 6500,
          effective_free_mb: 12000,
        },
      },
    })

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
      },
    })

    render(
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <MemoryRouter>
            <TaskListPage />
          </MemoryRouter>
        </TooltipProvider>
      </QueryClientProvider>,
    )

    await screen.findByText('Queued Training Task')

    expect(screen.getByText('Running')).toBeInTheDocument()
    expect(screen.getByText('feature_extraction')).toBeInTheDocument()
    expect(screen.getByText('cuda:1')).toBeInTheDocument()
  })
})
