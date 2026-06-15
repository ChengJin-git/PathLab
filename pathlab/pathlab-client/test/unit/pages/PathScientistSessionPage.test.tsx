import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PathScientistSessionPage from '@renderer/pages/PathScientistSessionPage'
import { deletePathScientistSession, getPathScientistEventsUrl, getPathScientistSession, stopPathScientistSession } from '@renderer/api/pathscientist'
import type { PathScientistEvent, PathScientistSessionDetail } from '@renderer/types/pathscientist'
<<<<<<< HEAD
=======
import { useAuth } from '@renderer/contexts/AuthContext'

vi.mock('@renderer/contexts/AuthContext', () => ({
  useAuth: vi.fn(),
}))
>>>>>>> auto-frontend/main

vi.mock('@renderer/api/pathscientist', () => ({
  deletePathScientistSession: vi.fn(),
  getPathScientistSession: vi.fn(),
  getPathScientistEventsUrl: vi.fn(),
  stopPathScientistSession: vi.fn(),
  getPathScientistRunDownloadUrl: (sessionId: string, runId: string) => (
    `/api/pathscientist/sessions/${sessionId}/runs/${runId}/download`
  ),
}))

class MockEventSource {
  static CLOSED = 2
  static instances: MockEventSource[] = []
  readyState = 1
  onerror: ((event: Event) => void) | null = null
  constructor(public url: string) {
    MockEventSource.instances.push(this)
  }
  addEventListener = vi.fn()
  close = vi.fn(() => {
    this.readyState = MockEventSource.CLOSED
  })
}

const events: PathScientistEvent[] = [
  { kind: 'session', status: 'running', stage: 'execution', summary: 'Session started' },
  { kind: 'message', stage: 'grounding', text: 'Task profile: mil_classification / slide\nextractor_name: virchow2\nABMIL baseline' },
  { kind: 'tool_call', ui_kind: 'tool', stage: 'execution', iteration: 1, tool: 'run_experiment', summary: 'run_experiment' },
  { kind: 'tool_observation', ui_kind: 'tool', stage: 'execution', iteration: 1, tool: 'run_experiment', exit_code: 0, summary: 'auc=0.760 finished' },
  {
    kind: 'state',
    status: 'running',
    state: {
      stage: 'execution',
      best_metric_value: 0.76,
      objective: { success_metric: 'auc', target_metric_value: 0.84, target_source: 'paper-x' },
      run_history: [{ iteration: 1, metric_name: 'auc', metric_value: 0.76, committed: true, run_id: 'run_a' }],
    },
  },
]

const session: PathScientistSessionDetail = {
  session_id: 's1',
  title: 'Gastritis MIL benchmark',
  question: 'Train a model for gastritis classification',
  model: 'gpt-5.5',
  status: 'running',
  stage: 'execution',
  workspace_size_bytes: 2048,
  events,
}

