// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT


import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { loadConversationFromBackend, openResearch, resetDeepResearchSession, useStore } from "../../lib/deep-research/store";
import { cn } from "../../lib/utils";

import { MessagesBlock } from "./components/messages-block";
import { ResearchBlock } from "./components/research-block";

export default function Main() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation();
  const { conversationId: urlConversationId } = useParams<{ conversationId?: string }>();
  const navigationState = location.state as {
    focusResearchId?: string;
    focusConversationId?: string;
    returnToAIChatConversationId?: string;
  } | null;
  const isDeepResearchRoute = location.pathname.startsWith("/deep-research");
  const forceNewSession = useMemo(
    () => new URLSearchParams(location.search).get("new") === "1",
    [location.search],
  );

  const skipNextHydrationRef = useRef<string | null>(null);
  const focusResearchAppliedRef = useRef<string | null>(null);
  const [pendingHydrationConversationId, setPendingHydrationConversationId] = useState<string | null>(null);
  const conversationId = useStore((state) => state.conversationId);
  const messageCount = useStore((state) => state.messageIds.length);
  const researchCount = useStore((state) => state.researchIds.length);
  const responding = useStore((state) => state.responding);
  const openResearchId = useStore((state) => state.openResearchId);
  const doubleColumnMode = useMemo(
    () => openResearchId !== null,
    [openResearchId],
  );

  const handleBackToAIChat = useCallback(() => {
    const returnToAIChatConversationId =
      navigationState?.returnToAIChatConversationId?.trim() ||
      sessionStorage.getItem("ai-chat-conversation-id")?.trim() ||
      "";

    if (returnToAIChatConversationId) {
      sessionStorage.removeItem("ai-chat-conversation-id");
      navigate(`/dashboard/${returnToAIChatConversationId}`);
      return;
    }

    navigate("/dashboard");
  }, [navigate, navigationState]);

  useEffect(() => {
    if (!isDeepResearchRoute || !forceNewSession) {
      return;
    }
    resetDeepResearchSession();
    navigate("/deep-research", { replace: true, state: location.state });
  }, [forceNewSession, navigate, location.state, isDeepResearchRoute]);

  useEffect(() => {
    if (!isDeepResearchRoute || !urlConversationId) {
      setPendingHydrationConversationId(null);
      return;
    }
    // Skip one hydration when URL change is initiated by this page right after
    // creating/selecting a local conversation, to avoid clobbering in-flight state.
    if (skipNextHydrationRef.current === urlConversationId) {
      skipNextHydrationRef.current = null;
      setPendingHydrationConversationId(null);
      return;
    }
    let cancelled = false;
    setPendingHydrationConversationId(urlConversationId);
    void (async () => {
      try {
        await loadConversationFromBackend(urlConversationId);
      } finally {
        if (!cancelled) {
          setPendingHydrationConversationId((current) =>
            current === urlConversationId ? null : current,
          );
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [urlConversationId, isDeepResearchRoute]);

  useEffect(() => {
    if (!isDeepResearchRoute || forceNewSession) {
      return;
    }
    // Respect explicit URL navigation (e.g. clicking a history item).
    if (urlConversationId) {
      return;
    }
    if (!conversationId) {
      return;
    }
    skipNextHydrationRef.current = conversationId;
    navigate(`/deep-research/${conversationId}`, { replace: true, state: location.state });
  }, [conversationId, urlConversationId, navigate, forceNewSession, location.state, isDeepResearchRoute]);

  useEffect(() => {
    if (!isDeepResearchRoute) {
      return;
    }
    const focusResearchId = navigationState?.focusResearchId?.trim();
    const focusConversationId = navigationState?.focusConversationId?.trim();
    if (!focusResearchId) {
      return;
    }
    const effectiveConversationId = focusConversationId || urlConversationId || conversationId || "";
    if (!effectiveConversationId || conversationId !== effectiveConversationId) {
      return;
    }
    const applyKey = `${effectiveConversationId}:${focusResearchId}`;
    if (focusResearchAppliedRef.current === applyKey) {
      return;
    }
    openResearch(focusResearchId);
    focusResearchAppliedRef.current = applyKey;
  }, [navigationState, urlConversationId, conversationId, isDeepResearchRoute]);

  const showConversationHydration = Boolean(
    isDeepResearchRoute
    && urlConversationId
    && pendingHydrationConversationId === urlConversationId
    && (conversationId !== urlConversationId || (messageCount === 0 && researchCount === 0 && !responding)),
  );

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-gray-50">
      <div className="mx-auto flex w-full max-w-[1500px] px-4 pt-4">
        <button
          type="button"
          onClick={handleBackToAIChat}
          aria-label={t("deepResearchPage.backToAIChat")}
          className="inline-flex items-center gap-2 px-1 py-1 text-sm font-medium text-gray-500 transition-colors hover:text-gray-900"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>{t("deepResearchPage.backToAIChat")}</span>
        </button>
      </div>
      <div className="flex-1 flex flex-col min-w-0 h-full relative z-10 overflow-hidden">
        <div
          className={cn(
            "mx-auto flex min-h-0 flex-1 w-full max-w-[1500px] px-4 pt-3 pb-4",
            showConversationHydration ? "justify-center" : doubleColumnMode ? "gap-6 pb-16" : "justify-center",
          )}
        >
          {showConversationHydration ? (
            <div className="flex w-full max-w-4xl items-center justify-center">
              <div className="flex min-h-[320px] w-full flex-col items-center justify-center rounded-[28px] border border-gray-200/70 bg-white/85 px-6 py-12 text-center shadow-sm backdrop-blur-sm">
                <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-50 text-primary-600 shadow-sm">
                  <Loader2 className="h-7 w-7 animate-spin" />
                </div>
                <div className="text-base font-medium text-gray-900">{t("deepResearchPage.loadingDeepResearch")}</div>
                <div className="mt-2 text-sm text-gray-500">{t("deepResearchPage.restoringConversation")}</div>
              </div>
            </div>
          ) : (
            <>
              <MessagesBlock
                className={cn(
                  "min-w-0 transition-all duration-300 ease-out",
                  !doubleColumnMode && "w-full max-w-[980px]",
                  doubleColumnMode && "w-[43%] min-w-[520px] max-w-[720px]",
                )}
              />
              <ResearchBlock
                className={cn(
                  "min-w-0 transition-all duration-300 ease-out",
                  !doubleColumnMode && "pointer-events-none w-0 scale-95 opacity-0",
                  doubleColumnMode && "h-full w-[57%] self-stretch",
                )}
                researchId={openResearchId}
              />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
