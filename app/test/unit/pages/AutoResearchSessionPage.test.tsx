import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within
} from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import AutoResearchSessionPage from '@renderer/pages/AutoResearchSessionPage'
import {
  getAutoResearchSession,
  continueResearch,
  pauseResearch,
  sendResearchMessage
} from '@renderer/api/autoresearch'
import i18n from '@renderer/i18n'
import { referenceResearchPath } from '@renderer/api/workbench'
vi.mock('echarts-for-react', () => ({ default: () => <div data-testid="metric-chart" /> }))
vi.mock('@renderer/api/workbench', () => ({referenceResearchPath: vi.fn(), researchActivity: vi.fn(), downloadWorkbenchFile: vi.fn()}))
vi.mock('@renderer/components/chat/FilePreviewContent', () => ({default: ({file}: {file: {name: string}}) => <div data-testid="typed-preview">{file.name}</div>}))

vi.mock('@renderer/api/autoresearch', () => ({
  getAutoResearchSession: vi.fn(),
  continueResearch: vi.fn(),
  pauseResearch: vi.fn(),
  sendResearchMessage: vi.fn(),
  downloadAutoResearchSession: vi.fn(),
  downloadResearchFile: vi.fn(),
  readResearchFile: vi.fn(),
  resumeAutoResearchSession: vi.fn(),
  stopAutoResearchSession: vi.fn()
}))
vi.mock('@renderer/components/autoresearch/useSessionStream', () => ({
  useSessionStream: (() => { const events: never[] = []; return () => ({ events, status: 'open' }) })()
}))
beforeEach(async () => {
  await i18n.changeLanguage('en-US')
  vi.mocked(getAutoResearchSession).mockResolvedValue({
    session_id: 's1',
    title: 'Cohort research',
    question: 'Compare',
    status: 'running',
    model: 'settings-model',
    events: [],
    state: { plan: [{ title: 'Compare baselines', status: 'running' }] },
    experiments: [
      {
        run_id: 'r1',
        experiment_name: 'Baseline',
        status: 'completed',
        iteration: 1,
        metrics: { 'test.auc': 0.82 },
        config: {}
      }
    ]
  })
  vi.mocked(sendResearchMessage).mockResolvedValue({ command_id: 'c1' })
  vi.mocked(pauseResearch).mockResolvedValue({
    session_id: 's1',
    question: 'Compare',
    status: 'pausing'
  })
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})
const show = () =>
  render(
    <MemoryRouter initialEntries={['/autoresearch/sessions/s1']}>
      <Routes>
        <Route
          path="/autoresearch/sessions/:id"
          element={<AutoResearchSessionPage />}
        />
      </Routes>
    </MemoryRouter>
  )

