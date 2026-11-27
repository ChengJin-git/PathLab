export interface PendingMessageLike {
  id: string
  role: 'user' | 'assistant'
  content: string
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
  if (pendingAssistant.role !== 'assistant') {
    return loadedMessages
  }

  // The stream owns this timeline until generation finishes. A history GET can
  // contain an earlier answer (including the cancellation being regenerated),
  // but replacing the local reply loses the ID used by every stream callback.
  // Keep partial content and backend-assigned IDs as well as empty placeholders.
  return currentMessages
}
