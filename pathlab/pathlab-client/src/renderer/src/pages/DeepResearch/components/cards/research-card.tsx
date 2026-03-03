// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import React, { useCallback, useMemo } from "react";
import i18n from "../../../../i18n";
import { useTranslations } from "../../../../lib/deep-research/i18n";
import { updateMessage as apiUpdateMessage } from "../../../../api";

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

function buildTrainingPromptWithReportContext(
    basePrompt: string,
    reportContent: string | undefined,
): string {
    const cleanedReport = (reportContent ?? "")
        .replace(/\n?\[PATHLAB_RESEARCH_META\][\s\S]*?\[\/PATHLAB_RESEARCH_META\]/g, "")
        .trim();
    if (!cleanedReport) {
        return basePrompt;
    }
    const clippedReport =
        cleanedReport.length > REPORT_CONTEXT_MAX_CHARS
            ? `${cleanedReport.slice(0, REPORT_CONTEXT_MAX_CHARS)}\n...(report truncated)`
            : cleanedReport;

    return [
        basePrompt,
        "[RESEARCH_REPORT_CONTEXT]",
        clippedReport,
        "[/RESEARCH_REPORT_CONTEXT]",
    ].join("\n\n");
}
import { RainbowText } from "../../../../components/deep-research/rainbow-text";
import { RollingText } from "../../../../components/deep-research/rolling-text";
import { Button } from "../../../../components/ui/button";
import { Card, CardFooter, CardHeader, CardTitle } from "../../../../components/ui/card";
import { closeResearch, openResearch, useResearchMessage, useStore } from "../../../../lib/deep-research/store";
import { cn } from "../../../../lib/utils";
import { parsePlannerPayload } from "../utils";

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
    const reportId = useStore((state) => state.researchReportIds.get(researchId));
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

    const handleStartTraining = useCallback(() => {
        const basePrompt = getChatTrainingBasePrompt();
        const prompt = buildTrainingPromptWithReportContext(
            basePrompt,
            reportMessage?.content,
        );
        onSendMessage?.(prompt);
    }, [onSendMessage, reportMessage?.content]);

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
                                {hasReport && !reportGenerating && (
                                    <>
                                        <Button onClick={handleStartTraining}>{t("startTraining")}</Button>
                                    </>
                                )}
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
        </div>
    );
}
