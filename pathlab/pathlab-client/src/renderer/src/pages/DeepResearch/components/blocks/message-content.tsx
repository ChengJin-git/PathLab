// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { nanoid } from "nanoid";
import React, { useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { addMessage as apiAddMessage, updateMessage as apiUpdateMessage } from "../../../../api";
import { AnalysisConfigCard, parseAnalysisConfig, type AgentAnalysisConfig, removeAnalysisConfigBlock } from "../../../../components/chat/AnalysisConfigCard";
import { DatasetRegistrationCard, parseDatasetRegistrationConfig, removeDatasetRegistrationBlock } from "../../../../components/chat/DatasetRegistrationCard";
import { NavigationCard, parseNavigateBlock, removeNavigateBlock } from "../../../../components/chat/NavigationCard";
import { OptionButtons, parseOptions, removeOptionsBlock } from "../../../../components/chat/OptionButtons";
import { QuickAnalysisViewer, parseQuickAnalysisConfig, type CachedAnalysisData, removeQuickAnalysisConfigBlock } from "../../../../components/chat/QuickAnalysisViewer";
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from "../../../../components/chat/TaskConfigCard";
import { TaskHistoryCard, parseTaskHistoryConfig, type CachedTaskData, removeTaskHistoryConfigBlock } from "../../../../components/chat/TaskHistoryCard";
import { removeVoiceControlBlock } from "../../../../components/chat/VoiceControlBlock";
import { Markdown } from "../../../../components/deep-research/markdown";
import type { Message } from "../../../../lib/deep-research/messages";
import { useStore } from "../../../../lib/deep-research/store";
import { stripResearchMeta } from "../../../../lib/deep-research/utils";
import { cn } from "../../../../lib/utils";

function parseTrainingChatLink(content: string): { conversationId: string; title?: string } | null {
    const match = content.match(/\[TRAINING_CHAT_LINK\]([\s\S]*?)\[\/TRAINING_CHAT_LINK\]/i);
    if (!match) return null;
    try {
        const parsed = JSON.parse(match[1].trim());
        return parsed?.conversation_id ? { conversationId: parsed.conversation_id, title: parsed.title } : null;
    } catch { return null; }
}

function removeTrainingChatLinkBlock(content: string): string {
    return content.replace(/\[TRAINING_CHAT_LINK\][\s\S]*?\[\/TRAINING_CHAT_LINK\]/gi, "").trim();
}

function injectSubmittedTaskId(content: string, taskId: string): string {
    return content.replace(
        /\[TASK_CONFIG\]([\s\S]*?)\[\/TASK_CONFIG\]/,
        (match, configJson) => {
            try {
                const parsed = JSON.parse(configJson.trim()) as Record<string, unknown>;
                parsed.submitted_task_id = taskId;
                return `[TASK_CONFIG]\n${JSON.stringify(parsed, null, 2)}\n[/TASK_CONFIG]`;
            } catch {
                return match;
            }
        },
    );
}

export function MessageBubble({
    className,
    message,
    children,
}: {
    className?: string;
    message: Message;
    children: React.ReactNode;
}) {
    return (
        <div
            className={cn(
                "group flex w-auto max-w-[80%] flex-col px-5 py-3.5 text-[15px] leading-7 shadow-sm",
                message.role === "user" &&
                "rounded-[20px] rounded-tr-sm bg-gradient-to-br from-primary-500 to-primary-600 text-white selection:bg-white/30",
                message.role === "assistant" &&
                "rounded-[20px] rounded-tl-sm border border-gray-100 bg-white text-gray-900",
                className,
            )}
            style={{ wordBreak: "break-word" }}
        >
            {children}
        </div>
    );
}

export function AssistantStructuredContent({
    message,
    onSendMessage,
}: {
    message: Message;
    onSendMessage?: (
        message: string,
        options?: { interruptFeedback?: string },
    ) => void;
}) {
    const { t } = useTranslation();
    const options = useMemo(() => parseOptions(message.content ?? ""), [message.content]);
    const taskConfig = useMemo(
        () => parseTaskConfig(message.content ?? ""),
        [message.content],
    );
    const analysisConfig = useMemo(
        () => parseAnalysisConfig(message.content ?? ""),
        [message.content],
    );
    const quickAnalysisConfig = useMemo(
        () => parseQuickAnalysisConfig(message.content ?? ""),
        [message.content],
    );
    const taskHistoryConfig = useMemo(
        () => parseTaskHistoryConfig(message.content ?? ""),
        [message.content],
    );
    const navigateBlock = useMemo(
        () => parseNavigateBlock(message.content ?? ""),
        [message.content],
    );
    const datasetRegistrationConfig = useMemo(
        () => parseDatasetRegistrationConfig(message.content ?? ""),
        [message.content],
    );
    const trainingChatLink = useMemo(
        () => parseTrainingChatLink(message.content ?? ""),
        [message.content],
    );
    const responding = useStore((state) => state.responding);
    const deepResearchConversationId = useStore((state) => state.conversationId);

    let displayContent = message.content ?? "";
    // Strip persisted research meta blocks that may leak into display content
    // after backend reload or cache restoration.
    displayContent = stripResearchMeta(displayContent);
    if (options) {
        displayContent = removeOptionsBlock(displayContent);
    }
    if (taskConfig) {
        displayContent = removeTaskConfigBlock(displayContent);
    }
    if (analysisConfig) {
        displayContent = removeAnalysisConfigBlock(displayContent);
    }
    if (quickAnalysisConfig) {
        displayContent = removeQuickAnalysisConfigBlock(displayContent);
    }
    if (taskHistoryConfig) {
        displayContent = removeTaskHistoryConfigBlock(displayContent);
    }
    if (navigateBlock) {
        displayContent = removeNavigateBlock(displayContent);
    }
    if (datasetRegistrationConfig) {
        displayContent = removeDatasetRegistrationBlock(displayContent);
    }
    if (trainingChatLink) {
        displayContent = removeTrainingChatLinkBlock(displayContent);
    }
    displayContent = removeVoiceControlBlock(displayContent);

    // If the message only contained a training chat link (no other content or cards), render nothing.
    const hasVisibleContent =
        displayContent.trim() ||
        options ||
        taskConfig ||
        analysisConfig ||
        quickAnalysisConfig ||
        taskHistoryConfig ||
        navigateBlock ||
        datasetRegistrationConfig;
    if (!hasVisibleContent && trainingChatLink) {
        return null;
    }

    const persistUpdatedContent = useCallback(
        async (nextContent: string, warningPrefix: string) => {
            const state = useStore.getState();
            const currentMessage = state.messages.get(message.id) ?? message;

            if (nextContent !== currentMessage.content) {
                state.updateMessage({
                    ...currentMessage,
                    content: nextContent,
                    contentChunks: [nextContent],
                });
            }

            const conversationId = state.conversationId;
            const backendId = state.messageBackendIds.get(message.id);
            if (!conversationId || backendId == null) {
                return;
            }

            try {
                await apiUpdateMessage(conversationId, backendId, nextContent);
            } catch (error) {
                console.warn(`${warningPrefix}:`, error);
            }
        },
        [message],
    );

    const appendAssistantMessage = useCallback(
        async (content: string) => {
            const state = useStore.getState();
            if (!state.threadId) {
                return;
            }

            const nextMessage: Message = {
                id: nanoid(),
                threadId: state.threadId,
                role: "assistant",
                content,
                contentChunks: [content],
            };
            state.appendMessage(nextMessage);

            if (!state.conversationId) {
                return;
            }

            try {
                const saved = await apiAddMessage(state.conversationId, "assistant", content);
                useStore.getState().setMessageBackendId(nextMessage.id, saved.id);
            } catch (error) {
                console.warn("[DeepResearch] Failed to persist appended assistant message:", error);
            }
        },
        [],
    );

    const handleTaskSubmitSuccess = useCallback(
        async (taskId: string) => {
            const currentContent = useStore.getState().messages.get(message.id)?.content ?? message.content ?? "";
            const nextContent = injectSubmittedTaskId(currentContent, taskId);
            await persistUpdatedContent(nextContent, "[DeepResearch] Failed to persist TASK_CONFIG submission");
        },
        [message.id, message.content, persistUpdatedContent],
    );

    const handleRegistrationSuccess = useCallback(
        async (taskId: string, fileCount: number, datasetName: string, mode: 'existing' | 'new') => {
            const currentContent = useStore.getState().messages.get(message.id)?.content ?? message.content ?? "";
            const nextContent = currentContent.replace(
                /\[DATASET_REGISTRATION\]([\s\S]*?)\[\/DATASET_REGISTRATION\]/,
                (_match, json) => {
                    try {
                        const config = JSON.parse(json.trim());
                        config.submitted_task_id = taskId;
                        config.submitted_file_count = fileCount;
                        config.submitted_dataset_name = datasetName;
                        config.submitted_mode = mode;
                        return `[DATASET_REGISTRATION]\n${JSON.stringify(config, null, 2)}\n[/DATASET_REGISTRATION]`;
                    } catch {
                        return _match;
                    }
                }
            );
            await persistUpdatedContent(nextContent, "[DeepResearch] Failed to persist DATASET_REGISTRATION submission");

            const successMsg = mode === 'new'
                ? `Started uploading ${fileCount} files to new dataset "${datasetName}". What should we do next?`
                : `Started uploading ${fileCount} files to existing dataset. What should we do next?`;
            onSendMessage?.(successMsg);
        },
        [message.id, message.content, onSendMessage, persistUpdatedContent],
    );

    const handleAnalysisSubmitSuccess = useCallback(
        async (taskId: string, analysisId: string) => {
            const currentContent = useStore.getState().messages.get(message.id)?.content ?? message.content ?? "";
            const nextContent = currentContent.replace(
                /\[ANALYSIS_CONFIG\]([\s\S]*?)\[\/ANALYSIS_CONFIG\]/,
                (_match, json) => {
                    try {
                        const config = JSON.parse(json.trim()) as AgentAnalysisConfig;
                        if (analysisId) {
                            config.submitted_analysis_id = analysisId;
                        } else {
                            config.external_validation_task_id = taskId;
                        }
                        return `[ANALYSIS_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/ANALYSIS_CONFIG]`;
                    } catch {
                        return _match;
                    }
                },
            );
            await persistUpdatedContent(nextContent, "[DeepResearch] Failed to persist ANALYSIS_CONFIG submission");

            const isExternalValidation = !analysisId;
            let quickAnalysisBlock = "";
            if (isExternalValidation) {
                const currentConfig = parseAnalysisConfig(nextContent) ?? parseAnalysisConfig(currentContent);
                if (currentConfig) {
                    const quickConfig: Record<string, unknown> = {
                        task_id: taskId,
                        task_name: currentConfig.target_name || currentConfig.task_name || taskId,
                        metrics: currentConfig.metrics || [],
                        charts: currentConfig.charts || [],
                        is_external_validation: true,
                    };
                    if (currentConfig.compute_bootstrap_ci) {
                        quickConfig.compute_bootstrap_ci = true;
                    }
                    if (currentConfig.bootstrap_ci_metrics) {
                        quickConfig.bootstrap_ci_metrics = currentConfig.bootstrap_ci_metrics;
                    }
                    quickAnalysisBlock = `\n\n[QUICK_ANALYSIS_CONFIG]\n${JSON.stringify(quickConfig, null, 2)}\n[/QUICK_ANALYSIS_CONFIG]`;
                }
            }

            const successContent = isExternalValidation
                ? `${t("aiChat.taskSuccess.externalValidationStarted", { taskId })}${quickAnalysisBlock}\n\n[NAVIGATE]\n${JSON.stringify({
                    target: "/results",
                    state: { selectedTaskId: taskId, pageMode: "external-validation" },
                    buttonTextKey: "aiChat.taskSuccess.viewResults",
                    descriptionKey: "aiChat.taskSuccess.validationResultsDesc",
                }, null, 2)}\n[/NAVIGATE]`
                : `${t("aiChat.taskSuccess.analysisCompleted")}\n\n[NAVIGATE]\n${JSON.stringify({
                    target: "/results",
                    state: { selectedTaskId: taskId },
                    buttonTextKey: "aiChat.taskSuccess.viewAnalysisResults",
                    descriptionKey: "aiChat.taskSuccess.analysisResultsDesc",
                }, null, 2)}\n[/NAVIGATE]`;

            await appendAssistantMessage(successContent);
        },
        [appendAssistantMessage, message.id, message.content, persistUpdatedContent, t],
    );

    const handleTaskHistoryDataLoaded = useCallback(
        async (data: CachedTaskData[]) => {
            const currentContent = useStore.getState().messages.get(message.id)?.content ?? message.content ?? "";
            const nextContent = currentContent.replace(
                /\[TASK_HISTORY_CONFIG\]([\s\S]*?)\[\/TASK_HISTORY_CONFIG\]/,
                (_match, json) => {
                    try {
                        const config = JSON.parse(json.trim()) as Record<string, unknown>;
                        config.cached_tasks = data;
                        config.cached_at = new Date().toISOString();
                        return `[TASK_HISTORY_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/TASK_HISTORY_CONFIG]`;
                    } catch {
                        return _match;
                    }
                },
            );
            await persistUpdatedContent(nextContent, "[DeepResearch] Failed to persist TASK_HISTORY_CONFIG cache");
        },
        [message.id, message.content, persistUpdatedContent],
    );

    const handleQuickAnalysisDataLoaded = useCallback(
        async (data: CachedAnalysisData) => {
            const currentContent = useStore.getState().messages.get(message.id)?.content ?? message.content ?? "";
            const nextContent = currentContent.replace(
                /\[QUICK_ANALYSIS_CONFIG\]([\s\S]*?)\[\/QUICK_ANALYSIS_CONFIG\]/,
                (_match, json) => {
                    try {
                        const config = JSON.parse(json.trim()) as Record<string, unknown>;
                        config.cached_data = data;
                        return `[QUICK_ANALYSIS_CONFIG]\n${JSON.stringify(config, null, 2)}\n[/QUICK_ANALYSIS_CONFIG]`;
                    } catch {
                        return _match;
                    }
                },
            );
            await persistUpdatedContent(nextContent, "[DeepResearch] Failed to persist QUICK_ANALYSIS_CONFIG cache");
        },
        [message.id, message.content, persistUpdatedContent],
    );

    return (
        <div className="flex w-full flex-col break-words">
            {displayContent.trim() && (
                <Markdown
                    className="prose-slate max-w-none prose-sm
                        prose-p:my-2 prose-p:leading-relaxed
                        prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-gray-900
                        prose-ul:my-3 prose-ul:list-disc prose-ul:pl-6
                        prose-ol:my-3 prose-ol:list-decimal prose-ol:pl-6
                        prose-li:my-1.5 prose-li:leading-relaxed
                        prose-code:bg-gray-100 prose-code:text-gray-800 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-xs prose-code:font-mono prose-code:before:content-none prose-code:after:content-none
                        prose-pre:bg-gray-900 prose-pre:text-gray-100 prose-pre:rounded-lg prose-pre:p-4 prose-pre:my-3
                        prose-strong:text-gray-900 prose-strong:font-semibold
                        prose-a:text-blue-600 prose-a:underline prose-a:decoration-blue-300 prose-a:underline-offset-2 hover:prose-a:text-blue-700 hover:prose-a:decoration-blue-500
                        prose-hr:border-gray-200 prose-hr:my-4
                        prose-table:text-sm
                        prose-img:rounded-lg prose-img:shadow-md prose-img:my-3 prose-img:max-w-full prose-img:h-auto prose-img:border prose-img:border-gray-200"
                >{displayContent}</Markdown>
            )}
            {options && (
                <OptionButtons
                    options={options}
                    onSelect={(text) => onSendMessage?.(text)}
                    disabled={responding}
                />
            )}
            {taskConfig && (
                <TaskConfigCard
                    config={taskConfig}
                    onSubmitSuccess={handleTaskSubmitSuccess}
                    onSubmitError={(error) => {
                        console.warn("[DeepResearch] TASK_CONFIG submit error:", error);
                    }}
                    messageId={message.id}
                />
            )}
            {analysisConfig && (
                <AnalysisConfigCard
                    config={analysisConfig}
                    onSubmitSuccess={handleAnalysisSubmitSuccess}
                    onSubmitError={(error) => {
                        console.warn("[DeepResearch] ANALYSIS_CONFIG submit error:", error);
                    }}
                    messageId={message.id}
                />
            )}
            {quickAnalysisConfig && (
                <QuickAnalysisViewer
                    config={quickAnalysisConfig}
                    onError={(error) => {
                        console.warn("[DeepResearch] QUICK_ANALYSIS_CONFIG load error:", error);
                    }}
                    onDataLoaded={handleQuickAnalysisDataLoaded}
                />
            )}
            {taskHistoryConfig && (
                <TaskHistoryCard
                    config={taskHistoryConfig}
                    onError={(error) => {
                        console.warn("[DeepResearch] TASK_HISTORY_CONFIG load error:", error);
                    }}
                    onDataLoaded={handleTaskHistoryDataLoaded}
                    navigationSource="deep-research"
                    deepResearchConversationId={deepResearchConversationId ?? undefined}
                />
            )}
            {navigateBlock && (
                <NavigationCard
                    config={navigateBlock}
                    navigationSource="deep-research"
                    deepResearchConversationId={deepResearchConversationId ?? undefined}
                />
            )}
            {datasetRegistrationConfig && (
                <DatasetRegistrationCard
                    config={datasetRegistrationConfig}
                    onUploadStarted={(taskId, fileCount, datasetName, mode) => handleRegistrationSuccess(taskId, fileCount, datasetName, mode)}
                    onError={(error) => console.error("[DeepResearch] Dataset upload error:", error)}
                    messageId={message.id}
                />
            )}
            {/* Training chat link UI moved to ResearchCard's TrainingCard — content stripping above still applies */}
        </div>
    );
}