<<<<<<< HEAD
function renderPage() {
=======
function mockAuth(role: 'admin' | 'pathologist' | 'guest' = 'admin') {
  vi.mocked(useAuth).mockReturnValue({
    isAdmin: role === 'admin',
    isPathologist: role === 'pathologist',
    isLoggedIn: true,
    isLoading: false,
    user: { role } as any,
    canUseGpu: role !== 'guest',
  } as any)
}

function renderPage(role: 'admin' | 'pathologist' | 'guest' = 'admin') {
  mockAuth(role)
>>>>>>> auto-frontend/main
  return render(
    <MemoryRouter initialEntries={["/pathscientist/sessions/s1"]}>
      <Routes>
        <Route path="/pathscientist/sessions/:id" element={<PathScientistSessionPage />} />
<<<<<<< HEAD
        <Route path="/pathscientist" element={<div>sessions</div>} />
=======
        <Route path="/pathscientist/new" element={<div>new session</div>} />
>>>>>>> auto-frontend/main
      </Routes>
    </MemoryRouter>,
  )
}

describe('PathScientistSessionPage', () => {
  afterEach(() => cleanup())

  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
    vi.mocked(getPathScientistSession).mockResolvedValue({
      ...session,
      status: 'finished',
      stage: 'finished',
      events: events.map((event, index) => ({ ...event, seq: index + 1, status: index === 0 ? 'finished' : event.status })),
    })
    vi.mocked(getPathScientistEventsUrl).mockReturnValue('/api/pathscientist/sessions/s1/events')
    vi.mocked(stopPathScientistSession).mockResolvedValue({
      ...session,
      status: 'interrupted',
      stage: 'interrupted',
      events,
    })
    vi.mocked(deletePathScientistSession).mockResolvedValue({ session_id: 's1', deleted: true, workspace_deleted: true })
  })

  it('uses the structured execution console instead of the raw event dump', async () => {
    renderPage()

    expect(await screen.findByText('Execution console')).toBeInTheDocument()
    expect(screen.getByText('Stage timeline')).toBeInTheDocument()
    expect(screen.queryByText('Target to beat')).not.toBeInTheDocument()
    expect(screen.getByText('Task type')).toBeInTheDocument()
    expect(screen.getAllByText('slide-level classification').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Foundation model').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Virchow2').length).toBeGreaterThan(0)
    expect(screen.getAllByText('MIL method').length).toBeGreaterThan(0)
    expect(screen.getAllByText('ABMIL').length).toBeGreaterThan(0)
    expect(screen.queryByText('Event stream')).not.toBeInTheDocument()
    expect(screen.queryByText('Raw state')).not.toBeInTheDocument()
    expect(screen.queryByText(/"kind"/)).not.toBeInTheDocument()
  })

  it('does not open the live event stream for completed replay sessions', async () => {
    vi.mocked(getPathScientistSession).mockResolvedValue({
      ...session,
      status: 'finished',
      stage: 'finished',
      events: events.map((event, index) => ({ ...event, seq: index + 1, status: index === 0 ? 'finished' : event.status })),
    })

    renderPage()

    expect(await screen.findByText('Execution console')).toBeInTheDocument()
    expect(MockEventSource.instances).toHaveLength(0)
    expect(screen.queryByText('closed replay')).not.toBeInTheDocument()
    expect(screen.queryByTestId('pathscientist-status-bar')).not.toBeInTheDocument()
  })

  it('shows a loading title while the LLM title is pending', async () => {
    vi.mocked(getPathScientistSession).mockResolvedValue({
      ...session,
      title: '',
      title_pending: true,
      status: 'running',
      stage: 'execution',
    })

    renderPage()

    expect(await screen.findByText('Generating title...')).toBeInTheDocument()
    expect(screen.getAllByText('Train a model for gastritis classification').length).toBeGreaterThan(0)
  })

  it('shows workspace disk usage on the detail summary cards', async () => {
    renderPage()

    expect(await screen.findByText('Execution console')).toBeInTheDocument()
    expect(screen.getByText('Workspace')).toBeInTheDocument()
    expect(screen.getByText('2.0 KB')).toBeInTheDocument()
  })

  it('stops a running session from the header action', async () => {
    vi.mocked(getPathScientistSession).mockResolvedValue({
      ...session,
      status: 'running',
      stage: 'execution',
    })

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /stop run/i }))

    await waitFor(() => expect(stopPathScientistSession).toHaveBeenCalledWith('s1'))
    await waitFor(() => expect(screen.getAllByText('interrupted').length).toBeGreaterThan(0))
  })

  it('shows elapsed running time next to the running status on the detail page', async () => {
    vi.mocked(getPathScientistSession).mockResolvedValue({
      ...session,
      status: 'running',
      stage: 'execution',
      created_at: Math.floor(Date.now() / 1000) - 185,
    })

    renderPage()

    expect(await screen.findByText('Execution console')).toBeInTheDocument()
    expect(screen.getByTestId('pathscientist-session-status-pill')).toHaveTextContent(/running.*3m/)
  })

  it('deletes a completed session from the detail page and returns to the list', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(getPathScientistSession).mockResolvedValue({
      ...session,
      status: 'completed',
      stage: 'completed',
    })

    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /delete session/i }))

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('workspace'))
    expect(confirm).not.toHaveBeenCalledWith(expect.stringContaining('kept'))
    await waitFor(() => expect(deletePathScientistSession).toHaveBeenCalledWith('s1'))
<<<<<<< HEAD
    expect(await screen.findByText('sessions')).toBeInTheDocument()
=======
    expect(await screen.findByText('new session')).toBeInTheDocument()
  })

  it('shows the simplified clinical view for pathologist users', async () => {
    renderPage('pathologist')

    expect(await screen.findByTestId('pathscientist-clinical-session')).toBeInTheDocument()
    expect(screen.getByTestId('pathscientist-clinical-overview')).toBeInTheDocument()
    expect(screen.getByTestId('pathscientist-clinical-progress')).toBeInTheDocument()
    expect(screen.getByText('pathScientist.clinical.technicalDetails')).toBeInTheDocument()
    expect(screen.queryByText('Execution console')).not.toBeInTheDocument()
    expect(screen.queryByText('Workspace')).not.toBeInTheDocument()
>>>>>>> auto-frontend/main
  })

  it('keeps a completed session completed when older stream events still say running', async () => {
    vi.mocked(getPathScientistSession).mockResolvedValue({
      ...session,
      status: 'completed',
      stage: 'completed',
      events: [
        { kind: 'state', status: 'running', stage: 'execution', state: { stage: 'execution' } },
        { kind: 'state', stage: 'completed', state: { stage: 'completed' }, summary: 'Stage completed' },
      ],
    })

    renderPage()

    expect(await screen.findByText('Execution console')).toBeInTheDocument()
    expect(screen.getAllByText('completed').length).toBeGreaterThan(0)
    expect(screen.queryByText('running')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /stop run/i })).not.toBeInTheDocument()
  })
})
