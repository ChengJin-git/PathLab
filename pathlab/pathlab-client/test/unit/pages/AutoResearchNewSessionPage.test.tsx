import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AutoResearchNewSessionPage from '@renderer/pages/AutoResearchNewSessionPage'
import { listAutoResearchSkills, startAutoResearchSession } from '@renderer/api/autoresearch'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/autoresearch', () => ({
  listAutoResearchSkills: vi.fn(),
  startAutoResearchSession: vi.fn(),
}))

describe('AutoResearchNewSessionPage', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US')
    vi.mocked(listAutoResearchSkills).mockResolvedValue({ items: [] })
    vi.mocked(startAutoResearchSession).mockResolvedValue({
      session_id: 'new-session',
      question: 'Train NSCLC',
      status: 'queued',
    })
  })

  afterEach(async () => {
    cleanup()
    vi.restoreAllMocks()
    await i18n.changeLanguage('en-US')
  })

  it('renders the new session form from zh-CN translations', async () => {
    await i18n.changeLanguage('zh-CN')

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchNewSessionPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '启动自动实验会话' })).toBeInTheDocument()
    expect(screen.getByText('描述计算病理任务。自动实验会启动后端会话，并把实时事件流写入运行详情页。')).toBeInTheDocument()
    expect(screen.getByLabelText('研究问题')).toBeInTheDocument()
    expect(screen.getByLabelText('最大迭代次数')).toHaveValue(5)
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '启动会话' })).toBeInTheDocument()
    expect(screen.queryByText('Start a AutoResearch session')).not.toBeInTheDocument()
    expect(screen.queryByText('AutoResearch')).not.toBeInTheDocument()
  })

  it('defaults max iterations to the AutoResearch CLI default', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchNewSessionPage />
      </MemoryRouter>,
    )

    expect(screen.queryByRole('button', { name: 'Session options' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Max iter')).toHaveValue(5)
  })

  it('does not render the manual skill selector', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchNewSessionPage />
      </MemoryRouter>,
    )

    expect(screen.queryByLabelText('Skill')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(listAutoResearchSkills).not.toHaveBeenCalled()
  })

  it('allows typing a replacement max iteration number', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchNewSessionPage />
      </MemoryRouter>,
    )

    const input = screen.getByLabelText('Max iter')

    fireEvent.change(input, { target: { value: '' } })
    expect(input).toHaveValue(null)

    fireEvent.change(input, { target: { value: '12' } })
    expect(input).toHaveValue(12)
  })

  it('submits the typed max iteration value', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchNewSessionPage />
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText('Research question'), { target: { value: 'Train NSCLC' } })
    fireEvent.change(screen.getByLabelText('Max iter'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Max iter'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start session' }))

    await waitFor(() => {
      expect(startAutoResearchSession).toHaveBeenCalledWith(expect.objectContaining({
        max_iter: 12,
      }))
    })
  })

  it('notifies the workspace when a session is created', async () => {
    const listener = vi.fn()
    window.addEventListener('autoresearch:session-created', listener)

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <AutoResearchNewSessionPage />
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText('Research question'), { target: { value: 'Train NSCLC' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start session' }))

    await waitFor(() => {
      expect(listener).toHaveBeenCalledWith(expect.objectContaining({
        detail: expect.objectContaining({
          session: expect.objectContaining({ session_id: 'new-session' }),
        }),
      }))
    })

    window.removeEventListener('autoresearch:session-created', listener)
  })
})
