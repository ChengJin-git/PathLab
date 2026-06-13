import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp, blobResp } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  submitMessageFeedback,
  deleteMessageFeedback,
  getConversationFeedbacks,
  getAdminFeedbacks,
  getFeedbackStats,
  exportFeedbacks,
  resetAllFeedbacks,
  type MessageFeedback,
} from '@renderer/api/feedback'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)

const MOCK_FEEDBACK: MessageFeedback = {
  id: 1,
  message_id: 42,
  user_id: 'user_1',
  username: 'Dr. Smith',
  feedback_type: 'thumbs_up',
  task_helpfulness: 'helpful',
  related_task_id: 'task_001',
  time_to_action_seconds: 30,
  message_content: 'Great analysis!',
  context_messages: null,
  task_type: 'training',
  task_title: 'BRCA Classification',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

beforeEach(() => {
  setAuthToken('test_token')
})

describe('submitMessageFeedback', () => {
  it('sends POST to /messages/:messageId/feedback', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_FEEDBACK))
    await submitMessageFeedback(42, 'thumbs_up')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/messages/42/feedback')
    expect(opts?.method).toBe('POST')
  })

  it('includes only provided fields in body', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_FEEDBACK))
    await submitMessageFeedback(42, 'thumbs_up', 'helpful', 'task_001', 30)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.feedback_type).toBe('thumbs_up')
    expect(body.task_helpfulness).toBe('helpful')
    expect(body.related_task_id).toBe('task_001')
    expect(body.time_to_action_seconds).toBe(30)
  })

  it('omits undefined fields', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_FEEDBACK))
    await submitMessageFeedback(42, 'thumbs_down')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.feedback_type).toBe('thumbs_down')
    expect('task_helpfulness' in body).toBe(false)
    expect('related_task_id' in body).toBe(false)
  })

  it('sends task type and title when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_FEEDBACK))
    await submitMessageFeedback(42, 'thumbs_up', 'helpful', 'task_001', null, null, null, 'training', 'BRCA Task')
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.task_type).toBe('training')
    expect(body.task_title).toBe('BRCA Task')
  })
})

describe('deleteMessageFeedback', () => {
  it('sends DELETE to /messages/:messageId/feedback', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, status: 204, headers: new Headers({ 'content-length': '0' }) } as unknown as Response)
    await deleteMessageFeedback(42)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/messages/42/feedback')
    expect(opts?.method).toBe('DELETE')
  })
})

describe('getConversationFeedbacks', () => {
  it('fetches from GET /conversations/:id/feedbacks', async () => {
    mockFetch.mockResolvedValueOnce(ok({ feedbacks: [MOCK_FEEDBACK] }))
    const result = await getConversationFeedbacks('conv_001')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/conversations/conv_001/feedbacks')
    expect(result).toHaveLength(1)
    expect(result[0].feedback_type).toBe('thumbs_up')
  })

  it('returns empty array when no feedbacks', async () => {
    mockFetch.mockResolvedValueOnce(ok({ feedbacks: [] }))
    const result = await getConversationFeedbacks('conv_empty')
    expect(result).toEqual([])
  })
})

describe('getAdminFeedbacks', () => {
  it('fetches from GET /admin/feedbacks with pagination', async () => {
    mockFetch.mockResolvedValueOnce(ok({ feedbacks: [MOCK_FEEDBACK], total: 1, skip: 0, limit: 50 }))
    await getAdminFeedbacks(0, 50)
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/admin/feedbacks')
    expect(String(url)).toContain('skip=0')
    expect(String(url)).toContain('limit=50')
  })

  it('appends feedback_type filter when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ feedbacks: [], total: 0, skip: 0, limit: 50 }))
    await getAdminFeedbacks(0, 50, 'thumbs_up')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('feedback_type=thumbs_up')
  })

  it('appends helpfulness filter when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ feedbacks: [], total: 0, skip: 0, limit: 50 }))
    await getAdminFeedbacks(0, 50, null, 'helpful')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('helpfulness=helpful')
  })
})

describe('getFeedbackStats', () => {
  it('fetches from GET /admin/feedbacks/stats', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      total_feedbacks: 100,
      thumbs_up_count: 70,
      thumbs_down_count: 30,
      helpful_count: 60,
      not_helpful_count: 40,
      unique_users: 10,
      avg_time_to_action_seconds: 25.5,
    }))
    const result = await getFeedbackStats()
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/admin/feedbacks/stats')
    expect(result.total_feedbacks).toBe(100)
    expect(result.thumbs_up_count).toBe(70)
  })
})

describe('exportFeedbacks', () => {
  it('returns JSON feedbacks array for json format', async () => {
    mockFetch.mockResolvedValueOnce(ok({ feedbacks: [MOCK_FEEDBACK] }))
    const result = await exportFeedbacks('json')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('format=json')
    expect((result as { feedbacks: MessageFeedback[] }).feedbacks).toHaveLength(1)
  })

  it('returns Blob for csv format', async () => {
    mockFetch.mockResolvedValueOnce(blobResp('id,message_id\n1,42', 'text/csv'))
    const result = await exportFeedbacks('csv')
    const [url] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('format=csv')
    expect(result).toBeInstanceOf(Blob)
  })
})

describe('resetAllFeedbacks', () => {
  it('sends DELETE to /admin/feedbacks/reset', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'All feedbacks deleted', deleted_count: 100 }))
    const result = await resetAllFeedbacks()
    const [url, opts] = mockFetch.mock.calls[0]
    expect(String(url)).toContain('/admin/feedbacks/reset')
    expect(opts?.method).toBe('DELETE')
    expect(result.deleted_count).toBe(100)
  })
})
