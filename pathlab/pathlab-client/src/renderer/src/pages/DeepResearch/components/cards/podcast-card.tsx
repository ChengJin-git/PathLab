// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import React, { useMemo, useState } from "react";
import { LoadingOutlined } from "@ant-design/icons";
import { Download, Headphones } from "lucide-react";
import { RainbowText } from "../../../../components/deep-research/rainbow-text";
import { Tooltip } from "../../../../components/deep-research/tooltip";
import { Button } from "../../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../../components/ui/card";
import type { Message } from "../../../../lib/deep-research/messages";
import { cn } from "../../../../lib/utils";

export function PodcastCard({
    className,
    message,
}: {
    className?: string;
    message: Message;
}) {
    const data = useMemo(() => {
        try {
            return JSON.parse(message.content ?? "{}");
        } catch {
            return { error: "Invalid podcast data" };
        }
    }, [message.content]);
    const title = data?.title;
    const audioUrl = data?.audioUrl;
    const isGenerating = message.isStreaming;
    const hasError = data?.error !== undefined;
    const [isPlaying, setIsPlaying] = useState(false);

    return (
        <Card className={cn("w-full max-w-2xl overflow-hidden border-gray-200/70 bg-white/90 shadow-sm", className)}>
            <CardHeader className="border-b border-gray-100 bg-gradient-to-r from-primary-50/70 via-white to-white">
                <div className="text-muted-foreground flex items-center justify-between text-sm">
                    <div className="flex items-center gap-2">
                        {isGenerating ? <LoadingOutlined /> : <Headphones size={16} />}
                        {!hasError ? (
                            <RainbowText animated={isGenerating}>
                                {isGenerating
                                    ? "Generating podcast..."
                                    : isPlaying
                                        ? "Now playing podcast..."
                                        : "Podcast"}
                            </RainbowText>
                        ) : (
                            <div className="text-red-500">
                                Error when generating podcast. Please try again.
                            </div>
                        )}
                    </div>
                    {!hasError && !isGenerating && (
                        <div className="flex">
                            <Tooltip title="Download podcast">
                                <Button variant="ghost" size="icon" asChild className="rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700">
                                    <a
                                        href={audioUrl}
                                        download={`${(title ?? "podcast").replaceAll(" ", "-")}.mp3`}
                                    >
                                        <Download size={16} />
                                    </a>
                                </Button>
                            </Tooltip>
                        </div>
                    )}
                </div>
                <CardTitle>
                    <div className="text-lg font-medium text-gray-900">
                        <RainbowText animated={isGenerating}>{title}</RainbowText>
                    </div>
                </CardTitle>
            </CardHeader>
            <CardContent className="bg-gray-50/40 pt-5">
                {audioUrl ? (
                    <audio
                        className="w-full"
                        src={audioUrl}
                        controls
                        onPlay={() => setIsPlaying(true)}
                        onPause={() => setIsPlaying(false)}
                    />
                ) : (
                    <div className="w-full"></div>
                )}
            </CardContent>
        </Card>
    );
}
