// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Loader2, Mic, MicOff, Paperclip, Pencil, Send, X } from "lucide-react";
import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

import MessageInput, {
  type MessageInputRef,
} from "../../../components/deep-research/message-input";
import { useConfig } from "../../../lib/deep-research/api/hooks";
import type { Option, Resource } from "../../../lib/deep-research/messages";
import { useRealtimeASR } from "../../../lib/useRealtimeASR";
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
  const { config, loading } = useConfig();
  const inputRef = useRef<MessageInputRef>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [currentPrompt, setCurrentPrompt] = useState("");
  const [isVoiceSessionActive, setIsVoiceSessionActive] = useState(false);
  const [realtimePartialText, setRealtimePartialText] = useState("");

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

  const handleTranscriptComplete = useCallback((transcript: string) => {
    const next = currentPrompt.trim().length
      ? `${currentPrompt} ${transcript}`
      : transcript;
    inputRef.current?.setContent(next);
    setCurrentPrompt(next);
    setRealtimePartialText("");
    setTimeout(() => {
      inputRef.current?.submit();
    }, 80);
  }, [currentPrompt]);

  const {
    isRecording: realtimeIsRecording,
    isConnecting: realtimeIsConnecting,
    startRecording: startRealtimeRecording,
    stopRecording: stopRealtimeRecording,
  } = useRealtimeASR({
    onTranscriptComplete: handleTranscriptComplete,
    onPartialTranscript: (text) => {
      setRealtimePartialText(text);
    },
    onError: (error) => {
      console.error("[DeepResearch Voice] Error:", error);
      setIsVoiceSessionActive(false);
      setRealtimePartialText("");
    },
    silenceDurationMs: 800,
    maxRecordingSeconds: 120,
  });

  const toggleVoiceSession = useCallback(() => {
    if (realtimeIsRecording || realtimeIsConnecting || isVoiceSessionActive) {
      stopRealtimeRecording();
      setIsVoiceSessionActive(false);
      setRealtimePartialText("");
      return;
    }
    setIsVoiceSessionActive(true);
    void startRealtimeRecording();
  }, [
    realtimeIsRecording,
    realtimeIsConnecting,
    isVoiceSessionActive,
    startRealtimeRecording,
    stopRealtimeRecording,
  ]);

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
            : "border-gray-200/50 hover:border-gray-300/80 hover:shadow-[0_8px_40px_rgba(0,0,0,0.15)] shadow-[0_8px_32px_rgba(0,0,0,0.12)]",
        )}
      >
        <MessageInput
          className="h-[44px] w-full px-0 pt-0"
          placeholder={feedback ? "Describe how you'd like to modify the plan..." : "Describe your research task..."}
          ref={inputRef}
          loading={loading}
          config={config}
          onEnter={handleSendMessage}
          onChange={setCurrentPrompt}
        />
        {(realtimeIsRecording || realtimeIsConnecting) && (
          <div className="pointer-events-none absolute top-0 right-[140px] bottom-0 left-4 flex items-center text-[15px] text-gray-700">
            <span className="truncate">
              {realtimePartialText || "Listening..."}
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
        <div className="absolute right-1.5 bottom-1.5 flex items-center gap-1 sm:gap-1.5">
          <button
            type="button"
            className="rounded-full p-2 text-gray-400 transition-all hover:bg-gray-100 hover:text-gray-600 active:scale-95 sm:p-2.5 disabled:opacity-50"
            title="Attach file"
            onClick={() => fileInputRef.current?.click()}
            disabled={responding}
          >
            <Paperclip className="h-4 w-4 sm:h-5 sm:w-5" />
          </button>
          <button
            type="button"
            className={cn(
              "rounded-full p-2 transition-all active:scale-95 sm:p-2.5",
              realtimeIsRecording || realtimeIsConnecting || isVoiceSessionActive
                ? "bg-primary-500 text-white shadow-md"
                : "text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:opacity-50",
            )}
            title="Voice input"
            onClick={toggleVoiceSession}
            disabled={responding && !isVoiceSessionActive}
          >
            {realtimeIsConnecting ? (
              <Loader2 className="h-4 w-4 animate-spin sm:h-5 sm:w-5" />
            ) : realtimeIsRecording || isVoiceSessionActive ? (
              <MicOff className="h-4 w-4 sm:h-5 sm:w-5" />
            ) : (
              <Mic className="h-4 w-4 sm:h-5 sm:w-5" />
            )}
          </button>
          <button
            type="button"
            className={cn(
              "rounded-full p-2 sm:p-2.5 transition-all duration-300 shadow-sm",
              (!responding && currentPrompt.trim().length === 0)
                ? "cursor-not-allowed bg-gray-100 text-gray-300"
                : "bg-primary-600 text-white shadow-md hover:bg-primary-700 active:scale-95",
            )}
            disabled={!responding && currentPrompt.trim().length === 0}
            onClick={() => inputRef.current?.submit()}
          >
            {responding ? (
              <div className="h-4 w-4 rounded-sm bg-gray-500 opacity-80" />
            ) : (
              <Send className="h-4 w-4 sm:h-5 sm:w-5" />
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
