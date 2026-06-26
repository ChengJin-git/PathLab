import { describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BackgroundTaskProvider, useBackgroundTask } from '@renderer/contexts/backgroundTask'
import { notifyAutoResearchSessionCreated } from '@renderer/lib/autoresearchSessionEvents'
import { getAutoResearchSession, stopAutoResearchSession } from '@renderer/api/autoresearch'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}))

vi.mock('@renderer/api/autoresearch', () => ({
  getAutoResearchSession: vi.fn(),
  stopAutoResearchSession: vi.fn(),
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

  it('syncs autoresearch status and progress from polling', async () => {
    vi.useFakeTimers()
    vi.mocked(getAutoResearchSession).mockResolvedValue({
      session_id: 'ar-poll-001',
      question: 'Poll test',
      status: 'running',
      current_iteration: 2,
      max_iterations: 5,
      events: [],
    })

    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <BackgroundTaskProvider>
          <TaskDetailsProbe />
        </BackgroundTaskProvider>
      </QueryClientProvider>,
    )

    act(() => {
      notifyAutoResearchSessionCreated({
        session_id: 'ar-poll-001',
        question: 'Poll test',
        status: 'queued',
        created_at: 1782403200,
        updated_at: 1782403200,
      })
    })

    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })

    const item = screen.getByText(/autoresearch/)
    expect(item.getAttribute('data-status')).toBe('running')
    expect(item.getAttribute('data-progress')).toBe('40')
    expect(item.getAttribute('data-server')).toBe('true')
    vi.useRealTimers()
  })

  it('marks autoresearch task cancelled when session is interrupted', async () => {
    vi.useFakeTimers()
    vi.mocked(getAutoResearchSession).mockResolvedValue({
      session_id: 'ar-interrupt-001',
      question: 'Interrupt test',
      status: 'interrupted',
      current_iteration: 3,
      max_iterations: 5,
      events: [],
    })

    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <BackgroundTaskProvider>
          <TaskDetailsProbe />
        </BackgroundTaskProvider>
      </QueryClientProvider>,
    )

    act(() => {
      notifyAutoResearchSessionCreated({
        session_id: 'ar-interrupt-001',
        question: 'Interrupt test',
        status: 'running',
        created_at: 1782403200,
        updated_at: 1782403200,
      })
    })

    await act(async () => { await vi.advanceTimersByTimeAsync(3000) })

    const item = screen.getByText(/autoresearch/)
    expect(item.getAttribute('data-status')).toBe('cancelled')
    vi.useRealTimers()
  })

  it('cancel calls stopAutoResearchSession for autoresearch tasks', async () => {
    vi.mocked(getAutoResearchSession).mockResolvedValue({
      session_id: 'ar-cancel-001',
      question: 'Cancel test',
      status: 'running',
      events: [],
    })
    vi.mocked(stopAutoResearchSession).mockResolvedValue({
      session_id: 'ar-cancel-001',
      status: 'interrupted',
      question: 'Cancel test',
    })

    const queryClient = new QueryClient()
    render(
      <QueryClientProvider client={queryClient}>
        <BackgroundTaskProvider>
          <CancelServerTaskProbe taskId="ar-cancel-001" />
        </BackgroundTaskProvider>
      </QueryClientProvider>,
    )

    act(() => {
      notifyAutoResearchSessionCreated({
        session_id: 'ar-cancel-001',
        question: 'Cancel test',
        status: 'running',
        created_at: 1782403200,
        updated_at: 1782403200,
      })
    })

    await waitFor(() => expect(screen.getByTestId('cancel-server')).toBeInTheDocument())
    await act(async () => {
      fireEvent.click(screen.getByTestId('cancel-server'))
    })
    await waitFor(() => expect(vi.mocked(stopAutoResearchSession)).toHaveBeenCalledWith('ar-cancel-001'))
  })
})

function TaskDetailsProbe() {
  const { tasks } = useBackgroundTask()
  return (
    <ul data-testid="task-details">
      {tasks.map(task => (
        <li key={task.id} data-status={task.status} data-progress={task.totalProgress} data-server={task.isServerTask ? 'true' : 'false'}>
          {task.type}:{task.status}:{task.totalProgress}
        </li>
      ))}
    </ul>
  )
}

function CancelServerTaskProbe({ taskId }: { taskId: string }) {
  const { cancelServerTask, tasks } = useBackgroundTask()
  const task = tasks.find(t => t.id === taskId)
  return (
    <button data-testid="cancel-server" onClick={() => task && cancelServerTask(task)}>Cancel</button>
  )
}
