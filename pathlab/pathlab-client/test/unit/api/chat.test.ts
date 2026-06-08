import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ok, errResp, createSSEStream } from '../../helpers/apiHelpers'

vi.mock('@renderer/config', () => ({
  API_BASE: 'http://localhost:6100',
  updateApiBase: vi.fn(),
  initializeApiConfig: vi.fn(),
}))

import {
  chatWithAI,
  createConversation,
  generateConversationTitle,
  getConversations,
  getConversation,
  deleteConversation,
  updateMessage,
  deleteMessagesFrom,
  addMessage,
  startChatPatchInference,
  getChatPatchInferenceTask,
  type ChatMessage,
} from '@renderer/api/chat'
import { setAuthToken } from '@renderer/api/client'

const mockFetch = vi.mocked(fetch)


const MOCK_CONVERSATION = {
  conversation_id: 'conv_001',
  user_id: 'user_1',
  title: 'BRCA Analysis Chat',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:05:00Z',
}

const MOCK_MESSAGES: ChatMessage[] = [
  { role: 'user', content: 'What is the WSI diagnosis?' },
  { role: 'assistant', content: 'Based on the pathology features...' },
]

beforeEach(() => {
  mockFetch.mockReset()
  setAuthToken('test_token')
  localStorage.setItem('openrouter_api_key', 'or_test_key')
  localStorage.setItem('openrouter_model', 'qwen/qwen3-plus')
  localStorage.setItem('openrouter_base_url', 'https://openrouter.ai/api/v1')
  localStorage.setItem('i18nextLng', 'en-US')
})

describe('chatWithAI (streaming)', () => {
  it('sends POST to /chat with messages and conversation_id', async () => {
    const sseLines = [
      'data: {"content": "Hello"}',
      'data: [DONE]',
    ]
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: createSSEStream(sseLines),
    } as unknown as Response)
    const chunks: string[] = []
    await chatWithAI(MOCK_MESSAGES, (chunk) => chunks.push(chunk), 'conv_001')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/chat')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.conversation_id).toBe('conv_001')
    expect(body.messages).toHaveLength(2)
    expect(chunks).toContain('Hello')
  })

  it('sends AI configuration headers from localStorage', async () => {
    const sseLines = ['data: [DONE]']
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: createSSEStream(sseLines),
    } as unknown as Response)
    await chatWithAI(MOCK_MESSAGES, vi.fn())
    const [, opts] = mockFetch.mock.calls[0]
    const headers = new Headers(opts?.headers)
    expect(headers.get('X-OpenRouter-API-Key')).toBe('or_test_key')
    expect(headers.get('X-OpenRouter-Model')).toBe('qwen/qwen3-plus')
  })

  it('calls onChunk for each content token', async () => {
    const sseLines = [
      'data: {"content": "Based"}',
      'data: {"content": " on"}',
      'data: {"content": " the"}',
      'data: [DONE]',
    ]
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: createSSEStream(sseLines),
    } as unknown as Response)
    const chunks: string[] = []
    await chatWithAI(MOCK_MESSAGES, (c) => chunks.push(c))
    expect(chunks).toEqual(['Based', ' on', ' the'])
  })

  it('calls onMessageId when message_id event is received', async () => {
    const sseLines = [
      'data: {"message_id": 42}',
      'data: [DONE]',
    ]
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: createSSEStream(sseLines),
    } as unknown as Response)
    const onMessageId = vi.fn()
    await chatWithAI(MOCK_MESSAGES, vi.fn(), undefined, onMessageId)
    expect(onMessageId).toHaveBeenCalledWith(42, undefined)
  })

  it('calls onContextLimit when context_limit flag is received', async () => {
    const sseLines = [
      'data: {"context_limit": true}',
      'data: [DONE]',
    ]
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: createSSEStream(sseLines),
    } as unknown as Response)
    const onContextLimit = vi.fn()
    await chatWithAI(MOCK_MESSAGES, vi.fn(), undefined, undefined, undefined, onContextLimit)
    expect(onContextLimit).toHaveBeenCalled()
  })

  it('calls onSearchStatus when search_status event is received', async () => {
    const sseLines = [
      'data: {"type": "search_status", "query": "lung cancer markers", "reason": "user asked"}',
      'data: [DONE]',
    ]
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: createSSEStream(sseLines),
    } as unknown as Response)
    const onSearchStatus = vi.fn()
    await chatWithAI(
      MOCK_MESSAGES, vi.fn(), undefined, undefined, undefined, undefined, undefined, undefined,
      onSearchStatus
    )
    expect(onSearchStatus).toHaveBeenCalledWith(expect.objectContaining({
      query: 'lung cancer markers',
      reason: 'user asked',
    }))
  })

  it('re-throws AbortError when request is aborted', async () => {
    const controller = new AbortController()
    mockFetch.mockRejectedValueOnce(new DOMException('Aborted', 'AbortError'))
    await expect(
      chatWithAI(MOCK_MESSAGES, vi.fn(), undefined, undefined, controller.signal)
    ).rejects.toMatchObject({ name: 'AbortError' })
  })

  it('throws ApiError with NETWORK_ERROR on fetch failure', async () => {
    mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(chatWithAI(MOCK_MESSAGES, vi.fn())).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
  })

  it('throws ApiError on non-200 HTTP response', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'AI service unavailable' }, 503))
    await expect(chatWithAI(MOCK_MESSAGES, vi.fn())).rejects.toMatchObject({ status: 503 })
  })

  it('buffers partial SSE lines across TCP chunk boundaries', async () => {
    const encoder = new TextEncoder()
    const part1 = 'data: {"conte'
    const part2 = 'nt": "hello"}\ndata: [DONE]\n'
    let chunkIndex = 0
    const chunks = [part1, part2]
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (chunkIndex < chunks.length) {
          controller.enqueue(encoder.encode(chunks[chunkIndex++]))
        } else {
          controller.close()
        }
      },
    })
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'text/event-stream' }),
      body: stream,
    } as unknown as Response)
    const received: string[] = []
    await chatWithAI(MOCK_MESSAGES, (c) => received.push(c))
    expect(received).toContain('hello')
  })
})

