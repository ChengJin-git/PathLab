import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PathScientistSessionsPage from '@renderer/pages/PathScientistSessionsPage'
import { deletePathScientistSession, listPathScientistSessions, stopPathScientistSession } from '@renderer/api/pathscientist'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/pathscientist', () => ({
  deletePathScientistSession: vi.fn(),
  listPathScientistSessions: vi.fn(),
  stopPathScientistSession: vi.fn(),
}))

describe('PathScientistSessionsPage', () => {
  beforeEach(() => {
    void i18n.changeLanguage('en-US')
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
    void i18n.changeLanguage('en-US')
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

  it('shows epoch progress on running session cards', async () => {
    vi.mocked(listPathScientistSessions).mockResolvedValue({
      items: [
        {
          session_id: 'running-epoch',
          conversation_id: 'conv-running-epoch',
          title: 'Running epoch',
          question: 'Train a model',
          model: 'gpt-5.5',
          status: 'running',
          stage: 'execution',
          created_at: 1779030000,
          updated_at: 1779030100,
          error: '',
          current_iteration: 0,
          max_iterations: 1,
          training_progress: {
            run_id: 'run_b',
            current_epoch: 7,
            total_epochs: 30,
            current_val_auc: 0.9636,
            best_val_auc: 0.9683,
          },
        },
      ],
    })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Running epoch')).toBeInTheDocument()
    const badges = screen.getByTestId('pathscientist-session-badges-running-epoch')
    expect(badges).toHaveTextContent('Iter 1/1')
    expect(badges).toHaveTextContent('Epoch 7/30')
    expect(badges).toHaveTextContent('AUC 0.964')
  })

  it('hides stale epoch progress on completed session cards', async () => {
    vi.mocked(listPathScientistSessions).mockResolvedValue({
      items: [
        {
          session_id: 'completed-epoch',
          conversation_id: 'conv-completed-epoch',
          title: 'Completed epoch',
          question: 'Train a model',
          model: 'gpt-5.5',
          status: 'completed',
          stage: 'completed',
          created_at: 1779030000,
          updated_at: 1779030100,
          error: '',
          current_iteration: 1,
          max_iterations: 1,
          training_progress: {
            run_id: 'run_b',
            current_epoch: 4,
            total_epochs: 5,
            current_val_auc: 1,
            best_val_auc: 1,
          },
        },
      ],
    })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Completed epoch')).toBeInTheDocument()
    const badges = screen.getByTestId('pathscientist-session-badges-completed-epoch')
    expect(badges).toHaveTextContent('completed')
    expect(badges).not.toHaveTextContent('Epoch')
    expect(badges).not.toHaveTextContent('AUC')
  })

  it('renders page chrome, empty state, and session actions from zh-CN translations', async () => {
    await i18n.changeLanguage('zh-CN')
    vi.mocked(listPathScientistSessions).mockResolvedValueOnce({ items: [] })

    const { unmount } = render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('研究会话')).toBeInTheDocument()
    expect(screen.getByText('刷新')).toBeInTheDocument()
    expect(screen.getByText('新建会话')).toBeInTheDocument()
    expect(screen.getByText('暂无 PathScientist 会话')).toBeInTheDocument()
    expect(screen.getByText('创建一个短会话，用于验证后端桥接和事件流。')).toBeInTheDocument()
    expect(screen.getByText('开始一个')).toBeInTheDocument()
    expect(screen.queryByText('Research sessions')).not.toBeInTheDocument()
    expect(screen.queryByText('No PathScientist sessions yet')).not.toBeInTheDocument()

    unmount()
    vi.mocked(listPathScientistSessions).mockResolvedValueOnce({
      items: [
        {
          session_id: 'i18n-running',
          conversation_id: 'conv-i18n',
          title: '',
          title_pending: true,
          question: 'Train a model',
          model: 'gpt-5.5',
          status: 'running',
          stage: 'execution',
          created_at: 1779030000,
          updated_at: 1779030100,
          workspace_size_bytes: 2048,
          error: '',
        },
      ],
    })

    render(
      <MemoryRouter>
        <PathScientistSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('正在生成标题...')).toBeInTheDocument()
    expect(screen.getByText('工作区')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /停止运行/ })).toBeInTheDocument()
    expect(screen.queryByText('Generating title...')).not.toBeInTheDocument()
    expect(screen.queryByText('Workspace')).not.toBeInTheDocument()
    expect(screen.queryByText('Stop run')).not.toBeInTheDocument()
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
