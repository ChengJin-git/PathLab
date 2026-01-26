import React, { useState, useRef, useEffect, useLayoutEffect, useMemo } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  chatWithAI,
  getConversations,
  createConversation,
  getConversation,
  deleteConversation,
  updateMessage,
  addMessage,
  transcribeAudio,
  type Conversation,
  type ChatMessage,
  type ChatMessageContent
} from '../api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import * as XLSX from 'xlsx'
import {
  Send, Loader2, Bot, User, MessageSquare, Trash2, Plus, Clock,
  Mic, MicOff, Paperclip, X, Rocket, Database,
  FlaskConical, Microscope, ArrowLeft, Sparkles, FileSpreadsheet
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { AudioVisualizer } from '../components/common/AudioVisualizer'
import { OptionButtons, parseOptions, removeOptionsBlock } from '../components/chat/OptionButtons'
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from '../components/chat/TaskConfigCard'
import { ImageRecommendationCard, parseImageRecommendation, removeImageRecommendationBlock } from '../components/chat/ImageRecommendationCard'
import { CSVActionCard, parseCSVAction, removeCSVActionBlock } from '../components/chat/CSVActionCard'
import { NavigationCard, parseNavigateBlock, removeNavigateBlock } from '../components/chat/NavigationCard'
import { CSVPreviewCard, parseCSVPreview, removeCSVPreviewBlock } from '../components/chat/CSVPreviewCard'
import { InferenceConfigCard, parseInferenceConfig, removeInferenceConfigBlock } from '../components/chat/InferenceConfigCard'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  images?: string[] // base64 images for display
  timestamp: Date
  csvAttachments?: { fileName: string; content: string }[] // CSV file contents for processing
}

interface ImageAttachment {
  id: string
  file: File
  preview: string // base64 data URL for preview
  base64: string // base64 data for API
}

interface FileAttachment {
  id: string
  file: File
  name: string
  type: 'csv' | 'xlsx'
  content: string // text content for CSV, parsed content for XLSX
  preview: string[] // first few rows for preview
}

// Scenario cards for guided experience
const SCENARIO_CARDS = [
  {
    id: 'start-fresh',
    icon: Rocket,
    title: 'Fresh Start',
    description: 'Begin a new pathology research project',
    prompt: 'I want to start a new pathology research project. Can you help me understand what options I have?',
    color: 'from-blue-500 to-cyan-500',
    bgColor: 'bg-blue-50 hover:bg-blue-100',
    iconColor: 'text-blue-600'
  },
  {
    id: 'train-model',
    icon: Database,
    title: 'Train Model',
    description: 'I have a dataset ready for training',
    prompt: 'I have a dataset of pathology images and want to train a deep learning model. What do I need to configure?',
    color: 'from-purple-500 to-pink-500',
    bgColor: 'bg-purple-50 hover:bg-purple-100',
    iconColor: 'text-purple-600'
  },
  {
    id: 'test-model',
    icon: FlaskConical,
    title: 'Test Model',
    description: 'Run inference with a trained model',
    prompt: 'I have a trained model and want to run inference on new images. How do I proceed?',
    color: 'from-green-500 to-emerald-500',
    bgColor: 'bg-green-50 hover:bg-green-100',
    iconColor: 'text-green-600'
  },
  {
    id: 'browse-images',
    icon: Microscope,
    title: 'Browse Images',
    description: 'Browse and analyze WSI or patches',
    prompt: 'I want to browse and analyze some pathology images (WSI or patches). Can you help me find the right ones based on my needs?',
    color: 'from-orange-500 to-amber-500',
    bgColor: 'bg-orange-50 hover:bg-orange-100',
    iconColor: 'text-orange-600'
  }
]

// Props interface for AssistantMessage component
interface AssistantMessageProps {
  content: string
  messageId: string
  onOptionSelect: (text: string) => void
  onTaskSubmitSuccess: (taskId: string, messageId: string) => void
  onInferenceSubmitSuccess: (taskId: string, messageId: string) => void
  onTaskSubmitError: (error: string) => void
  isStreaming: boolean
  isLoading: boolean
  csvContent?: string
  csvFileName?: string
  onToast: (toast: { type: 'error' | 'success' | 'info'; message: string }) => void
}

