import { useTranslations } from "../../../lib/deep-research/i18n";
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useCallback, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button } from "../../../components/ui/button";
import type { Option, Resource } from "../../../lib/deep-research/messages";
import { resetDeepResearchSession, sendMessage, useMessageIds, useStore } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";

import { ConversationStarter } from "./conversation-starter";
import { InputBox } from "./input-box";
import { MessageListView } from "./message-list-view";

import { useTranslation } from "react-i18next";

export function MessagesBlock({ className }: { className?: string }) {
  const { t: tGlobal } = useTranslation();
  const navigate = useNavigate();
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.messages");
  const messageIds = useMessageIds();
  const messageCount = messageIds.length;
  const responding = useStore((state) => state.responding);
  const [feedback, setFeedback] = useState<{ option: Option } | null>(null);
  const [draftPreviewText, setDraftPreviewText] = useState("");
  const abortControllerRef = useRef<AbortController | null>(null);
  const hasDraftPreview = draftPreviewText.trim().length > 0;
  const handleSend = useCallback(
    async (
      message: string,
      options?: {
        interruptFeedback?: string;
        resources?: Array<Resource>;
        voiceSessionActive?: boolean;
      },
    ) => {
      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      try {
        await sendMessage(
          message,
          {
            interruptFeedback:
              options?.interruptFeedback ?? feedback?.option.value,
            resources: options?.resources,
            voiceSessionActive: options?.voiceSessionActive,
          },
          {
            abortSignal: abortController.signal,
          },
        );
      } catch { }
    },
    [feedback],
  );
  const handleCancel = useCallback(() => {
    abortControllerRef.current?.abort("user_cancelled");
    abortControllerRef.current = null;
  }, []);
  const handleFeedback = useCallback(
    (feedback: { option: Option }) => {
      setFeedback(feedback);
    },
    [setFeedback],
  );
  const handleRemoveFeedback = useCallback(() => {
    setFeedback(null);
  }, [setFeedback]);
  const handleStartNewAIChat = useCallback(() => {
    resetDeepResearchSession();
    navigate("/dashboard", {
      replace: true,
      state: { forceNewChat: true },
    });
  }, [navigate]);
  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <div className="min-h-0 flex-1 overflow-hidden">
        {responding || messageCount !== 0 ? (
          <MessageListView
            className="flex h-full"
            onFeedback={handleFeedback}
            onSendMessage={handleSend}
            onNewChat={handleStartNewAIChat}
            draftPreviewText={draftPreviewText}
          />
        ) : hasDraftPreview ? (
          <MessageListView
            className="flex h-full"
            onFeedback={handleFeedback}
            onSendMessage={handleSend}
            onNewChat={handleStartNewAIChat}
            draftPreviewText={draftPreviewText}
            showConversationStarter
          />
        ) : (
          <ConversationStarter />
        )}
      </div>
      <div className="pointer-events-none fixed bottom-6 left-0 right-0 z-30 px-4 lg:left-[var(--sidebar-width,288px)] transition-[left] duration-300 ease-in-out">
        <div className="pointer-events-auto mx-auto max-w-4xl">
          <InputBox
            className="w-full"
            responding={responding}
            feedback={feedback}
            onSend={handleSend}
            onCancel={handleCancel}
            onRemoveFeedback={handleRemoveFeedback}
            onDraftChange={setDraftPreviewText}
          />
          <div className="mt-2 text-center text-xs text-gray-400/80 font-medium px-4 leading-relaxed">
            {tGlobal("aiChat.disclaimer")}
          </div>
        </div>
      </div>
    </div>
  );
}
