import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import ResearchRecoveryPanel from '@renderer/components/autoresearch/ResearchRecoveryPanel'
import * as api from '@renderer/api/autoresearch'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/autoresearch', () => ({ continueResearch: vi.fn(), getResearchDatasets: vi.fn(), listResearchSourceFiles: vi.fn(), readResearchFile: vi.fn(), saveResearchSource: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('resumes a budget checkpoint with added time and attempts', async () => {
  await i18n.changeLanguage('en-US')
  render(<MemoryRouter><ResearchRecoveryPanel sessionId="s" recovery={{ reason: 'budget' }} onContinued={vi.fn()} /></MemoryRouter>)
  expect(screen.getByText(/An unfinished manuscript stays a draft/)).toBeInTheDocument()
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Time allowance for continuation (hours)' }), { target: { value: '0.5' } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue task' }))
  await waitFor(() => expect(api.continueResearch).toHaveBeenCalledWith('s', expect.objectContaining({ additional_time_seconds: 1800, additional_experiments: 0 })))
})
it('lets users attach data, explain corrections and continue without losing context', async () => {
  await i18n.changeLanguage('en-US')
  vi.mocked(api.getResearchDatasets).mockResolvedValue({ items: [{ dataset_id: 'new-data', name: 'Uploaded cohort', data_type: 'wsi', file_count: 4 }] })
  const refreshed = vi.fn().mockResolvedValue(undefined)
  render(<MemoryRouter><ResearchRecoveryPanel sessionId="s" recovery={{ reason: 'missing_data', summary: 'Labels are missing.' }} onContinued={refreshed} /></MemoryRouter>)
  expect(screen.getByText('Labels are missing.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Attach Data Repo dataset' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Dataset to attach' }))
  fireEvent.click(screen.getByRole('option', { name: 'Uploaded cohort · 4' }))
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Use the uploaded labels and compute accuracy only.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue task' }))
  await waitFor(() => expect(api.continueResearch).toHaveBeenCalledWith('s', { text: 'Use the uploaded labels and compute accuracy only.', dataset_ids: ['new-data'], additional_experiments: 0, replace_datasets: false }))
  expect(refreshed).toHaveBeenCalled()
})

it('saves source with a revision and leaves resumption to the user', async () => {
  await i18n.changeLanguage('en-US')
  vi.mocked(api.listResearchSourceFiles).mockResolvedValue({ items: ['analysis.py'], editable: true })
  vi.mocked(api.readResearchFile).mockResolvedValue({ path: 'analysis.py', content: 'before', revision: 'v1' })
  vi.mocked(api.saveResearchSource).mockResolvedValue({ saved: true, revision: 'v2' })
  render(<MemoryRouter><ResearchRecoveryPanel sessionId="s" onContinued={vi.fn()} /></MemoryRouter>)
  fireEvent.click(screen.getByText('Attach data or edit code'))
  fireEvent.click(screen.getByRole('button', { name: 'Edit workspace code' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Source file' }))
  fireEvent.click(screen.getByRole('option', { name: 'analysis.py' }))
  fireEvent.change(await screen.findByRole('textbox', { name: 'Source editor' }), { target: { value: 'fixed code' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save file' }))
  await waitFor(() => expect(api.saveResearchSource).toHaveBeenCalledWith('s', 'analysis.py', 'fixed code', 'v1'))
  expect(api.continueResearch).not.toHaveBeenCalled()
})

it.each(['missing_data', 'data_access', 'data_preparation', 'code_error', 'service', 'budget', 'needs_input', 'direction', 'other'] as const)('keeps the general assistance title for %s, with a specific reason', async reason => {
  await i18n.changeLanguage('zh-CN')
  const view = render(<MemoryRouter><ResearchRecoveryPanel sessionId="s" recovery={{reason, summary:'具体阻塞原因', next_steps:['建议的处理方式'], detail:'详细诊断'}} onContinued={vi.fn()} /></MemoryRouter>)
  expect(screen.getByRole('heading', {name:'助手需要进一步协助'})).toBeInTheDocument()
  expect(screen.getByText('具体阻塞原因')).toBeInTheDocument()
  expect(screen.getByText('建议的处理方式')).toBeInTheDocument()
  expect(screen.getByText(/文件、结果和对话已保留/)).toBeInTheDocument()
  expect(view.container.querySelector('section')).toHaveClass('bg-white')
  expect(view.container.querySelector('section')).not.toHaveClass('bg-amber-50/60')
  fireEvent.click(screen.getByText('技术详情'))
  expect(screen.getByText('详细诊断')).toBeVisible()
})

it('does not silently replace the time allowance when only adding experiment attempts', async () => {
  await i18n.changeLanguage('en-US')
  render(<MemoryRouter><ResearchRecoveryPanel sessionId="s" recovery={{reason: 'budget'}} onContinued={vi.fn()} /></MemoryRouter>)
  fireEvent.change(screen.getByRole('spinbutton', {name: 'Additional experiment attempts (optional)'}), {target: {value: '8'}})
  fireEvent.click(screen.getByRole('button', {name: 'Continue task'}))
  await waitFor(() => expect(api.continueResearch).toHaveBeenCalledWith('s', {
    text: '', dataset_ids: [], additional_experiments: 8, replace_datasets: false,
  }))
})

it('identifies input preparation separately from model availability', async () => {
  await i18n.changeLanguage('zh-CN')
  render(<MemoryRouter><ResearchRecoveryPanel sessionId="s" recovery={{reason: 'data_preparation', detail: 'Dataset preparation timed out'}} onContinued={vi.fn()} /></MemoryRouter>)
  expect(screen.getByText('输入数据准备')).toBeVisible()
  expect(screen.getByText(/输入数据准备未完成/)).toBeVisible()
  expect(screen.queryByText(/模型或所需服务/)).not.toBeInTheDocument()
})

it('does not require unrelated data or budget input to retry a service issue', async () => {
  await i18n.changeLanguage('zh-CN')
  vi.mocked(api.continueResearch).mockResolvedValue({command_id:'resume', status:'queued'})
  render(<MemoryRouter><ResearchRecoveryPanel sessionId="existing" recovery={{reason:'service', summary:'数据准备接口超时'}} onContinued={vi.fn()} /></MemoryRouter>)
  expect(screen.getByText('数据准备接口超时')).toBeVisible()
  expect(screen.getByRole('spinbutton')).not.toBeVisible()
  expect(screen.getByRole('button', {name:'补充数据仓库数据'})).not.toBeVisible()
  fireEvent.click(screen.getByRole('button', {name:'继续任务'}))
  await waitFor(() => expect(api.continueResearch).toHaveBeenCalledWith('existing', {text:'', dataset_ids:[], additional_experiments:0, replace_datasets:false}))
})

it('retains the issue and entered guidance when continuation fails', async () => {
  await i18n.changeLanguage('en-US')
  vi.mocked(api.continueResearch).mockRejectedValue(new Error('Service still unavailable'))
  render(<MemoryRouter><ResearchRecoveryPanel sessionId="s" recovery={{reason:'service', summary:'Preparation timed out.'}} onContinued={vi.fn()} /></MemoryRouter>)
  fireEvent.change(screen.getByRole('textbox'), {target:{value:'Please retry preparation.'}})
  fireEvent.click(screen.getByRole('button', {name:'Continue task'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Service still unavailable')
  expect(screen.getByText('Preparation timed out.')).toBeVisible()
  expect(screen.getByRole('textbox')).toHaveValue('Please retry preparation.')
  expect(screen.getByRole('button', {name:'Continue task'})).toBeEnabled()
})