// Assistant message component with special markup parsing
// Defined outside of AIChatPage to prevent re-creation on every render
const AssistantMessage = React.memo(function AssistantMessage({
  content,
  messageId,
  onOptionSelect,
  onTaskSubmitSuccess,
  onInferenceSubmitSuccess,
  onTaskSubmitError,
  isStreaming,
  isLoading,
  csvContent,
  csvFileName,
  onToast
}: AssistantMessageProps) {
  // Parse special blocks
  const options = parseOptions(content)
  const taskConfig = parseTaskConfig(content)
  const imageRecommendation = parseImageRecommendation(content)
  const csvAction = parseCSVAction(content)
  const navigateBlock = parseNavigateBlock(content)
  const inferenceConfig = parseInferenceConfig(content)

  // Remove special blocks from display content
  let displayContent = content
  if (options) displayContent = removeOptionsBlock(displayContent)
  if (taskConfig) displayContent = removeTaskConfigBlock(displayContent)
  if (imageRecommendation) displayContent = removeImageRecommendationBlock(displayContent)
  if (csvAction) displayContent = removeCSVActionBlock(displayContent)
  if (navigateBlock) displayContent = removeNavigateBlock(displayContent)
  if (inferenceConfig) displayContent = removeInferenceConfigBlock(displayContent)

  return (
    <div>
      {/* Markdown content */}
      {displayContent.trim() && (
        <div className="prose prose-slate max-w-none prose-sm
          prose-p:my-2 prose-p:leading-relaxed
          prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-gray-900
          prose-ul:my-2 prose-ul:list-disc prose-ul:pl-5
          prose-ol:my-2 prose-ol:list-decimal prose-ol:pl-5
          prose-li:my-1
          prose-code:bg-gray-100 prose-code:text-gray-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-mono prose-code:before:content-none prose-code:after:content-none
          prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:rounded-lg prose-pre:p-4 prose-pre:my-3
          prose-strong:text-gray-900 prose-strong:font-semibold
          prose-a:text-primary-600 prose-a:no-underline hover:prose-a:underline
          prose-hr:border-gray-200 prose-hr:my-4
          prose-table:text-sm prose-th:bg-gray-50 prose-th:px-3 prose-th:py-2 prose-td:px-3 prose-td:py-2 prose-td:border-gray-200">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {displayContent}
          </ReactMarkdown>
        </div>
      )}

      {/* Option buttons */}
      {options && !isStreaming && (
        <OptionButtons
          options={options}
          onSelect={onOptionSelect}
          disabled={isLoading}
        />
      )}

      {/* Task config card */}
      {taskConfig && !isStreaming && (
        <TaskConfigCard
          config={taskConfig}
          onSubmitSuccess={(taskId) => onTaskSubmitSuccess(taskId, messageId)}
          onSubmitError={onTaskSubmitError}
        />
      )}

      {/* Inference config card */}
      {inferenceConfig && !isStreaming && (
        <InferenceConfigCard
          config={inferenceConfig}
          onSubmitSuccess={(taskId) => onInferenceSubmitSuccess(taskId, messageId)}
          onSubmitError={onTaskSubmitError}
        />
      )}

      {/* Image recommendation card */}
      {imageRecommendation && !isStreaming && (
        <ImageRecommendationCard recommendation={imageRecommendation} />
      )}

      {/* CSV action card */}
      {csvAction && !isStreaming && csvContent && csvFileName && (
        <CSVActionCard
          config={csvAction}
          csvContent={csvContent}
          fileName={csvFileName}
          onSuccess={() => {
            onToast({ type: 'success', message: 'CSV uploaded successfully!' })
          }}
          onError={(error) => {
            onToast({ type: 'error', message: error })
          }}
        />
      )}

      {/* Navigation card (for guiding to registration page) */}
      {navigateBlock && !isStreaming && (
        <NavigationCard
          config={navigateBlock}
          csvContent={csvContent}
          csvFileName={csvFileName}
        />
      )}
    </div>
  )
})

