/**
 * useRealtimeASR - Hook for realtime ASR (Automatic Speech Recognition)
 * 
 * Connects to the backend WebSocket proxy for qwen3-asr-realtime with server-side VAD.
 * Handles continuous voice input with automatic speech detection and transcription.
 * 
 * Flow:
 * 1. Call startRecording() to begin audio capture and WebSocket connection
 * 2. Audio is streamed to backend → DashScope in realtime
 * 3. Server VAD detects speech start/stop
 * 4. On speech_stopped, final transcript is delivered via onTranscriptComplete callback
 * 5. Recording continues until stopRecording() is called or max timeout
 */

import { useRef, useState, useCallback, useEffect } from 'react'
import { getApiBase } from '../config'
import { getAuthToken } from '../api'

// Error message mappings for user-friendly error display
const ERROR_MESSAGES: Record<string, string> = {
  'NotAllowedError': 'Microphone permission denied. Please allow microphone access and try again.',
  'NotFoundError': 'No microphone found. Please connect a microphone and try again.',
  'NotReadableError': 'Microphone is in use by another application. Please close other apps and try again.',
  'OverconstrainedError': 'Microphone does not support required audio settings.',
  'AbortError': 'Microphone access was interrupted.',
  'SecurityError': 'Microphone access blocked by security policy.',
  'TypeError': 'Invalid audio configuration.',
}

// ASR Event types from DashScope
export interface ASREvent {
  type: string
  event_id?: string
  // Session events
  session?: {
    id: string
    model: string
    input_audio_format: string
    turn_detection?: {
      type: string
      threshold: number
      silence_duration_ms: number
    }
  }
  // Speech events
  audio_start_ms?: number
  audio_end_ms?: number
  item_id?: string
  // Transcription events
  content_index?: number
  language?: string
  emotion?: string
  text?: string      // Confirmed text prefix
  stash?: string     // Tentative text (may change)
  transcript?: string // Final transcript (completed event)
  // Error
  error?: {
    type?: string
    code?: string
    message: string
    param?: string
  }
}

export interface UseRealtimeASROptions {
  // Called when VAD detects speech end and final transcript is ready
  onTranscriptComplete: (transcript: string) => void
  // Called with realtime partial transcription (text + stash)
  onPartialTranscript?: (text: string) => void
  // Called when speech is detected to start
  onSpeechStart?: () => void
  // Called when speech ends (before transcript is ready)
  onSpeechEnd?: () => void
  // Called on error
  onError?: (error: string) => void
  // VAD configuration
  vadThreshold?: number           // VAD detection threshold (default: 0.0)
  silenceDurationMs?: number      // Silence duration to trigger end (default: 600ms)
  // Maximum recording time in seconds (default: 60)
  maxRecordingSeconds?: number
}

export interface UseRealtimeASRReturn {
  isRecording: boolean
  isConnecting: boolean
  partialText: string
  mediaStream: MediaStream | null
  startRecording: () => Promise<void>
  stopRecording: () => void
  // Error state for UI display
  lastError: string | null
}

