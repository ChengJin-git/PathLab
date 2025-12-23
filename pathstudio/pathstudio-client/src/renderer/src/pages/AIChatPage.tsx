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
import { Lightbulb, Send, Loader2, Bot, User, Sparkles, MessageSquare, Trash2, Plus, Clock } from 'lucide-react'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

const WELCOME_MESSAGE: Message = {
  id: '1',
  role: 'assistant',
  content: 'Hello! I\'m PathStudio Agent. You can describe your research task in natural language, and I\'ll help you set it up. For example:\n\n"I want to classify HSIL and LSIL cervical cancer samples using deep learning"\n\nWhat would you like to research today?',
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
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
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
    setDeleteConfirmId(conversationId)
  }

  const confirmDelete = async () => {
    if (!deleteConfirmId) return

    try {
      await deleteConversation(deleteConfirmId)
      await loadConversations()
      if (currentConversationId === deleteConfirmId) {
        handleNewChat()
      }
    } catch (error) {
      console.error('Failed to delete conversation:', error)
    } finally {
      setDeleteConfirmId(null)
    }
  }

  const cancelDelete = () => {
    setDeleteConfirmId(null)
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
      }, conversationId || undefined) // Pass conversation_id to save messages
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
        <div className="flex-shrink-0 bg-gradient-to-r from-white via-purple-50/30 to-white border-b border-gray-200 px-4 py-3 shadow-sm">
          <div className="max-w-4xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-pink-500 flex items-center justify-center shadow-md">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <h1 className="text-base font-semibold text-gray-900 leading-tight">
                {currentConversationId
                  ? conversations.find(c => c.conversation_id === currentConversationId)?.title || 'Chat'
                  : 'New Conversation'
                }
              </h1>
            </div>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className={`p-2.5 rounded-xl transition-all ${
                showHistory
                  ? 'bg-blue-100 text-blue-700 shadow-inner'
                  : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100 shadow-sm'
              }`}
              title="Toggle chat history"
            >
              <MessageSquare className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Messages Container */}
        <div className="flex-1 overflow-y-auto px-4 py-6 min-h-0">
          <div className="max-w-4xl mx-auto space-y-6">
            {messages.map((message) => (
              <div
                key={message.id}
                className={`flex gap-3 ${message.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}
              >
                {/* Avatar */}
                <div className="flex-shrink-0">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center shadow-md ${
                      message.role === 'user'
                        ? 'bg-gradient-to-br from-blue-500 to-blue-600'
                        : 'bg-gradient-to-br from-purple-500 via-purple-600 to-pink-500'
                    }`}
                  >
                    {message.role === 'user' ? (
                      <User className="w-5 h-5 text-white" />
                    ) : (
                      <Bot className="w-5 h-5 text-white" />
                    )}
                  </div>
                </div>

                {/* Message Content */}
                <div className={`flex-1 min-w-0 max-w-[85%] ${message.role === 'user' ? 'items-end' : 'items-start'} flex flex-col`}>
                  {/* Role Label */}
                  <div className={`text-xs font-medium mb-1.5 px-1 ${
                    message.role === 'user' ? 'text-blue-700' : 'text-purple-700'
                  }`}>
                    {message.role === 'user' ? 'You' : 'PathStudio Agent'}
                  </div>

                  {/* Message Bubble */}
                  <div
                    className={`rounded-2xl px-4 py-3 ${
                      message.role === 'user'
                        ? 'bg-gradient-to-br from-blue-500 to-blue-600 text-white shadow-lg shadow-blue-500/30'
                        : 'bg-white border border-gray-200 text-gray-900 shadow-md'
                    }`}
                  >
                    {message.role === 'user' ? (
                      <div className="text-[15px] leading-relaxed whitespace-pre-wrap break-words">
                        {message.content}
                      </div>
                    ) : message.content === '' ? (
                      // Show thinking animation for empty assistant messages
                      <div className="flex items-center gap-2">
                        <div className="w-2.5 h-2.5 bg-purple-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                        <div className="w-2.5 h-2.5 bg-purple-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                        <div className="w-2.5 h-2.5 bg-purple-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
                        <span className="text-sm text-gray-500 ml-2">Thinking...</span>
                      </div>
                    ) : (
                      <div className="prose prose-sm max-w-none
                        prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold
                        prose-p:my-2 prose-p:leading-relaxed
                        prose-ul:my-2 prose-ol:my-2 prose-li:my-1
                        prose-code:bg-purple-50 prose-code:text-purple-900 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-mono
                        prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:rounded-lg prose-pre:shadow-inner
                        prose-strong:text-gray-900 prose-strong:font-semibold
                        prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>

                  {/* Timestamp */}
                  <div className={`text-xs text-gray-500 mt-1.5 px-1 flex items-center gap-1 ${
                    message.role === 'user' ? 'justify-end' : 'justify-start'
                  }`}>
                    <Clock className="w-3 h-3" />
                    {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </div>
                </div>
              </div>
            ))}

            {/* Welcome Message */}
            {messages.length === 0 && !isLoading && (
              <div className="flex items-center justify-center min-h-[60vh]">
                <div className="text-center max-w-2xl px-4">
                  {/* Animated Icon */}
                  <div className="relative inline-block mb-6">
                    <div className="absolute inset-0 bg-gradient-to-br from-purple-400 to-pink-400 rounded-3xl blur-2xl opacity-30 animate-pulse"></div>
                    <div className="relative w-20 h-20 mx-auto rounded-3xl bg-gradient-to-br from-purple-500 via-purple-600 to-pink-500 flex items-center justify-center shadow-2xl">
                      <Sparkles className="w-10 h-10 text-white" />
                    </div>
                  </div>

                  <h2 className="text-3xl font-bold text-gray-900 mb-3">
                    Welcome to PathStudio Agent
                  </h2>
                  <p className="text-base text-gray-600 mb-8 leading-relaxed">
                    Describe your research task in natural language, and I'll help you set it up with the right configuration.
                  </p>

                  {/* Example Cards */}
                  <div className="grid gap-3 mb-6">
                    <div className="bg-gradient-to-r from-blue-50 to-purple-50 border border-blue-200 rounded-xl p-4 text-left hover:shadow-md transition-shadow cursor-pointer group"
                         onClick={() => setInput('Classify HSIL and LSIL cervical cancer samples using deep learning')}>
                      <div className="flex items-start gap-3">
                        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center">
                          <Lightbulb className="w-4 h-4 text-white" />
                        </div>
                        <div className="flex-1">
                          <p className="text-sm font-medium text-gray-900 mb-1">Cervical Cancer Classification</p>
                          <p className="text-xs text-gray-600 italic">
                            "Classify HSIL and LSIL cervical cancer samples using deep learning"
                          </p>
                        </div>
                      </div>
                    </div>

                    <div className="bg-gradient-to-r from-green-50 to-teal-50 border border-green-200 rounded-xl p-4 text-left hover:shadow-md transition-shadow cursor-pointer group"
                         onClick={() => setInput('Analyze lung cancer pathology slides (LUAD vs LUSC vs Normal)')}>
                      <div className="flex items-start gap-3">
                        <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-green-500 flex items-center justify-center">
                          <Lightbulb className="w-4 h-4 text-white" />
                        </div>
                        <div className="flex-1">
                          <p className="text-sm font-medium text-gray-900 mb-1">Lung Cancer Analysis</p>
                          <p className="text-xs text-gray-600 italic">
                            "Analyze lung cancer pathology slides (LUAD vs LUSC vs Normal)"
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>

                  <p className="text-xs text-gray-500">
                    💡 Click an example above or type your own research task below
                  </p>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input Area */}
        <div className="flex-shrink-0 bg-gradient-to-t from-gray-50 to-white border-t border-gray-200 px-4 py-4">
          <div className="max-w-4xl mx-auto">
            {/* Quick Actions - Moved to top */}
            <div className="mb-3 flex flex-wrap gap-2 items-center">
              <span className="text-xs font-medium text-gray-500">Quick start:</span>
              <button
                onClick={() => setInput('Classify HSIL and LSIL cervical cancer samples using deep learning')}
                className="px-3 py-1.5 text-xs font-medium text-purple-700 bg-purple-50 border border-purple-200 rounded-full hover:bg-purple-100 hover:shadow-sm transition-all flex items-center gap-1.5"
                disabled={isLoading}
              >
                <Lightbulb className="w-3.5 h-3.5" />
                Cervical Cancer
              </button>
              <button
                onClick={() => setInput('Analyze lung cancer pathology slides (LUAD vs LUSC vs Normal)')}
                className="px-3 py-1.5 text-xs font-medium text-blue-700 bg-blue-50 border border-blue-200 rounded-full hover:bg-blue-100 hover:shadow-sm transition-all flex items-center gap-1.5"
                disabled={isLoading}
              >
                <Lightbulb className="w-3.5 h-3.5" />
                Lung Cancer
              </button>
              <button
                onClick={() => setInput('Train a model to detect tumor regions in breast cancer slides')}
                className="px-3 py-1.5 text-xs font-medium text-green-700 bg-green-50 border border-green-200 rounded-full hover:bg-green-100 hover:shadow-sm transition-all flex items-center gap-1.5"
                disabled={isLoading}
              >
                <Lightbulb className="w-3.5 h-3.5" />
                Breast Cancer
              </button>

              {/* Divider */}
              <div className="h-4 w-px bg-gray-300 mx-1"></div>

              {/* Link to structured setup */}
              <Link
                to="/task-setup"
                className="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-300 rounded-full hover:bg-gray-50 hover:shadow-sm transition-all flex items-center gap-1.5"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                <span>Step-by-step setup</span>
              </Link>
            </div>

            {/* Input Form */}
            <form onSubmit={handleSubmit} className="relative">
              <div className="relative flex items-end gap-2 bg-white rounded-2xl border-2 border-gray-200 shadow-lg focus-within:border-blue-400 focus-within:shadow-xl transition-all">
                <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Describe your research task... (Press Enter to send, Shift+Enter for new line)"
                  className="flex-1 px-4 py-3.5 text-[15px] bg-transparent border-none focus:outline-none resize-none text-gray-900 placeholder-gray-400 leading-relaxed"
                  rows={1}
                  style={{ maxHeight: '150px' }}
                  disabled={isLoading}
                />
                <button
                  type="submit"
                  disabled={!input.trim() || isLoading}
                  className="flex-shrink-0 m-2 p-3 bg-gradient-to-br from-blue-500 to-blue-600 text-white rounded-xl hover:from-blue-600 hover:to-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:from-gray-300 disabled:to-gray-400 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg disabled:shadow-none"
                  title={isLoading ? 'Sending...' : 'Send message'}
                >
                  {isLoading ? (
                    <Loader2 className="w-5 h-5 animate-spin" />
                  ) : (
                    <Send className="w-5 h-5" />
                  )}
                </button>
              </div>

              {/* Helper Text */}
              <div className="mt-2 px-1 flex items-center justify-between text-xs text-gray-500">
                <span>💡 Tip: Be specific about your research goals and data types</span>
                <span className={input.length > 500 ? 'text-orange-600 font-medium' : ''}>
                  {input.length > 0 && `${input.length} characters`}
                </span>
              </div>
            </form>
          </div>
        </div>
      </div>

      {/* Chat History Sidebar - Right Side */}
      {showHistory && (
        <>
          {/* Overlay for mobile */}
          <div
            className="fixed inset-0 bg-black bg-opacity-50 z-40 lg:hidden backdrop-blur-sm"
            onClick={() => setShowHistory(false)}
          />

          {/* Sidebar */}
          <div className="fixed lg:relative inset-y-0 right-0 w-80 bg-white border-l border-gray-200 z-50 flex flex-col shadow-2xl lg:shadow-none">
            {/* Sidebar Header */}
            <div className="p-4 border-b border-gray-200 bg-gradient-to-br from-gray-50 to-white">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-purple-600" />
                  <h2 className="text-lg font-semibold text-gray-900">History</h2>
                </div>
                <button
                  onClick={() => setShowHistory(false)}
                  className="lg:hidden p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <button
                onClick={handleNewChat}
                className="w-full px-4 py-2.5 bg-gradient-to-r from-blue-500 to-blue-600 text-white text-sm font-medium rounded-xl hover:from-blue-600 hover:to-blue-700 transition-all shadow-md hover:shadow-lg flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                New Conversation
              </button>
            </div>

            {/* Conversations List */}
            <div className="flex-1 overflow-y-auto p-3">
              {isLoadingConversations ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <div className="animate-spin rounded-full h-10 w-10 border-3 border-blue-200 border-t-blue-600 mb-3"></div>
                  <p className="text-sm text-gray-500">Loading conversations...</p>
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-3">
                    <MessageSquare className="w-8 h-8 text-gray-400" />
                  </div>
                  <p className="text-sm font-medium text-gray-900 mb-1">No conversations yet</p>
                  <p className="text-xs text-gray-500">Start a new chat to begin</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {conversations.map((conv) => (
                    <div
                      key={conv.conversation_id}
                      onClick={() => handleLoadConversation(conv.conversation_id)}
                      className={`group relative p-3 rounded-xl cursor-pointer transition-all ${
                        currentConversationId === conv.conversation_id
                          ? 'bg-gradient-to-br from-blue-50 to-purple-50 border-2 border-blue-300 shadow-md'
                          : 'hover:bg-gray-50 border-2 border-transparent hover:border-gray-200'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <MessageSquare className={`w-3.5 h-3.5 flex-shrink-0 ${
                              currentConversationId === conv.conversation_id ? 'text-blue-600' : 'text-gray-400'
                            }`} />
                            <h3 className={`text-sm font-medium truncate ${
                              currentConversationId === conv.conversation_id ? 'text-blue-900' : 'text-gray-900'
                            }`}>
                              {conv.title}
                            </h3>
                          </div>
                          <div className="flex items-center gap-1 text-xs text-gray-500">
                            <Clock className="w-3 h-3" />
                            {new Date(conv.updated_at).toLocaleDateString([], {
                              month: 'short',
                              day: 'numeric',
                              hour: '2-digit',
                              minute: '2-digit'
                            })}
                          </div>
                        </div>
                        <button
                          onClick={(e) => handleDeleteConversation(conv.conversation_id, e)}
                          className="opacity-0 group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                          title="Delete conversation"
                        >
                          <Trash2 className="w-4 h-4" />
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

      {/* Delete Confirmation Modal */}
      {deleteConfirmId && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 transform transition-all">
            <div className="flex items-start gap-4">
              <div className="flex-shrink-0 w-12 h-12 rounded-full bg-red-100 flex items-center justify-center">
                <Trash2 className="w-6 h-6 text-red-600" />
              </div>
              <div className="flex-1">
                <h3 className="text-lg font-semibold text-gray-900 mb-2">
                  Delete Conversation
                </h3>
                <p className="text-sm text-gray-600 mb-6">
                  Are you sure you want to delete this conversation? This action cannot be undone.
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={cancelDelete}
                    className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={confirmDelete}
                    className="px-4 py-2 text-sm font-medium text-white bg-red-600 hover:bg-red-700 rounded-lg transition-colors shadow-sm"
                  >
                    Delete
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

