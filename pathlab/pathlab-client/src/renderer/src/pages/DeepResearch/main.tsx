// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT


import { type MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Clock, History, Loader2, MessageSquare, PanelLeft, Plus, Trash2, Menu, Wrench, ChevronRight, Database, Brain, LineChart } from "lucide-react";

import { useTranslations } from "../../lib/deep-research/i18n";
import { loadConversationFromBackend, resetDeepResearchSession, useStore } from "../../lib/deep-research/store";
import { deleteConversation, getConversations, type Conversation } from "../../api";
import { cn } from "../../lib/utils";
import { Button } from "../../components/ui/button";
import { useTranslation } from "react-i18next";

import { MessagesBlock } from "./components/messages-block";
import { ResearchBlock } from "./components/research-block";

export default function Main() {
  const { t: tGlobal } = useTranslation();
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.main");
  const navigate = useNavigate();
  const location = useLocation();
  const { conversationId: urlConversationId } = useParams<{ conversationId?: string }>();
  const forceNewSession = useMemo(
    () => new URLSearchParams(location.search).get("new") === "1",
    [location.search],
  );
  const [showHistory, setShowHistory] = useState(() => {
    if (window.innerWidth < 1024) {
      return false;
    }
    const saved = localStorage.getItem("ai-chat-sidebar-open");
    if (saved !== null) {
      return saved === "true";
    }
    return true;
  });

  useEffect(() => {
    localStorage.setItem("ai-chat-sidebar-open", String(showHistory));
  }, [showHistory]);

  useEffect(() => {
    const handleToggle = () => setShowHistory((prev) => !prev);
    window.addEventListener("toggle-ai-sidebar", handleToggle);
    return () => window.removeEventListener("toggle-ai-sidebar", handleToggle);
  }, []);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const skipNextHydrationRef = useRef<string | null>(null);
  const conversationId = useStore((state) => state.conversationId);
  const openResearchId = useStore((state) => state.openResearchId);
  const doubleColumnMode = useMemo(
    () => openResearchId !== null,
    [openResearchId],
  );

  const loadConversationList = async () => {
    try {
      setLoadingConversations(true);
      const data = await getConversations(0, 100);
      setConversations(data);
    } catch (error) {
      console.warn("[DeepResearch] Failed to load conversations:", error);
    } finally {
      setLoadingConversations(false);
    }
  };

  const openConversation = (targetConversationId: string) => {
    navigate(`/deep-research/${targetConversationId}`);
    setShowHistory(false);
  };

  const handleNewChat = () => {
    resetDeepResearchSession();
    navigate("/dashboard", { replace: true });
    setShowHistory(false);
  };

  const handleDeleteConversation = async (
    targetConversationId: string,
    e: MouseEvent,
  ) => {
    e.stopPropagation();
    if (!confirm(t("deleteConversationConfirm"))) {
      return;
    }
    try {
      await deleteConversation(targetConversationId);
      await loadConversationList();
      if (conversationId === targetConversationId) {
        handleNewChat();
      }
    } catch (error) {
      console.warn("[DeepResearch] Failed to delete conversation:", error);
    }
  };

  const handleDeleteAllHistory = async () => {
    if (conversations.length === 0) {
      return;
    }
    if (!confirm(t("deleteAllConfirm"))) {
      return;
    }
    try {
      await Promise.all(conversations.map((conv) => deleteConversation(conv.conversation_id)));
      await loadConversationList();
      handleNewChat();
    } catch (error) {
      console.warn("[DeepResearch] Failed to delete all conversations:", error);
    }
  };

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
    void loadConversationList();
  }, []);

  useEffect(() => {
    if (showHistory) {
      void loadConversationList();
    }
  }, [showHistory, conversationId]);

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

  return (
    <div className="flex h-full bg-gray-50 relative overflow-hidden">
      {showHistory && (
        <div
          className="fixed top-16 inset-x-0 bottom-0 bg-black/20 z-30 lg:hidden backdrop-blur-sm transition-opacity"
          onClick={() => setShowHistory(false)}
        />
      )}
      <div
        className={`bg-gray-50 border-r border-gray-200 flex flex-col overflow-hidden
          fixed top-16 bottom-0 left-0 z-40 w-72 transition-transform duration-300 ease-in-out
          ${showHistory ? 'translate-x-0' : '-translate-x-full'}
          lg:relative lg:top-auto lg:bottom-auto lg:z-auto lg:flex-shrink-0 lg:translate-x-0 lg:transition-all
          ${showHistory ? 'lg:w-72' : 'lg:w-14'}
        `}
        role="navigation"
        aria-label={t("history")}
      >
        <div className={`hidden lg:flex items-center gap-1 p-2 pt-3 ${showHistory ? 'px-3' : 'flex-col'}`}>
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="p-2 text-gray-500 hover:text-gray-900 hover:bg-gray-100 rounded-full transition-colors flex-shrink-0"
            title={showHistory ? tGlobal("aiChat.closeChatHistory") : tGlobal("aiChat.openChatHistory")}
          >
            <Menu className="w-5 h-5" />
          </button>
        </div>

        <div className={`w-[268px] min-w-[268px] flex flex-col flex-1 overflow-hidden transition-opacity duration-300 ease-in-out pt-6 lg:pt-0 ${showHistory ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}>
          <div className="px-3 pb-3 pt-0">
            <button
              onClick={handleNewChat}
              className="w-full px-4 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-xl hover:bg-gray-800 transition-all shadow-sm flex items-center justify-center gap-2"
            >
              <Plus className="w-4 h-4" />
              {tGlobal("aiChat.newChat")}
            </button>
          </div>

          <div className="px-3 pb-2 border-b border-gray-100">
            <div className="flex items-center gap-2 px-2 mb-2">
              <Wrench className="w-4 h-4 text-gray-400" />
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">{tGlobal("aiChat.sidebar.tools")}</h3>
            </div>
            <div className="space-y-0.5">
              <button
                onClick={() => { navigate('/register'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-orange-50 hover:text-orange-700 transition-colors group"
              >
                <Plus className="w-4 h-4 text-orange-500 group-hover:text-orange-600" />
                <span className="flex-1 text-left">{tGlobal("aiChat.sidebar.registerData")}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-orange-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
              <button
                onClick={() => { navigate('/wsi-list'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-blue-50 hover:text-blue-700 transition-colors group"
              >
                <Database className="w-4 h-4 text-blue-500 group-hover:text-blue-600" />
                <span className="flex-1 text-left">{tGlobal("aiChat.sidebar.dataRepository")}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
              <button
                onClick={() => { navigate('/task-list'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-violet-50 hover:text-violet-700 transition-colors group"
              >
                <Brain className="w-4 h-4 text-violet-500 group-hover:text-violet-600" />
                <span className="flex-1 text-left">{tGlobal("aiChat.sidebar.analysisLab")}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-violet-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
              <button
                onClick={() => { navigate('/tools'); setShowHistory(false) }}
                className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm text-gray-700 hover:bg-emerald-50 hover:text-emerald-700 transition-colors group"
              >
                <LineChart className="w-4 h-4 text-emerald-500 group-hover:text-emerald-600" />
                <span className="flex-1 text-left">{tGlobal("aiChat.sidebar.insightsReports")}</span>
                <ChevronRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-emerald-400 opacity-0 group-hover:opacity-100 transition-all" />
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between px-5 pt-3 pb-1">
            <div className="flex items-center gap-2">
              <History className="w-4 h-4 text-gray-400" />
              <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-widest">{t("history")}</h3>
            </div>
            {conversations.length > 0 && (
              <button
                onClick={handleDeleteAllHistory}
                className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                title={t("deleteAllHistory")}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
          </div>
          <div className="flex-1 overflow-y-auto p-3">
            {loadingConversations ? (
              <div className="flex flex-col items-center justify-center py-12">
                <Loader2 className="w-8 h-8 text-primary-500 animate-spin mb-3" />
                <p className="text-sm text-gray-500">{t("loadingConversations")}</p>
              </div>
            ) : conversations.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-center">
                <div className="w-16 h-16 rounded-full bg-gray-50 flex items-center justify-center mb-3">
                  <MessageSquare className="w-8 h-8 text-gray-300" />
                </div>
                <p className="text-sm font-medium text-gray-900 mb-1">{t("noConversations")}</p>
                <p className="text-xs text-gray-500">{t("startNewChat")}</p>
              </div>
            ) : (
              <div className="space-y-2">
                {conversations.map((item) => (
                  <div
                    key={item.conversation_id}
                    onClick={() => openConversation(item.conversation_id)}
                    className={cn(
                      "group relative p-3 rounded-xl cursor-pointer transition-all border",
                      conversationId === item.conversation_id
                        ? "bg-primary-50 border-primary-200 shadow-sm"
                        : "hover:bg-gray-50 border-transparent hover:border-gray-100",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <h3
                          className={cn(
                            "text-sm font-medium truncate mb-1",
                            conversationId === item.conversation_id
                              ? "text-primary-900"
                              : "text-gray-900",
                          )}
                        >
                          {item.title || t("untitledConversation")}
                        </h3>
                        <div className="flex items-center gap-1 text-xs text-gray-500">
                          <Clock className="w-3 h-3" />
                          {new Date(item.updated_at).toLocaleDateString([], {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })}
                        </div>
                      </div>
                      <button
                        onClick={(e) => handleDeleteConversation(item.conversation_id, e)}
                        className="sm:opacity-0 sm:group-hover:opacity-100 p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-all"
                        title={t("deleteConversation")}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
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
    </div >
  );
}
