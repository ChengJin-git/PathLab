import { useTranslations } from "../../../lib/deep-research/i18n";
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  const conversationLockPhase = useStore((state) => {
    const hasAcceptedPlanSubmission =
      state.responding &&
      Array.from(state.planActionLocks.values()).some((action) => action === "accepted");
    if (hasAcceptedPlanSubmission) {
      return "researching" as const;
    }

    const latestStartedResearchId = [...state.researchIds].reverse().find((researchId) => {
      const runStatus = state.researchRunStatus.get(researchId);
      const reportId = state.researchReportIds.get(researchId);
      const hasExecutionActivity = (state.researchActivityIds.get(researchId) ?? []).some((messageId) => {
        const message = state.messages.get(messageId);
        return !!message && message.agent !== "planner";
      });

      return (
        state.ongoingResearchId === researchId ||
        !!reportId ||
        hasExecutionActivity ||
        runStatus === "running" ||
        runStatus === "success" ||
        runStatus === "error" ||
        runStatus === "cancelled"
      );
    });

    if (!latestStartedResearchId) {
      return "idle" as const;
    }

    const reportId = state.researchReportIds.get(latestStartedResearchId);
    const reportMessage = reportId ? state.messages.get(reportId) : undefined;
    const runStatus = state.researchRunStatus.get(latestStartedResearchId);

    if (reportMessage?.isStreaming) {
      return "generatingReport" as const;
    }

    if (
      (!!reportMessage && (reportMessage.content ?? "").trim().length > 0) ||
      (runStatus === "success" && !!reportId)
    ) {
      return "reportGenerated" as const;
    }

    if (runStatus === "cancelled" || state.cancelledResearchIds.has(latestStartedResearchId)) {
      return "cancelled" as const;
    }

    if (runStatus === "error") {
      return "error" as const;
    }

    return "researching" as const;
  });
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

  const lockPanelCopy = useMemo(() => {
    switch (conversationLockPhase) {
      case "generatingReport":
        return {
          title: t("generatingReport"),
          description: t("singleResearchPerConversation"),
          icon: <Loader2 className="h-5 w-5 animate-spin" />,
        };
      case "reportGenerated":
        return {
          title: t("reportGenerated"),
          description: t("singleResearchPerConversation"),
          icon: <CheckCircle2 className="h-5 w-5" />,
        };
      case "cancelled":
        return {
          title: t("researchCancelled"),
          description: t("singleResearchPerConversation"),
          icon: <AlertCircle className="h-5 w-5" />,
        };
      case "error":
        return {
          title: t("researchFailedNetwork"),
          description: t("singleResearchPerConversation"),
          icon: <AlertCircle className="h-5 w-5" />,
        };
      case "researching":
      default:
        return {
          title: t("researching"),
          description: t("singleResearchPerConversation"),
          icon: <Loader2 className="h-5 w-5 animate-spin" />,
        };
    }
  }, [conversationLockPhase, t]);

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
            {conversationLocked ? (
              <div className="rounded-[28px] border border-emerald-100 bg-white/90 px-4 py-3 shadow-[0_8px_32px_rgba(0,0,0,0.12)] backdrop-blur-xl">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
                    {lockPanelCopy.icon}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold text-gray-900">{lockPanelCopy.title}</div>
                    <div className="mt-0.5 text-sm text-gray-500">{lockPanelCopy.description}</div>
                  </div>
                  {conversationLockPhase === "reportGenerated" ? (
                    <Button className="shrink-0 rounded-full" size="sm" onClick={handleStartNewAIChat}>
                      {tGlobal("aiChat.newChat")}
                    </Button>
                  ) : responding ? (
                    <Button className="shrink-0 rounded-full" size="sm" variant="secondary" onClick={handleCancel}>
                      {tGlobal("aiChat.stopGenerating")}
                    </Button>
                  ) : null}
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
