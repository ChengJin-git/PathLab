import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PathScientistSessionsPage from '@renderer/pages/PathScientistSessionsPage'
import { deletePathScientistSession, listPathScientistSessions, stopPathScientistSession } from '@renderer/api/pathscientist'

vi.mock('@renderer/api/pathscientist', () => ({
  deletePathScientistSession: vi.fn(),
  listPathScientistSessions: vi.fn(),
  stopPathScientistSession: vi.fn(),
}))

describe('PathScientistSessionsPage', () => {
  beforeEach(() => {
    vi.mocked(listPathScientistSessions).mockResolvedValue({
      items: [
        {
          session_id: 'legacy1',
          conversation_id: 'conv1',
          title: 'Legacy run',
          question: 'Legacy run question',
          model: 'gpt-5.5',
          status: 'finished',
          stage: 'completed',
          created_at: 1779030000,
          updated_at: 1779030100,
          workspace_size_bytes: 1536,
          error: '',
        },
      ],
    })
    vi.mocked(stopPathScientistSession).mockReset()
    vi.mocked(deletePathScientistSession).mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('shows legacy finished sessions as completed on the main page', async () => {
    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    expect(screen.getAllByText('completed')).toHaveLength(1)
    expect(screen.queryByText('finished')).not.toBeInTheDocument()
  })

  it('shows each session workspace disk usage on the sessions page', async () => {
    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    expect(screen.getByText('Workspace')).toBeInTheDocument()
    expect(screen.getByText('1.5 KB')).toBeInTheDocument()
  })

  it('places the session status badge in the bottom-right metadata row', async () => {
    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    const card = screen.getByTestId('pathscientist-session-card-legacy1')
    const mainRow = screen.getByTestId('pathscientist-session-main-row-legacy1')
    const footer = screen.getByTestId('pathscientist-session-footer-legacy1')
    const badges = screen.getByTestId('pathscientist-session-badges-legacy1')

    expect(card).toContainElement(footer)
    expect(mainRow).not.toContainElement(footer)
    expect(footer).toContainElement(badges)
    expect(footer).toHaveClass('justify-between')
    expect(badges).toHaveClass('justify-end')
    expect(badges).toHaveTextContent('completed')
  })

  it('shows a loading title state while the LLM title is pending', async () => {
    vi.mocked(listPathScientistSessions).mockResolvedValue({
      items: [
        {
          session_id: 'pending-title',
          conversation_id: '',
          title: '',
          title_pending: true,
          question: 'Train a chronic gastritis WSI MIL classifier',
          model: 'gpt-5.5',
          status: 'running',
          stage: 'grounding',
          created_at: 1779030000,
          updated_at: 1779030100,
          error: '',
        },
      ],
    })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Generating title...')).toBeInTheDocument()
    expect(screen.getByText('Train a chronic gastritis WSI MIL classifier')).toBeInTheDocument()
  })

  it('shows elapsed running time on running session cards', async () => {
    vi.mocked(listPathScientistSessions).mockResolvedValue({
      items: [
        {
          session_id: 'running-timer',
          conversation_id: 'conv-running-timer',
          title: 'Running timer',
          question: 'Train a model',
          model: 'gpt-5.5',
          status: 'running',
          stage: 'execution',
          created_at: Math.floor(Date.now() / 1000) - 125,
          updated_at: Math.floor(Date.now() / 1000),
          error: '',
        },
      ],
    })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Running timer')).toBeInTheDocument()
    expect(screen.getByTestId('pathscientist-session-badges-running-timer')).toHaveTextContent(/running.*2m/)
  })

  it('deduplicates backend rows for the same workspace and keeps the live gateway session', async () => {
    vi.mocked(listPathScientistSessions).mockResolvedValue({
      items: [
        {
          session_id: 'legacy-dup',
          conversation_id: 'conv-dup',
          title: 'Legacy duplicate',
          question: 'Train LUAD LUSC',
          model: '',
          status: 'interrupted',
          stage: 'interrupted',
          created_at: 1779030100,
          updated_at: 1779030200,
          workspace_path: '/tmp/pathscientist/session_same',
          error: '',
        },
        {
          session_id: 'gateway-live',
          conversation_id: '',
          title: 'Gateway live',
          question: 'Train LUAD LUSC',
          model: 'gpt-5.5',
          status: 'running',
          stage: 'execution',
          created_at: 1779030000,
          updated_at: 1779030201,
          workspace_path: '/tmp/pathscientist/session_same',
          error: '',
        },
      ],
    })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Gateway live')).toBeInTheDocument()
    expect(screen.queryByText('Legacy duplicate')).not.toBeInTheDocument()
    expect(screen.getAllByTestId(/pathscientist-session-card-/)).toHaveLength(1)
  })

  it('shows a stop button for running sessions on the sessions page', async () => {
    vi.mocked(listPathScientistSessions).mockResolvedValue({
      items: [
        {
          session_id: 'running1',
          conversation_id: 'conv-running',
          title: 'Running run',
          question: 'Train a model',
          model: 'gpt-5.5',
          status: 'running',
          stage: 'execution',
          created_at: 1779030000,
          updated_at: 1779030100,
          error: '',
        },
      ],
    })
    vi.mocked(stopPathScientistSession).mockResolvedValue({
      session_id: 'running1',
      conversation_id: 'conv-running',
      title: 'Running run',
      question: 'Train a model',
      model: 'gpt-5.5',
      status: 'interrupted',
      stage: 'interrupted',
      created_at: 1779030000,
      updated_at: 1779030100,
      error: 'Stopped by user from PathLab.',
    })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    const stopButton = await screen.findByRole('button', { name: /stop run/i })
    fireEvent.click(stopButton)

    await waitFor(() => expect(stopPathScientistSession).toHaveBeenCalledWith('running1'))
    expect(await screen.findByText('interrupted')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /stop run/i })).not.toBeInTheDocument()
  })

  it('deletes a completed session from the sessions page', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(deletePathScientistSession).mockResolvedValue({ session_id: 'legacy1', deleted: true, workspace_deleted: true })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /delete session/i }))

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('workspace'))
    expect(confirm).not.toHaveBeenCalledWith(expect.stringContaining('kept'))
    await waitFor(() => expect(deletePathScientistSession).toHaveBeenCalledWith('legacy1'))
    expect(screen.queryByText('Legacy run')).not.toBeInTheDocument()
  })
})
