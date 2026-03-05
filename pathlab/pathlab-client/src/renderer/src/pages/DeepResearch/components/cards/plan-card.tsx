// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import React, { useCallback, useMemo } from "react";
import { motion } from "framer-motion";
import { Wrench } from "lucide-react";
import { useTranslations } from "../../../../lib/deep-research/i18n";
import { Markdown } from "../../../../components/deep-research/markdown";
import { Tooltip } from "../../../../components/deep-research/tooltip";
import { Button } from "../../../../components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "../../../../components/ui/card";
import type { Message, Option } from "../../../../lib/deep-research/messages";
import { flushDeepResearchPersistNow, rePersistMessageToBackend, useStore } from "../../../../lib/deep-research/store";
import { cn } from "../../../../lib/utils";
import { parsePlannerPayload } from "../utils";
import { ThoughtBlock } from "../blocks/thought-block";

// Stub for ToolsDisplay since it's used inside PlanCard but not exported
function ToolsDisplay({ tools }: { tools: string[] }) {
    if (!tools || tools.length === 0) return null;
    return (
        <div className="mt-2 flex flex-wrap gap-2">
            {tools.map((tool) => (
                <span key={tool} className="rounded-full bg-secondary px-2 py-1 text-[11px] font-mono leading-none text-secondary-foreground">
                    {tool}
                </span>
            ))}
        </div>
    );
}

