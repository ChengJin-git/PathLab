// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import React, { useState } from "react";
import { useTranslations } from "../../../../lib/deep-research/i18n";
import { ChevronDown, ChevronRight, Lightbulb } from "lucide-react";
import { LoadingAnimation } from "../../../../components/deep-research/loading-animation";
import { Markdown } from "../../../../components/deep-research/markdown";
import { ScrollContainer } from "../../../../components/deep-research/scroll-container";
import { Button } from "../../../../components/ui/button";
import { Card, CardContent } from "../../../../components/ui/card";
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "../../../../components/ui/collapsible";
import { cn } from "../../../../lib/utils";

export function ThoughtBlock({
    className,
    content,
    isStreaming,
    hasMainContent,
    contentChunks,
}: {
    className?: string;
    content: string;
    isStreaming?: boolean;
    hasMainContent?: boolean;
    contentChunks?: string[];
}) {
    // @ts-ignore - i18n shim
    const t = useTranslations("chat.research");
    const [isOpen, setIsOpen] = useState(true);
    const [hasAutoCollapsed, setHasAutoCollapsed] = useState(false);

    React.useEffect(() => {
        if (hasMainContent && !hasAutoCollapsed) {
            setIsOpen(false);
            setHasAutoCollapsed(true);
        }
    }, [hasMainContent, hasAutoCollapsed]);

    if (!content || content.trim() === "") {
        return null;
    }

    // Split content into static (previous chunks) and streaming (current chunk)
    const chunks = contentChunks ?? [];
    const staticContent = chunks.slice(0, -1).join("");
    const streamingChunk = isStreaming && chunks.length > 0 ? (chunks[chunks.length - 1] ?? "") : "";
    const hasStreamingContent = isStreaming && streamingChunk.length > 0;

    return (
        <div className={cn("mb-6 w-full", className)}>
            <Collapsible open={isOpen} onOpenChange={setIsOpen}>
                <CollapsibleTrigger asChild>
                    <Button
                        variant="ghost"
                        className={cn(
                            "h-auto w-full justify-start rounded-xl border px-6 py-4 text-left transition-all duration-200",
                            "hover:bg-accent hover:text-accent-foreground",
                            isStreaming
                                ? "border-primary/20 bg-primary/5 shadow-sm"
                                : "border-border bg-card",
                        )}
                    >
                        <div className="flex w-full items-center gap-3">
                            <Lightbulb
                                size={18}
                                className={cn(
                                    "shrink-0 transition-colors duration-200",
                                    isStreaming ? "text-primary" : "text-muted-foreground",
                                )}
                            />
                            <span
                                className={cn(
                                    "leading-none font-semibold transition-colors duration-200",
                                    isStreaming ? "text-primary" : "text-foreground",
                                )}
                            >
                                {t("deepThinking")}
                            </span>
                            {isStreaming && <LoadingAnimation className="ml-2 scale-75" />}
                            <div className="flex-grow" />
                            {isOpen ? (
                                <ChevronDown
                                    size={16}
                                    className="text-muted-foreground transition-transform duration-200"
                                />
                            ) : (
                                <ChevronRight
                                    size={16}
                                    className="text-muted-foreground transition-transform duration-200"
                                />
                            )}
                        </div>
                    </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:slide-up-2 data-[state=open]:slide-down-2 mt-3">
                    <Card
                        className={cn(
                            "transition-all duration-200",
                            isStreaming ? "border-primary/20 bg-primary/5" : "border-border",
                        )}
                    >
                        <CardContent>
                            <div className="flex h-40 w-full overflow-y-auto">
                                <ScrollContainer
                                    className={cn(
                                        "flex h-full w-full flex-col overflow-hidden",
                                        className,
                                    )}
                                    scrollShadow={false}
                                    autoScrollToBottom
                                >
                                    {staticContent && (
                                        <Markdown
                                            className={cn(
                                                "prose dark:prose-invert max-w-none transition-colors duration-200",
                                                "opacity-80",
                                            )}
                                            animated={false}
                                        >
                                            {staticContent}
                                        </Markdown>
                                    )}
                                    {hasStreamingContent && (
                                        <Markdown
                                            className={cn(
                                                "prose dark:prose-invert max-w-none transition-colors duration-200",
                                                "prose-primary",
                                            )}
                                            animated={false}
                                        >
                                            {streamingChunk}
                                        </Markdown>
                                    )}
                                    {!hasStreamingContent && (
                                        <Markdown
                                            className={cn(
                                                "prose dark:prose-invert max-w-none transition-colors duration-200",
                                                isStreaming ? "prose-primary" : "opacity-80",
                                            )}
                                            animated={false}
                                        >
                                            {content}
                                        </Markdown>
                                    )}
                                </ScrollContainer>
                            </div>
                        </CardContent>
                    </Card>
                </CollapsibleContent>
            </Collapsible>
        </div>
    );
}
