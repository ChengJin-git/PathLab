export interface PendingMessageLike {
  id: string
  role: 'user' | 'assistant'
  content: string
}

function isPersistedMessageId(messageId: string): boolean {
  const numericId = Number.parseInt(messageId, 10)
  return Number.isFinite(numericId) && numericId < 1_000_000_000
}

export function mergeLoadedMessagesWithPendingAssistant<T extends PendingMessageLike>(
  loadedMessages: T[],
  currentMessages: T[],
  isGenerating: boolean,
): T[] {
  if (!isGenerating || currentMessages.length === 0) {
    return loadedMessages
  }

  const pendingAssistant = currentMessages[currentMessages.length - 1]
  if (
    pendingAssistant.role !== 'assistant' ||
    pendingAssistant.content !== '' ||
    isPersistedMessageId(pendingAssistant.id)
  ) {
    return loadedMessages
  }

  const loadedHasAssistantReply = loadedMessages.some(
    (message) => message.role === 'assistant',
  )
  if (loadedHasAssistantReply) {
    return loadedMessages
  }

  const pendingUser = currentMessages[currentMessages.length - 2]
  if (
    pendingUser?.role === 'user' &&
    !loadedMessages.some((message) => message.id === pendingUser.id)
  ) {
    return [...loadedMessages, pendingUser, pendingAssistant]
  }

  return [...loadedMessages, pendingAssistant]
}
