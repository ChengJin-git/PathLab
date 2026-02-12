/**
 * useVoiceSession - State machine wrapper for voice input sessions.
 *
 * Encapsulates useRealtimeASR and manages the full lifecycle:
 *   idle → connecting → recording → processing → (connecting | idle)
 *
 * Eliminates scattered boolean flags and refs that previously lived in
 * AIChatPage, replacing them with a single deterministic state machine.
 */

import { useRef, useCallback } from 'react'
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

  // The state machine is driven by a single ref.
  // We derive the "voiceState" for rendering from ASR's isRecording/isConnecting
  // plus our own "processing" flag.
  const processingRef = useRef(false)
  // Whether the session is logically active (user toggled on and hasn't toggled off)
  const sessionActiveRef = useRef(false)

  // --- ASR callbacks (stable via optionsRef) ---

  const handleTranscriptComplete = useCallback((transcript: string) => {
    // Transition: recording → processing
    // The ASR WebSocket will close naturally after transcript completes,
    // or we stop it explicitly. Either way, ASR goes to idle.
    // We mark processing=true so the UI shows "processing" state.
    processingRef.current = true
    // Stop the current ASR session (cleanup WebSocket, audio, etc.)
    // We call stopRecording below after the ASR hook is set up.
    // For now, just forward the transcript.
    stopRef.current()
    optionsRef.current.onTranscript(transcript)
  }, [])

  const handleError = useCallback((error: string) => {
    // Any error → idle
    processingRef.current = false
    sessionActiveRef.current = false
    optionsRef.current.onError?.(error)
  }, [])

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
  let voiceState: VoiceState = 'idle'
  if (processingRef.current && sessionActiveRef.current) {
    voiceState = 'processing'
  } else if (isConnecting) {
    voiceState = 'connecting'
  } else if (isRecording) {
    voiceState = 'recording'
  } else if (sessionActiveRef.current) {
    // Session is active but ASR is not recording/connecting
    // This can happen briefly during transitions
    voiceState = processingRef.current ? 'processing' : 'idle'
  }

  // --- Actions ---

  const toggle = useCallback(() => {
    if (sessionActiveRef.current) {
      // Stop
      console.log('[VoiceSession] Toggle → stop')
      sessionActiveRef.current = false
      processingRef.current = false
      stopRef.current()
    } else {
      // Start
      console.log('[VoiceSession] Toggle → start')
      sessionActiveRef.current = true
      processingRef.current = false
      startRef.current()
    }
  }, [])

  const stop = useCallback(() => {
    console.log('[VoiceSession] Force stop')
    sessionActiveRef.current = false
    processingRef.current = false
    stopRef.current()
  }, [])

  const notifyResponseComplete = useCallback((aiContent: string) => {
    if (!sessionActiveRef.current) {
      // Session was stopped while LLM was responding
      processingRef.current = false
      return
    }

    processingRef.current = false
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
      sessionActiveRef.current = false
    }
  }, [])

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

