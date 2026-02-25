/**
 * useVoiceSession - State machine wrapper for voice input sessions.
 *
 * Encapsulates useRealtimeASR and manages the full lifecycle:
 *   idle → connecting → recording → processing → (connecting | idle)
 *
 * Eliminates scattered boolean flags and refs that previously lived in
 * AIChatPage, replacing them with a single deterministic state machine.
 */

import { useRef, useCallback, useState } from 'react'
import { useRealtimeASR } from './useRealtimeASR'
import { shouldContinueVoice } from '../components/chat/VoiceControlBlock'

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
  /** VAD silence duration in ms (default 800). */
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

  const setProcessing = useCallback((v: boolean) => {
    processingRef.current = v
    setProcessingState(v)
  }, [])

  const setSessionActive = useCallback((v: boolean) => {
    sessionActiveRef.current = v
    setSessionActiveState(v)
  }, [])

  // --- ASR callbacks (stable via optionsRef) ---

  const handleTranscriptComplete = useCallback((transcript: string) => {
    // Transition: recording → processing
    // The ASR WebSocket will close naturally after transcript completes,
    // or we stop it explicitly. Either way, ASR goes to idle.
    // We mark processing=true so the UI shows "processing" state.
    setProcessing(true)
    // Stop the current ASR session (cleanup WebSocket, audio, etc.)
    // We call stopRecording below after the ASR hook is set up.
    // For now, just forward the transcript.
    stopRef.current()
    optionsRef.current.onTranscript(transcript)
  }, [setProcessing])

  const handleError = useCallback((error: string) => {
    // Any error → idle
    setProcessing(false)
    setSessionActive(false)
    optionsRef.current.onError?.(error)
  }, [setProcessing, setSessionActive])

  // --- ASR hook ---
  const {
    isRecording,
    isConnecting,
    partialText,
    mediaStream,
    startRecording,
    stopRecording,
    lastError,
  } = useRealtimeASR({
    onTranscriptComplete: handleTranscriptComplete,
    onPartialTranscript: undefined, // partialText is returned directly by the hook
    onSpeechStart: undefined,
    onSpeechEnd: undefined,
    onError: handleError,
    silenceDurationMs: options.silenceDurationMs ?? 800,
    maxRecordingSeconds: options.maxRecordingSeconds ?? 120,
  })

  // We need a ref to stopRecording so handleTranscriptComplete can call it
  // without a circular dependency.
  const stopRef = useRef(stopRecording)
  stopRef.current = stopRecording
  const startRef = useRef(startRecording)
  startRef.current = startRecording

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
  }, [setSessionActive, setProcessing])

  const stop = useCallback(() => {
    console.log('[VoiceSession] Force stop')
    setSessionActive(false)
    setProcessing(false)
    stopRef.current()
  }, [setSessionActive, setProcessing])

  const notifyResponseComplete = useCallback((aiContent: string) => {
    if (!sessionActiveRef.current) {
      // Session was stopped while LLM was responding
      setProcessing(false)
      return
    }

    setProcessing(false)
    const shouldContinue = shouldContinueVoice(aiContent)

    if (shouldContinue) {
      console.log('[VoiceSession] AI says continue → restarting recording (300ms delay)')
      // Add a delay to ensure all async cleanup (AudioContext.close, WebSocket.close)
      // has fully completed before starting a new recording session.
      // This prevents intermittent failures from browser resource limits.
      setTimeout(() => {
        if (sessionActiveRef.current) {
          startRef.current()
        }
      }, 300)
    } else {
      console.log('[VoiceSession] AI says stop → ending session')
      setSessionActive(false)
    }
  }, [setProcessing, setSessionActive])

  return {
    voiceState,
    partialText,
    mediaStream,
    toggle,
    stop,
    notifyResponseComplete,
    lastError,
  }
}