export function useRealtimeASR(options: UseRealtimeASROptions): UseRealtimeASRReturn {
  const {
    onTranscriptComplete,
    onPartialTranscript,
    onSpeechStart,
    onSpeechEnd,
    onError,
    vadThreshold = 0.0,
    silenceDurationMs = 600,
    maxRecordingSeconds = 60
  } = options

  const [isRecording, setIsRecording] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [partialText, setPartialText] = useState('')
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<AudioWorkletNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const maxTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Debounce ref to prevent rapid clicks
  const startingRef = useRef(false)
  // Track if component is mounted
  const isMountedRef = useRef(true)

  const cleanup = useCallback(() => {
    // Clear debounce flag - IMPORTANT: Always reset to allow future starts
    startingRef.current = false

    // Clear max recording timeout
    if (maxTimeoutRef.current) {
      clearTimeout(maxTimeoutRef.current)
      maxTimeoutRef.current = null
    }

    // Stop audio processing - disconnect in correct order
    if (processorRef.current) {
      // Signal the AudioWorklet to stop processing
      try {
        processorRef.current.port.postMessage('STOP')
      } catch { /* ignore - processor may already be stopped */ }
      try {
        processorRef.current.disconnect()
      } catch { /* ignore */ }
      processorRef.current = null
    }

    if (sourceRef.current) {
      try {
        sourceRef.current.disconnect()
      } catch { /* ignore */ }
      sourceRef.current = null
    }

    // Close AudioContext properly to free resources
    if (audioContextRef.current) {
      const ctx = audioContextRef.current
      audioContextRef.current = null // Clear ref first to prevent reuse

      if (ctx.state !== 'closed') {
        // Close asynchronously but don't wait
        ctx.close().catch((err) => {
          console.warn('[ASR] AudioContext close error:', err)
        })
      }
    }

    // Stop media stream tracks
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => {
        try {
          track.stop()
        } catch { /* ignore */ }
      })
      mediaStreamRef.current = null
    }

    if (isMountedRef.current) {
      setMediaStream(null)
    }

    // Close WebSocket connection
    if (wsRef.current) {
      const ws = wsRef.current
      wsRef.current = null // Clear ref first to prevent reuse

      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        // Send session.finish before closing (only if open)
        if (ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify({
              event_id: 'event_finish',
              type: 'session.finish'
            }))
          } catch { /* ignore */ }
        }

        // Close the connection
        try {
          ws.close()
        } catch { /* ignore */ }
      }
    }

    // Update UI state
    if (isMountedRef.current) {
      setIsRecording(false)
      setIsConnecting(false)
      setPartialText('')
    }
  }, [])

  const stopRecording = useCallback(() => {
    cleanup()
  }, [cleanup])

  const startRecording = useCallback(async () => {
    // Edge case: Prevent rapid consecutive clicks
    if (isRecording || isConnecting || startingRef.current) {
      console.log('[ASR] Already recording or connecting, ignoring start request')
      return
    }
    startingRef.current = true

    setIsConnecting(true)
    setPartialText('')
    setLastError(null)

    try {
      // Get auth token
      const token = getAuthToken()
      if (!token) {
        throw new Error('Not authenticated')
      }

      // Build WebSocket URL
      const apiBase = getApiBase()
      const wsUrl = apiBase.replace(/^http/, 'ws') + `/asr/realtime?token=${encodeURIComponent(token)}`

      // Connect to WebSocket
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      // Handle WebSocket messages
      ws.onmessage = (event) => {
        try {
          const data: ASREvent = JSON.parse(event.data)

          switch (data.type) {
            case 'session.created':
              // Session ready, send config update
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                  event_id: 'event_session_update',
                  type: 'session.update',
                  session: {
                    input_audio_format: 'pcm',
                    sample_rate: 16000,
                    input_audio_transcription: {
                      // Auto language detection
                    },
                    turn_detection: {
                      type: 'server_vad',
                      threshold: vadThreshold,
                      silence_duration_ms: silenceDurationMs
                    }
                  }
                }))
              }
              break

            case 'session.updated':
              // Config applied, we're ready
              console.log('[ASR] Session updated, ready for audio')
              break

            case 'input_audio_buffer.speech_started':
              console.log('[ASR] Speech started')
              onSpeechStart?.()
              break

            case 'input_audio_buffer.speech_stopped':
              console.log('[ASR] Speech stopped (VAD triggered)')
              onSpeechEnd?.()
              break

            case 'conversation.item.input_audio_transcription.text':
              // Partial/realtime transcript
              const partial = (data.text || '') + (data.stash || '')
              setPartialText(partial)
              onPartialTranscript?.(partial)
              break

            case 'conversation.item.input_audio_transcription.completed':
              // Final transcript for this speech segment
              const transcript = data.transcript || ''
              console.log('[ASR] Transcript completed:', transcript)
              // Edge case: Ignore empty transcripts (just silence or noise)
              if (transcript && transcript.trim()) {
                onTranscriptComplete(transcript.trim())
              } else {
                console.log('[ASR] Empty transcript ignored')
              }
              setPartialText('')
              break

            case 'error':
              console.error('[ASR] Error:', data.error?.message)
              onError?.(data.error?.message || 'Unknown ASR error')
              break
          }
        } catch (e) {
          console.error('[ASR] Failed to parse message:', e)
        }
      }

      ws.onerror = (error) => {
        console.error('[ASR] WebSocket error:', error)
        const errorMsg = 'Failed to connect to voice service. Please try again.'
        setLastError(errorMsg)
        onError?.(errorMsg)
        cleanup()
      }

      ws.onclose = (event) => {
        // Only log as error if it's an abnormal closure
        if (event.code !== 1000 && event.code !== 1001) {
          console.warn('[ASR] WebSocket closed unexpectedly:', event.code, event.reason)
        } else {
          console.log('[ASR] WebSocket closed normally')
        }
        cleanup()
      }

      // Wait for connection with proper error handling
      await new Promise<void>((resolve, reject) => {
        const connectionTimeout = setTimeout(() => {
          reject(new Error('Connection timeout - please check your network'))
        }, 10000)

        ws.onopen = () => {
          clearTimeout(connectionTimeout)
          console.log('[ASR] WebSocket connected')
          resolve()
        }

        // If error occurs during connection, reject the promise
        const originalOnError = ws.onerror
        ws.onerror = (error) => {
          clearTimeout(connectionTimeout)
          if (originalOnError) {
            originalOnError.call(ws, error)
          }
          reject(new Error('WebSocket connection failed'))
        }
      })

      // Start audio capture
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true
        }
      })
      mediaStreamRef.current = stream
      setMediaStream(stream)

      // Edge case: Check if we were stopped during async operations
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        console.log('[ASR] Connection closed during setup, aborting')
        // Clean up the stream we just created
        stream.getTracks().forEach(track => track.stop())
        throw new Error('Connection closed during setup')
      }

      // Create audio context and load AudioWorklet processor
      const audioContext = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = audioContext

      // Edge case: Handle AudioContext being suspended (browser autoplay policy)
      if (audioContext.state === 'suspended') {
        console.log('[ASR] AudioContext suspended, attempting to resume...')
        await audioContext.resume()
      }

      // Load the PCM processor AudioWorklet module
      try {
        await audioContext.audioWorklet.addModule('/pcm-processor.js')
      } catch (workletError) {
        console.error('[ASR] Failed to load AudioWorklet module:', workletError)
        throw new Error('Failed to initialize audio processor. Please refresh the page.')
      }

      // Edge case: Check again if we were stopped during async operations
      if (!audioContextRef.current) {
        console.log('[ASR] AudioContext cleared during setup, aborting')
        throw new Error('AudioContext cleared during setup')
      }

      const source = audioContext.createMediaStreamSource(stream)
      sourceRef.current = source

      // Create AudioWorkletNode
      const pcmNode = new AudioWorkletNode(audioContext, 'pcm-processor')
      processorRef.current = pcmNode

      // Handle AudioWorklet errors
      pcmNode.onprocessorerror = (event) => {
        console.error('[ASR] AudioWorklet processor error:', event)
        onError?.('Audio processing error occurred')
        cleanup()
      }

      // Handle audio data from the AudioWorklet
      pcmNode.port.onmessage = (event) => {
        if (ws.readyState !== WebSocket.OPEN) return
        if (event.data.type !== 'audio') return

        const pcmData = new Uint8Array(event.data.data)
        // Send as base64
        const base64 = btoa(String.fromCharCode(...pcmData))
        ws.send(JSON.stringify({
          event_id: `event_audio_${Date.now()}`,
          type: 'input_audio_buffer.append',
          audio: base64
        }))
      }

      source.connect(pcmNode)
      pcmNode.connect(audioContext.destination)

      startingRef.current = false
      setIsRecording(true)
      setIsConnecting(false)

      // Set max recording timeout
      maxTimeoutRef.current = setTimeout(() => {
        console.log('[ASR] Max recording time reached')
        onError?.('Maximum recording time reached (2 minutes)')
        stopRecording()
      }, maxRecordingSeconds * 1000)

    } catch (error) {
      console.error('[ASR] Failed to start recording:', error)
      // Edge case: Map specific error types to user-friendly messages
      let errorMessage = 'Failed to start recording'
      if (error instanceof Error) {
        const mappedError = ERROR_MESSAGES[error.name]
        errorMessage = mappedError || error.message
      }
      setLastError(errorMessage)
      onError?.(errorMessage)
      cleanup()
    }
  }, [isRecording, isConnecting, vadThreshold, silenceDurationMs, maxRecordingSeconds,
      onTranscriptComplete, onPartialTranscript, onSpeechStart, onSpeechEnd, onError, cleanup, stopRecording])

  // Edge case: Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      cleanup()
    }
  }, [cleanup])

  return {
    isRecording,
    isConnecting,
    partialText,
    mediaStream,
    startRecording,
    stopRecording,
    lastError
  }
}

