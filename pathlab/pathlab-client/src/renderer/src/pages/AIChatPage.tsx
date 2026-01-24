import React, { useState, useRef, useEffect } from 'react'
import { useLocation, Link, useNavigate } from 'react-router-dom'
import {
  chatWithAI,
  getConversations,
  createConversation,
  getConversation,
  deleteConversation,
  transcribeAudio,
  type Conversation
} from '../api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Lightbulb, Send, Loader2, Bot, User, Sparkles, MessageSquare, Trash2, Plus, Clock, ArrowLeft, LayoutGrid, Mic, MicOff } from 'lucide-react'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { AudioVisualizer } from '../components/common/AudioVisualizer'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

const WELCOME_MESSAGE: Message = {
  id: '1',
  role: 'assistant',
  content: 'Hello! I\'m PathLab Agent. You can describe your research task in natural language, and I\'ll help you set it up. For example:\n\n"I want to classify HSIL and LSIL cervical cancer samples using deep learning"\n\nWhat would you like to research today?',
  timestamp: new Date()
}

export default function AIChatPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const [messages, setMessages] = useState<Message[]>([WELCOME_MESSAGE])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [isLoadingConversations, setIsLoadingConversations] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const [hasStartedConversation, setHasStartedConversation] = useState(false)
  const [showWelcomeHero, setShowWelcomeHero] = useState(!(location.state as any)?.fromDashboard)
  const [isRecording, setIsRecording] = useState(false)
  const [recordingStream, setRecordingStream] = useState<MediaStream | null>(null)
  const [isTranscribing, setIsTranscribing] = useState(false)
  const [toastMessage, setToastMessage] = useState<{ type: 'error' | 'success' | 'info'; message: string } | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const initialMessageSent = useRef(false)
  const audioContextRef = useRef<AudioContext | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const pcmChunksRef = useRef<Float32Array[]>([])

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
    const state = location.state as { initialMessage?: string; autoStartRecording?: boolean; fromDashboard?: boolean } | null
    
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

    if (state?.autoStartRecording && !isRecording && !isTranscribing) {
      // Clear the autoStartRecording flag so it doesn't trigger again
      navigate(location.pathname, { replace: true, state: { ...state, autoStartRecording: false } })
      startRecording()
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
    setShowHistory(false)
    setShowWelcomeHero(true)
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
      setHasStartedConversation(true)
      setShowWelcomeHero(false)
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

    setHasStartedConversation(true)
    setShowWelcomeHero(false)

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

  // Toast helper function
  const showToast = (type: 'error' | 'success' | 'info', message: string) => {
    setToastMessage({ type, message })
    setTimeout(() => setToastMessage(null), 5000)
  }

  // Voice recording functions using Web Audio API for PCM output
  const startRecording = async () => {
    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        console.error('MediaDevices API not available')
        showToast('error', 'Voice input is not available. Please check browser permissions.')
        return
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        }
      })

      // Use Web Audio API to get raw PCM data
      const audioContext = new AudioContext({ sampleRate: 16000 })
      const source = audioContext.createMediaStreamSource(stream)
      const processor = audioContext.createScriptProcessor(4096, 1, 1)

      pcmChunksRef.current = []

      processor.onaudioprocess = (event) => {
        const inputData = event.inputBuffer.getChannelData(0)
        // Clone the data since the buffer will be reused
        pcmChunksRef.current.push(new Float32Array(inputData))
      }

      source.connect(processor)
      processor.connect(audioContext.destination)

      audioContextRef.current = audioContext
      mediaStreamRef.current = stream
      setRecordingStream(stream)
      processorRef.current = processor
      setIsRecording(true)
    } catch (error) {
      console.error('Failed to start recording:', error)
      showToast('error', 'Failed to start recording. Please check microphone permissions.')
    }
  }

  const stopRecording = async () => {
    if (!isRecording) return

    // Stop recording
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    if (audioContextRef.current) {
      await audioContextRef.current.close()
      audioContextRef.current = null
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop())
      mediaStreamRef.current = null
    }

    setRecordingStream(null)
    setIsRecording(false)

    // Convert Float32Array chunks to Int16 PCM
    const totalLength = pcmChunksRef.current.reduce((acc, chunk) => acc + chunk.length, 0)
    if (totalLength === 0) return

    const pcmData = new Int16Array(totalLength)
    let offset = 0
    for (const chunk of pcmChunksRef.current) {
      for (let i = 0; i < chunk.length; i++) {
        // Convert float32 [-1, 1] to int16 [-32768, 32767]
        const s = Math.max(-1, Math.min(1, chunk[i]))
        pcmData[offset++] = s < 0 ? s * 0x8000 : s * 0x7FFF
      }
    }
    pcmChunksRef.current = []

    // Create blob from PCM data
    const audioBlob = new Blob([pcmData.buffer], { type: 'audio/pcm' })

    if (audioBlob.size > 0) {
      setIsTranscribing(true)
      try {
        const result = await transcribeAudio(audioBlob)
        if (result.success && result.text) {
          setInput(prev => prev + (prev ? ' ' : '') + result.text)
        } else if (result.error) {
          console.error('Transcription error:', result.error)
          showToast('error', `Transcription failed: ${result.error}`)
        }
      } catch (error) {
        console.error('Failed to transcribe audio:', error)
        showToast('error', 'Transcription request failed. Please check your connection and API key.')
      } finally {
        setIsTranscribing(false)
      }
    }
  }

  const toggleRecording = () => {
    if (isRecording) {
      stopRecording()
    } else {
      startRecording()
    }
  }

  return (
    <div className="flex h-full bg-gray-50 relative overflow-hidden">
      {/* Messages Container (Background for chat) */}
      <div className="absolute inset-0 flex flex-col z-10">
        {/* Top Bar with History Toggle */}
        <div className="flex-shrink-0 bg-white/80 backdrop-blur-md border-b border-gray-200 px-4 py-3 shadow-sm z-20">
          <div className="max-w-4xl mx-auto flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary-100 flex items-center justify-center shadow-md">
                <Bot className="w-5 h-5 text-primary-600" />
              </div>
              <h1 className="text-base font-semibold text-gray-900 leading-tight">
                {currentConversationId
                  ? conversations.find(c => c.conversation_id === currentConversationId)?.title || 'Chat'
                  : 'New Research Task'
                }
              </h1>
            </div>
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                onClick={() => navigate('/dashboard')}
                className="gap-2 text-sm font-normal"
              >
                <ArrowLeft className="w-4 h-4" />
                Back to Dashboard
              </Button>
              <button
                onClick={() => setShowHistory(!showHistory)}
                className={`p-2.5 rounded-xl transition-all ${
                  showHistory
                    ? 'bg-primary-50 text-primary-700 shadow-inner'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100 shadow-sm'
                }`}
                title="Toggle chat history"
              >
                <MessageSquare className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-4 py-6 min-h-0 pb-32">
          <div className="max-w-4xl mx-auto space-y-6">
            {messages.length <= 1 && showWelcomeHero && (
                <div className="flex flex-col items-center justify-center py-20 text-center space-y-4">
                    <div className="w-16 h-16 rounded-2xl bg-primary-100 flex items-center justify-center shadow-lg mb-2">
                        <Bot className="w-10 h-10 text-primary-600" />
                    </div>
                    <h2 className="text-2xl font-bold text-gray-900">How can I help you today?</h2>
                    <p className="text-gray-500 max-w-md">I can help you classify tumors, segment cells, or analyze WSI patterns with deep learning.</p>
                </div>
            )}
            {messages.map((message) => {
                if (message.id === '1') return null; // Skip welcome message in chat flow if we want cleaner look
                return (
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
                        : 'bg-primary-100 border-primary-200'
                    }`}
                  >
                    {message.role === 'user' ? (
                      <User className="w-5 h-5 text-gray-600" />
                    ) : (
                      <Bot className="w-5 h-5 text-primary-600" />
                    )}
                  </div>
                </div>

                {/* Message Content */}
                <div className={`flex-1 min-w-0 max-w-[85%] flex flex-col ${message.role === 'user' ? 'items-end' : 'items-start'}`}>
                  {/* Message Bubble */}
                  <div
                    className={`relative px-5 py-3.5 text-[15px] leading-7 ${
                      message.role === 'user'
                        ? 'bg-[#f4f4f4] text-gray-900 rounded-3xl rounded-tr-sm'
                        : 'bg-transparent text-gray-900 px-0 py-0'
                    }`}
                  >
                    {message.role === 'user' ? (
                      <div className="whitespace-pre-wrap break-words">
                        {message.content}
                      </div>
                    ) : message.content === '' ? (
                      // ChatGPT-like Thinking Indicator
                      <div className="flex items-center gap-2 py-2">
                        <div className="w-2.5 h-2.5 bg-gray-400 rounded-full animate-pulse"></div>
                        <span className="text-sm font-medium text-gray-500 animate-pulse">Thinking...</span>
                      </div>
                    ) : (
                      <div className="prose prose-slate max-w-none
                        prose-p:my-1.5 prose-p:leading-7
                        prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-gray-900
                        prose-ul:my-2 prose-ul:list-disc prose-ul:pl-4
                        prose-ol:my-2 prose-ol:list-decimal prose-ol:pl-4
                        prose-li:my-0.5
                        prose-code:bg-gray-100 prose-code:text-gray-900 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-xs prose-code:font-mono prose-code:before:content-none prose-code:after:content-none
                        prose-pre:bg-[#0d0d0d] prose-pre:text-gray-50 prose-pre:rounded-xl prose-pre:p-4
                        prose-strong:text-gray-900 prose-strong:font-bold
                        prose-a:text-blue-600 prose-a:no-underline hover:prose-a:underline">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {message.content}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>

                  {/* Timestamp & Actions */}
                  {message.role === 'assistant' && message.content !== '' && (
                     <div className="flex items-center gap-3 mt-2 text-gray-400">
                        <button className="hover:text-gray-600 transition-colors" title="Copy">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        </button>
                        <button className="hover:text-gray-600 transition-colors" title="Regenerate">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"></path><path d="M16 16h5v5"></path></svg>
                        </button>
                     </div>
                  )}
                </div>
              </div>
            )})}
            <div ref={messagesEndRef} />
          </div>
        </div>
      </div>


      {/* Input Area - Permanent position at bottom */}
      <div className="absolute left-1/2 -translate-x-1/2 bottom-8 translate-y-0 w-full max-w-4xl px-4 z-30">
         <form onSubmit={handleSubmit} className="relative group">
            <div className="relative flex items-center bg-white rounded-2xl shadow-xl border border-gray-300 focus-within:ring-2 focus-within:ring-primary-100 focus-within:border-primary-400 h-auto min-h-[60px] pl-4 pr-[100px] py-2 transition-all duration-300">
                 <textarea
                  ref={textareaRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Describe your research task..."
                  className={`w-full bg-transparent border-none focus:outline-none resize-none text-gray-900 placeholder-gray-400 transition-all text-base py-3 ${isRecording ? 'opacity-0' : 'opacity-100'}`}
                  rows={1}
                  style={{ maxHeight: '150px' }}
                  disabled={isLoading}
                  autoFocus
                />

                {/* Full-width Audio Visualizer overlay */}
                {isRecording && (
                    <div className="absolute inset-y-0 left-4 right-[100px] flex items-center justify-center animate-in zoom-in-95 fade-in duration-300 pointer-events-none">
                        <AudioVisualizer stream={recordingStream} isActive={isRecording} className="w-full h-2/3" />
                    </div>
                )}
                
                <div className="absolute right-2 md:right-3 flex items-center gap-1.5 md:gap-2 bottom-2">
                     {/* Voice Input Button */}
                     <button
                         type="button"
                         onClick={toggleRecording}
                         disabled={isLoading || isTranscribing}
                         className={`p-2 md:p-2.5 rounded-xl transition-all shadow-md hover:shadow-lg active:scale-95 ${
                             isRecording
                                 ? 'bg-red-500 text-white animate-pulse hover:bg-red-600'
                                 : isTranscribing
                                     ? 'bg-orange-400 text-white'
                                     : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                         } disabled:opacity-50 disabled:cursor-not-allowed`}
                         title={isRecording ? 'Stop recording' : isTranscribing ? 'Transcribing...' : 'Voice input'}
                     >
                         {isTranscribing ? (
                             <Loader2 className="w-4 h-4 md:w-5 md:h-5 animate-spin" />
                         ) : isRecording ? (
                             <MicOff className="w-4 h-4 md:w-5 md:h-5" />
                         ) : (
                             <Mic className="w-4 h-4 md:w-5 md:h-5" />
                         )}
                     </button>

                    <button
                        type="submit"
                        disabled={!input.trim() || isLoading}
                        className="p-2 md:p-2.5 bg-gray-900 text-white rounded-xl hover:bg-gray-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-900 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed transition-all shadow-md hover:shadow-lg active:scale-95"
                    >
                        {isLoading ? <Loader2 className="w-4 h-4 md:w-5 md:h-5 animate-spin" /> : <Send className="w-4 h-4 md:w-5 md:h-5" />}
                    </button>
                </div>
            </div>
         </form>
         
         <div className="mt-2 text-center text-xs text-gray-400 animate-in fade-in duration-700 delay-500">
            PathLab Agent can make mistakes. Consider checking important information.
         </div>
      </div>

      {/* Chat History Sidebar */}
      {showHistory && (
        <>
          <div
            className="fixed inset-0 bg-black/20 z-40 lg:hidden backdrop-blur-sm transition-opacity"
            onClick={() => setShowHistory(false)}
          />
          <div className="fixed lg:relative inset-y-0 right-0 w-80 bg-white border-l border-gray-200 z-50 flex flex-col shadow-2xl lg:shadow-none animate-in slide-in-from-right duration-300">
            <div className="p-4 border-b border-gray-200">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <MessageSquare className="w-5 h-5 text-gray-500" />
                  <h2 className="text-lg font-semibold text-gray-900">History</h2>
                </div>
                <button
                  onClick={() => setShowHistory(false)}
                  className="lg:hidden p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <ArrowLeft className="w-5 h-5" />
                </button>
              </div>
              <button
                onClick={handleNewChat}
                className="w-full px-4 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-xl hover:bg-gray-800 transition-all shadow-sm flex items-center justify-center gap-2"
              >
                <Plus className="w-4 h-4" />
                New Research Task
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {isLoadingConversations ? (
                <div className="flex flex-col items-center justify-center py-12">
                  <Loader2 className="w-8 h-8 text-primary-500 animate-spin mb-3" />
                  <p className="text-sm text-gray-500">Loading conversations...</p>
                </div>
              ) : conversations.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className="w-16 h-16 rounded-full bg-gray-50 flex items-center justify-center mb-3">
                    <MessageSquare className="w-8 h-8 text-gray-300" />
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
                      className={`group relative p-3 rounded-xl cursor-pointer transition-all border ${
                        currentConversationId === conv.conversation_id
                          ? 'bg-primary-50 border-primary-200 shadow-sm'
                          : 'hover:bg-gray-50 border-transparent hover:border-gray-100'
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1 min-w-0">
                          <h3 className={`text-sm font-medium truncate mb-1 ${
                            currentConversationId === conv.conversation_id ? 'text-primary-900' : 'text-gray-900'
                          }`}>
                            {conv.title}
                          </h3>
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
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6 transform transition-all scale-100">
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

      {/* Toast notification */}
      {toastMessage && (
        <div className={`fixed top-4 right-4 z-50 px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 animate-in slide-in-from-top-2 duration-300 ${
          toastMessage.type === 'error' ? 'bg-red-500 text-white' :
          toastMessage.type === 'success' ? 'bg-green-500 text-white' : 'bg-blue-500 text-white'
        }`}>
          <span>{toastMessage.message}</span>
          <button
            onClick={() => setToastMessage(null)}
            className="ml-2 hover:opacity-80"
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}


