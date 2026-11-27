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

  it('keeps the active retry when a stale persisted answer arrives', () => {
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

    expect(merged).toEqual(currentMessages)
  })

  it.each([
    { id: '1712766600001', content: '' },
    { id: '1712766600001', content: '已经核对论文成果' },
    { id: '11119', content: '已经核对论文成果' },
  ])('does not lose an active follow-up reply $id / $content', (reply) => {
    const history: TestMessage[] = [
      { id: '11114', role: 'user', content: '帮我准备博士论文' },
      { id: '11115', role: 'assistant', content: '先梳理研究主线' },
      { id: '11116', role: 'user', content: '先梳理我的论文成果' },
    ]
    const current: TestMessage[] = [...history, { ...reply, role: 'assistant' }]
    const stale: TestMessage[] = [...history, { id: '11117', role: 'assistant', content: '用户取消了回答。' }]

    expect(mergeLoadedMessagesWithPendingAssistant(stale, current, true)).toBe(current)
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
