import React, { useState, useRef, useEffect } from 'react'
import { useNavigate, useLocation, Link } from 'react-router-dom'
import { chatWithAI, parseTaskDescription } from '../api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

export default function AIChatPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'Hello! I\'m your AI research assistant. You can describe your research task in natural language, and I\'ll help you set it up. For example:\n\n"I want to classify HSIL and LSIL cervical cancer samples using deep learning"\n\nWhat would you like to research today?',
      timestamp: new Date()
    }
  ])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const initialMessageSent = useRef(false)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  useEffect(() => {
    // Auto-resize textarea
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = textareaRef.current.scrollHeight + 'px'
    }
  }, [input])

  // Handle initial message from navigation state
  useEffect(() => {
    const state = location.state as { initialMessage?: string } | null
    if (state?.initialMessage && !initialMessageSent.current) {
      initialMessageSent.current = true
      setInput(state.initialMessage)
      // Auto-submit after a short delay
      setTimeout(() => {
        const form = document.querySelector('form')
        if (form) {
          form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }))
        }
      }, 100)
    }
  }, [location.state])

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

    // Create a placeholder message for streaming
    const aiMessageId = (Date.now() + 1).toString()
    const aiMessage: Message = {
      id: aiMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date()
    }
    setMessages(prev => [...prev, aiMessage])
    setIsLoading(true)

    try {
      // Call backend API for streaming LLM response
      const chatMessages = messages
        .concat([userMessage])
        .map(m => ({ role: m.role, content: m.content }))

      let hasReceivedContent = false
      await chatWithAI(chatMessages, (chunk) => {
        if (!hasReceivedContent) {
          hasReceivedContent = true
          setIsLoading(false) // Stop loading animation once we start receiving content
        }
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, content: m.content + chunk }
              : m
          )
        )
      })
    } catch (error) {
      console.error('Failed to get AI response:', error)
      setMessages(prev =>
        prev.map(m =>
          m.id === aiMessageId
            ? { ...m, content: 'Sorry, I encountered an error. Please try again.' }
            : m
        )
      )
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit(e)
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Messages Container */}
      <div className="flex-1 overflow-y-auto px-4 py-6 min-h-0">
        <div className="max-w-5xl mx-auto space-y-4">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`flex items-start space-x-2.5 max-w-4xl ${
                  message.role === 'user' ? 'flex-row-reverse space-x-reverse' : ''
                }`}
              >
                {/* Avatar */}
                <div
                  className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center text-lg ${
                    message.role === 'user'
                      ? 'bg-gradient-to-br from-blue-500 to-blue-600 text-white'
                      : 'bg-gradient-to-br from-purple-500 to-purple-600 text-white'
                  }`}
                >
                  {message.role === 'user' ? '👤' : '🤖'}
                </div>

                {/* Message Content */}
                <div className="flex-1 min-w-0">
                  <div
                    className={`px-4 py-2.5 rounded-lg ${
                      message.role === 'user'
                        ? 'bg-blue-600 text-white'
                        : 'bg-white border border-gray-200 text-gray-900 shadow-sm'
                    }`}
                  >
                    {message.role === 'user' ? (
                      <div className="whitespace-pre-wrap break-words text-sm leading-relaxed">{message.content}</div>
                    ) : (
                      <div className="prose prose-sm max-w-none prose-headings:mt-3 prose-headings:mb-2 prose-p:my-2 prose-ul:my-2 prose-ol:my-2 prose-li:my-0.5 prose-code:bg-gray-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-pre:bg-gray-100 prose-pre:text-gray-900">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>
                  <div
                    className={`text-xs mt-1 px-1 ${
                      message.role === 'user' ? 'text-right text-gray-500' : 'text-gray-500'
                    }`}
                  >
                    {message.timestamp.toLocaleTimeString()}
                  </div>
                </div>
              </div>
            </div>
          ))}

          {/* Welcome Message */}
          {messages.length === 0 && !isLoading && (
            <div className="text-center py-12">
              <div className="text-5xl mb-3">🤖</div>
              <h2 className="text-xl font-bold text-gray-900 mb-2">
                Hello! I'm your AI research assistant
              </h2>
              <p className="text-sm text-gray-600 mb-6">
                Describe your research task in natural language, and I'll help you set it up.
              </p>
              <div className="max-w-2xl mx-auto">
                <div className="bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-lg p-3 text-left">
                  <p className="text-sm text-gray-700 italic">
                    "I want to classify HSIL and LSIL cervical cancer samples using deep learning"
                  </p>
                </div>
              </div>
            </div>
          )}

          {isLoading && (
            <div className="flex justify-start">
              <div className="flex items-start space-x-2.5 max-w-4xl">
                <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-purple-600 flex items-center justify-center text-lg text-white">
                  🤖
                </div>
                <div className="flex-1 min-w-0">
                  <div className="px-4 py-2.5 rounded-lg bg-white border border-gray-200 shadow-sm">
                    <div className="flex items-center space-x-2">
                      <div className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                      <div className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                      <div className="w-2 h-2 bg-purple-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input Area */}
      <div className="flex-shrink-0 bg-white border-t border-gray-200 px-4 py-4">
        <div className="max-w-5xl mx-auto">
          <form onSubmit={handleSubmit} className="flex items-end space-x-3">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Describe your research task... (Press Enter to send, Shift+Enter for new line)"
                className="w-full px-3 py-2.5 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none transition-all text-gray-900 placeholder-gray-400"
                rows={1}
                style={{ maxHeight: '150px' }}
                disabled={isLoading}
              />
            </div>
            <button
              type="submit"
              disabled={!input.trim() || isLoading}
              className="flex-shrink-0 px-5 py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm font-medium rounded-lg hover:from-blue-700 hover:to-blue-800 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:from-gray-300 disabled:to-gray-300 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md"
            >
              {isLoading ? (
                <span className="flex items-center space-x-1.5">
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  <span>Sending</span>
                </span>
              ) : (
                <span className="flex items-center space-x-1.5">
                  <span>Send</span>
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                  </svg>
                </span>
              )}
            </button>
          </form>

          {/* Quick Actions */}
          <div className="mt-2.5 flex flex-wrap gap-2 items-center">
            <button
              onClick={() => setInput('Classify HSIL and LSIL cervical cancer samples using deep learning')}
              className="px-2.5 py-1 text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded-md hover:bg-purple-100 transition-colors"
              disabled={isLoading}
            >
              💡 Cervical Cancer Classification
            </button>
            <button
              onClick={() => setInput('Analyze lung cancer pathology slides (LUAD vs LUSC vs Normal)')}
              className="px-2.5 py-1 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors"
              disabled={isLoading}
            >
              💡 Lung Cancer Analysis
            </button>
            <button
              onClick={() => setInput('Train a model to detect tumor regions in breast cancer slides')}
              className="px-2.5 py-1 text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-md hover:bg-green-100 transition-colors"
              disabled={isLoading}
            >
              💡 Breast Cancer Detection
            </button>

            {/* Divider */}
            <div className="h-4 w-px bg-gray-300 mx-1"></div>

            {/* Link to structured setup */}
            <Link
              to="/task-setup"
              className="px-2.5 py-1 text-xs font-medium text-gray-700 bg-gray-50 border border-gray-300 rounded-md hover:bg-gray-100 transition-colors flex items-center gap-1"
            >
              <span>📋</span>
              <span>Prefer step-by-step setup?</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

