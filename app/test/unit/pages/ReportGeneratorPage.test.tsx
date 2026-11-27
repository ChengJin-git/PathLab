import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ReportGeneratorPage from '@renderer/pages/ReportGeneratorPage'
import * as api from '@renderer/api/reports'
import i18n from '@renderer/i18n'

const actor = vi.hoisted(() => ({ role: 'pathologist' }))
vi.mock('@renderer/contexts/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'alice', role: actor.role } }),
}))
vi.mock('@renderer/api/reports', () => ({
  listReportSources: vi.fn(),
  listReports: vi.fn(),
  createReport: vi.fn(),
  saveReport: vi.fn(),
  downloadReport: vi.fn(),
  polishReport: vi.fn(),
  getReport: vi.fn(),
  getReportSource: vi.fn(),
  getReportFigure: vi.fn(),
  resumeReport: vi.fn(),
  deleteReport: vi.fn(),
}))

const report: api.Manuscript = {
  report_id: 'r1',
  user_id: 'alice',
  created_at: '2026-10-29T00:00:00Z',
  source_type: 'experiment',
  source_id: 'task1',
  title: 'CRC study',
  template: 'conference',
  content: '## Abstract\n\nValidation AUROC is 0.81.',
  revision: 1,
  status: 'ready',
  evidence: {
    runs: [{ run_id: 'task1', status: 'completed', metrics: { auc: 0.81 } }],
  },
  recommendation: { template: 'conference', completed_runs: 1, dataset_count: 1 },
  updated_at: '2026-10-29T00:00:00Z',
}
const show = (url = '/reports?report=r1') =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <ReportGeneratorPage />
    </MemoryRouter>,
  )

beforeEach(async () => {
  actor.role = 'pathologist'
  await i18n.changeLanguage('en-US')
  vi.mocked(api.listReportSources).mockResolvedValue({
    items: [
      { source_type: 'experiment', source_id: 'task1', title: 'CRC study' },
    ],
  })
  vi.mocked(api.listReports).mockResolvedValue({
    items: [
      {
        ...report,
        owner_name: 'Alice',
        excerpt: 'Validation AUROC is 0.81.',
      },
    ],
    next_cursor: null,
    page_size: 20,
  })
  vi.mocked(api.getReport).mockResolvedValue(report)
  vi.mocked(api.getReportSource).mockResolvedValue({
    title: report.title,
    recommendation: report.recommendation,
  })
  vi.mocked(api.saveReport).mockImplementation(async (value) => ({
    ...value,
    revision: value.revision + 1,
  }))
  vi.mocked(api.downloadReport).mockResolvedValue({
    filename: 'report.docx',
    headers: new Headers(),
  })
})
afterEach(() => {
  cleanup()
  vi.resetAllMocks()
})

it('opens the linked result and saves current edits before downloading', async () => {
  show()
  fireEvent.click(
    await screen.findByRole('tab', { name: 'Manuscript · Markdown' }),
  )
  const editor = await screen.findByRole('textbox', {
    name: 'Manuscript · Markdown',
  })
  expect(api.getReport).toHaveBeenCalledWith('r1', expect.any(AbortSignal))
  fireEvent.change(editor, { target: { value: 'Edited result 0.81' } })
  fireEvent.click(screen.getByRole('button', { name: 'Word' }))
  await waitFor(() =>
    expect(api.downloadReport).toHaveBeenCalledWith(
      expect.objectContaining({ content: 'Edited result 0.81', revision: 2 }),
      'docx',
    ),
  )
})

it('previews a selected-passage suggestion, applies it and supports undo', async () => {
  vi.mocked(api.polishReport).mockResolvedValue({
    suggestion: 'Measured validation AUROC is 0.81.',
    revision: 1,
  })
  show()
  fireEvent.click(
    await screen.findByRole('tab', { name: 'Manuscript · Markdown' }),
  )
  const editor = (await screen.findByRole('textbox', {
    name: 'Manuscript · Markdown',
  })) as HTMLTextAreaElement
  const start = report.content.indexOf('Validation')
  editor.focus()
  editor.setSelectionRange(start, report.content.length)
  fireEvent.select(editor)
  fireEvent.change(
    screen.getByRole('textbox', { name: 'Editing instruction' }),
    { target: { value: 'Clarify this result' } },
  )
  fireEvent.click(screen.getByRole('button', { name: 'Get a suggestion' }))
  await screen.findByText('Suggested revision')
  expect(api.polishReport).toHaveBeenCalledWith(report, 'Clarify this result', [
    start,
    report.content.length,
  ])
  expect(editor.value).toBe(report.content)
  fireEvent.click(screen.getByRole('button', { name: 'Apply revision' }))
  expect(editor.value).toBe('## Abstract\n\nMeasured validation AUROC is 0.81.')
  fireEvent.click(screen.getByRole('button', { name: 'Undo revision' }))
  expect(editor.value).toBe(report.content)
})

