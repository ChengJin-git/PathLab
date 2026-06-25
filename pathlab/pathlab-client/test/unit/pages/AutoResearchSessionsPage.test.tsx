import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AutoResearchSessionsPage from '@renderer/pages/AutoResearchSessionsPage'
import { deleteAutoResearchSession, listAutoResearchSessions, stopAutoResearchSession } from '@renderer/api/autoresearch'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/autoresearch', () => ({
  deleteAutoResearchSession: vi.fn(),
  listAutoResearchSessions: vi.fn(),
  stopAutoResearchSession: vi.fn(),
}))

describe('AutoResearchSessionsPage', () => {
  beforeEach(() => {
    void i18n.changeLanguage('en-US')
    vi.mocked(listAutoResearchSessions).mockResolvedValue({
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
    vi.mocked(stopAutoResearchSession).mockReset()
    vi.mocked(deleteAutoResearchSession).mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    void i18n.changeLanguage('en-US')
  })

  it('shows legacy finished sessions as completed on the main page', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    expect(screen.getAllByText('completed')).toHaveLength(1)
    expect(screen.queryByText('finished')).not.toBeInTheDocument()
  })

  it('shows each session workspace disk usage on the sessions page', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    expect(screen.getByText('Workspace')).toBeInTheDocument()
    expect(screen.getByText('1.5 KB')).toBeInTheDocument()
  })

  it('places the session status badge in the bottom-right metadata row', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    const card = screen.getByTestId('autoresearch-session-card-legacy1')
    const mainRow = screen.getByTestId('autoresearch-session-main-row-legacy1')
    const footer = screen.getByTestId('autoresearch-session-footer-legacy1')
    const badges = screen.getByTestId('autoresearch-session-badges-legacy1')

    expect(card).toContainElement(footer)
    expect(mainRow).not.toContainElement(footer)
    expect(footer).toContainElement(badges)
    expect(footer).toHaveClass('justify-between')
    expect(badges).toHaveClass('justify-end')
    expect(badges).toHaveTextContent('completed')
  })

  it('shows a loading title state while the LLM title is pending', async () => {
    vi.mocked(listAutoResearchSessions).mockResolvedValue({
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Generating title...')).toBeInTheDocument()
    expect(screen.getByText('Train a chronic gastritis WSI MIL classifier')).toBeInTheDocument()
  })

  it('shows elapsed running time on running session cards', async () => {
    vi.mocked(listAutoResearchSessions).mockResolvedValue({
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Running timer')).toBeInTheDocument()
    expect(screen.getByTestId('autoresearch-session-badges-running-timer')).toHaveTextContent(/running.*2m/)
  })

  it('shows epoch progress on running session cards', async () => {
    vi.mocked(listAutoResearchSessions).mockResolvedValue({
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Running epoch')).toBeInTheDocument()
    const badges = screen.getByTestId('autoresearch-session-badges-running-epoch')
    expect(badges).toHaveTextContent('Iter 1/1')
    expect(badges).toHaveTextContent('Epoch 7/30')
    expect(badges).toHaveTextContent('AUC 0.964')
  })

  it('hides stale epoch progress on completed session cards', async () => {
    vi.mocked(listAutoResearchSessions).mockResolvedValue({
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Completed epoch')).toBeInTheDocument()
    const badges = screen.getByTestId('autoresearch-session-badges-completed-epoch')
    expect(badges).toHaveTextContent('completed')
    expect(badges).not.toHaveTextContent('Epoch')
    expect(badges).not.toHaveTextContent('AUC')
  })

  it('renders page chrome, empty state, and session actions from zh-CN translations', async () => {
    await i18n.changeLanguage('zh-CN')
    vi.mocked(listAutoResearchSessions).mockResolvedValueOnce({ items: [] })

    const { unmount } = render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('研究会话')).toBeInTheDocument()
    expect(screen.getByText('刷新')).toBeInTheDocument()
    expect(screen.getByText('新建会话')).toBeInTheDocument()
    expect(screen.getByText('暂无自动实验会话')).toBeInTheDocument()
    expect(screen.getByText('创建一个短会话，用于验证后端桥接和事件流。')).toBeInTheDocument()
    expect(screen.getByText('开始一个')).toBeInTheDocument()
    expect(screen.queryByText('Research sessions')).not.toBeInTheDocument()
    expect(screen.queryByText('No AutoResearch sessions yet')).not.toBeInTheDocument()

    unmount()
    vi.mocked(listAutoResearchSessions).mockResolvedValueOnce({
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
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
    vi.mocked(listAutoResearchSessions).mockResolvedValue({
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
          workspace_path: '/tmp/autoresearch/session_same',
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
          workspace_path: '/tmp/autoresearch/session_same',
          error: '',
        },
      ],
    })

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Gateway live')).toBeInTheDocument()
    expect(screen.queryByText('Legacy duplicate')).not.toBeInTheDocument()
    expect(screen.getAllByTestId(/autoresearch-session-card-/)).toHaveLength(1)
  })

  it('shows a stop button for running sessions on the sessions page', async () => {
    vi.mocked(listAutoResearchSessions).mockResolvedValue({
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
    vi.mocked(stopAutoResearchSession).mockResolvedValue({
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
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    const stopButton = await screen.findByRole('button', { name: /stop run/i })
    fireEvent.click(stopButton)

    await waitFor(() => expect(stopAutoResearchSession).toHaveBeenCalledWith('running1'))
    expect(await screen.findByText('interrupted')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /stop run/i })).not.toBeInTheDocument()
  })

  it('deletes a completed session from the sessions page', async () => {
    vi.mocked(deleteAutoResearchSession).mockResolvedValue({ session_id: 'legacy1', deleted: true, workspace_deleted: true })

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /delete session/i }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/delete this autoresearch session/i)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => expect(deleteAutoResearchSession).toHaveBeenCalledWith('legacy1'))
    expect(screen.queryByText('Legacy run')).not.toBeInTheDocument()
  })

  it('does not poll when no sessions have live status', async () => {
    const intervals: Array<{ handler: TimerHandler; timeout?: number }> = []
    vi.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler, timeout?: number) => {
      intervals.push({ handler, timeout })
      return intervals.length as unknown as ReturnType<typeof window.setInterval>
    })

    vi.mocked(listAutoResearchSessions).mockResolvedValue({
      items: [
        {
          session_id: 'completed1',
          conversation_id: 'conv1',
          title: 'Completed session',
          question: 'Train a model',
          model: 'gpt-5.5',
          status: 'completed',
          stage: 'completed',
          created_at: 1779030000,
          updated_at: 1779030100,
          error: '',
        },
      ],
    })

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    const listPollIntervals = intervals.filter((interval) => interval.timeout === 5000)
    expect(listPollIntervals).toHaveLength(0)
  })

  it('polls every 5s when at least one session has live status', async () => {
    const intervals: Array<{ handler: TimerHandler; timeout?: number }> = []
    vi.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler, timeout?: number) => {
      intervals.push({ handler, timeout })
      return intervals.length as unknown as ReturnType<typeof window.setInterval>
    })

    vi.mocked(listAutoResearchSessions).mockResolvedValue({
      items: [
        {
          session_id: 'running1',
          conversation_id: 'conv1',
          title: 'Running session',
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

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Running session')).toBeInTheDocument()
    const listPollIntervals = intervals.filter((interval) => interval.timeout === 5000)
    expect(listPollIntervals.length).toBeGreaterThan(0)
  })

  it('uses ConfirmDialog instead of window.confirm for delete', async () => {
    vi.mocked(deleteAutoResearchSession).mockResolvedValue({ session_id: 'legacy1', deleted: true, workspace_deleted: true })

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /delete session/i }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/delete this autoresearch session/i)).toBeInTheDocument()
  })

  it('shows AutoResearch branding instead of AutoResearch', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchSessionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Legacy run')).toBeInTheDocument()
    expect(screen.getByText('AutoResearch')).toBeInTheDocument()
    expect(screen.queryByText('AutoResearch')).not.toBeInTheDocument()
  })
})
