import React, { useEffect, useMemo } from "react";
import { motion } from "framer-motion";
import { Bot, User } from "lucide-react";
import { Markdown } from "../../../components/deep-research/markdown";
import type { Message, Option } from "../../../lib/deep-research/messages";
import {
    debugDeepResearchStore,
    flushDeepResearchPersistNow,
    isDeepResearchDebugEnabled,
    useMessage,
    useStore,
} from "../../../lib/deep-research/store";
import { stripResearchMeta } from "../../../lib/deep-research/utils";
import { cn } from "../../../lib/utils";

import { MessageBubble, AssistantStructuredContent } from "./blocks/message-content";
import { PlanCard } from "./cards/plan-card";
import { ResearchCard } from "./cards/research-card";
import { parsePlannerPayload } from "./utils";

const REPORT_CONTEXT_BLOCK_RE =
    /\[RESEARCH_REPORT_CONTEXT\]([\s\S]*?)\[\/RESEARCH_REPORT_CONTEXT\]/;

function splitReportContext(content: string): {
    before: string;
    report: string;
    after: string;
} | null {
    const match = REPORT_CONTEXT_BLOCK_RE.exec(content);
    if (!match || match.index < 0) {
        return null;
    }
    const fullBlock = match[0];
    const report = (match[1] ?? "").trim();
    if (!report) {
        return null;
    }
    const before = content.slice(0, match.index).trim();
    const after = content.slice(match.index + fullBlock.length).trim();
    return { before, report, after };
}

function UserMessageContent({ content }: { content: string }) {
    const parsed = useMemo(() => splitReportContext(content), [content]);

    if (!parsed) {
        return (
            <Markdown className="prose-invert text-white">
                {content}
            </Markdown>
        );
    }

    return (
        <div className="flex w-full flex-col gap-2">
            {parsed.before ? (
                <Markdown className="prose-invert text-white">
                    {parsed.before}
                </Markdown>
            ) : null}
            <details className="rounded-lg border border-white/25 bg-white/10 px-3 py-2">
                <summary className="cursor-pointer text-xs font-medium text-white/90">
                    已附加报告上下文（默认折叠，点击展开）
                </summary>
                <div className="mt-2 max-h-64 overflow-y-auto pr-1">
                    <Markdown className="prose-invert text-white">
                        {parsed.report}
                    </Markdown>
                </div>
            </details>
            {parsed.after ? (
                <Markdown className="prose-invert text-white">
                    {parsed.after}
                </Markdown>
            ) : null}
        </div>
    );
}

