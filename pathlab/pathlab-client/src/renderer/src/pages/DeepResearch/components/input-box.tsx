// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Loader2, Mic, MicOff, Paperclip, Pencil, Send, Square, X } from "lucide-react";
import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { AudioVisualizer } from "../../../components/common/AudioVisualizer";
import MessageInput, {
  type MessageInputRef,
} from "../../../components/deep-research/message-input";
import { useConfig } from "../../../lib/deep-research/api/hooks";
import { useTranslations } from "../../../lib/deep-research/i18n";
import type { Option, Resource } from "../../../lib/deep-research/messages";
import { useVoiceSession } from "../../../lib/useVoiceSession";
import { cn } from "../../../lib/utils";

export function InputBox({
  className,
  responding,
  feedback,
  onSend,
  onCancel,
  onRemoveFeedback,
}: {
  className?: string;
  responding?: boolean;
  feedback?: { option: Option } | null;
  onSend?: (
    message: string,
    options?: {
      interruptFeedback?: string;
      resources?: Array<Resource>;
    },
  ) => void;
  onCancel?: () => void;
  onRemoveFeedback?: () => void;
}) {
  const { config } = useConfig();
  const { t: tGlobal } = useTranslation();
  const t = useTranslations("messageInput");
  const inputRef = useRef<MessageInputRef>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [currentPrompt, setCurrentPrompt] = useState("");
  const [voiceAwaitingResponse, setVoiceAwaitingResponse] = useState(false);
  const [voiceResponseStarted, setVoiceResponseStarted] = useState(false);

  // Auto-focus when feedback is set (e.g. user clicked "Edit plan")
  useEffect(() => {
    if (feedback) {
      inputRef.current?.focus();
    }
  }, [feedback]);

  const appendToInput = useCallback((text: string) => {
    const next = currentPrompt.trim().length
      ? `${currentPrompt}\n${text}`
      : text;
    inputRef.current?.setContent(next);
    setCurrentPrompt(next);
  }, [currentPrompt]);

  const handleSendMessage = useCallback(
    (message: string, resources: Array<Resource>) => {
      if (responding) {
        onCancel?.();
      } else {
        if (message.trim() === "") {
          return;
        }
        if (onSend) {
          onSend(message, {
            interruptFeedback: feedback?.option.value,
            resources,
          });
          onRemoveFeedback?.();
        }
      }
    },
    [responding, onCancel, onSend, feedback, onRemoveFeedback],
  );

  const {
    voiceState,
    partialText: realtimePartialText,
    mediaStream: realtimeMediaStream,
    toggle: toggleVoiceSession,
    stop: stopVoiceSession,
    forceSend: voiceForceSend,
  } = useVoiceSession({
    onTranscript: (transcript) => {
      const next = currentPrompt.trim().length
        ? `${currentPrompt} ${transcript}`
        : transcript;
      inputRef.current?.setContent(next);
      setCurrentPrompt(next);
      setVoiceAwaitingResponse(true);
      setVoiceResponseStarted(false);
      setTimeout(() => {
        inputRef.current?.submit();
      }, 80);
    },
    onError: (error) => {
      console.error("[DeepResearch Voice] Error:", error);
      setVoiceAwaitingResponse(false);
      setVoiceResponseStarted(false);
    },
    silenceDurationMs: 800,
    maxRecordingSeconds: 120,
  });

  const voiceSessionActive = voiceState !== "idle";
  const realtimeIsRecording = voiceState === "recording";
  const realtimeIsConnecting = voiceState === "connecting";

  useEffect(() => {
    if (!voiceAwaitingResponse) {
      return;
    }
    if (responding && !voiceResponseStarted) {
      setVoiceResponseStarted(true);
      return;
    }
    if (!responding && voiceResponseStarted) {
      setVoiceAwaitingResponse(false);
      setVoiceResponseStarted(false);
      stopVoiceSession();
    }
  }, [responding, stopVoiceSession, voiceAwaitingResponse, voiceResponseStarted]);

  const handleVoiceSessionToggle = useCallback(() => {
    if (voiceSessionActive) {
      setVoiceAwaitingResponse(false);
      setVoiceResponseStarted(false);
    }
    toggleVoiceSession();
  }, [toggleVoiceSession, voiceSessionActive]);

  const handleCancelResponse = useCallback(() => {
    onCancel?.();
    if (voiceSessionActive) {
      setVoiceAwaitingResponse(false);
      setVoiceResponseStarted(false);
      stopVoiceSession();
    }
  }, [onCancel, stopVoiceSession, voiceSessionActive]);

  const handleFileSelect = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const snippets: string[] = [];
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const lowerName = file.name.toLowerCase();
      const isTextLike =
        file.type.startsWith("text/") ||
        lowerName.endsWith(".md") ||
        lowerName.endsWith(".txt") ||
        lowerName.endsWith(".csv") ||
        lowerName.endsWith(".json");

      if (isTextLike) {
        try {
          const content = await file.text();
          const clipped = content.slice(0, 3000);
          snippets.push(`\n[Attached: ${file.name}]\n${clipped}`);
        } catch {
          snippets.push(`\n[Attached file: ${file.name}]`);
        }
      } else {
        snippets.push(`\n[Attached file: ${file.name}]`);
      }
    }

    appendToInput(snippets.join("\n"));
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, [appendToInput]);

  return (
    <div className={cn("relative group", className)}>
      {feedback && (
        <div className="mb-2 flex items-center gap-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-800 animate-in fade-in slide-in-from-bottom-2 duration-200">
          <Pencil className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">{feedback.option.text}</span>
          <button
            type="button"
            className="shrink-0 rounded-full p-0.5 hover:bg-amber-200/60 transition-colors"
            onClick={() => onRemoveFeedback?.()}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      <div
        className={cn(
          "relative flex min-h-[56px] items-center border bg-white/80 py-1.5 pl-4 pr-[104px] sm:pr-[120px] backdrop-blur-xl transition-all duration-300 rounded-[28px]",
          feedback
            ? "border-amber-300 shadow-[0_8px_32px_rgba(0,0,0,0.12)]"
            : (realtimeIsRecording || realtimeIsConnecting || voiceSessionActive)
              ? "border-primary-300 shadow-[0_0_0_4px_rgba(102,126,234,0.15)] bg-white/90"
              : "border-gray-200/50 hover:border-gray-300/80 hover:shadow-[0_8px_40px_rgba(0,0,0,0.15)] shadow-[0_8px_32px_rgba(0,0,0,0.12)]",
        )}
      >
        <MessageInput
          className={cn(
            "min-h-[52px] w-full px-0 pt-0 transition-opacity duration-200",
            voiceSessionActive && "pointer-events-none opacity-0",
          )}
          placeholder={feedback ? t("modifyPlanPlaceholder") : undefined}
          ref={inputRef}
          config={config}
          onEnter={handleSendMessage}
          onChange={setCurrentPrompt}
        />
        {(realtimeIsRecording || realtimeIsConnecting) && (
          <div className="pointer-events-none absolute left-4 right-[140px] top-0 bottom-0 flex items-center">
            {realtimePartialText ? (
              <div className="flex w-full items-center gap-2 overflow-hidden text-[15px] leading-relaxed text-gray-700">
                <span className="truncate">{realtimePartialText}</span>
                <span className="inline-flex flex-shrink-0 gap-0.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: "0ms" }} />
                  <span className="h-1.5 w-1.5 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: "150ms" }} />
                  <span className="h-1.5 w-1.5 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: "300ms" }} />
                </span>
              </div>
            ) : (
              <AudioVisualizer
                stream={realtimeMediaStream}
                isActive={realtimeIsRecording}
                className="h-12 w-full opacity-80"
              />
            )}
          </div>
        )}
        {voiceSessionActive && !realtimeIsRecording && !realtimeIsConnecting && voiceAwaitingResponse && (
          <div className="pointer-events-none absolute left-4 right-[140px] top-0 bottom-0 flex items-center justify-center">
            <span className="flex items-center gap-2 text-sm font-medium text-primary-600 animate-pulse">
              <div className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: "0ms" }} />
              <div className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: "150ms" }} />
              <div className="h-2 w-2 rounded-full bg-primary-500 animate-bounce" style={{ animationDelay: "300ms" }} />
              {tGlobal("aiChat.thinking")}
            </span>
          </div>
        )}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".txt,.md,.csv,.json,text/plain,text/markdown,text/csv,application/json"
          onChange={handleFileSelect}
          className="hidden"
        />
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-1 sm:gap-1.5">
          {!realtimeIsRecording && !realtimeIsConnecting && !voiceSessionActive && (
            <button
              type="button"
              className="rounded-full p-2 text-gray-400 transition-all hover:bg-gray-100 hover:text-gray-600 active:scale-95 sm:p-2.5 disabled:opacity-50"
              title={tGlobal("aiChat.attachFile")}
              aria-label={tGlobal("aiChat.attachFile")}
              onClick={() => fileInputRef.current?.click()}
              disabled={responding}
            >
              <Paperclip className="h-4 w-4 sm:h-5 sm:w-5" />
            </button>
          )}
          <button
            type="button"
            className={cn(
              "rounded-full p-2 transition-all duration-300 active:scale-95 sm:p-2.5",
              realtimeIsRecording
                ? "bg-red-50 text-red-500 hover:bg-red-100"
                : realtimeIsConnecting
                  ? "bg-primary-50 text-primary-500"
                  : voiceSessionActive
                    ? "bg-primary-500 text-white shadow-md"
                    : "text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50",
            )}
            title={voiceSessionActive || realtimeIsRecording ? tGlobal("aiChat.stopVoiceInput") : tGlobal("aiChat.voiceInput")}
            aria-label={voiceSessionActive || realtimeIsRecording ? tGlobal("aiChat.stopVoiceInput") : tGlobal("aiChat.voiceInput")}
            onClick={handleVoiceSessionToggle}
            disabled={responding && !voiceSessionActive}
          >
            {realtimeIsConnecting ? (
              <Loader2 className="h-4 w-4 animate-spin sm:h-5 sm:w-5" />
            ) : realtimeIsRecording ? (
              <Square className="h-3.5 w-3.5 sm:h-4 sm:w-4" fill="currentColor" />
            ) : voiceSessionActive ? (
              <MicOff className="h-4 w-4 sm:h-5 sm:w-5" />
            ) : (
              <Mic className="h-4 w-4 sm:h-5 sm:w-5" />
            )}
          </button>
          {responding ? (
            <button
              type="button"
              className="rounded-full p-2 sm:p-2.5 transition-all duration-300 shadow-sm bg-gray-800 text-white hover:bg-gray-900 shadow-md active:scale-95"
              onClick={handleCancelResponse}
            >
              <Square className="h-3.5 w-3.5 sm:h-4 sm:w-4" fill="currentColor" />
            </button>
          ) : realtimeIsRecording ? (
            <button
              type="button"
              className={cn(
                "rounded-full p-2 sm:p-2.5 transition-all duration-300 shadow-sm",
                !realtimePartialText?.trim()
                  ? "cursor-not-allowed bg-gray-100 text-gray-300"
                  : "bg-primary-600 text-white shadow-md hover:bg-primary-700 active:scale-95",
              )}
              disabled={!realtimePartialText?.trim()}
              aria-label={tGlobal("aiChat.sendVoiceMessage")}
              onClick={() => {
                setVoiceAwaitingResponse(true);
                setVoiceResponseStarted(false);
                voiceForceSend(realtimePartialText);
              }}
            >
              <Send className="h-4 w-4 sm:h-5 sm:w-5" />
            </button>
          ) : (
            <button
              type="button"
              className={cn(
                "rounded-full p-2 sm:p-2.5 transition-all duration-300 shadow-sm",
                currentPrompt.trim().length === 0
                  ? "cursor-not-allowed bg-gray-100 text-gray-300"
                  : "bg-primary-600 text-white shadow-md hover:bg-primary-700 active:scale-95",
              )}
              disabled={currentPrompt.trim().length === 0}
              onClick={() => inputRef.current?.submit()}
            >
              <Send className="h-4 w-4 sm:h-5 sm:w-5" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
