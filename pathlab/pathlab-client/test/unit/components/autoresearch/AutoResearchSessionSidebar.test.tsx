import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { TooltipProvider } from '@radix-ui/react-tooltip'
import AutoResearchSessionSidebar from '@renderer/components/autoresearch/AutoResearchSessionSidebar'
import { deleteAutoResearchSession, listAutoResearchSessions } from '@renderer/api/autoresearch'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/autoresearch', () => ({
  deleteAutoResearchSession: vi.fn(),
  listAutoResearchSessions: vi.fn(),
}))

vi.mock('@renderer/contexts/ToastContext', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key: string) => key }),
  initReactI18next: { type: 'backend' },
}))

describe('AutoResearchSessionSidebar', () => {
  beforeEach(() => {
    void i18n.changeLanguage('en-US')
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
    vi.mocked(deleteAutoResearchSession).mockReset()
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    void i18n.changeLanguage('en-US')
  })

  const renderWithProviders = (ui: React.ReactElement) =>
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TooltipProvider>{ui}</TooltipProvider>
      </MemoryRouter>,
    )

  it('renders the sidebar with sessions', async () => {
    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    expect(screen.getByText(/autoResearch\.sessions/)).toBeInTheDocument()
  })

  it('does not poll when no sessions have live status', async () => {
    const intervals: Array<{ handler: TimerHandler; timeout?: number }> = []
    vi.spyOn(window, 'setInterval').mockImplementation((handler: TimerHandler, timeout?: number) => {
      intervals.push({ handler, timeout })
      return intervals.length as unknown as ReturnType<typeof window.setInterval>
    })

    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    const listPollIntervals = intervals.filter((interval) => interval.timeout === 5000)
    expect(listPollIntervals).toHaveLength(0)
  })

  it('shows a newly created session without remounting', async () => {
    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()

    act(() => {
      window.dispatchEvent(new CustomEvent('autoresearch:session-created', {
        detail: {
          session: {
            session_id: 'new-session',
            conversation_id: 'new-conv',
            title: 'New NSCLC session',
            question: 'Train NSCLC',
            model: 'gpt-5.5',
            status: 'queued',
            stage: 'starting',
            created_at: 1779030200,
            updated_at: 1779030200,
            error: '',
          },
        },
      }))
    })

    expect(screen.getByText('New NSCLC session')).toBeInTheDocument()
    expect(screen.getByText('Completed session')).toBeInTheDocument()
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

    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Running session')).toBeInTheDocument()
    const listPollIntervals = intervals.filter((interval) => interval.timeout === 5000)
    expect(listPollIntervals.length).toBeGreaterThan(0)
  })

  it('shows a clear-all button for non-live sessions', async () => {
    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /autoResearch\.clearAll/i })).toBeInTheDocument()
  })

  it('shows ConfirmDialog when clicking clear-all', async () => {
    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /autoResearch\.clearAll/i }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/autoResearch\.clearAllConfirmTitle/i)).toBeInTheDocument()
  })

  it('uses ConfirmDialog instead of window.confirm for sidebar item delete', async () => {
    vi.mocked(deleteAutoResearchSession).mockResolvedValue({ session_id: 'completed1', deleted: true, workspace_deleted: true })

    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /autoResearch\.sessionActions\.delete/i }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByText(/autoResearch\.sessionActions\.deleteConfirmTitle/i)).toBeInTheDocument()
  })

  it('passes the correct session id when deleting a sidebar item', async () => {
    vi.mocked(deleteAutoResearchSession).mockResolvedValue({ session_id: 'completed1', deleted: true, workspace_deleted: true })

    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /autoResearch\.sessionActions\.delete/i }))

    expect(screen.getByRole('dialog')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /settings\.confirmDialog\.confirm/i }))

    await waitFor(() => expect(deleteAutoResearchSession).toHaveBeenCalledWith('completed1'))
  })

  it('shows AutoResearch branding instead of AutoResearch', async () => {
    renderWithProviders(<AutoResearchSessionSidebar />)

    expect(await screen.findByText('Completed session')).toBeInTheDocument()
    expect(screen.queryByText('AutoResearch')).not.toBeInTheDocument()
  })
})