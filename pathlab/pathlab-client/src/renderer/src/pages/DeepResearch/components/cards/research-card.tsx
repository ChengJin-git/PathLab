// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { nanoid } from "nanoid";
import i18n from "../../../../i18n";
import { createConversation as apiCreateChatConversation, addMessage as apiAddChatMessage, getConversation as apiGetConversation } from "../../../../api";
import { useTranslations } from "../../../../lib/deep-research/i18n";
import { stripResearchMeta } from "../../../../lib/deep-research/utils";
import { useNavigate } from "react-router-dom";
import { BookOpenText, Sparkles } from "lucide-react";

import { Badge } from "../../../../components/ui/badge";
import { Button } from "../../../../components/ui/button";
import { Card, CardFooter, CardHeader, CardTitle } from "../../../../components/ui/card";
import { closeResearch, flushDeepResearchPersistNow, openResearch, useResearchMessage, useStore } from "../../../../lib/deep-research/store";
import { cn } from "../../../../lib/utils";
import { parsePlannerPayload } from "../utils";

const REPORT_CONTEXT_MAX_CHARS = 8000;

/** Extract the first markdown H1/H2 heading from report content as a title fallback. */
function extractTitleFromReport(reportContent: string | undefined): string | undefined {
    if (!reportContent) return undefined;
    const match = reportContent.match(/^#{1,2}\s+(.+)/m);
    return match?.[1]?.trim() || undefined;
}

/** Clean and clip the report content for use as system-prompt context. */
function extractReportContext(reportContent: string | undefined): string {
    if (!reportContent) return "";
    const cleaned = stripResearchMeta(reportContent);
    if (!cleaned) return "";
    return cleaned.length > REPORT_CONTEXT_MAX_CHARS
        ? `${cleaned.slice(0, REPORT_CONTEXT_MAX_CHARS)}\n...(report truncated)`
        : cleaned;
}

function TrainingCard({
    existingTrainingLink,
    onStartTraining,
    t,
}: {
    existingTrainingLink: { conversation_id: string; title?: string } | null;
    onStartTraining: () => void;
    t: (key: string) => string;
}) {
    const navigate = useNavigate();
    // "checking" while we probe the backend on mount; "deleted" if 404
    const [linkStatus, setLinkStatus] = useState<"checking" | "ok" | "deleted">("checking");

    // Proactively verify the linked conversation exists as soon as the card appears
    useEffect(() => {
        if (!existingTrainingLink) return;
        let cancelled = false;
        setLinkStatus("checking");
        apiGetConversation(existingTrainingLink.conversation_id)
            .then(() => { if (!cancelled) setLinkStatus("ok"); })
            .catch(() => { if (!cancelled) setLinkStatus("deleted"); });
        return () => { cancelled = true; };
    }, [existingTrainingLink?.conversation_id]);

    const handleGo = useCallback(
        (e: React.MouseEvent) => {
            e.stopPropagation();
            if (!existingTrainingLink || linkStatus !== "ok") return;
            navigate(`/dashboard/${existingTrainingLink.conversation_id}`);
        },
        [existingTrainingLink, linkStatus, navigate],
    );

    if (existingTrainingLink) {
        const isDeleted = linkStatus === "deleted";
        const isChecking = linkStatus === "checking";
        return (
            <Card className="w-full overflow-hidden border-gray-200/70 bg-white/90 shadow-sm">
                <CardHeader className="border-b border-gray-100 bg-gradient-to-r from-primary-50/70 via-white to-white">
                    <div className="flex items-start gap-3">
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-primary-50 text-primary-600 shadow-sm">
                            <BookOpenText className="h-5 w-5" />
                        </div>
                        <div className="min-w-0">
                            <div className="mb-2">
                                <Badge className={isDeleted
                                    ? "border-red-100 bg-red-50 text-red-600 hover:bg-red-100"
                                    : "border-emerald-100 bg-emerald-50 text-emerald-700 hover:bg-emerald-100"
                                }>
                                    {isDeleted ? t("trainingDeleted") : t("continueTraining")}
                                </Badge>
                            </div>
                            <CardTitle className="text-lg font-semibold text-gray-900">
                                {existingTrainingLink.title || t("startTraining")}
                            </CardTitle>
                        </div>
                    </div>
                </CardHeader>
                <CardFooter className="flex flex-col items-stretch gap-3 bg-gray-50/60 sm:flex-row sm:items-center sm:justify-between">
                    <div className="flex w-full items-center gap-2">
                        <span className="flex-grow text-sm text-gray-500">
                            {isDeleted ? t("trainingDeletedDesc") : t("trainingStarted")}
                        </span>
                        {isDeleted ? (
                            <Button variant="default" onClick={onStartTraining} className="rounded-full">
                                {t("createNewTraining")}
                            </Button>
                        ) : (
                            <Button variant="default" disabled={isChecking} onClick={handleGo} className="rounded-full">
                                Go
                            </Button>
                        )}
                    </div>
                </CardFooter>
            </Card>
        );
    }

    return (
        <Card className="w-full overflow-hidden border-gray-200/70 bg-white/90 shadow-sm">
            <CardHeader className="border-b border-gray-100 bg-gradient-to-r from-primary-50/70 via-white to-white">
                <div className="flex items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-primary-50 text-primary-600 shadow-sm">
                        <BookOpenText className="h-5 w-5" />
                    </div>
                    <div>
                        <CardTitle className="text-lg font-semibold text-gray-900">{t("startTraining")}</CardTitle>
                    </div>
                </div>
            </CardHeader>
            <CardFooter className="flex flex-col items-stretch gap-3 bg-gray-50/60 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex w-full items-center gap-2">
                    <span className="flex-grow text-sm text-gray-500">{t("trainingDescription")}</span>
                    <Button onClick={onStartTraining} className="rounded-full">
                        {t("start")}
                    </Button>
                </div>
            </CardFooter>
        </Card>
    );
}

export function ResearchCard({
    className,
    researchId,
    onToggleResearch,
    onSendMessage,
    restartLocked,
    onRestartResearch,
}: {
    className?: string;
    researchId: string;
    onToggleResearch?: () => void;
    onSendMessage?: (
        message: string,
        options?: { interruptFeedback?: string },
    ) => void;
    restartLocked?: boolean;
    onRestartResearch?: () => void;
}) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const navigate = useNavigate();
    const reportId = useStore((state) => state.researchReportIds.get(researchId));
    const conversationId = useStore((state) => state.conversationId);
    const reportMessage = useStore((state) =>
        reportId ? state.messages.get(reportId) : undefined,
    );
    const hasReport = reportId !== undefined;
    const reportGenerating = useStore(
        (state) => Boolean(reportId && hasReport && state.messages.get(reportId)?.isStreaming),
    );
    const isCancelled = useStore((state) => state.cancelledResearchIds.has(researchId));
    const researchRunStatus = useStore((state) => state.researchRunStatus.get(researchId));
    const ongoingResearchId = useStore((state) => state.ongoingResearchId);
    const openResearchId = useStore((state) => state.openResearchId);
    const isActivelyResearching =
        researchRunStatus === "running" || ongoingResearchId === researchId;
    const isFailedState = !hasReport && !isActivelyResearching && !isCancelled;
    const state = useMemo(() => {
        if (hasReport) {
            return reportGenerating ? t("generatingReport") : t("reportGenerated");
        }
        if (researchRunStatus === "error") {
            return t("researchFailedNetwork");
        }
        if (researchRunStatus === "cancelled") {
            return t("researchCancelled");
        }
        if (isCancelled) {
            return t("researchCancelled");
        }
        if (isActivelyResearching) {
            return t("researching");
        }
        return t("researchFailedNetwork");
    }, [hasReport, reportGenerating, researchRunStatus, isCancelled, isActivelyResearching, t]);
    const showActions = hasReport || isActivelyResearching || isCancelled;
    const msg = useResearchMessage(researchId);
    const title = useMemo(() => {
        if (msg) {
            const payload = parsePlannerPayload(msg.content ?? "");
            if (payload?.title?.trim()) {
                return payload.title.trim();
            }
        }
        return undefined;
    }, [msg]);
    const statusClassName = useMemo(() => {
        if (hasReport && !reportGenerating) {
            return "border-emerald-100 bg-emerald-50 text-emerald-700 hover:bg-emerald-100";
        }
        if (reportGenerating || isActivelyResearching) {
            return "border-primary-100 bg-primary-50 text-primary-700 hover:bg-primary-100";
        }
        if (isCancelled || researchRunStatus === "cancelled") {
            return "border-gray-200 bg-gray-100 text-gray-600 hover:bg-gray-200";
        }
        return "border-amber-100 bg-amber-50 text-amber-700 hover:bg-amber-100";
    }, [hasReport, isActivelyResearching, isCancelled, reportGenerating, researchRunStatus]);
    const handleOpen = useCallback(() => {
        if (openResearchId === researchId) {
            closeResearch();
        } else {
            openResearch(researchId);
        }
        onToggleResearch?.();
    }, [openResearchId, researchId, onToggleResearch]);

    // Scan all messages for [TRAINING_CHAT_LINK] — use the LAST occurrence so that a newly
    // created link (after deletion recovery) takes precedence over the stale one.
    const allMessages = useStore((state) => state.messages);
    const existingTrainingLink = useMemo(() => {
        let last: { conversation_id: string; title?: string } | null = null;
        for (const msg of allMessages.values()) {
            const content = msg.content ?? "";
            const match = content.match(/\[TRAINING_CHAT_LINK\]\s*([\s\S]*?)\s*\[\/TRAINING_CHAT_LINK\]/);
            if (match?.[1]) {
                try {
                    const parsed = JSON.parse(match[1]);
                    if (parsed.conversation_id) last = parsed as { conversation_id: string; title?: string };
                } catch { /* ignore parse errors */ }
            }
        }
        return last;
    }, [allMessages]);

    const handleStartTraining = useCallback(async () => {
        // If a training chat already exists, try to navigate to it directly
        if (existingTrainingLink) {
            try {
                await apiGetConversation(existingTrainingLink.conversation_id);
                // Conversation still exists — navigate directly
                navigate(`/dashboard/${existingTrainingLink.conversation_id}`);
                return;
            } catch {
                // Conversation was deleted — fall through to create a new one
            }
        }

            // Extract report content for system prompt context
        const reportContext = extractReportContext(reportMessage?.content);

        // Chat title: "Training: [research title]"
        // Fall back to extracting from the report content's first heading if the store title is unavailable
        const resolvedTitle = title || extractTitleFromReport(reportMessage?.content);
        const chatTitle = resolvedTitle
            ? `Training: ${resolvedTitle}`
            : i18n.t("aiChat.newTrainingConversation", { defaultValue: "Training Chat" });

        // Pre-create AI Chat conversation so we can link back to it
        let preCreatedConversationId: string | undefined;
        try {
            const newConv = await apiCreateChatConversation(chatTitle, 'ai_chat', reportContext || undefined);
            preCreatedConversationId = newConv.conversation_id;
            if (typeof window !== "undefined") {
                window.dispatchEvent(new CustomEvent("conversations-changed"));
            }

            const storeState = useStore.getState();
            const drConversationId = storeState.conversationId;
            const threadId = storeState.threadId;

            // Add a [DEEP_RESEARCH_LINK] card as the first assistant message in the new AI chat
            if (preCreatedConversationId && drConversationId) {
                const deepResearchLinkContent = [
                    "[DEEP_RESEARCH_LINK]",
                    JSON.stringify({
                        conversation_id: drConversationId,
                        research_id: researchId,
                        title: resolvedTitle ?? undefined,
                    }, null, 2),
                    "[/DEEP_RESEARCH_LINK]",
                ].join("\n");
                try {
                    await apiAddChatMessage(preCreatedConversationId, "assistant", deepResearchLinkContent);
                } catch (e) {
                    console.warn("[DeepResearch] Failed to persist deep research link card:", e);
                }
            }

            // Append a [TRAINING_CHAT_LINK] message in the Deep Research conversation so user can return
            if (drConversationId && threadId) {
                const linkContent = [
                    "[TRAINING_CHAT_LINK]",
                    JSON.stringify({
                        conversation_id: preCreatedConversationId,
                        title: chatTitle,
                    }),
                    "[/TRAINING_CHAT_LINK]",
                ].join("\n");
                const linkMessage = {
                    id: nanoid(),
                    threadId,
                    role: "assistant" as const,
                    content: linkContent,
                    contentChunks: [linkContent],
                };
                storeState.appendMessage(linkMessage);
                try {
                    const saved = await apiAddChatMessage(drConversationId, "assistant", linkContent);
                    useStore.getState().setMessageBackendId(linkMessage.id, saved.id);
                } catch (e) {
                    console.warn("[DeepResearch] Failed to persist training chat link:", e);
                }
            }
        } catch (e) {
            console.warn("[DeepResearch] Failed to pre-create chat conversation:", e);
        }

        // Flush local cache before navigating away
        flushDeepResearchPersistNow();

        // Navigate directly to the new conversation — the [DEEP_RESEARCH_LINK] card is already
        // persisted as the first assistant message and will load automatically.
        // Pass an initial message so the AI automatically opens the training discussion.
        const welcomeMsg = i18n.t("aiChat.trainingWelcomeMessage", {
            defaultValue: "你好！请根据研究报告内容，帮我梳理一下核心发现和关键结论，然后引导我开始深入学习讨论。",
        });
        navigate(
            preCreatedConversationId ? `/dashboard/${preCreatedConversationId}` : "/dashboard",
            preCreatedConversationId ? { state: { initialMessage: welcomeMsg } } : undefined,
        );
    }, [reportMessage?.content, researchId, title, navigate, existingTrainingLink]);

    return (
        <div className={cn("w-full flex flex-col gap-4", className)}>
            <Card className="w-full overflow-hidden border-gray-200/70 bg-white/90 shadow-sm">
                <CardHeader className="border-b border-gray-100 bg-gradient-to-r from-primary-50/70 via-white to-white">
                    <div className="flex items-start justify-between gap-4">
                        <div className="flex min-w-0 items-start gap-3">
                            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 shadow-lg">
                                <Sparkles className="h-5 w-5 text-white" />
                            </div>
                            <div className="min-w-0">
                                <CardTitle className="truncate text-lg font-semibold text-gray-900">
                                    {title !== undefined && title !== "" ? title : t("deepResearch")}
                                </CardTitle>
                                <div className="mt-2">
                                    <Badge className={statusClassName}>{state}</Badge>
                                </div>
                            </div>
                        </div>
                        {showActions && (
                            <Button
                                variant={researchId !== openResearchId ? "default" : "secondary"}
                                onClick={handleOpen}
                                className="rounded-full"
                            >
                                {researchId !== openResearchId ? t("open") : t("close")}
                            </Button>
                        )}
                    </div>
                </CardHeader>
                <CardFooter className="flex flex-col items-stretch gap-3 bg-gray-50/60 sm:flex-row sm:items-center sm:justify-between">
                    <div className="w-full text-sm text-gray-500">
                        {hasReport && !reportGenerating ? t("postReportGuidanceHeading") : t("singleResearchPerConversation")}
                    </div>
                    <div className="flex justify-end gap-2">
                        {isFailedState && (
                            <Button
                                variant={restartLocked ? "secondary" : "default"}
                                disabled={restartLocked}
                                onClick={onRestartResearch}
                                className="rounded-full"
                            >
                                {t("restartResearch")}
                            </Button>
                        )}
                    </div>
                </CardFooter>
            </Card>
            {hasReport && !reportGenerating && (
                <TrainingCard
                    existingTrainingLink={existingTrainingLink}
                    onStartTraining={handleStartTraining}
                    t={t}
                />
            )}
        </div>
    );
}
