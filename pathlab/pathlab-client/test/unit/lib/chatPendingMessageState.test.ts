import { describe, expect, it } from 'vitest'

import { mergeLoadedMessagesWithPendingAssistant } from '@renderer/lib/chatPendingMessageState'

type TestMessage = {
  id: string
  role: 'user' | 'assistant'
  content: string
}

describe('mergeLoadedMessagesWithPendingAssistant', () => {
  it('preserves the local pending user/assistant pair while generation is in progress', () => {
    const loadedMessages: TestMessage[] = []
    const currentMessages: TestMessage[] = [
      { id: 'local-user-1', role: 'user', content: '阅读全文' },
      { id: '1712766600001', role: 'assistant', content: '' },
    ]

    const merged = mergeLoadedMessagesWithPendingAssistant(
      loadedMessages,
      currentMessages,
      true,
    )

    expect(merged).toEqual(currentMessages)
  })

  it('does not append the pending placeholder once a persisted assistant reply exists', () => {
    const loadedMessages: TestMessage[] = [
      { id: '1', role: 'user', content: '阅读全文' },
      { id: '2', role: 'assistant', content: '完整解读如下' },
    ]
    const currentMessages: TestMessage[] = [
      { id: 'local-user-1', role: 'user', content: '阅读全文' },
      { id: '1712766600001', role: 'assistant', content: '' },
    ]

    const merged = mergeLoadedMessagesWithPendingAssistant(
      loadedMessages,
      currentMessages,
      true,
    )

    expect(merged).toEqual(loadedMessages)
  })

  it('returns loaded messages unchanged when generation is idle', () => {
    const loadedMessages: TestMessage[] = [
      { id: '1', role: 'user', content: 'hi' },
    ]
    const currentMessages: TestMessage[] = [
      { id: 'local-user-1', role: 'user', content: '阅读全文' },
      { id: '1712766600001', role: 'assistant', content: '' },
    ]

    const merged = mergeLoadedMessagesWithPendingAssistant(
      loadedMessages,
      currentMessages,
      false,
    )

    expect(merged).toEqual(loadedMessages)
  })

  it('keeps a streaming placeholder when the backend reload still only has the local user message', () => {
    const loadedMessages: TestMessage[] = [
      { id: 'local-user-1', role: 'user', content: '阅读全文' },
    ]
    const currentMessages: TestMessage[] = [
      { id: 'local-user-1', role: 'user', content: '阅读全文' },
      { id: '1712766600001', role: 'assistant', content: '' },
    ]

    const merged = mergeLoadedMessagesWithPendingAssistant(
      loadedMessages,
      currentMessages,
      true,
    )

    expect(merged).toEqual(currentMessages)
  })
})
