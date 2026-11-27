import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import { NavigationCard, parseNavigateBlock } from '@renderer/components/chat/NavigationCard'
import i18n from '@renderer/i18n'

afterEach(() => { cleanup(); sessionStorage.clear() })
const config = { type: 'research' as const, target: '/autoresearch/new', buttonText: 'Open AutoResearch', description: 'Run the full study.', state: { researchGoal: 'Compare two baselines on CSCNEC.', datasetIds: ['dataset-1'] } }
it.each([
  ['zh-CN', '自主探索', '打开自主探索'],
  ['zh-HK', '自主探索', '開啟自主探索'],
  ['en-US', 'AutoResearch', 'Open AutoResearch']
])('localizes research card chrome in %s independently of model output', async (language, title, button) => {
  await i18n.changeLanguage(language)
  const parsed = parseNavigateBlock('[NAVIGATE]{"type":"research","target":"/autoresearch/new","description":"CRC-MSI"}[/NAVIGATE]')
  expect(parsed).not.toBeNull()
  render(<MemoryRouter><NavigationCard config={parsed!} /></MemoryRouter>)
  expect(screen.getByRole('heading', { name: title })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: button })).toBeInTheDocument()
})
function Location() { const location = useLocation(); return <output data-testid="route">{JSON.stringify(location)}</output> }
it('selects the research skill in the current conversation after the user clicks', async () => {
  await i18n.changeLanguage('en-US')
  const selected = vi.fn()
  window.addEventListener('workbench:select-research', selected)
  render(<MemoryRouter initialEntries={['/dashboard/chat-1']}><NavigationCard config={config} conversationId="chat-1" /><Location /></MemoryRouter>)
  expect(screen.getByTestId('route')).toHaveTextContent('/dashboard/chat-1')
  fireEvent.click(screen.getByRole('button', { name: 'Open AutoResearch' }))
  expect(screen.getByTestId('route')).toHaveTextContent('/dashboard/chat-1')
  expect(selected).toHaveBeenCalledOnce()
  expect(selected.mock.calls[0][0].detail).toEqual({ goal: 'Compare two baselines on CSCNEC.', datasetIds: ['dataset-1'], conversationId: 'chat-1' })
  window.removeEventListener('workbench:select-research', selected)
})
it('never executes an automatic research decision when historical messages mount', () => {
  const selected = vi.fn()
  window.addEventListener('workbench:select-research', selected)
  render(<MemoryRouter><NavigationCard config={{ ...config, execute: true }} conversationId="chat-1" /></MemoryRouter>)
  expect(screen.queryByRole('button', { name: 'Open AutoResearch' })).not.toBeInTheDocument()
  expect(selected).not.toHaveBeenCalled()
  window.removeEventListener('workbench:select-research', selected)
})
it('remembers dismissal for the conversation across remounts', async () => {
  await i18n.changeLanguage('en-US')
  const view = () => <MemoryRouter><NavigationCard config={config} conversationId="chat-2" /></MemoryRouter>
  const first = render(view())
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  first.unmount()
  render(view())
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
})
