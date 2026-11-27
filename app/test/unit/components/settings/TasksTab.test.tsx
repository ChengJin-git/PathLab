import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { TasksTab } from '@renderer/components/settings/TasksTab'
import { TooltipProvider } from '@renderer/components/ui/tooltip'
import { researchEn } from '@renderer/locales/research'

vi.mock('react-i18next', () => ({
  initReactI18next: { type: '3rdParty', init: () => {} },
  useTranslation: () => ({
    i18n: { language: 'en-US' },
    t: (key: string, options?: Record<string, unknown>) => {
      if (key === 'autoResearch.workbench') return researchEn
      if (options?.count !== undefined) return `${key}:${String(options.count)}`
      if (options?.running !== undefined || options?.max !== undefined) {
        return `${key}:${String(options?.running)}/${String(options?.max)}`
      }
      return key
    },
  }),
}))

const getQueueStatusMock = vi.fn()
const getQueueConfigMock = vi.fn()
const updateQueueConfigMock = vi.fn()

vi.mock('@renderer/api/queue', () => ({
  getQueueStatus: (...args: unknown[]) => getQueueStatusMock(...args),
  getQueueConfig: (...args: unknown[]) => getQueueConfigMock(...args),
  updateQueueConfig: (...args: unknown[]) => updateQueueConfigMock(...args),
}))

function renderTasksTab() {
  return render(
    <TooltipProvider>
      <TasksTab showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} />
    </TooltipProvider>,
  )
}

describe('TasksTab', () => {
  it('saves the research slider independently of GPU concurrency', async () => {
    getQueueStatusMock.mockResolvedValue({ max_concurrent: 4, gpu_count: 2, running_count: 0, pending_count: 0, queue_size: 0, running_task_ids: [], pending_task_ids: [], is_running: true })
    getQueueConfigMock.mockResolvedValue({ max_concurrent: 4, max_autoresearch_concurrent: 2, task_timeout: 86400 })
    updateQueueConfigMock.mockResolvedValue({ config: { max_concurrent: 4, max_autoresearch_concurrent: 3, task_timeout: 86400 } })
    render(<TooltipProvider><TasksTab showConfirmDialog={vi.fn()} closeConfirmDialog={vi.fn()} /></TooltipProvider>)
    const slider = await screen.findByRole('slider')
    await waitFor(() => expect(slider).toHaveValue('2'))
    fireEvent.change(slider, { target: { value: '3' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save limit' }))
    await waitFor(() => expect(updateQueueConfigMock).toHaveBeenCalledWith({ max_autoresearch_concurrent: 3 }))
  })
  beforeEach(() => {
    vi.clearAllMocks()

    getQueueConfigMock.mockResolvedValue({
      max_autoresearch_concurrent: 2,
      max_concurrent: 2,
      task_timeout: 259200,
    })
  })

  it('shows the updated max concurrent value immediately after increment even if queue status is stale', async () => {
    const user = userEvent.setup()

    getQueueStatusMock.mockResolvedValue({
      max_concurrent: 2,
      gpu_count: 7,
      running_count: 0,
      pending_count: 0,
      queue_size: 0,
      running_task_ids: [],
      running_tasks: [],
      pending_task_ids: [],
      is_running: true,
    })

    updateQueueConfigMock.mockResolvedValue({
      message: 'max_concurrent updated to 3',
      config: {
        max_concurrent: 3,
        task_timeout: 259200,
      },
    })

    renderTasksTab()

    const input = (await screen.findAllByDisplayValue('2')).find(element => element.getAttribute('type') === 'number')!
    const spinner = input.parentElement

    expect(spinner).toBeTruthy()

    const buttons = within(spinner as HTMLElement).getAllByRole('button')
    const plusButton = buttons[1]

    await user.click(plusButton)

    await waitFor(() => {
      expect(updateQueueConfigMock).toHaveBeenCalledWith({ max_concurrent: 3 })
    })

    await waitFor(() => {
      expect(screen.getByDisplayValue('3')).toBeInTheDocument()
    })

    expect(getQueueStatusMock).toHaveBeenCalled()
    expect(input).not.toBeDisabled()
  })
})