export default function AIChatPage() {
  const navigate = useNavigate()
  const location = useLocation()

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [imageAttachments, setImageAttachments] = useState<ImageAttachment[]>([])
  const [fileAttachments, setFileAttachments] = useState<FileAttachment[]>([])

  // Conversation management
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [isLoadingConversations, setIsLoadingConversations] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)

  // UI state
  const [showWelcomeHero, setShowWelcomeHero] = useState(true)
  const [toastMessage, setToastMessage] = useState<{ type: 'error' | 'success' | 'info'; message: string } | null>(null)

  // Voice recording state
  const [isRecording, setIsRecording] = useState(false)
  const [recordingStream, setRecordingStream] = useState<MediaStream | null>(null)
  const [isTranscribing, setIsTranscribing] = useState(false)

  // Refs
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const initialMessageSent = useRef(false)
  const audioContextRef = useRef<AudioContext | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const pcmChunksRef = useRef<Float32Array[]>([])

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Pre-compute CSV content mapping: assistant message ID -> most recent CSV from any previous user message
  // Uses O(n) single pass: track the most recent CSV as we iterate forward
  const csvContentMap = useMemo(() => {
    const map = new Map<string, { content: string; fileName: string }>()
    let lastCSV: { content: string; fileName: string } | null = null

    for (const msg of messages) {
      if (msg.role === 'user' && msg.csvAttachments?.length) {
        // Update the most recent CSV
        const csv = msg.csvAttachments[0]
        lastCSV = { content: csv.content, fileName: csv.fileName }
      } else if (msg.role === 'assistant' && lastCSV) {
        // Associate this assistant message with the most recent CSV
        map.set(msg.id, lastCSV)
      }
    }
    return map
  }, [messages])

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  // Use useLayoutEffect for textarea resize to prevent visual jitter
  // This runs synchronously after DOM updates but before browser paint
  useLayoutEffect(() => {
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
    setMessages([])
    setCurrentConversationId(null)
    setInput('')
    setImageAttachments([])
    setFileAttachments([])
    setShowHistory(false)
    setShowWelcomeHero(true)
  }

  const handleLoadConversation = async (conversationId: string) => {
    try {
      const conv = await getConversation(conversationId)
      const loadedMessages: Message[] = conv.messages.map(msg => ({
        id: String(msg.id),
        role: msg.role as 'user' | 'assistant',
        content: msg.content,
        timestamp: new Date(msg.created_at)
      }))
      setMessages(loadedMessages)
      setCurrentConversationId(conversationId)
      setShowHistory(false)
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

  // File upload handlers (images, CSV, XLSX)
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files) return

    const newImageAttachments: ImageAttachment[] = []
    const newFileAttachments: FileAttachment[] = []

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const fileName = file.name.toLowerCase()

      // Handle image files
      if (file.type.startsWith('image/')) {
        const base64 = await new Promise<string>((resolve) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result as string)
          reader.readAsDataURL(file)
        })

        newImageAttachments.push({
          id: `${Date.now()}-${i}`,
          file,
          preview: base64,
          base64
        })
      }
      // Handle CSV files
      else if (fileName.endsWith('.csv') || file.type === 'text/csv') {
        const content = await new Promise<string>((resolve) => {
          const reader = new FileReader()
          reader.onload = () => resolve(reader.result as string)
          reader.readAsText(file)
        })

        // Parse CSV to get preview (first 5 rows)
        const lines = content.split('\n').filter(line => line.trim())
        const preview = lines.slice(0, 6) // Header + 5 data rows

        newFileAttachments.push({
          id: `${Date.now()}-${i}`,
          file,
          name: file.name,
          type: 'csv',
          content,
          preview
        })
      }
      // Handle XLSX files - parse and convert to CSV
      else if (fileName.endsWith('.xlsx') || fileName.endsWith('.xls') ||
               file.type === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' ||
               file.type === 'application/vnd.ms-excel') {
        try {
          const arrayBuffer = await file.arrayBuffer()
          const workbook = XLSX.read(arrayBuffer, { type: 'array' })

          // Check for multiple sheets - if so, we'll note it for the agent to reject
          const sheetNames = workbook.SheetNames
          if (sheetNames.length > 1) {
            // Multiple sheets - let agent know to reject
            newFileAttachments.push({
              id: `${Date.now()}-${i}`,
              file,
              name: file.name,
              type: 'xlsx',
              content: `__MULTIPLE_SHEETS__:${sheetNames.join(',')}`,
              preview: [
                `Excel file has ${sheetNames.length} sheets:`,
                ...sheetNames.slice(0, 5).map(s => `  • ${s}`),
                sheetNames.length > 5 ? `  ... and ${sheetNames.length - 5} more` : ''
              ].filter(Boolean)
            })
          } else {
            // Single sheet - convert to CSV
            const worksheet = workbook.Sheets[sheetNames[0]]
            const csvContent = XLSX.utils.sheet_to_csv(worksheet)

            // Parse CSV to get preview (first 5 rows)
            const lines = csvContent.split('\n').filter(line => line.trim())
            const preview = lines.slice(0, 6) // Header + 5 data rows

            newFileAttachments.push({
              id: `${Date.now()}-${i}`,
              file,
              name: file.name,
              type: 'xlsx', // Keep as xlsx to indicate original format
              content: csvContent, // Store as CSV content
              preview
            })
          }
        } catch (error) {
          console.error('Failed to parse XLSX file:', error)
          newFileAttachments.push({
            id: `${Date.now()}-${i}`,
            file,
            name: file.name,
            type: 'xlsx',
            content: `__PARSE_ERROR__:${error instanceof Error ? error.message : 'Unknown error'}`,
            preview: [`Failed to parse Excel file: ${file.name}`]
          })
        }
      }
    }

    if (newImageAttachments.length > 0) {
      setImageAttachments(prev => [...prev, ...newImageAttachments])
    }
    if (newFileAttachments.length > 0) {
      setFileAttachments(prev => [...prev, ...newFileAttachments])
    }

    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleImageRemove = (id: string) => {
    setImageAttachments(prev => prev.filter(img => img.id !== id))
  }

  const handleFileRemove = (id: string) => {
    setFileAttachments(prev => prev.filter(f => f.id !== id))
  }

  const handleScenarioCardClick = (card: typeof SCENARIO_CARDS[number]) => {
    setInput(card.prompt)
    setShowWelcomeHero(false)
    // Focus the textarea
    setTimeout(() => textareaRef.current?.focus(), 100)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if ((!input.trim() && imageAttachments.length === 0 && fileAttachments.length === 0) || isLoading) return

    // Build user message content with optional file info
    let messageContent = input.trim()

    // Append file attachment info to message content for AI to analyze
    if (fileAttachments.length > 0) {
      const fileInfos = fileAttachments.map(f => {
        // Check for special error/warning markers in XLSX content
        if (f.type === 'xlsx' && f.content.startsWith('__MULTIPLE_SHEETS__:')) {
          const sheets = f.content.replace('__MULTIPLE_SHEETS__:', '')
          return `\n\n📎 **Uploaded Excel: ${f.name}**\n **Warning: This file has multiple sheets (${sheets})**\nPlease save only the data sheet as a separate CSV file and re-upload.`
        } else if (f.type === 'xlsx' && f.content.startsWith('__PARSE_ERROR__:')) {
          const error = f.content.replace('__PARSE_ERROR__:', '')
          return `\n\n📎 **Uploaded Excel: ${f.name}**\n **Error: Failed to parse file** - ${error}`
        } else {
          // Both CSV and successfully parsed XLSX (converted to CSV)
          // Use [CSV_PREVIEW] block for beautiful rendering
          const totalRows = f.content.split('\n').filter(line => line.trim()).length
          const previewData = {
            fileName: f.name,
            fileType: f.type,
            preview: f.preview,
            totalRows: totalRows
          }
          return `\n\n[CSV_PREVIEW]${JSON.stringify(previewData)}[/CSV_PREVIEW]`
        }
      }).join('')
      messageContent += fileInfos
    }

    // Build user message with optional images and CSV attachments
    // Include both CSV files and successfully parsed XLSX files (which now contain CSV content)
    const currentImages = imageAttachments.map(img => img.base64)
    const csvAttachments = fileAttachments
      .filter(f => {
        // Include CSV files and XLSX files that were successfully converted (no error markers)
        if (f.type === 'csv') return true
        if (f.type === 'xlsx' && !f.content.startsWith('__MULTIPLE_SHEETS__:') && !f.content.startsWith('__PARSE_ERROR__:')) return true
        return false
      })
      .map(f => ({ fileName: f.name, content: f.content }))
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageContent,
      images: currentImages.length > 0 ? currentImages : undefined,
      csvAttachments: csvAttachments.length > 0 ? csvAttachments : undefined,
      timestamp: new Date()
    }

    setShowWelcomeHero(false)
    setMessages(prev => [...prev, userMessage])
    setInput('')
    setImageAttachments([]) // Clear attachments after sending
    setFileAttachments([]) // Clear file attachments after sending

    // Create a new conversation if this is the first user message
    let conversationId = currentConversationId
    if (!conversationId && messages.length === 0) {
      try {
        // Generate title from first message (truncate if too long)
        const title = userMessage.content.length > 50
          ? userMessage.content.substring(0, 50) + '...'
          : userMessage.content || 'Image Analysis'
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
      // Build chat messages for API (with multimodal support)
      const chatMessages: ChatMessage[] = messages
        .concat([userMessage])
        .map(m => {
          // If message has images, use multimodal format
          if (m.images && m.images.length > 0) {
            const content: ChatMessageContent = [
              { type: 'text' as const, text: m.content },
              ...m.images.map(imgBase64 => ({
                type: 'image_url' as const,
                image_url: { url: imgBase64 }
              }))
            ]
            return { role: m.role, content }
          }
          // Text-only message
          return { role: m.role, content: m.content }
        })

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
      }, conversationId || undefined, (messageId) => {
        // Update the AI message ID to the backend ID for proper persistence
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, id: String(messageId) }
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

  // Toast helper function
  const showToast = (type: 'error' | 'success' | 'info', message: string) => {
    setToastMessage({ type, message })
    setTimeout(() => setToastMessage(null), 5000)
  }

  // Copy message content to clipboard
  const handleCopy = async (content: string) => {
    try {
      await navigator.clipboard.writeText(content)
      showToast('success', 'Copied to clipboard')
    } catch (error) {
      console.error('Failed to copy:', error)
      showToast('error', 'Failed to copy to clipboard')
    }
  }

  // Regenerate AI response for a specific message
  const handleRegenerate = async (messageIndex: number) => {
    if (isLoading) return

    // Find the user message that prompted this response
    const userMessageIndex = messageIndex - 1
    if (userMessageIndex < 0 || messages[userMessageIndex].role !== 'user') {
      showToast('error', 'Cannot regenerate: no user message found')
      return
    }

    // Remove the current assistant message and keep messages up to (not including) it
    const newMessages = messages.slice(0, messageIndex)
    setMessages(newMessages)

    // Create a new placeholder for streaming
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
      // Build chat messages for API (with multimodal support)
      const chatMessages: ChatMessage[] = newMessages.map(m => {
        if (m.images && m.images.length > 0) {
          const content: ChatMessageContent = [
            { type: 'text' as const, text: m.content },
            ...m.images.map(imgBase64 => ({
              type: 'image_url' as const,
              image_url: { url: imgBase64 }
            }))
          ]
          return { role: m.role, content }
        }
        return { role: m.role, content: m.content }
      })

      let hasReceivedContent = false
      await chatWithAI(chatMessages, (chunk) => {
        if (!hasReceivedContent) {
          hasReceivedContent = true
          setIsLoading(false)
        }
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, content: m.content + chunk }
              : m
          )
        )
      }, currentConversationId || undefined, (messageId) => {
        // Update the AI message ID to the backend ID for proper persistence
        setMessages(prev =>
          prev.map(m =>
            m.id === aiMessageId
              ? { ...m, id: String(messageId) }
              : m
          )
        )
      })
    } catch (error) {
      console.error('Failed to regenerate response:', error)
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

  // Handle option button selection - auto-send message
  const handleOptionSelect = (text: string) => {
    setInput(text)
    // Auto-submit
    setTimeout(() => {
      const form = document.querySelector('form')
      if (form) {
        form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      }
    }, 100)
  }

  // Handle task submission success
  const handleTaskSubmitSuccess = async (taskId: string, messageId: string) => {
    // Update the original message's TASK_CONFIG block to include submitted_task_id
    // This persists the submission status so it's preserved when reloading the conversation

    // First, compute the updated content
    let updatedContent: string | null = null
    setMessages(prev => prev.map(m => {
      if (m.id === messageId) {
        updatedContent = m.content.replace(
          /\[TASK_CONFIG\]([\s\S]*?)\[\/TASK_CONFIG\]/,
          (_match, json) => {
            try {
              const config = JSON.parse(json.trim())
              config.submitted_task_id = taskId
              return `[TASK_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/TASK_CONFIG]`
            } catch {
              return _match // If parsing fails, keep original
            }
          }
        )
        return { ...m, content: updatedContent }
      }
      return m
    }))

    // Try to persist the update to backend if we have a conversation ID
    // Message IDs from backend are small integers (auto-increment), while
    // frontend-generated IDs are timestamps (large numbers like 1706191234567)
    if (currentConversationId && updatedContent) {
      const numericId = parseInt(messageId, 10)
      // Backend message IDs are typically small integers (< 1000000000)
      // Timestamps are 13-digit numbers (> 1000000000000)
      if (!isNaN(numericId) && numericId < 1000000000) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          // Silently fail - local state is already updated
          console.warn('Failed to persist message update to backend:', error)
        }
      }
    }

    // Add a success message to the chat and persist to backend
    const successContent = `Training task created successfully! Task ID: \`${taskId}\`\n\nYou can monitor the progress in the Tasks page.`
    const successMessage: Message = {
      id: Date.now().toString(),
      role: 'assistant',
      content: successContent,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, successMessage])

    // Persist success message to backend
    if (currentConversationId) {
      try {
        const savedMessage = await addMessage(currentConversationId, 'assistant', successContent)
        // Update the message ID to the backend ID
        setMessages(prev => prev.map(m =>
          m.id === successMessage.id
            ? { ...m, id: String(savedMessage.id) }
            : m
        ))
      } catch (error) {
        console.warn('Failed to persist success message to backend:', error)
      }
    }
  }

  // Handle task submission error
  const handleTaskSubmitError = (error: string) => {
    // Send error to agent for analysis
    const errorMessage = `The task submission failed with error: "${error}". Can you help me understand what went wrong and how to fix it?`
    setInput(errorMessage)
  }

  // Handle inference submission success
  const handleInferenceSubmitSuccess = async (taskId: string, messageId: string) => {
    // Update the original message's INFERENCE_CONFIG block to include submitted_task_id
    // This persists the submission status so it's preserved when reloading the conversation

    // First, compute the updated content
    let updatedContent: string | null = null
    setMessages(prev => prev.map(m => {
      if (m.id === messageId) {
        updatedContent = m.content.replace(
          /\[INFERENCE_CONFIG\]([\s\S]*?)\[\/INFERENCE_CONFIG\]/,
          (_match, json) => {
            try {
              const config = JSON.parse(json.trim())
              config.submitted_task_id = taskId
              return `[INFERENCE_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/INFERENCE_CONFIG]`
            } catch {
              return _match // If parsing fails, keep original
            }
          }
        )
        return { ...m, content: updatedContent }
      }
      return m
    }))

    // Try to persist the update to backend if we have a conversation ID
    if (currentConversationId && updatedContent) {
      const numericId = parseInt(messageId, 10)
      if (!isNaN(numericId) && numericId < 1000000000) {
        try {
          await updateMessage(currentConversationId, numericId, updatedContent)
        } catch (error) {
          console.warn('Failed to persist message update to backend:', error)
        }
      }
    }

    // Add a success message with navigation card to Results Viewer and persist to backend
    const successContent = `Inference task submitted successfully! Task ID: \`${taskId}\`\n\nOnce the inference is complete, you can view the analysis results in the Results Viewer.\n\n[NAVIGATE]\n${JSON.stringify({
      target: '/results',
      state: { selectedTaskId: taskId },
      buttonText: 'View Results',
      description: 'Click to open the Results Viewer and analyze the inference results.'
    }, null, 2)}\n[/NAVIGATE]`
    const successMessage: Message = {
      id: Date.now().toString(),
      role: 'assistant',
      content: successContent,
      timestamp: new Date()
    }
    setMessages(prev => [...prev, successMessage])

    // Persist success message to backend
    if (currentConversationId) {
      try {
        const savedMessage = await addMessage(currentConversationId, 'assistant', successContent)
        // Update the message ID to the backend ID
        setMessages(prev => prev.map(m =>
          m.id === successMessage.id
            ? { ...m, id: String(savedMessage.id) }
            : m
        ))
      } catch (error) {
        console.warn('Failed to persist success message to backend:', error)
      }
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
            {/* Gemini-style Welcome Hero with Scenario Cards */}
            {messages.length === 0 && showWelcomeHero && (
              <div className="flex flex-col items-center justify-center py-12 text-center space-y-8">
                {/* Hero Title */}
                <div className="space-y-3">
                  <div className="flex items-center justify-center gap-2 mb-4">
                    <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 flex items-center justify-center shadow-lg">
                      <Sparkles className="w-7 h-7 text-white" />
                    </div>
                  </div>
                  <h1 className="text-3xl font-bold bg-gradient-to-r from-gray-900 via-gray-700 to-gray-900 bg-clip-text text-transparent">
                    Hello, I'm PathLab Agent
                  </h1>
                  <p className="text-gray-500 max-w-lg mx-auto text-base">
                    Your AI assistant for pathology research. I can help you train models, run inference, and analyze whole slide images.
                  </p>
                </div>

                {/* Scenario Cards */}
                <div className="grid grid-cols-2 gap-4 w-full max-w-2xl mt-8">
                  {SCENARIO_CARDS.map((card) => {
                    const Icon = card.icon
                    return (
                      <button
                        key={card.id}
                        onClick={() => handleScenarioCardClick(card)}
                        className={`${card.bgColor} p-5 rounded-2xl text-left transition-all duration-200 hover:shadow-md hover:scale-[1.02] group border border-transparent hover:border-gray-200`}
                      >
                        <div className={`w-10 h-10 rounded-xl bg-white shadow-sm flex items-center justify-center mb-3 group-hover:shadow-md transition-shadow`}>
                          <Icon className={`w-5 h-5 ${card.iconColor}`} />
                        </div>
                        <h3 className="font-semibold text-gray-900 mb-1">{card.title}</h3>
                        <p className="text-sm text-gray-600">{card.description}</p>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}
            {messages.map((message, index) => (
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
                  {/* User Images */}
                  {message.role === 'user' && message.images && message.images.length > 0 && (
                    <div className="flex flex-wrap gap-2 mb-2 justify-end">
                      {message.images.map((img, idx) => (
                        <img
                          key={idx}
                          src={img}
                          alt={`Attachment ${idx + 1}`}
                          className="max-w-[200px] max-h-[200px] rounded-xl object-cover border border-gray-200 shadow-sm"
                        />
                      ))}
                    </div>
                  )}

                  {/* Message Bubble */}
                  <div
                    className={`relative px-5 py-3.5 text-[15px] leading-7 ${
                      message.role === 'user'
                        ? 'bg-[#f4f4f4] text-gray-900 rounded-3xl rounded-tr-sm'
                        : 'bg-transparent text-gray-900 px-0 py-0'
                    }`}
                  >
                    {message.role === 'user' ? (
                      (() => {
                        // Parse CSV preview from user message
                        const csvPreview = parseCSVPreview(message.content)
                        const displayContent = csvPreview ? removeCSVPreviewBlock(message.content) : message.content

                        return (
                          <div>
                            {displayContent.trim() && (
                              <div className="whitespace-pre-wrap break-words">
                                {displayContent}
                              </div>
                            )}
                            {csvPreview && (
                              <CSVPreviewCard {...csvPreview} />
                            )}
                          </div>
                        )
                      })()
                    ) : message.content === '' ? (
                      // ChatGPT-like Thinking Indicator
                      <div className="flex items-center gap-2 py-2">
                        <div className="w-2.5 h-2.5 bg-gray-400 rounded-full animate-pulse"></div>
                        <span className="text-sm font-medium text-gray-500 animate-pulse">Thinking...</span>
                      </div>
                    ) : (
                      <AssistantMessage
                        content={message.content}
                        messageId={message.id}
                        onOptionSelect={handleOptionSelect}
                        onTaskSubmitSuccess={handleTaskSubmitSuccess}
                        onInferenceSubmitSuccess={handleInferenceSubmitSuccess}
                        onTaskSubmitError={handleTaskSubmitError}
                        isStreaming={isLoading && index === messages.length - 1}
                        isLoading={isLoading}
                        csvContent={csvContentMap.get(message.id)?.content}
                        csvFileName={csvContentMap.get(message.id)?.fileName}
                        onToast={setToastMessage}
                      />
                    )}
                  </div>

                  {/* Timestamp & Actions */}
                  {message.role === 'assistant' && message.content !== '' && (
                     <div className="flex items-center gap-3 mt-2 text-gray-400">
                        <button
                            onClick={() => handleCopy(message.content)}
                            className="hover:text-gray-600 transition-colors"
                            title="Copy"
                        >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                        </button>
                        <button
                            onClick={() => handleRegenerate(index)}
                            disabled={isLoading}
                            className={`hover:text-gray-600 transition-colors ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                            title="Regenerate"
                        >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"></path><path d="M3 3v5h5"></path><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"></path><path d="M16 16h5v5"></path></svg>
                        </button>
                     </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      </div>


      {/* Input Area - Permanent position at bottom */}
      <div className="absolute left-1/2 -translate-x-1/2 bottom-8 translate-y-0 w-full max-w-4xl px-4 z-30">
         {/* Image Attachments Preview */}
         {imageAttachments.length > 0 && (
           <div className="mb-3 flex flex-wrap gap-2 p-3 bg-white/80 backdrop-blur-sm rounded-xl border border-gray-200">
             {imageAttachments.map((attachment) => (
               <div key={attachment.id} className="relative group">
                 <img
                   src={attachment.preview}
                   alt="Attachment"
                   className="w-16 h-16 object-cover rounded-lg border border-gray-200"
                 />
                 <button
                   type="button"
                   onClick={() => handleImageRemove(attachment.id)}
                   className="absolute -top-2 -right-2 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
                 >
                   <X className="w-3 h-3" />
                 </button>
               </div>
             ))}
           </div>
         )}

         {/* File Attachments Preview (CSV/XLSX) */}
         {fileAttachments.length > 0 && (
           <div className="mb-3 p-3 bg-white/80 backdrop-blur-sm rounded-xl border border-gray-200">
             {fileAttachments.map((attachment) => (
               <div key={attachment.id} className="relative group flex items-start gap-3 mb-2 last:mb-0">
                 <div className="flex-shrink-0 w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
                   <FileSpreadsheet className="w-5 h-5 text-green-600" />
                 </div>
                 <div className="flex-1 min-w-0">
                   <div className="flex items-center gap-2">
                     <span className="text-sm font-medium text-gray-900 truncate">{attachment.name}</span>
                     <span className="text-xs text-gray-500 uppercase">{attachment.type}</span>
                   </div>
                   {attachment.type === 'csv' && (
                     <div className="mt-1 text-xs text-gray-500 font-mono bg-gray-50 rounded p-1 overflow-x-auto max-h-16 overflow-y-auto">
                       {attachment.preview.slice(0, 3).map((line, i) => (
                         <div key={i} className="truncate">{line}</div>
                       ))}
                       {attachment.preview.length > 3 && <div className="text-gray-400">...</div>}
                     </div>
                   )}
                   {attachment.type === 'xlsx' && (
                     <div className="mt-1 text-xs text-gray-500">
                       {attachment.preview.join(' • ')}
                     </div>
                   )}
                 </div>
                 <button
                   type="button"
                   onClick={() => handleFileRemove(attachment.id)}
                   className="flex-shrink-0 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity shadow-md"
                 >
                   <X className="w-3 h-3" />
                 </button>
               </div>
             ))}
           </div>
         )}

         <form onSubmit={handleSubmit} className="relative group">
            <div className="relative flex items-center bg-white rounded-2xl shadow-xl border border-gray-300 focus-within:ring-2 focus-within:ring-primary-100 focus-within:border-primary-400 h-auto min-h-[60px] pl-4 pr-[140px] py-2 transition-all duration-300">
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

                {/* Hidden file input - accepts images, CSV, and XLSX */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*,.csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
                  multiple
                  onChange={handleFileSelect}
                  className="hidden"
                />

                {/* Full-width Audio Visualizer overlay */}
                {isRecording && (
                    <div className="absolute inset-y-0 left-4 right-[140px] flex items-center justify-center animate-in zoom-in-95 fade-in duration-300 pointer-events-none">
                        <AudioVisualizer stream={recordingStream} isActive={isRecording} className="w-full h-2/3" />
                    </div>
                )}

                <div className="absolute right-2 md:right-3 flex items-center gap-1.5 md:gap-2 bottom-2">
                     {/* File Upload Button (Images, CSV, XLSX) */}
                     <button
                         type="button"
                         onClick={() => fileInputRef.current?.click()}
                         disabled={isLoading || isRecording}
                         className="p-2 md:p-2.5 rounded-xl transition-all bg-gray-100 text-gray-600 hover:bg-gray-200 disabled:opacity-50 disabled:cursor-not-allowed"
                         title="Attach files (images, CSV, XLSX)"
                     >
                         <Paperclip className="w-4 h-4 md:w-5 md:h-5" />
                     </button>

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
                        disabled={(!input.trim() && imageAttachments.length === 0 && fileAttachments.length === 0) || isLoading}
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


