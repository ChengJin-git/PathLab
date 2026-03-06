// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import React, { useCallback, useMemo } from "react";
import { updateMessage as apiUpdateMessage } from "../../../../api";
import { OptionButtons, parseOptions, removeOptionsBlock } from "../../../../components/chat/OptionButtons";
import { TaskConfigCard, parseTaskConfig, removeTaskConfigBlock } from "../../../../components/chat/TaskConfigCard";
import { DatasetRegistrationCard, parseDatasetRegistrationConfig, removeDatasetRegistrationBlock } from "../../../../components/chat/DatasetRegistrationCard";
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
    const options = useMemo(() => parseOptions(message.content ?? ""), [message.content]);
    const taskConfig = useMemo(
        () => parseTaskConfig(message.content ?? ""),
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
    if (datasetRegistrationConfig) {
        displayContent = removeDatasetRegistrationBlock(displayContent);
    }
    if (trainingChatLink) {
        displayContent = removeTrainingChatLinkBlock(displayContent);
    }

    // If the message only contained a training chat link (no other content or cards), render nothing.
    const hasVisibleContent = displayContent.trim() || options || taskConfig || datasetRegistrationConfig;
    if (!hasVisibleContent && trainingChatLink) {
        return null;
    }

    const handleTaskSubmitSuccess = useCallback(
        async (taskId: string) => {
            const nextContent = injectSubmittedTaskId(message.content ?? "", taskId);
            if (nextContent !== message.content) {
                useStore.getState().updateMessage({
                    ...message,
                    content: nextContent,
                    contentChunks: [nextContent],
                });
            }

            const state = useStore.getState();
            const conversationId = state.conversationId;
            const backendId = state.messageBackendIds.get(message.id);
            if (!conversationId || backendId == null) {
                return;
            }
            try {
                await apiUpdateMessage(conversationId, backendId, nextContent);
            } catch (error) {
                console.warn("[DeepResearch] Failed to persist TASK_CONFIG submission:", error);
            }
        },
        [message],
    );

    const handleRegistrationSuccess = useCallback(
        async (taskId: string, fileCount: number, datasetName: string, mode: 'existing' | 'new') => {
            const currentContent = message.content ?? "";
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

            if (nextContent !== currentContent) {
                useStore.getState().updateMessage({
                    ...message,
                    content: nextContent,
                    contentChunks: [nextContent],
                });

                const state = useStore.getState();
                const conversationId = state.conversationId;
                const backendId = state.messageBackendIds.get(message.id);
                if (conversationId && backendId != null) {
                    try {
                        await apiUpdateMessage(conversationId, backendId, nextContent);
                    } catch (error) {
                        console.warn("[DeepResearch] Failed to persist DATASET_REGISTRATION submission:", error);
                    }
                }
            }

            const successMsg = mode === 'new'
                ? `Started uploading ${fileCount} files to new dataset "${datasetName}". What should we do next?`
                : `Started uploading ${fileCount} files to existing dataset. What should we do next?`;
            onSendMessage?.(successMsg);
        },
        [message, onSendMessage],
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