describe('createConversation', () => {
  it('sends POST to /conversations with title', async () => {
    mockFetch.mockResolvedValueOnce(ok(MOCK_CONVERSATION))
    const result = await createConversation('BRCA Analysis Chat')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/conversations')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.title).toBe('BRCA Analysis Chat')
    expect(result.conversation_id).toBe('conv_001')
  })

  it('defaults title to "New Conversation" when not provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ ...MOCK_CONVERSATION, title: 'New Conversation' }))
    await createConversation()
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.title).toBe('New Conversation')
  })

  it('includes source_conversation_id when branching from an existing conversation', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      ...MOCK_CONVERSATION,
      conversation_id: 'conv_002',
      parent_conversation_id: 'conv_001',
      parent_conversation_title: 'BRCA Analysis Chat',
      branch_source_message_count: 7,
    }))
    await createConversation('BRCA Analysis Chat', { sourceConversationId: 'conv_001' })
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.source_conversation_id).toBe('conv_001')
  })
})

describe('generateConversationTitle', () => {
  it('passes the current i18n language header to the backend', async () => {
    localStorage.setItem('i18nextLng', 'zh-CN')
    mockFetch.mockResolvedValueOnce(ok({ title: '查看 ucec 任务' }))

    await generateConversationTitle('conv_001')

    const [url, opts] = mockFetch.mock.lastCall ?? []
    expect(url).toContain('/conversations/conv_001/generate-title')
    const headers = new Headers(opts?.headers)
    expect(headers.get('X-Language')).toBe('zh-CN')
  })
})

describe('getConversations', () => {
  it('fetches conversations with pagination params', async () => {
    mockFetch.mockResolvedValueOnce(ok({ items: [MOCK_CONVERSATION], total: 1 }))
    const result = await getConversations(0, 50)
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/conversations')
    expect(url).toContain('skip=0')
    expect(url).toContain('limit=50')
    expect(result).toHaveLength(1)
    expect(result[0].conversation_id).toBe('conv_001')
  })

  it('returns empty array when items is missing', async () => {
    mockFetch.mockResolvedValueOnce(ok({ total: 0 }))
    const result = await getConversations()
    expect(result).toEqual([])
  })
})

describe('getConversation', () => {
  it('fetches a conversation with messages by ID', async () => {
    mockFetch.mockResolvedValueOnce(ok({
      ...MOCK_CONVERSATION,
      parent_conversation_id: 'conv_root',
      parent_conversation_title: 'Root conversation',
      branch_source_message_count: 3,
      messages: [
        { id: 1, conversation_id: 'conv_001', role: 'user', content: 'Hello', created_at: '2024-01-01T00:00:00Z' },
      ],
    }))
    const result = await getConversation('conv_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/conversations/conv_001')
    expect(result.messages).toHaveLength(1)
    expect(result.messages[0].content).toBe('Hello')
    expect(result.parent_conversation_id).toBe('conv_root')
    expect(result.parent_conversation_title).toBe('Root conversation')
    expect(result.branch_source_message_count).toBe(3)
  })

  it('throws NOT_FOUND for unknown conversation', async () => {
    mockFetch.mockResolvedValueOnce(errResp({ detail: 'Not found' }, 404))
    await expect(getConversation('bad_id')).rejects.toMatchObject({ status: 404, code: 'NOT_FOUND' })
  })
})