export function MessageListItem({
    className,
    messageId,
    waitForFeedback,
    interruptMessage,
    onFeedback,
    onSendMessage,
    onNewChat,
    onToggleResearch,
}: {
    className?: string;
    messageId: string;
    waitForFeedback?: boolean;
    onFeedback?: (feedback: { option: Option }) => void;
    interruptMessage?: Message | null;
    onSendMessage?: (
        message: string,
        options?: { interruptFeedback?: string },
    ) => void;
    onNewChat?: () => void;
    onToggleResearch?: () => void;
}) {
    const showRestartPlan = useStore((state) =>
        state.restartPlanShownResearchIds.has(messageId),
    );
    const message = useMessage(messageId);
    const researchIds = useStore((state) => state.researchIds);
    const researchPlanIds = useStore((state) => state.researchPlanIds);
    const researchReportIds = useStore((state) => state.researchReportIds);
    const researchActivityIds = useStore((state) => state.researchActivityIds);
    const researchRunStatus = useStore((state) => state.researchRunStatus);
    const hasPlannerMessage = useStore((state) => state.researchPlanIds.size > 0);
    const startOfResearch = useMemo(() => {
        return researchIds.includes(messageId);
    }, [researchIds, messageId]);
    const trimmedContent = stripResearchMeta(message?.content).replace(
        /\[TRAINING_CHAT_LINK\][\s\S]*?\[\/TRAINING_CHAT_LINK\]/g,
        "",
    ).trim();
    const isLocaleOnly =
        !!trimmedContent && /^[a-z]{2}(-[A-Z]{2})?$/.test(trimmedContent);
    const isEmptyContent =
        !trimmedContent &&
        !startOfResearch &&
        message?.agent !== "planner" &&
        true;
    const canRenderCurrentMessage =
        !!message &&
        !isLocaleOnly &&
        !isEmptyContent &&
        (message.role === "user" ||
            message.role === "assistant" ||
            message.agent === "coordinator" ||
            startOfResearch);

    useEffect(() => {
        if (!isDeepResearchDebugEnabled() || canRenderCurrentMessage) return;
        debugDeepResearchStore("message-list item skipped", {
            messageId,
            hasMessage: !!message,
            role: message?.role ?? null,
            agent: message?.agent ?? null,
            startOfResearch,
            isLocaleOnly,
            isEmptyContent,
            contentLength: trimmedContent.length,
        });
    }, [
        canRenderCurrentMessage,
        isEmptyContent,
        isLocaleOnly,
        message,
        messageId,
        startOfResearch,
        trimmedContent.length,
    ]);

    if (message) {
        const strippedContent = stripResearchMeta(message.content);
        const plannerPayload = parsePlannerPayload(strippedContent);
        const isPlannerLikeMessage =
            message.role === "assistant" &&
            (message.agent === "planner" || plannerPayload !== null);
        // Render as ResearchCard only when there is actual execution
        // evidence (report, non-planner activity, or run status).
        // A planner message may land in researchIds after backend
        // reconstruction normalises the research anchor, but if no
        // research execution ever happened (user refreshed mid-plan)
        // it should still render as PlanCard.
        const shouldRenderResearchCard = (() => {
            if (!startOfResearch) return false;
            if (!isPlannerLikeMessage) return true;
            const activities = researchActivityIds.get(messageId) ?? [];
            const hasNonPlannerActivity = activities.some((id) => id !== messageId);
            const hasReport = researchReportIds.has(messageId);
            const status = researchRunStatus.get(messageId);
            return (
                hasReport ||
                hasNonPlannerActivity ||
                status === "running" ||
                status === "success" ||
                status === "error" ||
                status === "cancelled"
            );
        })();
        const showRestartPlanAfterResearchCard = (() => {
            if (!shouldRenderResearchCard) {
                return false;
            }
            const status = researchRunStatus.get(messageId);
            const hasReport = researchReportIds.has(messageId);
            return !hasReport && status !== "running" && hasPlannerMessage;
        })();

        if (
            !isLocaleOnly && !isEmptyContent && (
                message.role === "user" ||
                message.role === "assistant" ||
                message.agent === "coordinator" ||
                isPlannerLikeMessage ||
                startOfResearch
            )) {
            let content: React.ReactNode;
            if (shouldRenderResearchCard) {
                content = (
                    <div className="w-full">
                        <ResearchCard
                            researchId={message.id}
                            onToggleResearch={onToggleResearch}
                            onSendMessage={onSendMessage}
                            restartLocked={showRestartPlan}
                            onRestartResearch={() => {
                                useStore.getState().setRestartPlanShown(message.id, true);
                                flushDeepResearchPersistNow();
                            }}
                        />
                    </div>
                );
            } else if (isPlannerLikeMessage) {
                content = (
                    <div className="w-full">
                        <PlanCard
                            message={message}
                            waitForFeedback={waitForFeedback}
                            interruptMessage={interruptMessage}
                            onFeedback={onFeedback}
                            onSendMessage={onSendMessage}
                        />
                    </div>
                );
            } else {
                content = message.content ? (
                    <div
                        className={cn(
                            "flex w-full items-start gap-4",
                            message.role === "user" ? "flex-row-reverse" : "flex-row",
                            className,
                        )}
                    >
                        <div className="mt-1 hidden h-8 w-8 shrink-0 items-center justify-center rounded-full border border-gray-100 bg-white shadow-sm sm:flex">
                            {message.role === "user" ? (
                                <User className="h-5 w-5 text-gray-600" />
                            ) : (
                                <Bot className="h-5 w-5 text-primary-600" />
                            )}
                        </div>
                        <MessageBubble message={message}>
                            {message.role === "assistant" ? (
                                <AssistantStructuredContent
                                    message={message}
                                    onSendMessage={onSendMessage}
                                    onNewChat={onNewChat}
                                />
                            ) : (
                                <div className="flex w-full flex-col break-words">
                                    <UserMessageContent content={message.content ?? ""} />
                                </div>
                            )}
                        </MessageBubble>
                    </div>
                ) : null;
            }
            if (content) {
                return (
                    <motion.li
                        className="mb-6 w-full max-w-full overflow-hidden"
                        key={messageId}
                        id={`dr-msg-${messageId}`}
                        initial={{ opacity: 0, y: 24 }}
                        animate={{ opacity: 1, y: 0 }}
                        style={{ transition: "all 0.2s ease-out" }}
                        transition={{
                            duration: 0.2,
                            ease: "easeOut",
                        }}
                    >
                        {content}
                    </motion.li>
                );
            }
        }
        return null;
    }
}
