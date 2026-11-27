/** Qwen realtime ASR: parallel setup, cancellable lifecycle and reusable turns. */
import { useRef, useState, useCallback, useEffect } from 'react'
import { getApiBase } from '../../config'
import { getAuthToken } from '../../api/client'

// Conversation pauses are longer than voice-command pauses. Keep transport fast,
// but don't treat a short breath as the end of the user's turn.
export const ASR_SILENCE_DURATION_MS = 1200
const SETUP_IDLE_TIMEOUT_MS = 15000
// Allow the gateway's 10s local attempt + two 10s remote attempts/retry, while
// bounding the whole setup even if it keeps reporting progress.
export const ASR_SETUP_DEADLINE_MS = 45000
const PAUSED_CONNECTION_TTL_MS = 45000
// PCM16 mono at 16kHz. The buffer must cover the SAME setup window, not become an
// earlier timeout (the old 8s cap killed the gateway's first 10s connection attempt).
// One extra second covers worklet/timer scheduling at the deadline (~1.47 MB max).
export const ASR_MAX_PENDING_AUDIO_BYTES = 16000 * 2 * (ASR_SETUP_DEADLINE_MS / 1000 + 1)

const ERROR_MESSAGES: Record<string, string> = {
  NotAllowedError: 'Microphone permission denied. Please allow microphone access and try again.',
  NotFoundError: 'No microphone found. Please connect a microphone and try again.',
  NotReadableError: 'Microphone is in use by another application. Please close other apps and try again.',
  OverconstrainedError: 'Microphone does not support required audio settings.',
  SecurityError: 'Microphone access blocked by security policy.',
}

export interface ASREvent {
  type: string
  item_id?: string
  text?: string
  stash?: string
  transcript?: string
  error?: { message: string }
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
  startRecording: () => Promise<void>
  stopRecording: () => void
  /** Mute capture during the AI response; retain the ready connection for the next turn. */
  pauseRecording: () => void
  lastError: string | null
}

interface RecordingSession {
  ws?: WebSocket
  context?: AudioContext
  stream?: MediaStream
  source?: MediaStreamAudioSourceNode
  processor?: AudioWorkletNode
  timer?: ReturnType<typeof setTimeout>
  setupTimer?: ReturnType<typeof setTimeout>
  setupDeadlineTimer?: ReturnType<typeof setTimeout>
  rejectSetup?: (error: Error) => void
  ready: boolean
  pendingAudio: ArrayBuffer[]
  pendingAudioBytes: number
  paused: boolean
  completedItems: Set<string>
  startedAt: number
  speechEndedAt?: number
}

