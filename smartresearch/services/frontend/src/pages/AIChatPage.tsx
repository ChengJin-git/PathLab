import React, { useState, useRef, useEffect } from 'react'
import { useLocation, Link } from 'react-router-dom'
import {
  chatWithAI,
  getConversations,
  createConversation,
  getConversation,
  deleteConversation,
  type Conversation
} from '../api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Lightbulb, Send, Loader2, Bot, User } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

const WELCOME_MESSAGE: Message = {
  id: '1',
  role: 'assistant',
  content: 'Hello! I\'m your AI research assistant. You can describe your research task in natural language, and I\'ll help you set it up. For example:\n\n"I want to classify HSIL and LSIL cervical cancer samples using deep learning"\n\nWhat would you like to research today?',
  timestamp: new Date()
}

export default function AIChatPage() {
  const location = useLocation()
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [isLoadingConversations, setIsLoadingConversations] = useState(false)
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

  // Load conversations on mount
  useEffect(() => {
    loadConversations()
  }, [])

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

  const loadConversations = async () => {
    try {
      setIsLoadingConversations(true)
      const convs = await getConversations()
      setConversations(convs)
    } catch (error) {
      console.error('Failed to load conversations:', error)
    } finally {
      setIsLoadingConversations(false)
    }
  }

  const handleNewChat = () => {
    setMessages([WELCOME_MESSAGE])
    setCurrentConversationId(null)
    setInput('')
  }

  const handleLoadConversation = async (conversationId: string) => {
    try {
      const conv = await getConversation(conversationId)
      const loadedMessages: Message[] = conv.messages.map(msg => ({
        id: String(msg.id),
        role: msg.role,
        content: msg.content,
        timestamp: new Date(msg.created_at)
      }))
      setMessages(loadedMessages.length > 0 ? loadedMessages : [WELCOME_MESSAGE])
      setCurrentConversationId(conversationId)
      setShowHistory(false)
    } catch (error) {
      console.error('Failed to load conversation:', error)
    }
  }

  const handleDeleteConversation = async (conversationId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Are you sure you want to delete this conversation?')) {
      return
    }
    try {
      await deleteConversation(conversationId)
      await loadConversations()
      if (currentConversationId === conversationId) {
        handleNewChat()
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error)
    }
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

    // Filter out welcome message for actual chat
    const actualMessages = messages.filter(m => m.id !== '1')
    setMessages(prev => [...prev, userMessage])
    setInput('')

    // Create a new conversation if this is the first user message
    let conversationId = currentConversationId
    if (!conversationId && actualMessages.length === 0) {
      try {
        // Generate title from first message (truncate if too long)
        const title = userMessage.content.length > 50
          ? userMessage.content.substring(0, 50) + '...'
          : userMessage.content
        const newConv = await createConversation(title)
        conversationId = newConv.conversation_id
        setCurrentConversationId(conversationId)
        await loadConversations()
      } catch (error) {
        console.error('Failed to create conversation:', error)
      }
    }

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
        .filter(m => m.id !== '1') // Exclude welcome message
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
    <div className="flex h-full bg-gray-50 relative">
      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar with History Toggle */}
        <div className="flex-shrink-0 bg-white border-b border-gray-200 px-4 py-3">
          <div className="max-w-5xl mx-auto flex items-center justify-between">
            <h1 className="text-lg font-semibold text-gray-900">
              {currentConversationId
                ? conversations.find(c => c.conversation_id === currentConversationId)?.title || 'Chat'
                : 'New Chat'
              }
            </h1>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
              title="Toggle chat history"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </button>
          </div>
        </div>

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
                    className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${
                      message.role === 'user'
                        ? 'bg-gradient-to-br from-blue-500 to-blue-600 text-white'
                        : 'bg-gradient-to-br from-purple-500 to-purple-600 text-white'
                    }`}
                  >
                    {message.role === 'user' ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
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
                <div className="w-16 h-16 mx-auto mb-3 rounded-2xl bg-gradient-to-br from-purple-500 to-purple-600 flex items-center justify-center">
                  <Bot className="w-10 h-10 text-white" />
                </div>
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
                  <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-purple-600 flex items-center justify-center text-white">
                    <Bot className="w-5 h-5" />
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
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Sending</span>
                  </span>
                ) : (
                  <span className="flex items-center space-x-1.5">
                    <span>Send</span>
                    <Send className="w-4 h-4" />
                  </span>
                )}
              </button>
            </form>

            {/* Quick Actions */}
            <div className="mt-2.5 flex flex-wrap gap-2 items-center">
              <button
                onClick={() => setInput('Classify HSIL and LSIL cervical cancer samples using deep learning')}
                className="px-2.5 py-1 text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded-md hover:bg-purple-100 transition-colors flex items-center gap-1"
                disabled={isLoading}
              >
                <Lightbulb className="w-3.5 h-3.5" />
                Cervical Cancer Classification
              </button>
              <button
                onClick={() => setInput('Analyze lung cancer pathology slides (LUAD vs LUSC vs Normal)')}
                className="px-2.5 py-1 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-md hover:bg-blue-100 transition-colors flex items-center gap-1"
                disabled={isLoading}
              >
                <Lightbulb className="w-3.5 h-3.5" />
                Lung Cancer Analysis
              </button>
              <button
                onClick={() => setInput('Train a model to detect tumor regions in breast cancer slides')}
                className="px-2.5 py-1 text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-md hover:bg-green-100 transition-colors flex items-center gap-1"
                disabled={isLoading}
              >
                <Lightbulb className="w-3.5 h-3.5" />
                Breast Cancer Detection
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

      {/* Chat History Sidebar - Right Side */}
      {showHistory && (
        <>
          {/* Overlay for mobile */}
          <div
            className="fixed inset-0 bg-black bg-opacity-50 z-40 lg:hidden"
            onClick={() => setShowHistory(false)}
          />

          {/* Sidebar */}
          <div className="fixed lg:relative inset-y-0 right-0 w-80 bg-white border-l border-gray-200 z-50 flex flex-col">
            {/* Sidebar Header */}
            <div className="p-4 border-b border-gray-200">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-lg font-semibold text-gray-900">Chat History</h2>
                <button
                  onClick={() => setShowHistory(false)}
                  className="lg:hidden p-1 text-gray-500 hover:text-gray-700 rounded"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <button
                onClick={handleNewChat}
                className="w-full px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white text-sm font-medium rounded-lg hover:from-blue-700 hover:to-blue-800 transition-all shadow-sm flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                </svg>
                New Chat
              </button>
            </div>

            {/* Conversations List */}
            <div className="flex-1 overflow-y-auto p-2">
              {isLoadingConversations ? (
                <div className="flex items-center justify-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                </div>
              ) : conversations.length === 0 ? (
                <div className="text-center py-8 text-gray-500 text-sm">
                  No conversations yet
                </div>
              ) : (
                <div className="space-y-1">
                  {conversations.map((conv) => (
                    <div
                      key={conv.conversation_id}
                      onClick={() => handleLoadConversation(conv.conversation_id)}
                      className={`group relative p-3 rounded-lg cursor-pointer transition-colors ${
                        currentConversationId === conv.conversation_id
                          ? 'bg-blue-50 border border-blue-200'
                          : 'hover:bg-gray-50 border border-transparent'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <h3 className="text-sm font-medium text-gray-900 truncate">
                            {conv.title}
                          </h3>
                          <p className="text-xs text-gray-500 mt-1">
                            {new Date(conv.updated_at).toLocaleDateString()}
                          </p>
                        </div>
                        <button
                          onClick={(e) => handleDeleteConversation(conv.conversation_id, e)}
                          className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-red-600 transition-opacity"
                          title="Delete conversation"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}

