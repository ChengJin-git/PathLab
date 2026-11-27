import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ChatSessionHint, { isLongConversation } from '@renderer/components/chat/ChatSessionHint'
import i18n from '@renderer/i18n'

afterEach(cleanup)
it('uses cheap turn/character thresholds rather than a model request', () => {
  expect(isLongConversation([{ role: 'user', content: 'Hi' }])).toBe(false)
  expect(isLongConversation([{ role: 'user', content: 'a'.repeat(24000) }])).toBe(true)
  expect(isLongConversation(Array.from({ length: 24 }, () => ({ role: 'assistant', content: 'short' })))).toBe(true)
})
it('lets the user keep chatting and never creates a session without a click', async () => {
  await i18n.changeLanguage('en-US')
  const create = vi.fn()
  render(<ChatSessionHint messages={[{ role: 'user', content: 'a'.repeat(24000) }]} generating={false} onNewSession={create} />)
  expect(screen.getByRole('status')).toHaveTextContent('The chat is getting longer')
  expect(create).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Keep this conversation' }))
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(create).not.toHaveBeenCalled()
})