it('does not overwrite edited text with an old suggestion and keeps edits on failure', async () => {
  vi.mocked(api.polishReport).mockResolvedValue({
    suggestion: 'Suggested',
    revision: 1,
  })
  show()
  fireEvent.click(
    await screen.findByRole('tab', { name: 'Manuscript · Markdown' }),
  )
  const editor = await screen.findByRole('textbox', {
    name: 'Manuscript · Markdown',
  })
  fireEvent.change(
    screen.getByRole('textbox', { name: 'Editing instruction' }),
    { target: { value: 'Polish' } },
  )
  fireEvent.click(screen.getByRole('button', { name: 'Get a suggestion' }))
  await screen.findByText('Suggested revision')
  fireEvent.change(editor, { target: { value: 'My own edits' } })
  expect(
    screen.queryByRole('button', { name: 'Apply revision' }),
  ).not.toBeInTheDocument()
  vi.mocked(api.saveReport).mockRejectedValue(new Error('Conflict'))
  fireEvent.click(screen.getByRole('button', { name: 'LaTeX' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Conflict')
  expect(editor).toHaveValue('My own edits')
  expect(api.downloadReport).not.toHaveBeenCalled()
})

it('retains unsaved edits when language changes', async () => {
  show()
  fireEvent.click(
    await screen.findByRole('tab', { name: 'Manuscript · Markdown' }),
  )
  fireEvent.change(
    await screen.findByRole('textbox', { name: 'Manuscript · Markdown' }),
    { target: { value: 'Keep my edits' } },
  )
  await act(() => i18n.changeLanguage('zh-CN'))
  expect(
    await screen.findByRole('textbox', { name: '报告正文 · Markdown' }),
  ).toHaveValue('Keep my edits')
  expect(api.getReport).toHaveBeenCalledTimes(1)
})

it('shows recent articles before selecting any experiment and opens one', async () => {
  show('/reports')
  fireEvent.click(await screen.findByRole('heading', { name: 'CRC study' }))
  expect(
    await screen.findByRole('heading', { name: 'CRC study' }),
  ).toBeInTheDocument()
  expect(api.getReport).toHaveBeenCalledWith('r1', expect.any(AbortSignal))
})

it('starts a durable LLM generation task with writing focus and language', async () => {
  vi.mocked(api.createReport).mockResolvedValue({
    ...report,
    content: '',
    status: 'draft',
    generation: {
      status: 'queued',
      stage: 'evidence',
      completed_sections: [],
      total_sections: 7,
      current_section: '',
      reference_count: 0,
      language: 'en-US',
    },
  })
  show('/reports?source_type=experiment&source_id=task1')
  const button = await screen.findByRole('button', {
    name: 'Generate with LLM',
  })
  await waitFor(() => expect(button).toBeEnabled())
  fireEvent.change(
    screen.getByRole('textbox', { name: 'Writing focus · optional' }),
    { target: { value: 'Discuss clinical limitations' } },
  )
  fireEvent.click(button)
  await waitFor(() =>
    expect(api.createReport).toHaveBeenCalledWith(
      { source_type: 'experiment', source_id: 'task1' },
      'auto',
      'en-US',
      'Discuss clinical limitations',
    ),
  )
})

it('does not request reports or sources for guests', async () => {
  actor.role = 'guest'
  show('/reports')
  expect(screen.getByText('Access restricted')).toBeInTheDocument()
  expect(api.listReports).not.toHaveBeenCalled()
  expect(api.listReportSources).not.toHaveBeenCalled()
})

it('confirms deletion and removes the article only after server success', async () => {
  vi.mocked(api.deleteReport).mockImplementation(async () => {
    vi.mocked(api.listReports).mockResolvedValue({
      items: [],
      next_cursor: null,
      page_size: 20,
    })
    return { deleted: true, report_id: 'r1' }
  })
  show('/reports')
  fireEvent.click(
    await screen.findByRole('button', { name: 'Delete CRC study' }),
  )
  expect(
    screen.getByRole('dialog', { name: 'Delete this report?' }),
  ).toBeInTheDocument()
  expect(api.deleteReport).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  await screen.findByText('Your research, ready to become a paper')
  expect(api.deleteReport).toHaveBeenCalledWith('r1')
})

it('keeps the report when deletion fails or is cancelled', async () => {
  vi.mocked(api.deleteReport).mockRejectedValue(new Error('failed'))
  show('/reports')
  fireEvent.click(
    await screen.findByRole('button', { name: 'Delete CRC study' }),
  )
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(api.deleteReport).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete CRC study' }))
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not delete')
  expect(screen.getByRole('heading', { name: 'CRC study' })).toBeInTheDocument()
})

it('uses server cursors for next/previous and returns to page one after debounced search', async () => {
  const makeItem = (title: string): api.ReportSummary => ({
    ...report,
    title,
    owner_name: 'Alice',
    excerpt: '',
  })
  vi.mocked(api.listReports).mockImplementation(async (filters) => ({
    items: [
      makeItem(
        filters?.query
          ? 'Filtered article'
          : filters?.cursor
            ? 'Second page article'
            : 'First page article',
      ),
    ],
    next_cursor:
      !filters?.cursor && !filters?.query ? 'next-page-cursor' : null,
    page_size: 20,
  }))
  show('/reports')
  await screen.findByRole('heading', { name: 'First page article' })
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByRole('heading', { name: 'Second page article' })
  expect(api.listReports).toHaveBeenLastCalledWith(
    { query: '', cursor: 'next-page-cursor' },
    expect.any(AbortSignal),
  )
  expect(screen.getByText('Page 2 · 20 per page')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
  await screen.findByRole('heading', { name: 'First page article' })
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await screen.findByRole('heading', { name: 'Second page article' })
  const calls = vi.mocked(api.listReports).mock.calls.length
  const search = screen.getByRole('textbox', { name: 'Search articles' })
  fireEvent.change(search, { target: { value: 'CRC' } })
  fireEvent.change(search, { target: { value: 'CRC-MSI' } })
  expect(api.listReports).toHaveBeenCalledTimes(calls)
  await screen.findByRole('heading', { name: 'Filtered article' })
  expect(api.listReports).toHaveBeenCalledTimes(calls + 1)
  expect(api.listReports).toHaveBeenLastCalledWith(
    { query: 'CRC-MSI' },
    expect.any(AbortSignal),
  )
})

it('disables repeated next-page clicks and ignores late responses after a search', async () => {
  let resolveNext!: (value: api.ReportPage) => void
  const item: api.ReportSummary = {
    ...report,
    owner_name: 'Alice',
    excerpt: '',
  }
  vi.mocked(api.listReports).mockImplementation(async (filters) => {
    if (filters?.cursor)
      return new Promise((resolve) => {
        resolveNext = resolve
      })
    return {
      items: [
        { ...item, title: filters?.query ? 'Current search' : 'First page' },
      ],
      next_cursor: filters?.query ? null : 'next',
      page_size: 20,
    }
  })
  show('/reports')
  await screen.findByRole('heading', { name: 'First page' })
  fireEvent.click(screen.getByRole('button', { name: 'Next' }))
  await waitFor(() =>
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled(),
  )
  const signal = vi.mocked(api.listReports).mock.calls.at(-1)![1]!
  fireEvent.change(screen.getByRole('textbox', { name: 'Search articles' }), {
    target: { value: 'new query' },
  })
  await screen.findByRole('heading', { name: 'Current search' })
  expect(signal.aborted).toBe(true)
  await act(async () =>
    resolveNext({
      items: [{ ...item, title: 'Stale page' }],
      next_cursor: null,
      page_size: 20,
    }),
  )
  expect(
    screen.queryByRole('heading', { name: 'Stale page' }),
  ).not.toBeInTheDocument()
  expect(
    screen.getByRole('heading', { name: 'Current search' }),
  ).toBeInTheDocument()
})
