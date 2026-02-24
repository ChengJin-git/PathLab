/**
 * useRealtimeASR - Hook for realtime ASR (Automatic Speech Recognition)
 *
 * Connects to the backend WebSocket proxy for qwen3-asr-realtime with server-side VAD.
 * Handles continuous voice input with automatic speech detection and transcription.
 *
 * Key design: All callbacks are stored in refs and all state guards use refs,
 * so startRecording/stopRecording are **stable references** that never go stale.
 */

import { useRef, useState, useCallback, useEffect } from 'react'
import { getApiBase } from '../config'
import { getAuthToken } from '../api'

const ERROR_MESSAGES: Record<string, string> = {
  'NotAllowedError': 'Microphone permission denied. Please allow microphone access and try again.',
  'NotFoundError': 'No microphone found. Please connect a microphone and try again.',
  'NotReadableError': 'Microphone is in use by another application. Please close other apps and try again.',
  'OverconstrainedError': 'Microphone does not support required audio settings.',
  'AbortError': 'Microphone access was interrupted.',
  'SecurityError': 'Microphone access blocked by security policy.',
  'TypeError': 'Invalid audio configuration.',
}

export interface ASREvent {
  type: string
  event_id?: string
  session?: {
    id: string
    model: string
    input_audio_format: string
    turn_detection?: { type: string; threshold: number; silence_duration_ms: number }
  }
  audio_start_ms?: number
  audio_end_ms?: number
  item_id?: string
  content_index?: number
  language?: string
  emotion?: string
  text?: string
  stash?: string
  transcript?: string
  error?: { type?: string; code?: string; message: string; param?: string }
}

export interface UseRealtimeASROptions {
  onTranscriptComplete: (transcript: string) => void
  onPartialTranscript?: (text: string) => void
  onSpeechStart?: () => void
  onSpeechEnd?: () => void
  onError?: (error: string) => void
  vadThreshold?: number
  silenceDurationMs?: number
  maxRecordingSeconds?: number
}

export interface UseRealtimeASRReturn {
  isRecording: boolean
  isConnecting: boolean
  partialText: string
  mediaStream: MediaStream | null
  /** Stable reference – safe to call from any closure or setTimeout. */
  startRecording: () => Promise<void>
  /** Stable reference – safe to call from any closure or setTimeout. */
  stopRecording: () => void
  lastError: string | null
}

