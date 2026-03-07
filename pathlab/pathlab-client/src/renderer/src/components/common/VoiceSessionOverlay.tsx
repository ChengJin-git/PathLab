import React from 'react'

import { AudioVisualizer } from './AudioVisualizer'

interface VoiceSessionOverlayProps {
  partialText: string
  mediaStream: MediaStream | null
  isRecording: boolean
  isConnecting: boolean
  isThinking: boolean
  thinkingLabel: string
}

export function VoiceSessionOverlay({
  partialText,
  mediaStream,
  isRecording,
  isConnecting,
  isThinking,
  thinkingLabel
}: VoiceSessionOverlayProps) {
  return (
    <>
      {(isRecording || isConnecting) && (
        <div className="pointer-events-none absolute left-4 right-[140px] top-0 bottom-0 flex items-center">
          {partialText ? (
            <div className="flex w-full items-center gap-2 overflow-hidden text-[15px] leading-relaxed text-gray-700">
              <span className="truncate">{partialText}</span>
              <span className="inline-flex flex-shrink-0 gap-0.5">
                <span className="h-1.5 w-1.5 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '0ms' }} />
                <span className="h-1.5 w-1.5 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '150ms' }} />
                <span className="h-1.5 w-1.5 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '300ms' }} />
              </span>
            </div>
          ) : (
            <AudioVisualizer
              stream={mediaStream}
              isActive={isRecording}
              className="h-12 w-full opacity-80"
            />
          )}
        </div>
      )}

      {isThinking && !isRecording && !isConnecting && (
        <div className="pointer-events-none absolute left-4 right-[140px] top-0 bottom-0 flex items-center justify-center">
          <span className="flex items-center gap-2 text-sm font-medium text-primary-600 animate-pulse">
            <span className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: '300ms' }} />
            {thinkingLabel}
          </span>
        </div>
      )}
    </>
  )
}