import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor
} from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ResearchQuestion from '@renderer/components/autoresearch/ResearchQuestion'
import { answerResearchQuestion } from '@renderer/api/autoresearch'
import i18n from '@renderer/i18n'

vi.mock('@renderer/api/autoresearch', () => ({
  answerResearchQuestion: vi.fn()
}))
afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})
it('submits a native form answer using the field keys and form identity', async () => {
  await i18n.changeLanguage('en-US')
  vi.mocked(answerResearchQuestion).mockResolvedValue({ command_id: 'c1' })
  render(
    <ResearchQuestion
      sessionId="session"
      form={{
        id: 'form1',
        title: 'Evaluation target',
        fields: [
          {
            key: 'target',
            title: 'Target',
            type: 'string',
            required: true,
            options: [{ value: 'survival', label: 'Survival' }]
          }
        ]
      }}
    />
  )
  fireEvent.click(screen.getByRole('button',{name:'Target'}))
  fireEvent.click(await screen.findByRole('option',{name:'Survival'}))
  fireEvent.click(screen.getByRole('button', { name: 'Send' }))
  await waitFor(() =>
    expect(answerResearchQuestion).toHaveBeenCalledWith('session', 'form1', {
      target: 'survival'
    })
  )
})
