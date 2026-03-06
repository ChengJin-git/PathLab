// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import React, { useCallback, useMemo, useState } from "react";
import { nanoid } from "nanoid";
import i18n from "../../../../i18n";
import { createConversation as apiCreateChatConversation, addMessage as apiAddChatMessage, getConversation as apiGetConversation } from "../../../../api";
import { useTranslations } from "../../../../lib/deep-research/i18n";
import { stripResearchMeta } from "../../../../lib/deep-research/utils";
import { useNavigate } from "react-router-dom";

const CHAT_TRAINING_BASE_PROMPT_ZH =
    "我有一组病理图像数据集，想训练一个深度学习模型。我需要配置什么？";
const CHAT_TRAINING_PROMPT_KEY = "app.aiChat.scenarios.trainModel.prompt";
const REPORT_CONTEXT_MAX_CHARS = 4000;

function getChatTrainingBasePrompt(): string {
    const translated = i18n.t(CHAT_TRAINING_PROMPT_KEY, {
        defaultValue: CHAT_TRAINING_BASE_PROMPT_ZH,
    });
    return typeof translated === "string" && translated.trim().length > 0
        ? translated
        : CHAT_TRAINING_BASE_PROMPT_ZH;
}

/** Clean and clip the report content for use as system-prompt context. */
function extractReportContext(reportContent: string | undefined): string {
    const cleaned = stripResearchMeta(reportContent);
    if (!cleaned) return "";
    return cleaned.length > REPORT_CONTEXT_MAX_CHARS
        ? `${cleaned.slice(0, REPORT_CONTEXT_MAX_CHARS)}\n...(report truncated)`
        : cleaned;
}

