/**
 * useVoiceSession - State machine wrapper for voice input sessions.
 *
 * Encapsulates useRealtimeASR and manages the full lifecycle:
 *   idle → connecting → recording → processing → (recording | idle)
 *
 * Eliminates scattered boolean flags and refs that previously lived in
 * AIChatPage, replacing them with a single deterministic state machine.
 */

import { useRef, useCallback, useState, useEffect } from 'react'
import { ASR_SILENCE_DURATION_MS, useRealtimeASR } from './useRealtimeASR'
import { parseVoiceControlBlock } from '../../components/chat/VoiceControlBlock'

// An ASR final ends a segment, not necessarily the user's conversational turn.
export const VOICE_CONTINUATION_WINDOW_MS = 350

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type VoiceState = 'idle' | 'connecting' | 'recording' | 'processing'

export interface UseVoiceSessionOptions {
  /**
   * Called when a complete transcript is ready.
   * The page should submit this text to the LLM.
   */
  onTranscript: (transcript: string) => void
  /** Called on any voice error. */
  onError?: (error: string) => void
  /** VAD silence duration in ms (default 1200). */
  silenceDurationMs?: number
  /** Max recording seconds per ASR connection (default 120). */
  maxRecordingSeconds?: number
}

export interface UseVoiceSessionReturn {
  /** Current state of the voice session. */
  voiceState: VoiceState
  /** Realtime partial transcript from ASR. */
  partialText: string
  /** Media stream for audio visualizer. */
  mediaStream: MediaStream | null
  /** Toggle voice session on/off. Safe to call from any closure. */
  toggle: () => void
  /** Force-stop everything. Safe to call from any closure. */
  stop: () => void
  /**
   * Force-send the current partial transcript immediately.
   * Stops the current ASR recording and triggers onTranscript with the given text.
   * Use this when the user wants to manually send without waiting for VAD silence detection.
   */
  forceSend: (currentPartialText: string) => void
  /** Apply a complete control prefix as soon as it arrives, before the prose finishes. */
  notifyResponseProgress: (aiContent: string) => void
  /**
   * Notify that the LLM response is complete.
   * Parses VOICE_CONTROL from aiContent to decide whether to continue.
   * Must be called from handleSubmit's finally block.
   */
  notifyResponseComplete: (aiContent: string) => void
  /** Last error message, if any. */
  lastError: string | null
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useVoiceSession(options: UseVoiceSessionOptions): UseVoiceSessionReturn {
  // Store options in ref so callbacks are always fresh
  const optionsRef = useRef(options)
  optionsRef.current = options

  // The state machine is driven by both state (for triggering re-renders) and refs
  // (for reliable access inside callbacks/timeouts without stale closures).
  // This mirrors the pattern used in useRealtimeASR for isRecording/isRecordingRef.
  const [processing, setProcessingState] = useState(false)
  const [sessionActive, setSessionActiveState] = useState(false)
  const processingRef = useRef(false)
  const sessionActiveRef = useRef(false)
  const [pendingText, setPendingText] = useState('')
  const segmentsRef = useRef<string[]>([])
  const awaitingFinalsRef = useRef(0)
  const speakingRef = useRef(false)
  const submitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const cancelPendingSubmit = useCallback(() => {
    if (submitTimerRef.current !== null) clearTimeout(submitTimerRef.current)
    submitTimerRef.current = null
  }, [])

  const resetTurn = useCallback(() => {
    cancelPendingSubmit()
    segmentsRef.current = []
    awaitingFinalsRef.current = 0
    speakingRef.current = false
    setPendingText('')
  }, [cancelPendingSubmit])

  useEffect(() => () => cancelPendingSubmit(), [cancelPendingSubmit])

  const setProcessing = useCallback((v: boolean) => {
    processingRef.current = v
    setProcessingState(v)
  }, [])

  const setSessionActive = useCallback((v: boolean) => {
    sessionActiveRef.current = v
    setSessionActiveState(v)
  }, [])

  // --- ASR callbacks (stable via optionsRef) ---

  const submitTurn = useCallback((text: string, manual = false) => {
    resetTurn()
    setProcessing(true)
    if (manual) stopRef.current()
    else pauseRef.current()
    optionsRef.current.onTranscript(text)
  }, [resetTurn, setProcessing])

  const handleTranscriptComplete = useCallback((transcript: string) => {
    if (!sessionActiveRef.current || processingRef.current) return
    awaitingFinalsRef.current = Math.max(0, awaitingFinalsRef.current - 1)
    const text = transcript.trim()
    if (text) segmentsRef.current.push(text)
    setPendingText(segmentsRef.current.join(' '))
    cancelPendingSubmit()
    // A new sentence may already be in progress while the previous final arrives.
    if (speakingRef.current || awaitingFinalsRef.current || !segmentsRef.current.length) return
    submitTimerRef.current = setTimeout(() => {
      submitTimerRef.current = null
      if (!sessionActiveRef.current || processingRef.current || speakingRef.current || awaitingFinalsRef.current) return
      const complete = segmentsRef.current.join(' ')
      submitTurn(complete)
    }, VOICE_CONTINUATION_WINDOW_MS)
  }, [cancelPendingSubmit, submitTurn])

  const handleSpeechStart = useCallback(() => {
    if (!sessionActiveRef.current || processingRef.current) return
    cancelPendingSubmit()
    speakingRef.current = true
    awaitingFinalsRef.current++
  }, [cancelPendingSubmit])

  const handleSpeechEnd = useCallback(() => {
    speakingRef.current = false
  }, [])

  const handleError = useCallback((error: string) => {
    // Any error → idle
    resetTurn()
    setProcessing(false)
    setSessionActive(false)
    optionsRef.current.onError?.(error)
  }, [resetTurn, setProcessing, setSessionActive])

  // --- ASR hook ---
  const {
    isRecording,
    isConnecting,
    partialText,
    mediaStream,
    startRecording,
    stopRecording,
    pauseRecording,
    lastError,
  } = useRealtimeASR({
    onTranscriptComplete: handleTranscriptComplete,
    onPartialTranscript: undefined, // partialText is returned directly by the hook
    onSpeechStart: handleSpeechStart,
    onSpeechEnd: handleSpeechEnd,
    onError: handleError,
    silenceDurationMs: options.silenceDurationMs ?? ASR_SILENCE_DURATION_MS,
    maxRecordingSeconds: options.maxRecordingSeconds ?? 120,
  })

  // Stable controls for callbacks without circular dependencies.
  const stopRef = useRef(stopRecording)
  stopRef.current = stopRecording
  const startRef = useRef(startRecording)
  startRef.current = startRecording
  const pauseRef = useRef(pauseRecording)
  pauseRef.current = pauseRecording

  // --- Derive voiceState ---
  // Priority: processing > connecting > recording > idle
  // Uses state variables (not refs) so changes trigger re-renders.
  let voiceState: VoiceState = 'idle'
  if (processing && sessionActive) {
    voiceState = 'processing'
  } else if (isConnecting) {
    voiceState = 'connecting'
  } else if (isRecording) {
    voiceState = 'recording'
  } else if (sessionActive) {
    // Session is active but ASR is not recording/connecting
    // This can happen briefly during transitions
    voiceState = processing ? 'processing' : 'idle'
  }

  // --- Actions ---

  const toggle = useCallback(() => {
    resetTurn()
    if (sessionActiveRef.current) {
      // Stop
      console.log('[VoiceSession] Toggle → stop')
      setSessionActive(false)
      setProcessing(false)
      stopRef.current()
    } else {
      // Start
      console.log('[VoiceSession] Toggle → start')
      setSessionActive(true)
      setProcessing(false)
      startRef.current()
    }
  }, [resetTurn, setSessionActive, setProcessing])

  const stop = useCallback(() => {
    console.log('[VoiceSession] Force stop')
    resetTurn()
    setSessionActive(false)
    setProcessing(false)
    stopRef.current()
  }, [resetTurn, setSessionActive, setProcessing])

  const forceSend = useCallback((currentPartialText: string) => {
    if (!sessionActiveRef.current || processingRef.current) return
    const text = currentPartialText.trim()
    if (!text) return
    submitTurn(text, true)
  }, [submitTurn])

  const notifyResponseProgress = useCallback((aiContent: string) => {
    if (!sessionActiveRef.current || !processingRef.current) return
    if (parseVoiceControlBlock(aiContent)?.action === 'stop') {
      setSessionActive(false)
      setProcessing(false)
      stopRef.current()
    }
  }, [setProcessing, setSessionActive])

  const notifyResponseComplete = useCallback((aiContent: string) => {
    notifyResponseProgress(aiContent)
    if (!processingRef.current) return
    if (!sessionActiveRef.current) {
      // Session was stopped while LLM was responding
      setProcessing(false)
      return
    }

    setProcessing(false)
    void startRef.current()
  }, [notifyResponseProgress, setProcessing])

  return {
    voiceState,
    partialText: [pendingText, partialText].filter(Boolean).join(' '),
    mediaStream,
    toggle,
    stop,
    forceSend,
    notifyResponseProgress,
    notifyResponseComplete,
    lastError,
  }
}
