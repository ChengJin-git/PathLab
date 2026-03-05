// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT


import { useEffect, useMemo, useRef } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

import { loadConversationFromBackend, openResearch, resetDeepResearchSession, useStore } from "../../lib/deep-research/store";
import { cn } from "../../lib/utils";

import { MessagesBlock } from "./components/messages-block";
import { ResearchBlock } from "./components/research-block";

export default function Main() {
  const navigate = useNavigate();
  const location = useLocation();
  const { conversationId: urlConversationId } = useParams<{ conversationId?: string }>();
  const forceNewSession = useMemo(
    () => new URLSearchParams(location.search).get("new") === "1",
    [location.search],
  );

  const skipNextHydrationRef = useRef<string | null>(null);
  const focusResearchAppliedRef = useRef<string | null>(null);
  const conversationId = useStore((state) => state.conversationId);
  const openResearchId = useStore((state) => state.openResearchId);
  const doubleColumnMode = useMemo(
    () => openResearchId !== null,
    [openResearchId],
  );

  useEffect(() => {
    if (!forceNewSession) {
      return;
    }
    resetDeepResearchSession();
    navigate("/deep-research", { replace: true });
  }, [forceNewSession, navigate]);

  useEffect(() => {
    if (!urlConversationId) {
      return;
    }
    // Skip one hydration when URL change is initiated by this page right after
    // creating/selecting a local conversation, to avoid clobbering in-flight state.
    if (skipNextHydrationRef.current === urlConversationId) {
      skipNextHydrationRef.current = null;
      return;
    }
    void loadConversationFromBackend(urlConversationId);
  }, [urlConversationId]);

  useEffect(() => {
    if (forceNewSession) {
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
    navigate(`/deep-research/${conversationId}`, { replace: true });
  }, [conversationId, urlConversationId, navigate, forceNewSession]);

  useEffect(() => {
    const state = location.state as {
      focusResearchId?: string;
      focusConversationId?: string;
    } | null;
    const focusResearchId = state?.focusResearchId?.trim();
    const focusConversationId = state?.focusConversationId?.trim();
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
  }, [location.state, urlConversationId, conversationId]);

  return (
    <div className="flex h-full bg-gray-50 relative overflow-hidden">
      <div className="flex-1 flex flex-col min-w-0 h-full relative z-10 overflow-hidden">
        <div
          className={cn(
            "mx-auto flex min-h-0 flex-1 w-full max-w-[1500px] px-4 pt-3 pb-4",
            doubleColumnMode ? "gap-6 pb-16" : "justify-center",
          )}
        >
          <MessagesBlock
            className={cn(
              "min-w-0 transition-all duration-300 ease-out",
              !doubleColumnMode && "w-full max-w-4xl",
              doubleColumnMode && "w-[42%] min-w-[520px]",
            )}
          />
          <ResearchBlock
            className={cn(
              "min-w-0 transition-all duration-300 ease-out",
              !doubleColumnMode && "pointer-events-none w-0 scale-95 opacity-0",
              doubleColumnMode && "h-[calc(100%-4rem)] w-[58%] self-start",
            )}
            researchId={openResearchId}
          />
        </div>
      </div>
    </div>
  );
}
