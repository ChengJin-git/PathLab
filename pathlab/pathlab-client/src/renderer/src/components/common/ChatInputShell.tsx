import React from 'react'
import { Loader2, Mic, MicOff, Paperclip, Send, Square } from 'lucide-react'

import { cn } from '../../lib/utils'

type ShellTone = 'default' | 'voice' | 'feedback'
type VoiceButtonState = 'idle' | 'connecting' | 'recording' | 'active'

interface ChatInputShellProps {
  className?: string
  topContent?: React.ReactNode
  attachmentsPreview?: React.ReactNode
  editor: React.ReactNode
  editorHidden?: boolean
  overlay?: React.ReactNode
  hiddenInput?: React.ReactNode
  shellTone?: ShellTone
  showAttachButton?: boolean
  onAttachClick?: () => void
  attachLabel?: string
  attachDisabled?: boolean
  voiceButtonState: VoiceButtonState
  onVoiceToggle: () => void
  voiceLabel: string
  stopVoiceLabel: string
  voiceDisabled?: boolean
  responding?: boolean
  onStopResponding?: () => void
  stopRespondingLabel?: string
  showVoiceSendButton?: boolean
  onVoiceSend?: () => void
  voiceSendDisabled?: boolean
  voiceSendLabel?: string
  onSend?: () => void
  sendDisabled?: boolean
  sendLabel?: string
  sendButtonType?: 'button' | 'submit'
}

export function ChatInputShell({
  className,
  topContent,
  attachmentsPreview,
  editor,
  editorHidden = false,
  overlay,
  hiddenInput,
  shellTone = 'default',
  showAttachButton = false,
  onAttachClick,
  attachLabel,
  attachDisabled = false,
  voiceButtonState,
  onVoiceToggle,
  voiceLabel,
  stopVoiceLabel,
  voiceDisabled = false,
  responding = false,
  onStopResponding,
  stopRespondingLabel,
  showVoiceSendButton = false,
  onVoiceSend,
  voiceSendDisabled = false,
  voiceSendLabel,
  onSend,
  sendDisabled = false,
  sendLabel,
  sendButtonType = 'button'
}: ChatInputShellProps) {
  const voiceIsConnecting = voiceButtonState === 'connecting'
  const voiceIsRecording = voiceButtonState === 'recording'
  const voiceIsActive = voiceButtonState === 'active' || voiceIsConnecting || voiceIsRecording

  return (
    <div className={cn('relative group', className)}>
      {topContent}
      <div
        className={cn(
          'relative flex min-h-[56px] flex-col rounded-[28px] border bg-white/80 py-1.5 backdrop-blur-xl transition-all duration-300',
          shellTone === 'feedback'
            ? 'border-amber-300 shadow-[0_8px_32px_rgba(0,0,0,0.12)]'
            : shellTone === 'voice'
              ? 'border-primary-300 bg-white/90 shadow-[0_0_0_4px_rgba(102,126,234,0.15)]'
              : 'border-gray-200/50 shadow-[0_8px_32px_rgba(0,0,0,0.12)] hover:border-gray-300/80 hover:shadow-[0_8px_40px_rgba(0,0,0,0.15)]',
        )}
      >
        {attachmentsPreview}

        <div className="relative flex min-h-[52px] items-center pl-4 pr-[104px] sm:pr-[120px]">
          <div
            className={cn(
              'w-full transition-opacity duration-200',
              editorHidden && 'pointer-events-none opacity-0',
            )}
          >
            {editor}
          </div>

          {hiddenInput}
          {overlay}

          <div className="absolute right-1.5 bottom-1.5 flex items-center gap-1 sm:gap-1.5">
            {showAttachButton && (
              <button
                type="button"
                onClick={onAttachClick}
                disabled={attachDisabled}
                title={attachLabel}
                aria-label={attachLabel}
                className="rounded-full p-2 text-gray-400 transition-all hover:bg-gray-100 hover:text-gray-600 active:scale-95 disabled:opacity-50 sm:p-2.5"
              >
                <Paperclip className="h-4 w-4 sm:h-5 sm:w-5" />
              </button>
            )}

            <button
              type="button"
              onClick={onVoiceToggle}
              disabled={voiceDisabled}
              title={voiceIsActive ? stopVoiceLabel : voiceLabel}
              aria-label={voiceIsActive ? stopVoiceLabel : voiceLabel}
              className={cn(
                'rounded-full p-2 transition-all duration-300 active:scale-95 sm:p-2.5',
                voiceIsRecording
                  ? 'bg-red-50 text-red-500 hover:bg-red-100'
                  : voiceIsConnecting
                    ? 'bg-primary-50 text-primary-500'
                    : voiceButtonState === 'active'
                      ? 'bg-primary-500 text-white shadow-md'
                      : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50',
              )}
            >
              {voiceIsConnecting ? (
                <Loader2 className="h-4 w-4 animate-spin sm:h-5 sm:w-5" />
              ) : voiceIsRecording ? (
                <Square className="h-3.5 w-3.5 sm:h-4 sm:w-4" fill="currentColor" />
              ) : voiceButtonState === 'active' ? (
                <MicOff className="h-4 w-4 sm:h-5 sm:w-5" />
              ) : (
                <Mic className="h-4 w-4 sm:h-5 sm:w-5" />
              )}
            </button>

            {responding ? (
              <button
                type="button"
                onClick={onStopResponding}
                title={stopRespondingLabel}
                aria-label={stopRespondingLabel}
                className="rounded-full bg-gray-800 p-2 text-white shadow-sm transition-all duration-300 hover:bg-gray-900 active:scale-95 sm:p-2.5"
              >
                <Square className="h-3.5 w-3.5 sm:h-4 sm:w-4" fill="currentColor" />
              </button>
            ) : showVoiceSendButton ? (
              <button
                type="button"
                onClick={onVoiceSend}
                disabled={voiceSendDisabled}
                title={voiceSendLabel}
                aria-label={voiceSendLabel}
                className={cn(
                  'rounded-full p-2 shadow-sm transition-all duration-300 sm:p-2.5',
                  voiceSendDisabled
                    ? 'cursor-not-allowed bg-gray-100 text-gray-300'
                    : 'bg-primary-600 text-white shadow-md hover:bg-primary-700 active:scale-95',
                )}
              >
                <Send className="h-4 w-4 sm:h-5 sm:w-5" />
              </button>
            ) : (
              <button
                type={sendButtonType}
                onClick={sendButtonType === 'button' ? onSend : undefined}
                disabled={sendDisabled}
                title={sendLabel}
                aria-label={sendLabel}
                className={cn(
                  'rounded-full p-2 shadow-sm transition-all duration-300 sm:p-2.5',
                  sendDisabled
                    ? 'cursor-not-allowed bg-gray-100 text-gray-300'
                    : 'bg-primary-600 text-white shadow-md hover:bg-primary-700 active:scale-95',
                )}
              >
                <Send className="h-4 w-4 sm:h-5 sm:w-5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}