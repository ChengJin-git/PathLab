import React, { useState, useRef, useEffect } from 'react'
import { agentChat, type AgentChatEvent } from '../api'
import { Bot, User, Send, Trash2, Loader2, Search, FlaskConical } from 'lucide-react'
import { Button } from '../components/ui/button'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  type?: string // For special message types
}

export default function AgentTestPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [conversationId, setConversationId] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const currentMessageIdRef = useRef<string | null>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [input])

  const handleClear = () => {
    setMessages([])
    setConversationId(null)
    currentMessageIdRef.current = null
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: input.trim(),
      timestamp: new Date()
    }

    setMessages(prev => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    // Create assistant message placeholder
    const aiMessageId = (Date.now() + 1).toString()
    currentMessageIdRef.current = aiMessageId
    const aiMessage: Message = {
      id: aiMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }
    setMessages(prev => [...prev, aiMessage])

    try {
      let fullContent = ''
      let hasAgentPrefix = false

      await agentChat(userMessage.content, {
        conversationId: conversationId || undefined,
        onContent: (chunk) => {
          fullContent += chunk
          setMessages(prev =>
            prev.map(m =>
              m.id === aiMessageId
                ? { ...m, content: fullContent }
                : m
            )
          )
        },
        onEvent: (event: AgentChatEvent) => {
          console.log('[Agent Event]', event)

          // Handle different event types
          switch (event.type) {
            case 'agent_prefix':
              hasAgentPrefix = true
              break

            case 'content':
              // Content is handled by onContent callback
              break

            case 'status':
              // Show status message
              const statusMsg: Message = {
                id: `${Date.now()}-status`,
                role: 'system',
                content: `🔍 ${event.stage || 'Processing'}${event.topic ? `: ${event.topic}` : ''}...`,
                timestamp: new Date(),
                type: 'status'
              }
              setMessages(prev => [...prev, statusMsg])
              break

            case 'search_result':
              const searchMsg: Message = {
                id: `${Date.now()}-search`,
                role: 'system',
                content: `📄 结果: ${event.topic || 'Found'}: ${event.snippet || ''}...`,
                timestamp: new Date(),
                type: 'search_result'
              }
              setMessages(prev => [...prev, searchMsg])
              break

            case 'search_hit':
              const hitMsg: Message = {
                id: `${Date.now()}-hit`,
                role: 'system',
                content: `🔎 搜索: ${event.source || 'Source'} | ${event.topic || ''}`,
                timestamp: new Date(),
                type: 'search_hit'
              }
              setMessages(prev => [...prev, hitMsg])
              break

            case 'token_usage':
              const tokenMsg: Message = {
                id: `${Date.now()}-token`,
                role: 'system',
                content: `[Token使用] 输入: ${event.input || 0} | 输出: ${event.output || 0} | 总计: ${event.total || 0}`,
                timestamp: new Date(),
                type: 'token_usage'
              }
              setMessages(prev => [...prev, tokenMsg])
              break

            case 'message':
              // Final message (if not streamed)
              if (event.content) {
                setMessages(prev =>
                  prev.map(m =>
                    m.id === aiMessageId
                      ? { ...m, content: event.content || '' }
                      : m
                  )
                )
              }
              break

            case 'system':
              // System messages (hints, prompts, etc.)
              const systemMsg: Message = {
                id: `${Date.now()}-system`,
                role: 'system',
                content: event.content || '',
                timestamp: new Date(),
                type: 'system'
              }
              setMessages(prev => [...prev, systemMsg])
              break

            case 'error':
              const errorMsg: Message = {
                id: `${Date.now()}-error`,
                role: 'system',
                content: `❌ ${event.content || 'Error occurred'}`,
                timestamp: new Date(),
                type: 'error'
              }
              setMessages(prev => [...prev, errorMsg])
              break

            default:
              // Other custom events
              console.log('[Agent] Unhandled event:', event)
          }
        }
      })
    } catch (error) {
      console.error('Failed to get agent response:', error)
      setMessages(prev =>
        prev.map(m =>
          m.id === aiMessageId
            ? { ...m, content: `❌ Error: ${error instanceof Error ? error.message : 'Unknown error'}` }
            : m
        )
      )
    } finally {
      setIsLoading(false)
      currentMessageIdRef.current = null
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className="flex h-full bg-gray-50 flex-col">
      {/* Header */}
      <div className="flex-shrink-0 bg-white border-b border-gray-200 px-4 py-3 shadow-sm">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary-100 flex items-center justify-center">
              <Bot className="w-5 h-5 text-primary-600" />
            </div>
            <div>
              <h1 className="text-base font-semibold text-gray-900">Agent Test (LangGraph REPL)</h1>
              <p className="text-xs text-gray-500">Direct agent integration - based on __main__.py</p>
            </div>
          </div>
          <Button
            variant="outline"
            onClick={handleClear}
            className="gap-2"
          >
            <Trash2 className="w-4 h-4" />
            Clear History
          </Button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-6 min-h-0 pb-32">
        <div className="max-w-4xl mx-auto space-y-4">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center space-y-4">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center shadow-lg">
                <Bot className="w-8 h-8 text-white" />
              </div>
              <div>
                <h2 className="text-2xl font-bold text-gray-900 mb-2">Agent Test Page</h2>
                <p className="text-gray-600 max-w-lg">
                  This page directly uses the LangGraph agent from <code className="bg-gray-100 px-2 py-1 rounded">__main__.py</code>
                </p>
              </div>
              <div className="mt-6 space-y-2 text-left bg-gray-50 p-4 rounded-lg">
                <p className="text-sm font-semibold text-gray-900">Available commands:</p>
                <ul className="text-sm text-gray-600 space-y-1 list-disc list-inside">
                  <li><code>/research &lt;问题&gt;</code> - 深度研究</li>
                  <li><code>/training</code> - 创建训练任务</li>
                  <li><code>/clear</code> - 清空历史</li>
                  <li>普通对话可调 list_wsi 等 PathLab tools</li>
                </ul>
              </div>
            </div>
          )}

          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex gap-4 ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'} items-start`}
            >
              {/* Avatar */}
              <div className="flex-shrink-0 mt-1">
                <div
                  className={`w-8 h-8 rounded-full flex items-center justify-center border ${
                    message.role === 'user'
                      ? 'bg-white border-gray-200'
                      : message.role === 'system'
                      ? 'bg-yellow-100 border-yellow-200'
                      : 'bg-primary-100 border-primary-200'
                  }`}
                >
                  {message.role === 'user' ? (
                    <User className="w-5 h-5 text-gray-600" />
                  ) : message.role === 'system' ? (
                    message.type === 'status' ? (
                      <Search className="w-4 h-4 text-yellow-600" />
                    ) : message.type === 'search_result' ? (
                      <Search className="w-4 h-4 text-blue-600" />
                    ) : (
                      <FlaskConical className="w-4 h-4 text-yellow-600" />
                    )
                  ) : (
                    <Bot className="w-5 h-5 text-primary-600" />
                  )}
                </div>
              </div>

              {/* Message Content */}
              <div className={`flex-1 min-w-0 max-w-[85%] ${message.role === 'user' ? 'items-end' : 'items-start'} flex flex-col`}>
                <div
                  className={`relative px-5 py-3.5 text-[15px] leading-7 ${
                    message.role === 'user'
                      ? 'bg-[#f4f4f4] text-gray-900 rounded-3xl rounded-tr-sm'
                      : message.role === 'system'
                      ? 'bg-yellow-50 text-gray-800 rounded-xl border border-yellow-200'
                      : 'bg-transparent text-gray-900 px-0 py-0'
                  }`}
                >
                  {message.content || (message.role === 'assistant' && isLoading ? (
                    <div className="flex items-center gap-2 py-2">
                      <div className="w-2.5 h-2.5 bg-gray-400 rounded-full animate-pulse"></div>
                      <span className="text-sm font-medium text-gray-500 animate-pulse">Thinking...</span>
                    </div>
                  ) : null)}
                </div>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area */}
      <div className="absolute left-1/2 -translate-x-1/2 bottom-8 translate-y-0 w-full max-w-4xl px-4 z-30">
        <form onSubmit={handleSubmit} className="relative">
          <div className="relative flex items-center bg-white rounded-2xl shadow-xl border border-gray-300 focus-within:ring-2 focus-within:ring-primary-100 focus-within:border-primary-400 h-auto min-h-[60px] pl-4 pr-[100px] py-2">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Type your message... (e.g., /research pathology AI models)"
              className="w-full bg-transparent border-none focus:outline-none resize-none text-gray-900 placeholder-gray-400 transition-all text-base py-3"
              rows={1}
              style={{ maxHeight: '150px' }}
              disabled={isLoading}
              autoFocus
            />
            <div className="absolute right-2 flex items-center gap-2 bottom-2">
              <button
                type="submit"
                disabled={!input.trim() || isLoading}
                className="p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-900 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg active:scale-95"
              >
                {isLoading ? <Loader2 className="w-5 h-5 animate-spin" /> : <Send className="w-5 h-5" />}
              </button>
            </div>
          </div>
          <div className="mt-2 text-center text-xs text-gray-400">
            PathLab Agent can make mistakes. Consider checking important information.
          </div>
        </form>
      </div>
    </div>
  )
}
