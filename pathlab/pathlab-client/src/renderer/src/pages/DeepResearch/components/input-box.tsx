// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Pencil, X } from "lucide-react";
import { type ChangeEvent, useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChatInputShell } from "../../../components/common/ChatInputShell";
import { VoiceSessionOverlay } from "../../../components/common/VoiceSessionOverlay";
import MessageInput, {
  type MessageInputRef,
} from "../../../components/deep-research/message-input";
import { useConfig } from "../../../lib/deep-research/api/hooks";
import { useTranslations } from "../../../lib/deep-research/i18n";
import type { Option, Resource } from "../../../lib/deep-research/messages";
import { useStore } from "../../../lib/deep-research/store";
import { useVoiceSession } from "../../../lib/useVoiceSession";

export function InputBox({
  className,
  responding,
  feedback,
  onSend,
  onCancel,
  onRemoveFeedback,
  onDraftChange,
}: {
  className?: string;
  responding?: boolean;
  feedback?: { option: Option } | null;
  onSend?: (
    message: string,
    options?: {
      interruptFeedback?: string;
      resources?: Array<Resource>;
      voiceSessionActive?: boolean;
    },
  ) => void;
  onCancel?: () => void;
  onRemoveFeedback?: () => void;
  onDraftChange?: (draft: string) => void;
}) {
  const { config } = useConfig();
  const { t: tGlobal } = useTranslation();
  const t = useTranslations("messageInput");
  const inputRef = useRef<MessageInputRef>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const currentPromptRef = useRef("");
  const voiceStateRef = useRef("idle");
  const [currentPrompt, setCurrentPrompt] = useState("");
  const [pendingVoiceDraft, setPendingVoiceDraft] = useState("");
  const [voiceAwaitingResponse, setVoiceAwaitingResponse] = useState(false);
  const [voiceResponseStarted, setVoiceResponseStarted] = useState(false);
  const generationPhase = useStore((state) => state.generationPhase);
  const latestAssistantContent = useStore((state) => {
    for (let i = state.messageIds.length - 1; i >= 0; i -= 1) {
      const messageId = state.messageIds[i];
      const message = messageId ? state.messages.get(messageId) : undefined;
      if (message?.role === "assistant") {
        return message.content ?? "";
      }
    }
    return "";
  });

  useEffect(() => {
    onDraftChange?.(currentPrompt);
  }, [currentPrompt, onDraftChange]);

  // Auto-focus when feedback is set (e.g. user clicked "Edit plan")
  useEffect(() => {
    if (feedback) {
      inputRef.current?.focus();
    }
  }, [feedback]);

  const appendToInput = useCallback((text: string) => {
    const base = currentPromptRef.current.trim();
    const next = base.length
      ? `${base}\n${text}`
      : text;
    inputRef.current?.setContent(next);
    currentPromptRef.current = next;
    setCurrentPrompt(next);
  }, []);

  const handleSendMessage = useCallback(
    (message: string, resources: Array<Resource>) => {
      if (responding) {
        onCancel?.();
        return;
      }

      const trimmed = message.trim();
      if (trimmed === "") {
        return;
      }

      if (onSend) {
        onSend(trimmed, {
          interruptFeedback: feedback?.option.value,
          resources,
          voiceSessionActive: voiceStateRef.current !== "idle",
        });
        currentPromptRef.current = "";
        setCurrentPrompt("");
        onRemoveFeedback?.();
      }
    },
    [responding, onCancel, onSend, feedback, onRemoveFeedback],
  );

  const submitVoiceDraft = useCallback((next: string) => {
    const trimmed = next.trim();
    if (!trimmed) {
      return;
    }

    inputRef.current?.setContent(trimmed);
    currentPromptRef.current = trimmed;
    setCurrentPrompt(trimmed);
    setPendingVoiceDraft(trimmed);
    setVoiceAwaitingResponse(true);
    setVoiceResponseStarted(false);

    setTimeout(() => {
      handleSendMessage(trimmed, []);
      inputRef.current?.setContent("");
    }, 50);
  }, [handleSendMessage]);

  const {
    voiceState,
    partialText: realtimePartialText,
    mediaStream: realtimeMediaStream,
    toggle: toggleVoiceSession,
    stop: stopVoiceSession,
    forceSend: voiceForceSend,
    notifyResponseComplete: notifyVoiceResponseComplete,
  } = useVoiceSession({
    onTranscript: (transcript) => {
      const base = currentPromptRef.current.trim();
      const next = base.length
        ? `${base} ${transcript}`
        : transcript;
      submitVoiceDraft(next);
    },
    onError: (error) => {
      console.error("[DeepResearch Voice] Error:", error);
      setPendingVoiceDraft("");
      setVoiceAwaitingResponse(false);
      setVoiceResponseStarted(false);
    },
    silenceDurationMs: 800,
    maxRecordingSeconds: 120,
  });

  voiceStateRef.current = voiceState;

  const voiceSessionActive = voiceState !== "idle";
  const realtimeIsRecording = voiceState === "recording";
  const realtimeIsConnecting = voiceState === "connecting";

  useEffect(() => {
    if (!voiceAwaitingResponse) {
      return;
    }
    if (responding && !voiceResponseStarted) {
      setPendingVoiceDraft("");
      setVoiceResponseStarted(true);
      return;
    }
    if (!responding && voiceResponseStarted) {
      setPendingVoiceDraft("");
      setVoiceAwaitingResponse(false);
      setVoiceResponseStarted(false);
      notifyVoiceResponseComplete(latestAssistantContent);
    }
  }, [
    latestAssistantContent,
    notifyVoiceResponseComplete,
    responding,
    voiceAwaitingResponse,
    voiceResponseStarted,
  ]);

  const handleVoiceSessionToggle = useCallback(() => {
    if (voiceSessionActive) {
      setPendingVoiceDraft("");
      setVoiceAwaitingResponse(false);
      setVoiceResponseStarted(false);
    }
    toggleVoiceSession();
  }, [toggleVoiceSession, voiceSessionActive]);

  const handleCancelResponse = useCallback(() => {
    onCancel?.();
    if (voiceSessionActive) {
      setPendingVoiceDraft("");
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
    <ChatInputShell
      className={className}
      topContent={feedback ? (
        <div className="mb-2 flex items-center gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 animate-in fade-in slide-in-from-bottom-2 duration-200">
          <Pencil className="h-3.5 w-3.5 shrink-0" />
          <span className="flex-1">{feedback.option.text}</span>
          <button
            type="button"
            className="shrink-0 rounded-full p-0.5 transition-colors hover:bg-amber-200/60"
            onClick={() => onRemoveFeedback?.()}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}
      shellTone={feedback ? "feedback" : voiceSessionActive ? "voice" : "default"}
      editor={(
        <MessageInput
          className="min-h-[52px] w-full px-0 pt-0"
          placeholder={feedback ? t("modifyPlanPlaceholder") : undefined}
          ref={inputRef}
          config={config}
          onEnter={handleSendMessage}
          onChange={(next) => {
            currentPromptRef.current = next;
            setCurrentPrompt(next);
          }}
        />
      )}
      editorHidden={voiceSessionActive}
      hiddenInput={(
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".txt,.md,.csv,.json,text/plain,text/markdown,text/csv,application/json"
          onChange={handleFileSelect}
          className="hidden"
        />
      )}
      overlay={(
        <VoiceSessionOverlay
          partialText={realtimePartialText}
          pendingText={pendingVoiceDraft}
          mediaStream={realtimeMediaStream}
          isRecording={realtimeIsRecording}
          isConnecting={realtimeIsConnecting}
          isThinking={voiceSessionActive && !realtimeIsRecording && !realtimeIsConnecting && (generationPhase === "thinking" || (voiceAwaitingResponse && !voiceResponseStarted))}
          thinkingLabel={tGlobal("aiChat.thinking")}
        />
      )}
      showAttachButton={!realtimeIsRecording && !realtimeIsConnecting && !voiceSessionActive}
      onAttachClick={() => fileInputRef.current?.click()}
      attachLabel={tGlobal("aiChat.attachFile")}
      attachDisabled={responding}
      voiceButtonState={realtimeIsRecording ? "recording" : realtimeIsConnecting ? "connecting" : voiceSessionActive ? "active" : "idle"}
      onVoiceToggle={handleVoiceSessionToggle}
      voiceLabel={tGlobal("aiChat.voiceInput")}
      stopVoiceLabel={tGlobal("aiChat.stopVoiceInput")}
      voiceDisabled={responding && !voiceSessionActive}
      responding={responding}
      onStopResponding={handleCancelResponse}
      stopRespondingLabel={tGlobal("aiChat.stopGenerating")}
      showVoiceSendButton={realtimeIsRecording}
      onVoiceSend={() => voiceForceSend(realtimePartialText)}
      voiceSendDisabled={!realtimePartialText?.trim()}
      voiceSendLabel={tGlobal("aiChat.sendVoiceMessage")}
      onSend={() => inputRef.current?.submit()}
      sendDisabled={currentPrompt.trim().length === 0}
      sendLabel={tGlobal("aiChat.sendMessage")}
    />
  );
}