/** Build the visible user message (no report context — that goes in system prompt now). */
function buildTrainingPrompt(
    basePrompt: string,
    handoffInstruction: string,
    jumpMetadata?: {
        conversationId?: string | null;
        researchId?: string;
        title?: string;
    },
): string {
    const chunks: string[] = [basePrompt];
    chunks.push(
        "[TRAINING_HANDOFF_CONTEXT]",
        handoffInstruction,
        "[/TRAINING_HANDOFF_CONTEXT]",
    );
    if (jumpMetadata?.conversationId && jumpMetadata?.researchId) {
        chunks.push(
            "[RESEARCH_JUMP]",
            JSON.stringify(
                {
                    conversation_id: jumpMetadata.conversationId,
                    research_id: jumpMetadata.researchId,
                    title: jumpMetadata.title ?? null,
                },
                null,
                2,
            ),
            "[/RESEARCH_JUMP]",
        );
    }
    return chunks.join("\n\n");
}
import { RainbowText } from "../../../../components/deep-research/rainbow-text";
import { RollingText } from "../../../../components/deep-research/rolling-text";
import { Button } from "../../../../components/ui/button";
import { Card, CardFooter, CardHeader, CardTitle } from "../../../../components/ui/card";
import { closeResearch, flushDeepResearchPersistNow, openResearch, useResearchMessage, useStore } from "../../../../lib/deep-research/store";
import { cn } from "../../../../lib/utils";
import { parsePlannerPayload } from "../utils";

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
    const [deleted, setDeleted] = useState(false);

    const handleGo = useCallback(
        async (e: React.MouseEvent) => {
            e.stopPropagation();
            if (!existingTrainingLink) return;
            try {
                await apiGetConversation(existingTrainingLink.conversation_id);
                navigate(`/dashboard/${existingTrainingLink.conversation_id}`);
            } catch {
                setDeleted(true);
            }
        },
        [existingTrainingLink, navigate],
    );

    if (existingTrainingLink) {
        return (
            <Card className="w-full">
                <CardHeader>
                    <CardTitle>
                        {existingTrainingLink.title || t("startTraining")}
                    </CardTitle>
                </CardHeader>
                <CardFooter>
                    <div className="flex w-full items-center gap-2">
                        <span className="text-muted-foreground flex-grow text-sm">
                            {deleted ? t("trainingDeleted") : t("trainingStarted")}
                        </span>
                        <Button variant={deleted ? "secondary" : "default"} disabled={deleted} onClick={handleGo}>
                            Go
                        </Button>
                    </div>
                </CardFooter>
            </Card>
        );
    }

    return (
        <Card className="w-full">
            <CardHeader>
                <CardTitle>{t("startTraining")}</CardTitle>
            </CardHeader>
            <CardFooter>
                <div className="flex w-full items-center gap-2">
                    <span className="text-muted-foreground flex-grow text-sm">{t("trainingDescription")}</span>
                    <Button onClick={onStartTraining}>
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
    const handleOpen = useCallback(() => {
        if (openResearchId === researchId) {
            closeResearch();
        } else {
            openResearch(researchId);
        }
        onToggleResearch?.();
    }, [openResearchId, researchId, onToggleResearch]);

    // Scan all messages for an existing [TRAINING_CHAT_LINK] to prevent duplicate creation
    const allMessages = useStore((state) => state.messages);
    const existingTrainingLink = useMemo(() => {
        for (const msg of allMessages.values()) {
            const content = msg.content ?? "";
            const match = content.match(/\[TRAINING_CHAT_LINK\]\s*([\s\S]*?)\s*\[\/TRAINING_CHAT_LINK\]/);
            if (match?.[1]) {
                try {
                    const parsed = JSON.parse(match[1]);
                    if (parsed.conversation_id) return parsed as { conversation_id: string; title?: string };
                } catch { /* ignore parse errors */ }
            }
        }
        return null;
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

        const basePrompt = getChatTrainingBasePrompt();
        const handoffInstruction = [
            "Please continue in normal AI chat mode.",
            t("uploadDataFirst"),
            "First guide the user to upload/select dataset, then help complete training setup.",
            "When needed, provide structured [DATASET_REGISTRATION] and [TASK_CONFIG] blocks.",
        ].join("\n");
        // Report context is now passed separately and injected into the system prompt
        // by the backend, instead of being embedded in the user message on every turn.
        const reportContext = extractReportContext(reportMessage?.content);
        const prompt = buildTrainingPrompt(
            basePrompt,
            handoffInstruction,
            {
                conversationId,
                researchId,
                title,
            },
        );

        // Pre-create AI Chat conversation so we can link back to it
        let preCreatedConversationId: string | undefined;
        try {
            // Prefer the report's H1 title, fall back to the plan title
            const reportH1 = reportMessage?.content?.match(/^#\s+(.+)$/m)?.[1]?.trim();
            const resolvedTitle = reportH1 || title;
            const chatTitle = resolvedTitle ? `Training: ${resolvedTitle}` : "Training Chat";
            const newConv = await apiCreateChatConversation(chatTitle, undefined, reportContext || undefined);
            preCreatedConversationId = newConv.conversation_id;

            // Append a link message in the Deep Research conversation
            const storeState = useStore.getState();
            const drConversationId = storeState.conversationId;
            const threadId = storeState.threadId;
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
                // Persist to backend
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

        // Flush local cache before navigating away so the link message survives
        // the SPA route change (beforeunload doesn't fire for React Router nav).
        flushDeepResearchPersistNow();

        navigate(preCreatedConversationId ? `/dashboard/${preCreatedConversationId}` : "/dashboard", {
            state: {
                initialMessage: prompt,
                forceNewChat: true,
                fromDeepResearchStartTraining: true,
                preCreatedConversationId,
                reportContext: reportContext || undefined,
            },
        });
    }, [t, reportMessage?.content, conversationId, researchId, title, navigate, existingTrainingLink]);

    return (
        <div className={cn("w-full flex flex-col gap-4", className)}>
            <Card className="w-full">
                <CardHeader>
                    <CardTitle>
                        <RainbowText
                            animated={
                                state !== t("reportGenerated") &&
                                state !== t("researchCancelled") &&
                                state !== t("researchFailedNetwork")
                            }
                        >
                            {title !== undefined && title !== "" ? title : t("deepResearch")}
                        </RainbowText>
                    </CardTitle>
                </CardHeader>
                <CardFooter>
                    <div className="flex w-full items-center gap-2">
                        <RollingText className="text-muted-foreground flex-grow text-sm">
                            {state}
                        </RollingText>
                        {showActions && (
                            <>
                                <Button
                                    variant={!openResearchId ? "default" : "outline"}
                                    onClick={handleOpen}
                                >
                                    {researchId !== openResearchId ? t("open") : t("close")}
                                </Button>
                            </>
                        )}
                        {isFailedState && (
                            <Button
                                variant={restartLocked ? "secondary" : "default"}
                                disabled={restartLocked}
                                onClick={onRestartResearch}
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
