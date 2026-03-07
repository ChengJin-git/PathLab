import { useTranslations } from "../../../lib/deep-research/i18n";
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { CheckCircle2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import type { Option, Resource } from "../../../lib/deep-research/messages";
import { resetDeepResearchSession, sendMessage, useDeepResearchConversationLocked, useMessageIds, useStore } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";
import { Button } from "../../../components/ui/button";

import { ConversationStarter } from "./conversation-starter";
import { InputBox } from "./input-box";
import { MessageListView } from "./message-list-view";

import { useTranslation } from "react-i18next";

export function MessagesBlock({ className }: { className?: string }) {
  const { t: tGlobal } = useTranslation();
  const navigate = useNavigate();
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.research");
  const messageIds = useMessageIds();
  const messageCount = messageIds.length;
  const responding = useStore((state) => state.responding);
  const conversationLocked = useDeepResearchConversationLocked();
  const [feedback, setFeedback] = useState<{ option: Option } | null>(null);
  const [draftPreviewText, setDraftPreviewText] = useState("");
  const abortControllerRef = useRef<AbortController | null>(null);
  const hasDraftPreview = draftPreviewText.trim().length > 0;
  const openResearchId = useStore((state) => state.openResearchId);
  const doubleColumnMode = openResearchId !== null;

  useEffect(() => {
    if (!conversationLocked) {
      return;
    }
    setFeedback(null);
    setDraftPreviewText("");
  }, [conversationLocked]);

  const handleSend = useCallback(
    async (
      message: string,
      options?: {
        interruptFeedback?: string;
        resources?: Array<Resource>;
        voiceSessionActive?: boolean;
      },
    ) => {
      if (conversationLocked) {
        return;
      }
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
    [conversationLocked, feedback],
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
        <div className={cn("pointer-events-auto mx-auto w-full", doubleColumnMode ? "max-w-[1500px]" : "max-w-4xl")}>
          <div className={cn(doubleColumnMode ? "w-full lg:w-[43%] lg:min-w-[520px] lg:max-w-[720px]" : "mx-auto w-full max-w-4xl")}>
            {conversationLocked && !responding ? (
              <div className="rounded-[28px] border border-emerald-100 bg-white/90 px-4 py-3 shadow-[0_8px_32px_rgba(0,0,0,0.12)] backdrop-blur-xl">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
                    <CheckCircle2 className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-gray-900">{t("reportGenerated")}</div>
                    <div className="mt-0.5 text-sm text-gray-500">{t("singleResearchPerConversation")}</div>
                  </div>
                  <Button className="shrink-0 rounded-full" size="sm" onClick={handleStartNewAIChat}>
                    {tGlobal("aiChat.newChat")}
                  </Button>
                </div>
              </div>
            ) : (
              <InputBox
                className="w-full"
                responding={responding}
                feedback={feedback}
                onSend={handleSend}
                onCancel={handleCancel}
                onRemoveFeedback={handleRemoveFeedback}
                onDraftChange={setDraftPreviewText}
              />
            )}
            <div className="mt-2 px-4 text-center text-xs font-medium leading-relaxed text-gray-400/80">
              {tGlobal("aiChat.disclaimer")}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
