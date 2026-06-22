import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PathScientistNewSessionPage from '@renderer/pages/PathScientistNewSessionPage'
import { listPathScientistSkills, startPathScientistSession } from '@renderer/api/pathscientist'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/pathscientist', () => ({
  listPathScientistSkills: vi.fn(),
  startPathScientistSession: vi.fn(),
}))

describe('PathScientistNewSessionPage', () => {
  beforeEach(async () => {
    await i18n.changeLanguage('en-US')
    vi.mocked(listPathScientistSkills).mockResolvedValue({ items: [] })
    vi.mocked(startPathScientistSession).mockResolvedValue({
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
        <PathScientistNewSessionPage />
      </MemoryRouter>,
    )

    expect(screen.getByRole('heading', { name: '启动自动实验会话' })).toBeInTheDocument()
    expect(screen.getByText('描述计算病理任务。自动实验会启动后端会话，并把实时事件流写入运行详情页。')).toBeInTheDocument()
    expect(screen.getByLabelText('研究问题')).toBeInTheDocument()
    expect(screen.getByLabelText('最大迭代次数')).toHaveValue(5)
    expect(screen.getByRole('button', { name: '取消' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '启动会话' })).toBeInTheDocument()
    expect(screen.queryByText('Start a PathScientist session')).not.toBeInTheDocument()
    expect(screen.queryByText('PathScientist')).not.toBeInTheDocument()
  })

  it('defaults max iterations to the PathScientist CLI default', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <PathScientistNewSessionPage />
      </MemoryRouter>,
    )

    expect(screen.queryByRole('button', { name: 'Session options' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Max iter')).toHaveValue(5)
  })

  it('does not render the manual skill selector', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <PathScientistNewSessionPage />
      </MemoryRouter>,
    )

    expect(screen.queryByLabelText('Skill')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    expect(listPathScientistSkills).not.toHaveBeenCalled()
  })

  it('allows typing a replacement max iteration number', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <PathScientistNewSessionPage />
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
        <PathScientistNewSessionPage />
      </MemoryRouter>,
    )

    fireEvent.change(screen.getByLabelText('Research question'), { target: { value: 'Train NSCLC' } })
    fireEvent.change(screen.getByLabelText('Max iter'), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText('Max iter'), { target: { value: '12' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start session' }))

    await waitFor(() => {
      expect(startPathScientistSession).toHaveBeenCalledWith(expect.objectContaining({
        max_iter: 12,
      }))
    })
  })
})
