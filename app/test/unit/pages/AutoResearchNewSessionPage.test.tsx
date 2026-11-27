import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import AutoResearchNewSessionPage from '@renderer/pages/AutoResearchNewSessionPage'
import {
  getResearchConfiguration,
  getResearchDatasets,
  getResearchHandoff,
  polishResearchGoal,
  importResearchSkill,
  uploadResearchSkills,
  startAutoResearchSession
} from '@renderer/api/autoresearch'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/autoresearch', () => ({
  getResearchConfiguration: vi.fn(),
  getResearchDatasets: vi.fn(),
  getResearchHandoff: vi.fn(),
  polishResearchGoal: vi.fn(),
  importResearchSkill: vi.fn(),
  uploadResearchSkills: vi.fn(),
  startAutoResearchSession: vi.fn()
}))
beforeEach(async () => {
  await i18n.changeLanguage('en-US')
  vi.mocked(getResearchConfiguration).mockResolvedValue({
    effort_presets: {
        standard: { low: { max_experiments: 3, time_budget_seconds: 3600 }, medium: { max_experiments: 8, time_budget_seconds: 14400 }, high: { max_experiments: 20, time_budget_seconds: 43200 } },
        scientific: { low: { max_experiments: 12, time_budget_seconds: 43200 }, medium: { max_experiments: 40, time_budget_seconds: 172800 }, high: { max_experiments: 100, time_budget_seconds: 259200 } },
      },
    model: { model: 'settings-model' },
    error: '',
    can_execute: true
  })
  vi.mocked(getResearchDatasets).mockResolvedValue({
    items: [
      {
        dataset_id: 'dataset-a',
        name: 'Real cohort',
        data_type: 'wsi',
        file_count: 40
      }
    ]
  })
  vi.mocked(startAutoResearchSession).mockResolvedValue({
    session_id: 'new',
    question: 'Compare baselines',
    status: 'queued'
  })
  vi.mocked(getResearchHandoff).mockResolvedValue({ context: 'Only design; no training', message_count: 2, included_messages: 2 })
  vi.mocked(polishResearchGoal).mockResolvedValue({ question: 'Polished research request' })
})
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('research creation', () => {
  // Locale bundles load on demand; fetch all three up front so each case measures the page, not the import.
  beforeAll(() => i18n.loadLanguages(['en-US', 'zh-CN', 'zh-HK']), 30_000)

  it.each(['en-US', 'zh-CN', 'zh-HK'])('uploads a full package and localizes import failures in %s', async language => {
    await i18n.changeLanguage(language)
    const { researchEn, researchZhCN, researchZhHK } = await import('@renderer/locales/research')
    const text = language === 'zh-CN' ? researchZhCN : language === 'zh-HK' ? researchZhHK : researchEn
    const skill = { name: 'Image analysis', content: '# Run\nRead scripts/analyze.py', entrypoint: 'analysis/SKILL.md', package_id: 'a'.repeat(64) }
    vi.mocked(uploadResearchSkills).mockResolvedValue({ skills: [skill], files: [{ path: 'analysis/scripts/analyze.py', size: 24 }], total_bytes: 24, warnings: ['skillRuntimeRequirements'] })
    render(<MemoryRouter><AutoResearchNewSessionPage /></MemoryRouter>)
    fireEvent.click(screen.getByText(text.advancedSettings))
    const file = new File(['zip data'], 'analysis.skill', { type: 'application/zip' })
    fireEvent.change(screen.getByLabelText(text.skillUpload), { target: { files: [file] } })
    expect(await screen.findByText(text.skillRuntimeRequirements)).toBeInTheDocument()
    expect(screen.getByText('analysis/scripts/analyze.py · 24 B')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: `${text.skillAddSelected} (1)` }))
    expect(screen.getByLabelText(`${text.skillContent} 1`)).toHaveValue(skill.content)
    vi.mocked(importResearchSkill).mockRejectedValue(new Error('skillUnsupportedUrl'))
    fireEvent.change(screen.getByLabelText(text.skillUrl), { target: { value: 'https://example.org/landing' } })
    fireEvent.click(screen.getByRole('button', { name: text.importSkill }))
    expect(await screen.findByRole('alert')).toHaveTextContent(text.skillUnsupportedUrl)
    fireEvent.change(screen.getByLabelText(text.goal), { target: { value: 'Analyze images' } })
    fireEvent.click(screen.getByRole('button', { name: text.start }))
    await waitFor(() => expect(startAutoResearchSession).toHaveBeenCalledWith(expect.objectContaining({ language, advanced: { skills: [skill] } })))
  })
  it('expands advanced settings, imports an editable skill and resets budget when effort changes', async () => {
    vi.mocked(importResearchSkill).mockResolvedValue({ skills: [{ name: 'Validation', content: '# Validate\nKeep patient splits', source_url: 'https://example.org/SKILL.md' }], files: [{ path: 'SKILL.md', size: 40 }], total_bytes: 40, warnings: [] })
    render(<MemoryRouter><AutoResearchNewSessionPage /></MemoryRouter>)
    fireEvent.click(screen.getByText('Advanced settings'))
    await waitFor(() => expect(screen.getByLabelText('Maximum experiment attempts')).toHaveValue(8))
    fireEvent.change(screen.getByLabelText('Maximum experiment attempts'), { target: { value: '5' } })
    fireEvent.change(screen.getByLabelText('Time limit (hours)'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Skill URL'), { target: { value: 'https://example.org/SKILL.md' } })
    fireEvent.click(screen.getByRole('button', { name: 'Import' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Add selected (1)' }))
    expect(await screen.findByLabelText('Skill Markdown 1')).toHaveValue('# Validate\nKeep patient splits')
    fireEvent.click(screen.getByRole('button', { name: 'Low' }))
    expect(screen.getByLabelText('Maximum experiment attempts')).toHaveValue(3)
    expect(screen.getByLabelText('Time limit (hours)')).toHaveValue(1)
    fireEvent.change(screen.getByLabelText('Maximum experiment attempts'), { target: { value: '6' } })
    fireEvent.change(screen.getByLabelText('Research goal'), { target: { value: 'Compare baselines' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start research' }))
    await waitFor(() => expect(startAutoResearchSession).toHaveBeenCalledWith(expect.objectContaining({ effort: 'low', advanced: { max_experiments: 6, skills: [{ name: 'Validation', content: '# Validate\nKeep patient splits', source_url: 'https://example.org/SKILL.md' }] } })))
  })
  it.each([
    ['zh-CN', '沿用聊天背景', '润色'],
    ['zh-HK', '沿用聊天背景', '潤飾'],
    ['en-US', 'Use chat context', 'Polish']
  ])('localizes the handoff and polish controls in %s', async (language, label, button) => {
    await i18n.changeLanguage(language)
    render(<MemoryRouter initialEntries={[{ pathname: '/autoresearch/new', state: { sourceConversationId: 'chat', researchGoal: 'CRC-MSI' } }]}><AutoResearchNewSessionPage /></MemoryRouter>)
    expect(screen.getByRole('checkbox', { name: label })).toBeChecked()
    expect(screen.getByRole('button', { name: button })).toBeEnabled()
    expect(screen.queryByText(/继承 Chat|繼承 Chat/)).not.toBeInTheDocument()
    await waitFor(() => expect(getResearchHandoff).toHaveBeenCalledWith('chat'))
  })

  it('polishes on click with authorized context and supports undo without submitting', async () => {
    render(<MemoryRouter initialEntries={[{ pathname: '/autoresearch/new', state: { sourceConversationId: 'chat', researchGoal: 'Original request' } }]}><AutoResearchNewSessionPage /></MemoryRouter>)
    expect(polishResearchGoal).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Polish' }))
    await waitFor(() => expect(screen.getByLabelText('Research goal')).toHaveValue('Polished research request'))
    expect(polishResearchGoal).toHaveBeenCalledWith({ question: 'Original request', language: 'en-US', source_conversation_id: 'chat' }, expect.any(AbortSignal))
    expect(startAutoResearchSession).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Undo polish' }))
    expect(screen.getByLabelText('Research goal')).toHaveValue('Original request')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Use chat context' }))
    fireEvent.click(screen.getByRole('button', { name: 'Polish' }))
    await waitFor(() => expect(polishResearchGoal).toHaveBeenLastCalledWith({ question: 'Original request', language: 'en-US', source_conversation_id: undefined }, expect.any(AbortSignal)))
  })

  it('keeps edits made while polishing instead of overwriting them with a late response', async () => {
    let resolve!: (value: { question: string }) => void
    vi.mocked(polishResearchGoal).mockReturnValue(new Promise(done => { resolve = done }))
    render(<MemoryRouter><AutoResearchNewSessionPage /></MemoryRouter>)
    const input = screen.getByLabelText('Research goal')
    fireEvent.change(input, { target: { value: 'Original request' } })
    fireEvent.click(screen.getByRole('button', { name: 'Polish' }))
    expect(screen.getByRole('button', { name: 'Start research' })).toBeDisabled()
    fireEvent.change(input, { target: { value: 'New user correction' } })
    resolve({ question: 'Outdated polished request' })
    expect(await screen.findByRole('status')).toHaveTextContent('Your edits were kept')
    expect(input).toHaveValue('New user correction')
  })

  it('keeps the original text and shows a localized failure without provider details', async () => {
    await i18n.changeLanguage('zh-CN')
    vi.mocked(polishResearchGoal).mockRejectedValue(new Error('secret-provider model endpoint'))
    render(<MemoryRouter><AutoResearchNewSessionPage /></MemoryRouter>)
    fireEvent.change(screen.getByLabelText('研究目标'), { target: { value: '原始研究需求' } })
    fireEvent.click(screen.getByRole('button', { name: '润色' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('暂时无法润色，原文已保留')
    expect(screen.getByLabelText('研究目标')).toHaveValue('原始研究需求')
    expect(screen.queryByText(/secret-provider/)).not.toBeInTheDocument()
  })
  it('submits selected data and effort with no technical budget controls', async () => {
    render(
      <MemoryRouter>
        <AutoResearchNewSessionPage />
      </MemoryRouter>
    )
    expect(screen.queryByText(/administrator/)).not.toBeInTheDocument()
    expect(screen.getByText('Advanced settings').closest('details')).not.toHaveAttribute('open')
    expect(screen.getByRole('button', { name: 'Medium' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(
      await screen.findByRole('checkbox', { name: /Real cohort/ })
    )
    fireEvent.change(screen.getByLabelText('Research goal'), {
      target: { value: 'Compare baselines' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'High' }))
    fireEvent.click(screen.getByRole('checkbox', { name: 'Find and acquire public datasets' }))
    fireEvent.click(screen.getByRole('button', { name: 'Start research' }))
    await waitFor(() =>
      expect(startAutoResearchSession).toHaveBeenCalledWith({
        question: 'Compare baselines',
        language: 'en-US',
        dataset_ids: ['dataset-a'],
        workspace_id: undefined,
        effort: 'high',
        advanced: {},
        allow_downloads: false
      })
    )
  })
  it('blocks submission when model configuration is unavailable', async () => {
    vi.mocked(getResearchConfiguration).mockResolvedValue({
      effort_presets: {
        standard: { low: { max_experiments: 3, time_budget_seconds: 3600 }, medium: { max_experiments: 8, time_budget_seconds: 14400 }, high: { max_experiments: 20, time_budget_seconds: 43200 } },
        scientific: { low: { max_experiments: 12, time_budget_seconds: 43200 }, medium: { max_experiments: 40, time_budget_seconds: 172800 }, high: { max_experiments: 100, time_budget_seconds: 259200 } },
      },
      model: {},
      error: 'Model unavailable',
      can_execute: true
    })
    render(
      <MemoryRouter>
        <AutoResearchNewSessionPage />
      </MemoryRouter>
    )
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Model unavailable'
    )
    fireEvent.change(screen.getByLabelText('Research goal'), {
      target: { value: 'Compare baselines' }
    })
    expect(
      screen.getByRole('button', { name: 'Start research' })
    ).toBeDisabled()
  })
})
