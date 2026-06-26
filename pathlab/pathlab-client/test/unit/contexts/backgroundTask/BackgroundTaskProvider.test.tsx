import { describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BackgroundTaskProvider, useBackgroundTask } from '@renderer/contexts/backgroundTask'
import { notifyAutoResearchSessionCreated } from '@renderer/lib/autoresearchSessionEvents'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/contexts/AuthContext', () => ({
  useAuth: () => ({ isAdmin: true, isLoggedIn: true }),
}))

vi.mock('@renderer/api/client', () => ({
  apiFetch: vi.fn().mockResolvedValue({ status: 'idle' }),
  getAuthToken: () => 'token-1',
}))

vi.mock('@renderer/lib/utils/trainingSubmissionTracker', () => ({
  clearTrainingSubmissionRecord: vi.fn(),
  isTrainingSubmissionPendingTimedOut: vi.fn(() => false),
  listTrainingSubmissionRecords: vi.fn(() => []),
}))

vi.mock('@renderer/contexts/backgroundTask/useTrainingSSE', () => ({
  useTrainingSSE: () => ({ trainingTasks: [], rawTrainingTasks: [] }),
}))

vi.mock('@renderer/contexts/backgroundTask/useAnalysisSSE', () => ({
  useAnalysisSSE: () => ({ analysisTasks: [] }),
}))

vi.mock('@renderer/contexts/backgroundTask/useStorageSSE', () => ({
  useStorageSSE: () => ({
    storageTasks: [
      {
        id: 'scan_scan_123',
        type: 'scan_directory',
        title: 'Scan Directory',
        items: [{ id: 'scan_123', name: 'Scan Directory', status: 'running', progress: 0 }],
        status: 'running',
        createdAt: new Date('2026-01-01T00:00:00Z'),
        totalProgress: 0,
        successCount: 0,
        failedCount: 0,
        isServerTask: true,
        serverTaskStatus: 'processing',
      },
      {
        id: 'import_import_123',
        type: 'batch_import',
        title: 'Batch Import',
        items: [{ id: 'import_123', name: 'Batch Import', status: 'running', progress: 25 }],
        status: 'running',
        createdAt: new Date('2026-01-01T00:00:00Z'),
        totalProgress: 25,
        successCount: 0,
        failedCount: 0,
        isServerTask: true,
        serverTaskStatus: 'processing',
      },
    ],
  }),
}))

function TaskListProbe() {
  const { tasks } = useBackgroundTask()
  return (
    <ul>
      {tasks.map(task => <li key={task.id}>{task.title}</li>)}
    </ul>
  )
}

function TaskTypesProbe() {
  const { tasks } = useBackgroundTask()
  return (
    <ul data-testid="task-types">
      {tasks.map(task => (
        <li key={task.id} data-type={task.type} data-created-at={task.createdAt.toISOString()}>
          {task.type}
        </li>
      ))}
    </ul>
  )
}

describe('BackgroundTaskProvider', () => {
  it('keeps page-local scan_directory tasks out of the global notification list', async () => {
    const queryClient = new QueryClient()

    render(
      <QueryClientProvider client={queryClient}>
        <BackgroundTaskProvider>
          <TaskListProbe />
        </BackgroundTaskProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => expect(screen.getByText('Batch Import')).toBeInTheDocument())
    expect(screen.queryByText('Scan Directory')).not.toBeInTheDocument()
  })

  it('exposes an autoresearch task when notifyAutoResearchSessionCreated is fired', async () => {
    const queryClient = new QueryClient()

    render(
      <QueryClientProvider client={queryClient}>
        <BackgroundTaskProvider>
          <TaskTypesProbe />
        </BackgroundTaskProvider>
      </QueryClientProvider>,
    )

    act(() => {
      notifyAutoResearchSessionCreated({
        session_id: 'ar-session-001',
        question: 'Test research question',
        status: 'running',
        created_at: 1782403200,
        updated_at: 1782403200,
      })
    })

    await waitFor(() => {
      const autoresearchItems = screen.getAllByText('autoresearch')
      expect(autoresearchItems.length).toBeGreaterThan(0)
    })
    expect(screen.getByText('autoresearch')).toHaveAttribute('data-created-at', '2026-06-25T16:00:00.000Z')
  })
})