export function PlanCard({
    className,
    message,
    interruptMessage,
    onFeedback,
    waitForFeedback,
    onSendMessage,
    allowRestartActions = false,
}: {
    className?: string;
    message: Message;
    interruptMessage?: Message | null;
    onFeedback?: (feedback: { option: Option }) => void;
    onSendMessage?: (
        message: string,
        options?: { interruptFeedback?: string },
    ) => void;
    waitForFeedback?: boolean;
    allowRestartActions?: boolean;
}) {
    const submittedAction = useStore(
        (state) => state.planActionLocks.get(message.id) ?? null,
    );
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const PLAN_FALLBACK_OPTIONS: Option[] = useMemo(() => [
        { text: t("startResearch"), value: "accepted" },
        { text: t("modifyPlan"), value: "replan" },
    ], [t]);
    const plan = useMemo<{
        title?: string;
        thought?: string;
        steps?: { title?: string; description?: string; tools?: string[] }[];
    }>(() => {
        return parsePlannerPayload(message.content ?? "") ?? {};
    }, [message.content]);

    const reasoningContent = message.reasoningContent;
    const hasMainContent = Boolean(
        message.content && message.content.trim() !== "",
    );
    // 判断是否正在思考：有推理内容但还没有主要内容
    const isThinking = Boolean(reasoningContent && !hasMainContent);

    // Planner messages should show card shell immediately while streaming.
    // This avoids the "card pops only after full content" effect.
    const shouldShowPlan = hasMainContent || Boolean(message.isStreaming);
    const hasInterruptOptions = Boolean(interruptMessage?.options?.length);
    const attachedResearchId = useStore((state) =>
        Array.from(state.researchPlanIds.entries()).find(([, planId]) => planId === message.id)?.[0],
    );
    const isPlanAttachedToResearch = attachedResearchId !== undefined;
    const hasResearchStartedForPlan = useStore((state) => {
        if (!attachedResearchId) return false;
        const status = state.researchRunStatus.get(attachedResearchId);
        const hasReport = state.researchReportIds.has(attachedResearchId);
        const hasExecutionActivity = (state.researchActivityIds.get(attachedResearchId) ?? []).some(
            (id) => {
                const msg = state.messages.get(id);
                return !!msg && msg.agent !== "planner";
            },
        );
        return (
            state.ongoingResearchId === attachedResearchId ||
            hasReport ||
            hasExecutionActivity ||
            status === "running" ||
            status === "success" ||
            status === "error" ||
            status === "cancelled"
        );
    });
    const hasStartedResearchBeforeThisPlan = useStore((state) => {
        const planIndex = state.messageIds.indexOf(message.id);
        if (planIndex < 0) return false;

        let earliestStartedResearchIndex = Number.POSITIVE_INFINITY;
        for (const rid of state.researchIds) {
            const status = state.researchRunStatus.get(rid);
            const hasReport = state.researchReportIds.has(rid);
            const hasExecutionActivity = (state.researchActivityIds.get(rid) ?? []).some((id) => {
                const msg = state.messages.get(id);
                return !!msg && msg.agent !== "planner";
            });
            const started =
                state.ongoingResearchId === rid ||
                hasReport ||
                hasExecutionActivity ||
                status === "running" ||
                status === "success" ||
                status === "error" ||
                status === "cancelled";
            if (!started) continue;
            const idx = state.messageIds.indexOf(rid);
            if (idx >= 0 && idx < earliestStartedResearchIndex) {
                earliestStartedResearchIndex = idx;
            }
        }

        if (!Number.isFinite(earliestStartedResearchIndex)) return false;
        return planIndex < earliestStartedResearchIndex;
    });
    const isAttachedResearchCompleted = useStore((state) => {
        if (!attachedResearchId) return false;
        const status = state.researchRunStatus.get(attachedResearchId);
        return state.researchReportIds.has(attachedResearchId) || status === "success";
    });
    const actionOptions = hasInterruptOptions
        ? (interruptMessage?.options ?? [])
        : allowRestartActions
            ? PLAN_FALLBACK_OPTIONS
            : !isPlanAttachedToResearch || !isAttachedResearchCompleted
                ? PLAN_FALLBACK_OPTIONS
                : [];
    const showActions = !message.isStreaming && actionOptions.length > 0;
    const lockedByResearchStarted =
        allowRestartActions ? false : hasResearchStartedForPlan || hasStartedResearchBeforeThisPlan;
    const effectiveSubmittedAction =
        allowRestartActions ? null : submittedAction ?? (lockedByResearchStarted ? "accepted" : null);
    const persistPlanActionLock = useCallback(
        async (action: "accepted" | "replan") => {
            useStore.getState().setPlanActionLock(message.id, action);
            flushDeepResearchPersistNow();
            // Re-persist the plan message to backend so the PATHLAB_RESEARCH_META
            // block includes the updated planActionLock.  Without this, the lock
            // is lost when localStorage cache is cleared.
            rePersistMessageToBackend(message.id);
        },
        [message.id],
    );
    const resolveAcceptedUserMessage = useCallback((): string => {
        const state = useStore.getState();
        const allIds = state.messageIds;
        const planIndex = allIds.indexOf(message.id);
        let cursor = planIndex >= 0 ? planIndex - 1 : allIds.length - 1;

        for (; cursor >= 0; cursor -= 1) {
            const candidate = state.messages.get(allIds[cursor]);
            if (!candidate || candidate.role !== "user") continue;
            const text = (candidate.content ?? "").trim();
            if (!text) continue;
            if (text.includes("[PATHLAB_RESEARCH_META]")) continue;
            return text;
        }

        // Fallback text when no previous user query can be recovered.
        return "Continue with the approved research plan.";
    }, [message.id]);

    const handleAccept = useCallback(async () => {
        if (onSendMessage) {
            onSendMessage(
                resolveAcceptedUserMessage(),
                {
                    interruptFeedback: "accepted",
                },
            );
        }
    }, [onSendMessage, resolveAcceptedUserMessage]);
    return (
        <div className={cn("w-full", className)}>
            {shouldShowPlan && (
                <motion.div
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, ease: "easeOut" }}
                >
                    <Card className="w-full">
                        <CardHeader>
                            <CardTitle>
                                <Markdown animated={false}>
                                    {`### ${plan.title !== undefined && plan.title !== ""
                                        ? plan.title
                                        : t("deepResearch")
                                        }`}
                                </Markdown>
                            </CardTitle>
                        </CardHeader>
                        <CardContent>
                            <div style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>
                                {reasoningContent && (
                                    <ThoughtBlock
                                        content={reasoningContent}
                                        isStreaming={isThinking && message.isStreaming}
                                        hasMainContent={hasMainContent}
                                        contentChunks={message.reasoningContentChunks}
                                    />
                                )}
                                <Markdown className="opacity-80" animated={false}>
                                    {plan.thought}
                                </Markdown>
                                {plan.steps && (
                                    <ul className="my-2 flex list-decimal flex-col gap-4 border-l-[2px] pl-8">
                                        {plan.steps.map((step, i) => (
                                            <li key={`step-${i}`} style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>
                                                <div className="flex items-start gap-2">
                                                    <div className="flex-1">
                                                        <h3 className="mb flex items-center gap-2 text-lg font-medium">
                                                            <Markdown animated={false}>
                                                                {step.title}
                                                            </Markdown>
                                                            {step.tools && step.tools.length > 0 && (
                                                                <Tooltip
                                                                    title={`Uses ${step.tools.length} MCP tool${step.tools.length > 1 ? "s" : ""}`}
                                                                >
                                                                    <div className="flex items-center gap-1 rounded-full bg-blue-100 px-2 py-1 text-xs text-blue-800">
                                                                        <Wrench size={12} />
                                                                        <span>{step.tools.length}</span>
                                                                    </div>
                                                                </Tooltip>
                                                            )}
                                                        </h3>
                                                        <div className="text-muted-foreground text-sm" style={{ wordBreak: 'break-all', whiteSpace: 'normal' }}>
                                                            <Markdown animated={false}>
                                                                {step.description}
                                                            </Markdown>
                                                        </div>
                                                        {step.tools && step.tools.length > 0 && (
                                                            <ToolsDisplay tools={step.tools} />
                                                        )}
                                                    </div>
                                                </div>
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        </CardContent>
                        <CardFooter className="flex justify-end">
                            {showActions && (
                                <motion.div
                                    className="flex gap-2"
                                    initial={{ opacity: 0, y: 12 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ duration: 0.3, delay: 0.3 }}
                                >
                                    {actionOptions.map((option) => (
                                        <Button
                                            key={option.value}
                                            variant={
                                                effectiveSubmittedAction === option.value
                                                    ? "secondary"
                                                    : option.value === "accepted"
                                                        ? "default"
                                                        : "outline"
                                            }
                                            disabled={
                                                effectiveSubmittedAction !== null ||
                                                (hasInterruptOptions ? !waitForFeedback : false)
                                            }
                                            onClick={() => {
                                                if (effectiveSubmittedAction !== null) {
                                                    return;
                                                }
                                                if (!allowRestartActions) {
                                                    void persistPlanActionLock(
                                                        option.value === "accepted" ? "accepted" : "replan",
                                                    );
                                                }
                                                if (option.value === "accepted") {
                                                    void handleAccept();
                                                } else {
                                                    onFeedback?.({
                                                        option,
                                                    });
                                                }
                                            }}
                                        >
                                            {option.text}
                                        </Button>
                                    ))}
                                </motion.div>
                            )}
                        </CardFooter>
                    </Card>
                </motion.div>
            )}
        </div>
    );
}