describe('research workbench', () => {
  it.each(['pdf', 'pptx', 'docx', 'xlsx', 'html', 'png'])('routes a %s deliverable from prose and artifacts into the shared preview', async suffix => {
    const session = await getAutoResearchSession('s1')
    const path = `outputs/result.${suffix}`
    vi.mocked(getAutoResearchSession).mockResolvedValue({...session, activity: [{kind: 'message', seq: 1, message: {id: 'delivery', type:'assistant', text: `[Open deliverable](${path})`} as unknown as string}], state: {...session.state, artifacts: [{path, name: `result.${suffix}`}]}})
    vi.mocked(referenceResearchPath).mockResolvedValue({kind:'file', id:'f', name:`result.${suffix}`, revision:'v1'})
    show()
    await screen.findByRole('button', {name: 'Open deliverable'})
    fireEvent.click(screen.getByRole('button', {name: 'Open deliverable'}))
    await waitFor(() => expect(referenceResearchPath).toHaveBeenCalled())
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
    expect(await screen.findByTestId('typed-preview')).toHaveTextContent(`result.${suffix}`)
    expect(referenceResearchPath).toHaveBeenCalledWith('s1', path, expect.any(AbortSignal), true)
    fireEvent.click(screen.getByRole('button', {name: 'Close'}))
    fireEvent.click(screen.getByRole('tab', {name: 'Artifacts'}))
    fireEvent.click(screen.getByRole('button', {name: `Preview result.${suffix}`}))
    expect(await screen.findByTestId('typed-preview')).toHaveTextContent(`result.${suffix}`)
  })
  it('returns to the linked conversation while retaining the outline and result tabs', async () => {
    const session = await getAutoResearchSession('s1')
    vi.mocked(getAutoResearchSession).mockResolvedValue({...session, chat_conversation_id: 'chat-original'})
    show()
    expect(await screen.findByRole('link', {name: 'Back to conversation'})).toHaveAttribute('href', '/dashboard/chat-original')
    expect(within(screen.getByTestId('research-outline')).getByText('Compare baselines')).toBeInTheDocument()
    expect(screen.getByRole('tab', {name: 'Experiments'})).toBeInTheDocument()
  })
  it('links completed model experiments to the report editor', async () => {
    const session = await getAutoResearchSession('s1')
    vi.mocked(getAutoResearchSession).mockResolvedValue({ ...session, status: 'completed' })
    show()
    expect(await screen.findByRole('link', { name: 'Write report' })).toHaveAttribute('href', '/reports?source_type=research&source_id=s1')
  })
  it('has no manuscript button for completed download or metric-only tasks', async () => {
    vi.mocked(getAutoResearchSession).mockResolvedValue({ session_id: 's1', question: 'Download only', status: 'completed', experiments: [], events: [], state: { report: 'Dataset registered' } })
    show()
    await screen.findByText('Download only')
    expect(screen.queryByRole('link', { name: 'Write report' })).not.toBeInTheDocument()
  })
  it('continues a completed study with an explicit baseline, instructions and budget', async () => {
    const session = await getAutoResearchSession('s1')
    vi.mocked(getAutoResearchSession).mockResolvedValue({ ...session, status: 'completed', max_iterations: 1, current_iteration: 1 })
    vi.mocked(continueResearch).mockImplementation(async () => {
      vi.mocked(getAutoResearchSession).mockResolvedValue({ ...session, status: 'queued', max_iterations: 3, current_iteration: 1 })
      return { command_id: 'next', status: 'queued' }
    })
    show()
    const submit = await screen.findByRole('button', { name: 'Continue optimization' })
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Starting point' }))
    fireEvent.click(await screen.findByRole('option', { name: '1. Baseline' }))
    fireEvent.change(screen.getByRole('textbox', { name: 'What would you like to improve?' }), { target: { value: 'Compare another MIL aggregator using the same patient splits' } })
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '2' } })
    fireEvent.click(submit)
    await waitFor(() => expect(continueResearch).toHaveBeenCalledWith('s1', {
      text: 'Compare another MIL aggregator using the same patient splits', baseline_run_id: 'r1', additional_experiments: 2
    }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Continue optimization' })).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Send' })).toBeInTheDocument()
  })
  it('shows queue position and server busy without claiming the research is running', async () => {
    vi.mocked(getAutoResearchSession).mockResolvedValue({ session_id: 's1', question: 'Queued study', status: 'queued', events: [], state: {}, queue: { limit: 2, running: 2, position: 3, busy: true } })
    show()
    expect(await screen.findByRole('status')).toHaveTextContent('The server is busy')
    expect(screen.getByRole('status')).toHaveTextContent('Queue position #3')
    expect(screen.getByRole('button', { name: 'End research' })).toBeEnabled()
  })
  it('displays plan and measured experiment metrics', async () => {
    show()
    expect(await within(screen.getByTestId('research-outline')).findByText('Compare baselines')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: 'Experiments' }))
    expect(screen.getAllByText('test.auc').length).toBeGreaterThan(0)
    expect(screen.getAllByText('0.8200').length).toBeGreaterThan(0)
  })
  it('adapts a literature task to its actual plan without a fixed experiment workflow', async () => {
    vi.mocked(getAutoResearchSession).mockResolvedValue({
      session_id: 'review', chat_conversation_id: 'chat-review', status: 'running', task_kind: 'document',
      title: 'Review spatial proteomics',
      question: 'Explore original research in IMC, CODEX, MIBI and multiplex immunofluorescence.',
      created_at: Date.now() / 1000 - 38652, updated_at: Date.now() / 1000, events: [], experiments: [], jobs: [],
      state: {plan: [
        {id: 'evidence', title: 'Review evidence and data availability', status: 'completed'},
        {id: 'directions', title: 'Compare feasible research directions', status: 'running'},
        {id: 'delivery', title: 'Prepare the evidence review', status: 'pending'},
      ]},
    })
    show()
    expect(within(await screen.findByTestId('research-current-work')).getByText('Compare feasible research directions')).toBeVisible()
    expect(screen.getByRole('heading', {name: 'Task plan'})).toBeInTheDocument()
    expect(screen.queryByText('Ideation')).not.toBeInTheDocument()
    expect(screen.queryByText('Planning', {exact: true})).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', {name: 'Experiments'})).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', {name: 'Raw log'})).not.toBeInTheDocument()
    expect(screen.getByText('Elapsed 10 hr 44 min')).toBeInTheDocument()
    fireEvent.click(within(screen.getByTestId('research-outline')).getByRole('button', {name: /Compare feasible research directions/}))
    expect(screen.getByRole('button', {name: 'All activity'})).toBeInTheDocument()
  })
  it('continues a completed document task with a generic follow-up rather than training controls', async () => {
    vi.mocked(getAutoResearchSession).mockResolvedValue({
      session_id: 's1', status: 'completed', task_kind: 'document', title: 'Review spatial proteomics', question: 'Review spatial proteomics',
      events: [], experiments: [], state: {plan: [
        {id: 'directions', title: 'Compare feasible research directions', status: 'completed'},
        {id: 'evidence', title: 'Review evidence and data availability', status: 'completed'},
      ]},
    })
    show()
    const followup = await screen.findByLabelText('What would you like to do next?')
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', {name: 'Starting point'})).not.toBeInTheDocument()
    fireEvent.change(followup, {target: {value: 'Investigate another source and revise the review'}})
    fireEvent.click(screen.getByRole('button', {name: 'Continue task'}))
    await waitFor(() => expect(continueResearch).toHaveBeenCalledWith('s1', {text: 'Investigate another source and revise the review'}))
    await waitFor(() => expect(getAutoResearchSession).toHaveBeenCalledTimes(2))
  })
  it('sends instructions into the active research and supports pausing', async () => {
    show()
    await screen.findByText('Cohort research')
    fireEvent.click(screen.getByRole('tab', { name: 'Experiments' }))
    fireEvent.change(screen.getByRole('textbox'), {
      target: { value: 'Add external validation' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    await waitFor(() =>
      expect(sendResearchMessage).toHaveBeenCalledWith(
        's1',
        'Add external validation'
      )
    )
    fireEvent.click(screen.getByRole('button', { name: 'Pause progression' }))
    await waitFor(() => expect(pauseResearch).toHaveBeenCalledWith('s1'))
  })
})