export function useRealtimeASR(options: UseRealtimeASROptions): UseRealtimeASRReturn {
  // ---------------------------------------------------------------------------
  // State (for UI rendering)
  // ---------------------------------------------------------------------------
  const [isRecording, setIsRecording] = useState(false)
  const [isConnecting, setIsConnecting] = useState(false)
  const [partialText, setPartialText] = useState('')
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)

  // ---------------------------------------------------------------------------
  // Refs – single source of truth for guards & callbacks
  // ---------------------------------------------------------------------------
  // Mirror state into refs so startRecording/stopRecording never read stale values
  const isRecordingRef = useRef(false)
  const isConnectingRef = useRef(false)

  const wsRef = useRef<WebSocket | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<AudioWorkletNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const maxTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const startingRef = useRef(false)
  const isMountedRef = useRef(true)
  // Track pending async cleanup (AudioContext.close) so startRecording can await it
  const cleanupPromiseRef = useRef<Promise<void>>(Promise.resolve())
  // Resolve function for session.updated promise - called when server is ready for audio
  const sessionUpdatedResolveRef = useRef<(() => void) | null>(null)

  // Store all callbacks in refs so they are always fresh
  const optionsRef = useRef(options)
  optionsRef.current = options

  // ---------------------------------------------------------------------------
  // Helper: set state + ref in one call
  // ---------------------------------------------------------------------------
  const setRecording = useCallback((v: boolean) => {
    isRecordingRef.current = v
    setIsRecording(v)
  }, [])

  const setConnecting = useCallback((v: boolean) => {
    isConnectingRef.current = v
    setIsConnecting(v)
  }, [])

  // ---------------------------------------------------------------------------
  // cleanup – tears down all resources, resets to idle
  // ---------------------------------------------------------------------------
  const cleanup = useCallback(() => {
    startingRef.current = false
    sessionUpdatedResolveRef.current = null

    if (maxTimeoutRef.current) {
      clearTimeout(maxTimeoutRef.current)
      maxTimeoutRef.current = null
    }

    if (processorRef.current) {
      try { processorRef.current.port.postMessage('STOP') } catch { /* */ }
      try { processorRef.current.disconnect() } catch { /* */ }
      processorRef.current = null
    }

    if (sourceRef.current) {
      try { sourceRef.current.disconnect() } catch { /* */ }
      sourceRef.current = null
    }

    const asyncCleanupPromises: Promise<void>[] = []

    if (audioContextRef.current) {
      const ctx = audioContextRef.current
      audioContextRef.current = null
      if (ctx.state !== 'closed') {
        asyncCleanupPromises.push(ctx.close().catch((err) => console.warn('[ASR] AudioContext close error:', err)))
      }
    }

    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(t => { try { t.stop() } catch { /* */ } })
      mediaStreamRef.current = null
    }

    if (wsRef.current) {
      const ws = wsRef.current
      wsRef.current = null
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        if (ws.readyState === WebSocket.OPEN) {
          try { ws.send(JSON.stringify({ event_id: 'event_finish', type: 'session.finish' })) } catch { /* */ }
        }
        try { ws.close() } catch { /* */ }
      }
    }

    if (isMountedRef.current) {
      setMediaStream(null)
      setRecording(false)
      setConnecting(false)
      setPartialText('')
    }

    // Track async cleanup completion so startRecording can await it
    cleanupPromiseRef.current = asyncCleanupPromises.length > 0
      ? Promise.all(asyncCleanupPromises).then(() => {})
      : Promise.resolve()
  }, [setRecording, setConnecting])

  // ---------------------------------------------------------------------------
  // stopRecording – stable reference (deps are all stable)
  // ---------------------------------------------------------------------------
  const stopRecording = useCallback(() => { cleanup() }, [cleanup])

  // ---------------------------------------------------------------------------
  // startRecording – stable reference (guards via refs, callbacks via refs)
  // ---------------------------------------------------------------------------
  const startRecording = useCallback(async () => {
    // Guard via refs – immune to stale closures
    if (isRecordingRef.current || isConnectingRef.current || startingRef.current) {
      console.log('[ASR] Already recording/connecting, ignoring start')
      return
    }

    // Wait for any pending async cleanup (AudioContext.close, etc.) to complete
    // This prevents browser resource limits from being hit when rapidly restarting
    try {
      await cleanupPromiseRef.current
    } catch {
      // Ignore cleanup errors – they were already logged
    }

    startingRef.current = true
    setConnecting(true)
    setPartialText('')
    setLastError(null)

    // Read options from ref (always fresh)
    const {
      onTranscriptComplete,
      onPartialTranscript,
      onSpeechStart,
      onSpeechEnd,
      onError,
      vadThreshold = 0.0,
      silenceDurationMs = 600,
      maxRecordingSeconds = 60,
    } = optionsRef.current

    try {
      const token = getAuthToken()
      if (!token) throw new Error('Not authenticated')

      const apiBase = getApiBase()
      const wsUrl = apiBase.replace(/^http/, 'ws') + `/asr/realtime?token=${encodeURIComponent(token)}`
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      // --- WebSocket message handler ---
      ws.onmessage = (event) => {
        try {
          const data: ASREvent = JSON.parse(event.data)
          // Read callbacks from ref inside handler so they are always fresh
          const opts = optionsRef.current
          switch (data.type) {
            case 'session.created':
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({
                  event_id: 'event_session_update',
                  type: 'session.update',
                  session: {
                    modalities: ['text'],
                    input_audio_format: 'pcm',
                    sample_rate: 16000,
                    input_audio_transcription: {},
                    turn_detection: { type: 'server_vad', threshold: vadThreshold, silence_duration_ms: silenceDurationMs },
                  },
                }))
              }
              break
            case 'session.updated':
              console.log('[ASR] Session updated, ready for audio')
              // Notify waiting code that server is ready for audio
              if (sessionUpdatedResolveRef.current) {
                sessionUpdatedResolveRef.current()
                sessionUpdatedResolveRef.current = null
              }
              break
            case 'input_audio_buffer.speech_started':
              // console.log('[ASR] Speech started')
              opts.onSpeechStart?.()
              break
            case 'input_audio_buffer.speech_stopped':
              // console.log('[ASR] Speech stopped (VAD)')
              opts.onSpeechEnd?.()
              break
            case 'conversation.item.input_audio_transcription.text': {
              const partial = (data.text || '') + (data.stash || '')
              setPartialText(partial)
              opts.onPartialTranscript?.(partial)
              break
            }
            case 'conversation.item.input_audio_transcription.completed': {
              const transcript = (data.transcript || '').trim()
              // console.log('[ASR] Transcript completed:', transcript)
              if (transcript) {
                opts.onTranscriptComplete(transcript)
              } else {
                // console.log('[ASR] Empty transcript ignored')
              }
              setPartialText('')
              break
            }
            case 'error':
              console.error('[ASR] Server error:', data.error?.message)
              opts.onError?.(data.error?.message || 'Unknown ASR error')
              break
          }
        } catch (e) {
          console.error('[ASR] Failed to parse message:', e)
        }
      }

      ws.onerror = (error) => {
        if (wsRef.current !== ws) return
        console.error('[ASR] WebSocket error:', error)
        const msg = 'Failed to connect to voice service. Please try again.'
        setLastError(msg)
        optionsRef.current.onError?.(msg)
        cleanup()
      }

      ws.onclose = (event) => {
        if (wsRef.current !== ws) return
        if (event.code !== 1000 && event.code !== 1001) {
          console.warn('[ASR] WebSocket closed unexpectedly:', event.code, event.reason)
        } else {
          // console.log('[ASR] WebSocket closed normally')
        }
        cleanup()
      }

      // Wait for connection
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Connection timeout')), 15000)
        ws.onopen = () => { clearTimeout(timeout); console.log('[ASR] WebSocket connected'); resolve() }
        const origErr = ws.onerror
        ws.onerror = (err) => { clearTimeout(timeout); origErr?.call(ws, err); reject(new Error('WebSocket connection failed')) }
      })

      // Wait for session.updated from server (indicates server is ready for audio)
      // This is critical: the server needs to complete session setup before we send audio
      // Backend may retry upstream connections (up to 3×30s), so allow generous timeout
      console.log('[ASR] Waiting for session.updated...')
      await new Promise<void>((resolve, reject) => {
        const timeout = setTimeout(() => {
          reject(new Error('Session setup timeout - server did not respond'))
        }, 35000)
        sessionUpdatedResolveRef.current = () => {
          clearTimeout(timeout)
          resolve()
        }
        // Also reject if WebSocket closes during wait
        const origOnClose = ws.onclose
        ws.onclose = (event) => {
          clearTimeout(timeout)
          if (sessionUpdatedResolveRef.current) {
            sessionUpdatedResolveRef.current = null
            reject(new Error('WebSocket closed during session setup'))
          }
          origOnClose?.call(ws, event)
        }
      })
      console.log('[ASR] Session ready, starting audio capture')

      // Audio capture
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
      })
      mediaStreamRef.current = stream
      setMediaStream(stream)

      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        stream.getTracks().forEach(t => t.stop())
        throw new Error('Connection closed during setup')
      }

      const audioContext = new AudioContext({ sampleRate: 16000 })
      audioContextRef.current = audioContext
      if (audioContext.state === 'suspended') await audioContext.resume()

      try {
        await audioContext.audioWorklet.addModule('/pcm-processor.js')
      } catch (e) {
        console.error('[ASR] Failed to load AudioWorklet:', e)
        throw new Error('Failed to initialize audio processor. Please refresh the page.')
      }

      if (!audioContextRef.current) throw new Error('AudioContext cleared during setup')

      const source = audioContext.createMediaStreamSource(stream)
      sourceRef.current = source
      const pcmNode = new AudioWorkletNode(audioContext, 'pcm-processor')
      processorRef.current = pcmNode

      pcmNode.onprocessorerror = (ev) => {
        if (processorRef.current !== pcmNode) return
        console.error('[ASR] AudioWorklet error:', ev)
        optionsRef.current.onError?.('Audio processing error occurred')
        cleanup()
      }

      pcmNode.port.onmessage = (ev) => {
        if (ws.readyState !== WebSocket.OPEN || ev.data.type !== 'audio') return
        const base64 = btoa(String.fromCharCode(...new Uint8Array(ev.data.data)))
        ws.send(JSON.stringify({ event_id: `event_audio_${Date.now()}`, type: 'input_audio_buffer.append', audio: base64 }))
      }

      source.connect(pcmNode)
      pcmNode.connect(audioContext.destination)

      startingRef.current = false
      setRecording(true)
      setConnecting(false)

      maxTimeoutRef.current = setTimeout(() => {
        // console.log('[ASR] Max recording time reached')
        optionsRef.current.onError?.('Maximum recording time reached')
        cleanup()
      }, maxRecordingSeconds * 1000)
    } catch (error) {
      console.error('[ASR] Failed to start recording:', error)
      let msg = 'Failed to start recording'
      if (error instanceof Error) {
        msg = ERROR_MESSAGES[error.name] || error.message
      }
      setLastError(msg)
      onError?.(msg)
      cleanup()
    }
  }, [cleanup, setRecording, setConnecting])  // all deps are stable

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true
    return () => { isMountedRef.current = false; cleanup() }
  }, [cleanup])

  return { isRecording, isConnecting, partialText, mediaStream, startRecording, stopRecording, lastError }
}