export function useRealtimeASR(options: UseRealtimeASROptions): UseRealtimeASRReturn {
  const [isRecording, setRecording] = useState(false)
  const [isConnecting, setConnecting] = useState(false)
  const [partialText, setPartialText] = useState('')
  const [mediaStream, setMediaStream] = useState<MediaStream | null>(null)
  const [lastError, setLastError] = useState<string | null>(null)
  const optionsRef = useRef(options)
  optionsRef.current = options
  const sessionRef = useRef<RecordingSession | null>(null)
  const mountedRef = useRef(true)
  const closingRef = useRef<Promise<unknown>>(Promise.resolve())

  const stopRecording = useCallback(() => {
    const session = sessionRef.current
    sessionRef.current = null // Invalidate async work before releasing anything.
    if (session) {
      clearTimeout(session.timer)
      clearTimeout(session.setupTimer)
      clearTimeout(session.setupDeadlineTimer)
      session.pendingAudio = []
      session.pendingAudioBytes = 0
      session.rejectSetup?.(new Error('Recording stopped'))
      session.processor?.port.postMessage('STOP')
      session.processor?.disconnect()
      session.source?.disconnect()
      session.stream?.getTracks().forEach(track => track.stop())
      if (session.context && session.context.state !== 'closed') {
        closingRef.current = session.context.close().catch(() => {})
      }
      if (session.ws) {
        if (session.ws.readyState === WebSocket.OPEN) {
          session.ws.send(JSON.stringify({ event_id: `finish_${Date.now()}`, type: 'session.finish' }))
        }
        session.ws.close()
      }
    }
    if (mountedRef.current) {
      setRecording(false)
      setConnecting(false)
      setMediaStream(null)
      setPartialText('')
    }
  }, [])

  const fail = useCallback((session: RecordingSession, error: Error) => {
    if (sessionRef.current !== session) return
    const paused = session.paused
    stopRecording()
    // An idle connection can expire while the LLM responds. Reconnect on the next turn.
    if (!paused) {
      const message = ERROR_MESSAGES[error.name] || error.message
      setLastError(message)
      optionsRef.current.onError?.(message)
    }
  }, [stopRecording])

  const armRecordingLimit = useCallback((session: RecordingSession) => {
    clearTimeout(session.timer)
    session.timer = setTimeout(() => {
      fail(session, new Error('Maximum recording time reached'))
    }, (optionsRef.current.maxRecordingSeconds ?? 120) * 1000)
  }, [fail])

  const pauseRecording = useCallback(() => {
    const session = sessionRef.current
    if (!session?.ready || session.paused) return
    session.paused = true
    session.processor?.port.postMessage('PAUSE')
    session.stream?.getAudioTracks().forEach(track => { track.enabled = false })
    clearTimeout(session.timer)
    session.timer = setTimeout(() => {
      if (sessionRef.current === session && session.paused) stopRecording()
    }, PAUSED_CONNECTION_TTL_MS)
    setRecording(false)
    setPartialText('')
  }, [stopRecording])

  const startRecording = useCallback(async () => {
    const current = sessionRef.current
    if (current) {
      if (!current.paused) return
      if (current.ready && current.ws?.readyState === WebSocket.OPEN && current.context?.state === 'running') {
        current.paused = false
        current.speechEndedAt = undefined
        current.processor?.port.postMessage('RESUME')
        current.stream?.getAudioTracks().forEach(track => { track.enabled = true })
        setPartialText('')
        setRecording(true)
        armRecordingLimit(current)
        console.debug('[ASRTiming] resumed_ready_session')
        return
      }
      stopRecording()
    }

    const session: RecordingSession = {
      ready: false, paused: false, completedItems: new Set(), startedAt: performance.now(),
      pendingAudio: [], pendingAudioBytes: 0,
    }
    sessionRef.current = session // Guard concurrent starts before the first await.
    const active = () => mountedRef.current && sessionRef.current === session
    setConnecting(true)
    setPartialText('')
    setLastError(null)

    try {
      await closingRef.current
      if (!active()) return
      const token = getAuthToken()
      if (!token) throw new Error('Not authenticated')
      const ws = new WebSocket(getApiBase().replace(/^http/, 'ws') + `/asr/realtime?token=${encodeURIComponent(token)}`)
      session.ws = ws

      // Install the waiter before any events can arrive (including a pre-warmed session).
      const ready = new Promise<void>((resolve, reject) => {
        session.rejectSetup = reject
        const setupTimedOut = () => {
          if (!active() || session.ready) return
          console.warn('[ASRTiming] setup_timeout', {
            elapsed_ms: Math.round(performance.now() - session.startedAt),
            buffered_audio_ms: Math.round(session.pendingAudioBytes / 32),
          })
          reject(new Error('Voice service setup timed out. Please try again.'))
        }
        const resetTimeout = () => {
          clearTimeout(session.setupTimer)
          session.setupTimer = setTimeout(setupTimedOut, SETUP_IDLE_TIMEOUT_MS)
        }
        resetTimeout()
        session.setupDeadlineTimer = setTimeout(setupTimedOut, ASR_SETUP_DEADLINE_MS)
        ws.onopen = () => {
          if (!active()) return
          // Qwen accepts session.update immediately after connection; the proxy queues it
          // while connecting upstream, avoiding another browser/server round trip.
          ws.send(JSON.stringify({
            event_id: `setup_${Date.now()}`, type: 'session.update',
            session: {
              modalities: ['text'], input_audio_format: 'pcm', sample_rate: 16000,
              input_audio_transcription: {},
              turn_detection: {
                type: 'server_vad', threshold: optionsRef.current.vadThreshold ?? 0.0,
                silence_duration_ms: optionsRef.current.silenceDurationMs ?? ASR_SILENCE_DURATION_MS,
              },
            },
          }))
        }
        ws.onmessage = event => {
          if (!active()) return
          let data: ASREvent
          try { data = JSON.parse(event.data) } catch { return }
          const opts = optionsRef.current
          switch (data.type) {
            case 'session.progress':
              if (!session.ready) resetTimeout()
              break
            case 'session.updated':
              clearTimeout(session.setupTimer)
              clearTimeout(session.setupDeadlineTimer)
              session.rejectSetup = undefined
              session.ready = true
              for (const audio of session.pendingAudio) ws.send(audio)
              session.pendingAudio = []
              session.pendingAudioBytes = 0
              console.debug('[ASRTiming] session_ready_ms', Math.round(performance.now() - session.startedAt))
              resolve()
              break
            case 'input_audio_buffer.speech_started':
              if (session.paused) {
                if (data.item_id) session.completedItems.add(data.item_id)
              } else { session.speechEndedAt = undefined; opts.onSpeechStart?.() }
              break
            case 'input_audio_buffer.speech_stopped':
              if (!session.paused) { session.speechEndedAt = performance.now(); opts.onSpeechEnd?.() }
              break
            case 'conversation.item.input_audio_transcription.text': {
              if (session.paused) {
                if (data.item_id) session.completedItems.add(data.item_id)
                break
              }
              if (data.item_id && session.completedItems.has(data.item_id)) break
              const text = (data.text || '') + (data.stash || '')
              setPartialText(text)
              opts.onPartialTranscript?.(text)
              break
            }
            case 'conversation.item.input_audio_transcription.completed': {
              if (session.paused) {
                if (data.item_id) session.completedItems.add(data.item_id)
                break
              }
              if (data.item_id && session.completedItems.has(data.item_id)) break
              if (data.item_id) session.completedItems.add(data.item_id)
              const transcript = data.transcript?.trim()
              setPartialText('')
              if (transcript) {
                if (session.speechEndedAt !== undefined) console.debug('[ASRTiming] vad_to_final_ms', Math.round(performance.now() - session.speechEndedAt))
              }
              // Empty finals still settle a detected speech segment in the turn buffer.
              opts.onTranscriptComplete(transcript || '')
              break
            }
            case 'error':
            case 'conversation.item.input_audio_transcription.failed':
              fail(session, new Error(data.error?.message || 'Speech recognition failed'))
              break
            case 'session.finished':
              fail(session, new Error('Voice session ended. Please start recording again.'))
              break
          }
        }
        ws.onerror = () => fail(session, new Error('Failed to connect to voice service. Please try again.'))
        ws.onclose = () => fail(session, new Error('Voice connection closed. Please try again.'))
      })

      // Request microphone permission and initialize Web Audio while ASR connects.
      const capture = (async () => {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true, noiseSuppression: true },
        })
        if (!active()) { stream.getTracks().forEach(track => track.stop()); return }
        session.stream = stream
        const context = new AudioContext({ sampleRate: 16000, latencyHint: 'interactive' })
        session.context = context
        if (context.state === 'suspended') await context.resume()
        if (!active()) return
        await context.audioWorklet.addModule('/pcm-processor.js')
        if (!active()) return

        const source = context.createMediaStreamSource(stream)
        const processor = new AudioWorkletNode(context, 'pcm-processor')
        session.source = source
        session.processor = processor
        processor.onprocessorerror = () => fail(session, new Error('Audio processing error occurred'))
        processor.port.onmessage = event => {
          if (!active() || session.paused || event.data.type !== 'audio') return
          const audio: ArrayBuffer = event.data.data
          if (!session.ready) {
            if (session.pendingAudioBytes + audio.byteLength > ASR_MAX_PENDING_AUDIO_BYTES) {
              fail(session, new Error('Voice startup audio buffer exceeded its limit. Please try again.'))
              return
            }
            session.pendingAudio.push(audio)
            session.pendingAudioBytes += audio.byteLength
          } else if (ws.readyState === WebSocket.OPEN) {
            // Proxy converts PCM to Qwen's base64 envelope once, off the UI thread.
            ws.send(audio)
          }
        }
        source.connect(processor)
        processor.connect(context.destination)
        // Recording reflects actual local capture, independently of cloud setup.
        setMediaStream(stream)
        setRecording(true)
        setConnecting(false)
        armRecordingLimit(session)
        console.debug('[ASRTiming] capture_ready_ms', Math.round(performance.now() - session.startedAt))
      })()
      await Promise.all([ready, capture])
      if (!active()) return
      console.debug('[ASRTiming] streaming_ready_ms', Math.round(performance.now() - session.startedAt))
    } catch (error) {
      fail(session, error instanceof Error ? error : new Error('Failed to start recording'))
    }
  }, [armRecordingLimit, fail, stopRecording])

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false; stopRecording() }
  }, [stopRecording])

  return { isRecording, isConnecting, partialText, mediaStream, startRecording, stopRecording, pauseRecording, lastError }
}
