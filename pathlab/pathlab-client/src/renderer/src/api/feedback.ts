import { API_BASE } from '../config'
import { apiFetch, ApiError, getAuthToken } from './client'

// ============================================================================
// Message Feedback APIs
// ============================================================================

/**
 * Context message for feedback (previous message for context)
 */
export interface FeedbackContextMessage {
  role: 'user' | 'assistant'
  content: string
}

/**
 * Feedback data for a message
 */
export interface MessageFeedback {
  id: number
  message_id: number
  user_id: string
  username: string | null  // Display name (nickname or email) from User table
  feedback_type: 'thumbs_up' | 'thumbs_down' | null
  task_helpfulness: 'helpful' | 'not_helpful' | null
  related_task_id: string | null
  time_to_action_seconds: number | null
  message_content: string | null
  context_messages: FeedbackContextMessage[] | null
  task_type: 'training' | 'inference' | 'analysis' | null
  task_title: string | null
  created_at: string
  updated_at: string
}

/**
 * Submit or update feedback for a message
 * @param messageId - Message ID (number)
 * @param feedbackType - 'thumbs_up', 'thumbs_down', or null
 * @param taskHelpfulness - 'helpful', 'not_helpful', or null
 * @param relatedTaskId - Optional task ID for task helpfulness feedback
 * @param timeToActionSeconds - Time from user message to task submission
 * @param messageContent - The rated message content (preserved for admin review)
 * @param contextMessages - Previous message(s) for context
 * @param taskType - Task type: 'training', 'inference', 'analysis'
 * @param taskTitle - Task name/title
 * @returns Created or updated feedback
 * @throws {ApiError} If the request fails
 */
export async function submitMessageFeedback(
  messageId: number,
  feedbackType?: 'thumbs_up' | 'thumbs_down' | null,
  taskHelpfulness?: 'helpful' | 'not_helpful' | null,
  relatedTaskId?: string | null,
  timeToActionSeconds?: number | null,
  messageContent?: string | null,
  contextMessages?: FeedbackContextMessage[] | null,
  taskType?: 'training' | 'inference' | 'analysis' | 'registration' | null,
  taskTitle?: string | null
): Promise<MessageFeedback> {
  return apiFetch(
    `${API_BASE}/messages/${messageId}/feedback`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        feedback_type: feedbackType,
        task_helpfulness: taskHelpfulness,
        related_task_id: relatedTaskId,
        time_to_action_seconds: timeToActionSeconds,
        message_content: messageContent,
        context_messages: contextMessages,
        task_type: taskType,
        task_title: taskTitle
      })
    },
    'Failed to submit feedback'
  )
}

/**
 * Get all feedbacks for messages in a conversation
 * @param conversationId - Conversation ID
 * @returns Array of feedbacks
 * @throws {ApiError} If the request fails
 */
export async function getConversationFeedbacks(
  conversationId: string
): Promise<MessageFeedback[]> {
  const result = await apiFetch<{ feedbacks: MessageFeedback[] }>(
    `${API_BASE}/conversations/${conversationId}/feedbacks`,
    undefined,
    'Failed to get conversation feedbacks'
  )
  return result.feedbacks
}

// ============================================================================
// Admin Feedback Management APIs
// ============================================================================

/**
 * Feedback statistics from admin endpoint
 */
export interface FeedbackStats {
  total_feedbacks: number
  thumbs_up_count: number
  thumbs_down_count: number
  helpful_count: number
  not_helpful_count: number
  unique_users: number
  avg_time_to_action_seconds: number | null
}

/**
 * Paginated feedback list response from admin endpoint
 */
export interface AdminFeedbackListResponse {
  feedbacks: MessageFeedback[]
  total: number
  skip: number
  limit: number
}

/**
 * Get all feedbacks with pagination and filtering (admin only)
 * @param skip - Number of records to skip
 * @param limit - Maximum number of records to return
 * @param feedbackType - Filter by feedback type ('thumbs_up' or 'thumbs_down')
 * @param helpfulness - Filter by helpfulness ('helpful' or 'not_helpful')
 * @param userId - Filter by user ID
 * @returns Paginated feedback list
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function getAdminFeedbacks(
  skip: number = 0,
  limit: number = 50,
  feedbackType?: 'thumbs_up' | 'thumbs_down' | null,
  helpfulness?: 'helpful' | 'not_helpful' | null,
  userId?: string | null
): Promise<AdminFeedbackListResponse> {
  const params = new URLSearchParams()
  params.append('skip', skip.toString())
  params.append('limit', limit.toString())
  if (feedbackType) params.append('feedback_type', feedbackType)
  if (helpfulness) params.append('helpfulness', helpfulness)
  if (userId) params.append('user_id', userId)

  return apiFetch(
    `${API_BASE}/admin/feedbacks?${params.toString()}`,
    undefined,
    'Failed to get feedbacks'
  )
}

/**
 * Get feedback statistics (admin only)
 * @returns Feedback statistics
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function getFeedbackStats(): Promise<FeedbackStats> {
  return apiFetch(
    `${API_BASE}/admin/feedbacks/stats`,
    undefined,
    'Failed to get feedback statistics'
  )
}

/**
 * Export all feedbacks (admin only)
 * @param format - Export format ('json' or 'csv')
 * @returns For JSON: Object with feedbacks array. For CSV: Blob with CSV content.
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function exportFeedbacks(
  format: 'json' | 'csv' = 'json'
): Promise<{ feedbacks: MessageFeedback[] } | Blob> {
  const token = getAuthToken()

  const response = await fetch(`${API_BASE}/admin/feedbacks/export?format=${format}`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {})
    }
  })

  if (!response.ok) {
    throw new ApiError('Failed to export feedbacks', response.status)
  }

  if (format === 'csv') {
    return response.blob()
  } else {
    return response.json()
  }
}

/**
 * Reset (delete) all feedbacks (admin only)
 * @returns Object with deleted count
 * @throws {ApiError} If the request fails or user is not admin
 */
export async function resetAllFeedbacks(): Promise<{ message: string; deleted_count: number }> {
  return apiFetch(
    `${API_BASE}/admin/feedbacks/reset`,
    { method: 'DELETE' },
    'Failed to reset feedbacks'
  )
}

