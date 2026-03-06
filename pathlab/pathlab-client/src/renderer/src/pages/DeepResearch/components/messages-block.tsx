import { useTranslations } from "../../../lib/deep-research/i18n";
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { useCallback, useRef, useState } from "react";

import { Button } from "../../../components/ui/button";
import type { Option, Resource } from "../../../lib/deep-research/messages";
import { sendMessage, useMessageIds, useStore } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";

import { ConversationStarter } from "./conversation-starter";
import { InputBox } from "./input-box";
import { MessageListView } from "./message-list-view";

import { useTranslation } from "react-i18next";

export function MessagesBlock({ className }: { className?: string }) {
  const { t: tGlobal } = useTranslation();
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.messages");
  const messageIds = useMessageIds();
  const messageCount = messageIds.length;
  const responding = useStore((state) => state.responding);
  const [feedback, setFeedback] = useState<{ option: Option } | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const handleSend = useCallback(
    async (
      message: string,
      options?: {
        interruptFeedback?: string;
        resources?: Array<Resource>;
      },
    ) => {
      const abortController = new AbortController();
      abortControllerRef.current = abortController;
      try {
        await sendMessage(
          message,
          {
            interruptFeedback:
              options?.interruptFeedback ?? feedback?.option.value,
            resources: options?.resources,
          },
          {
            abortSignal: abortController.signal,
          },
        );
      } catch { }
    },
    [feedback],
  );
  const handleCancel = useCallback(() => {
    abortControllerRef.current?.abort("user_cancelled");
    abortControllerRef.current = null;
  }, []);
  const handleFeedback = useCallback(
    (feedback: { option: Option }) => {
      setFeedback(feedback);
    },
    [setFeedback],
  );
  const handleRemoveFeedback = useCallback(() => {
    setFeedback(null);
  }, [setFeedback]);
  return (
    <div className={cn("flex h-full min-h-0 flex-col", className)}>
      <div className="min-h-0 flex-1 overflow-hidden">
        {responding || messageCount !== 0 ? (
          <MessageListView
            className="flex h-full"
            onFeedback={handleFeedback}
            onSendMessage={handleSend}
          />
        ) : (
          <ConversationStarter />
        )}
      </div>
      <div className="pointer-events-none fixed bottom-6 left-0 right-0 z-30 px-4">
        <div className="pointer-events-auto mx-auto max-w-4xl">
          <InputBox
            className="w-full"
            responding={responding}
            feedback={feedback}
            onSend={handleSend}
            onCancel={handleCancel}
            onRemoveFeedback={handleRemoveFeedback}
          />
          <div className="mt-4 pb-2 text-center text-xs text-gray-400">
            {tGlobal("aiChat.disclaimer")}
          </div>
        </div>
      </div>
    </div>
  );
}
