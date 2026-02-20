import { API_BASE } from '../config'
import { apiFetch, ApiError, ApiErrorCode, getAuthToken, parseErrorResponse, getErrorCodeFromStatus, PaginatedResponse } from './client'

// ============================================================================
// Chat with AI (Streaming)
// ============================================================================

/**
 * Chat message content type - supports both text and multimodal
 */
export type ChatMessageContent =
  | string
  | Array<
    | { type: 'text'; text: string }
    | { type: 'image_url'; image_url: { url: string } }
  >

/**
 * Chat message type
 */
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: ChatMessageContent
}

/**
 * Chat with AI assistant (streaming)
 * Supports both text-only and multimodal messages (with images)
 *
 * @param messages - Array of chat messages (text or multimodal)
 * @param onChunk - Callback for each chunk of response
 * @param conversationId - Optional conversation ID to save messages to database
 * @returns Promise that resolves when streaming is complete
 * @throws {ApiError} If the request fails
 */
export async function chatWithAI(
  messages: ChatMessage[],
  onChunk: (chunk: string) => void,
  conversationId?: string,
  onMessageId?: (messageId: number) => void,
  signal?: AbortSignal
): Promise<void> {
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('openrouter_api_key') || ''
  const baseUrl = localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1'
  const model = localStorage.getItem('openrouter_model') || 'qwen/qwen3.5-plus-02-15'

  let response: Response
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-OpenRouter-API-Key': apiKey,
      'X-OpenRouter-Base-URL': baseUrl,
      'X-OpenRouter-Model': model
    }
    const token = getAuthToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    response = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages,
        conversation_id: conversationId
      }),
      signal
    })
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error)
    if (
      errorMessage.toLowerCase().includes('fetch') ||
      errorMessage.toLowerCase().includes('network')
    ) {
      throw new ApiError(
        'Failed to connect to AI service. Please check your network connection.',
        0,
        ApiErrorCode.NETWORK_ERROR,
        errorMessage
      )
    }
    throw error
  }

  if (!response.ok) {
    const { message, detail } = await parseErrorResponse(response)
    throw new ApiError(`Failed to chat with AI: ${message}`, response.status, getErrorCodeFromStatus(response.status), detail)
  }

  // Handle streaming response
  const reader = response.body?.getReader()
  if (!reader) {
    throw new ApiError('Response body is not readable', 0, ApiErrorCode.UNKNOWN)
  }

  const decoder = new TextDecoder()

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      const lines = chunk.split('\n')

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') {
            return
          }
          try {
            const parsed = JSON.parse(data)
            if (parsed.content) {
              onChunk(parsed.content)
            }
            // Handle message_id event for persistence
            if (parsed.message_id && onMessageId) {
              onMessageId(parsed.message_id)
            }
          } catch (e) {
            // Skip invalid JSON
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ============================================================================
// Chat Conversation Management APIs
// ============================================================================

export interface Conversation {
  conversation_id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
}

export interface ConversationWithMessages extends Conversation {
  messages: Array<{
    id: number
    conversation_id: string
    role: 'user' | 'assistant'
    content: string
    created_at: string
  }>
}

/**
 * Create a new conversation
 * User ID is automatically determined from JWT token.
 * @param title - Optional conversation title
 * @returns Created conversation
 * @throws {ApiError} If the request fails
 */
export async function createConversation(title?: string): Promise<Conversation> {
  return apiFetch<Conversation>(
    `${API_BASE}/conversations`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title: title || 'New Conversation'
      })
    },
    'Failed to create conversation'
  )
}

/**
 * Get all conversations for the current user.
 * User ID is automatically determined from JWT token.
 * @param skip - Number of conversations to skip
 * @param limit - Maximum number of conversations to return
 * @returns List of conversations
 * @throws {ApiError} If the request fails
 */
export async function getConversations(
  skip: number = 0,
  limit: number = 50
): Promise<Conversation[]> {
  const params = new URLSearchParams({
    skip: String(skip),
    limit: String(limit)
  })

  const data = await apiFetch<PaginatedResponse<Conversation>>(
    `${API_BASE}/conversations?${params}`,
    undefined,
    'Failed to get conversations'
  )
  return data.items || []
}

/**
 * Get a conversation with all messages
 * @param conversationId - Conversation ID
 * @returns Conversation with messages
 * @throws {ApiError} If the request fails (use .isNotFound() to check for 404)
 */
export async function getConversation(conversationId: string): Promise<ConversationWithMessages> {
  return apiFetch<ConversationWithMessages>(
    `${API_BASE}/conversations/${conversationId}`,
    undefined,
    'Failed to get conversation'
  )
}

/**
 * Delete a conversation
 * @param conversationId - Conversation ID
 * @throws {ApiError} If the request fails
 */
export async function deleteConversation(conversationId: string): Promise<void> {
  await apiFetch(
    `${API_BASE}/conversations/${conversationId}`,
    { method: 'DELETE' },
    'Failed to delete conversation'
  )
}

/**
 * Update a message's content
 * Used to persist task submission status in the message content
 * @param conversationId - Conversation ID
 * @param messageId - Message ID (number)
 * @param content - New message content
 * @returns Updated message
 * @throws {ApiError} If the request fails
 */
export async function updateMessage(
  conversationId: string,
  messageId: number,
  content: string
): Promise<{ id: number; conversation_id: string; role: string; content: string; created_at: string }> {
  return apiFetch(
    `${API_BASE}/conversations/${conversationId}/messages/${messageId}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content })
    },
    'Failed to update message'
  )
}

/**
 * Delete a message and all subsequent messages in a conversation
 * Used for conversation branching - allows users to delete from a point and restart
 * @param conversationId - Conversation ID
 * @param messageId - Message ID (number) from which to delete (inclusive)
 * @returns Delete result with count of deleted messages
 * @throws {ApiError} If the request fails
 */
export async function deleteMessagesFrom(
  conversationId: string,
  messageId: number
): Promise<{ message: string; deleted_count: number }> {
  return apiFetch(
    `${API_BASE}/conversations/${conversationId}/messages/${messageId}`,
    { method: 'DELETE' },
    'Failed to delete messages'
  )
}

/**
 * Add a message to a conversation
 * Used to persist task submission success messages
 * @param conversationId - Conversation ID
 * @param role - Message role ("user" or "assistant")
 * @param content - Message content
 * @returns Created message
 * @throws {ApiError} If the request fails
 */
export async function addMessage(
  conversationId: string,
  role: 'user' | 'assistant',
  content: string
): Promise<{ id: number; conversation_id: string; role: string; content: string; created_at: string }> {
  return apiFetch(
    `${API_BASE}/conversations/${conversationId}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, content })
    },
    'Failed to add message'
  )
}