describe('deleteConversation', () => {
  it('sends DELETE to /conversations/:id', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      headers: new Headers({ 'content-length': '0' }),
    } as unknown as Response)
    await deleteConversation('conv_001')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/conversations/conv_001')
    expect(opts?.method).toBe('DELETE')
  })
})

describe('updateMessage', () => {
  it('sends PATCH to /conversations/:id/messages/:msgId', async () => {
    mockFetch.mockResolvedValueOnce(ok({ id: 1, conversation_id: 'conv_001', role: 'assistant', content: 'Updated content', created_at: '2024-01-01T00:00:00Z' }))
    const result = await updateMessage('conv_001', 1, 'Updated content')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/conversations/conv_001/messages/1')
    expect(opts?.method).toBe('PATCH')
    const body = JSON.parse(opts?.body as string)
    expect(body.content).toBe('Updated content')
    expect(result.content).toBe('Updated content')
  })

  it('includes artifacts in body when provided', async () => {
    mockFetch.mockResolvedValueOnce(ok({ id: 1, conversation_id: 'conv_001', role: 'assistant', content: 'text', created_at: '2024-01-01T00:00:00Z' }))
    const artifacts = { search: { statuses: [], phase: 'done' as const, pdfStatuses: [], webSearchResults: [], pdfParseResults: [] } }
    await updateMessage('conv_001', 1, 'text', artifacts)
    const body = JSON.parse(mockFetch.mock.calls[0][1]?.body as string)
    expect(body.metadata.artifacts).toEqual(artifacts)
  })
})

describe('deleteMessagesFrom', () => {
  it('sends DELETE to messages endpoint from a specific message ID', async () => {
    mockFetch.mockResolvedValueOnce(ok({ message: 'Deleted', deleted_count: 3 }))
    const result = await deleteMessagesFrom('conv_001', 5)
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/conversations/conv_001/messages/5')
    expect(opts?.method).toBe('DELETE')
    expect(result.deleted_count).toBe(3)
  })
})

describe('addMessage', () => {
  it('sends POST with role and content', async () => {
    mockFetch.mockResolvedValueOnce(ok({ id: 10, conversation_id: 'conv_001', role: 'user', content: 'New message', created_at: '2024-01-01T00:00:00Z' }))
    const result = await addMessage('conv_001', 'user', 'New message')
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/conversations/conv_001/messages')
    expect(opts?.method).toBe('POST')
    const body = JSON.parse(opts?.body as string)
    expect(body.role).toBe('user')
    expect(body.content).toBe('New message')
    expect(result.id).toBe(10)
  })
})

describe('startChatPatchInference', () => {
  it('sends POST to /patch-inference with request body', async () => {
    const mockTask = {
      task_id: 'inf_001',
      conversation_id: 'conv_001',
      message_id: 5,
      inference_type: 'classification' as const,
      model_id: 'model_001',
      model_name: 'BRCA Classifier',
      status: 'queued' as const,
      progress: 0,
      result: null,
      error: null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:00:00Z',
    }
    mockFetch.mockResolvedValueOnce(ok(mockTask))
    const result = await startChatPatchInference({
      conversation_id: 'conv_001',
      message_id: 5,
      inference_type: 'classification',
      model_id: 'model_001',
      image_data_url: 'data:image/png;base64,abc123',
    })
    const [url, opts] = mockFetch.mock.calls[0]
    expect(url).toContain('/patch-inference')
    expect(opts?.method).toBe('POST')
    expect(result.task_id).toBe('inf_001')
    expect(result.status).toBe('queued')
  })
})

describe('getChatPatchInferenceTask', () => {
  it('fetches inference task by ID', async () => {
    const mockTask = {
      task_id: 'inf_001',
      conversation_id: 'conv_001',
      message_id: 5,
      inference_type: 'classification' as const,
      model_id: 'model_001',
      model_name: 'BRCA Classifier',
      status: 'completed' as const,
      progress: 100,
      result: { predicted_label: 'LUAD', probabilities: { LUAD: 0.9, LUSC: 0.1 } },
      error: null,
      created_at: '2024-01-01T00:00:00Z',
      updated_at: '2024-01-01T00:01:00Z',
    }
    mockFetch.mockResolvedValueOnce(ok(mockTask))
    const result = await getChatPatchInferenceTask('inf_001')
    const [url] = mockFetch.mock.calls[0]
    expect(url).toContain('/patch-inference/inf_001')
    expect(result.status).toBe('completed')
    expect(result.result?.predicted_label).toBe('LUAD')
  })
})
