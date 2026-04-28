import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import TaskListPage from '../../../src/renderer/src/pages/TaskListPage'
import * as apiModule from '../../../src/renderer/src/api'
import { TooltipProvider } from '../../../src/renderer/src/components/ui/tooltip'

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
  useAuth: () => ({
    isAdmin: false,
    user: { id: 'user-1' },
  }),
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
})
