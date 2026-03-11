import { API_BASE } from '../config'
import { apiFetch, ApiError, ApiErrorCode, buildAuthRequestInit, buildSearchParams, parseErrorResponse, getErrorCodeFromStatus, PaginatedResponse } from './client'

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
  signal?: AbortSignal,
  onContextLimit?: () => void
): Promise<void> {
  // Get AI configuration from localStorage
  const apiKey = localStorage.getItem('openrouter_api_key') || ''
  const baseUrl = localStorage.getItem('openrouter_base_url') || 'https://openrouter.ai/api/v1'
  const model = localStorage.getItem('openrouter_model') || 'qwen/qwen3.5-plus-02-15'

  // Pass the user's explicit i18n language preference so the backend selects the
  // correct system-prompt language instead of relying solely on message-content heuristics.
  const uiLang = localStorage.getItem('i18nextLng') || 'en-US'

  // Pass the browser's IANA timezone (e.g. "Asia/Shanghai") so the backend can
  // include the correct local date/time in the AI context.
  const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone

  let response: Response
  try {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'X-OpenRouter-API-Key': apiKey,
      'X-OpenRouter-Base-URL': baseUrl,
      'X-OpenRouter-Model': model,
      'X-Language': uiLang,
      'X-Timezone': userTimezone
    }
    response = await fetch(`${API_BASE}/chat`, buildAuthRequestInit({
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages,
        conversation_id: conversationId
      }),
      signal
    }))
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
  // Buffer for incomplete lines that span across TCP chunks.
  // reader.read() may split an SSE message at any byte boundary, e.g.:
  //   chunk1: 'data: {"content":"hel'   chunk2: 'lo"}\n\n'
  // Without buffering, chunk1's partial line fails JSON.parse and is silently
  // dropped, causing "blank first load, content after refresh" bugs.
  let lineBuffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value, { stream: true })
      // Prepend any leftover from the previous read
      const text = lineBuffer + chunk
      const lines = text.split('\n')
      // The last element may be an incomplete line — save it for the next iteration.
      // If `text` ended with '\n', the last element is '' (complete), which is fine.
      lineBuffer = lines.pop() || ''

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
            // Handle context_limit event — LLM output was truncated (finish_reason: "length")
            if (parsed.context_limit && onContextLimit) {
              onContextLimit()
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
    metadata?: { images?: string[] } | null
    created_at: string
  }>
}

export type ChatPatchInferenceType = 'classification' | 'segmentation'

export interface ChatPatchInferenceStartRequest {
  conversation_id: string
  message_id: number
  inference_type: ChatPatchInferenceType
  model_id: string
  image_data_url: string
  source?: string | null
}

export interface ChatPatchInferenceTaskResult {
  predicted_label?: string
  probabilities?: Record<string, number>
  top_predictions?: Array<{ label: string; score: number }>
  class_names?: string[]
  positive_classes?: Array<{ label: string; coverage_ratio: number }>
  coverage_by_class?: Array<{ label: string; coverage_ratio: number }>
  has_positive_mask?: boolean
  mask_shape?: [number, number]
}

export interface ChatPatchInferenceTask {
  task_id: string
  conversation_id: string
  message_id: number
  inference_type: ChatPatchInferenceType
  model_id: string
  model_name: string
  source?: string | null
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  result?: ChatPatchInferenceTaskResult | null
  error?: string | null
  created_at: string
  updated_at: string
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
  const params = buildSearchParams({
    skip,
    limit
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

export async function startChatPatchInference(
  request: ChatPatchInferenceStartRequest
): Promise<ChatPatchInferenceTask> {
  return apiFetch<ChatPatchInferenceTask>(
    `${API_BASE}/patch-inference`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request)
    },
    'Failed to start chat patch inference'
  )
}

export async function getChatPatchInferenceTask(taskId: string): Promise<ChatPatchInferenceTask> {
  return apiFetch<ChatPatchInferenceTask>(
    `${API_BASE}/patch-inference/${encodeURIComponent(taskId)}`,
    undefined,
    'Failed to fetch chat patch inference task'
  )
}

