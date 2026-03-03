import { useTranslations } from "../../../lib/deep-research/i18n";
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { parse as bestEffortParse } from "best-effort-json-parser";
import { LoadingOutlined } from "@ant-design/icons";
import { motion } from "framer-motion";
import {
  Download,
  Headphones,
  ChevronDown,
  ChevronRight,
  Lightbulb,
  Wrench,
  Bot,
  User,
} from "lucide-react";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { updateMessage as apiUpdateMessage } from "../../../api";
import i18n from "../../../i18n";
import {
  OptionButtons,
  parseOptions,
  removeOptionsBlock,
} from "../../../components/chat/OptionButtons";
import {
  TaskConfigCard,
  parseTaskConfig,
  removeTaskConfigBlock,
} from "../../../components/chat/TaskConfigCard";
import { LoadingAnimation } from "../../../components/deep-research/loading-animation";
import { Markdown } from "../../../components/deep-research/markdown";
import { RainbowText } from "../../../components/deep-research/rainbow-text";
import { RollingText } from "../../../components/deep-research/rolling-text";
import { DatasetRegistrationCard, parseDatasetRegistrationConfig, removeDatasetRegistrationBlock } from "../../../components/chat/DatasetRegistrationCard";
import {
  ScrollContainer,
  type ScrollContainerRef,
} from "../../../components/deep-research/scroll-container";
import { Tooltip } from "../../../components/deep-research/tooltip";
import { Button } from "../../../components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "../../../components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../../../components/ui/collapsible";
import type { Message, Option } from "../../../lib/deep-research/messages";
import {
  closeResearch,
  debugDeepResearchStore,
  flushDeepResearchPersistNow,
  getDeepResearchDebugSnapshot,
  isDeepResearchDebugEnabled,
  openResearch,
  useLastFeedbackMessageId,
  useLastInterruptMessage,
  useMessage,
  useMessageIds,
  useRenderableMessageIds,
  useResearchMessage,
  useStore,
} from "../../../lib/deep-research/store";
import { parseJSON } from "../../../lib/deep-research/utils";
import { cn } from "../../../lib/utils";

import { parsePlannerPayload } from "./utils";
import { MessageBubble, AssistantStructuredContent } from "./blocks/message-content";
import { ThoughtBlock } from "./blocks/thought-block";
import { PlanCard } from "./cards/plan-card";
import { ResearchCard } from "./cards/research-card";
import { PodcastCard } from "./cards/podcast-card";




export function MessageListView({
  className,
  onFeedback,
  onSendMessage,
}: {
  className?: string;
  onFeedback?: (feedback: { option: Option }) => void;
  onSendMessage?: (
    message: string,
    options?: { interruptFeedback?: string },
  ) => void;
}) {
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.research");
  const scrollContainerRef = useRef<ScrollContainerRef>(null);
  // Use renderable message IDs to avoid React key warnings from duplicate or non-rendering messages
  const messageIds = useRenderableMessageIds();
  const rawMessageIds = useMessageIds();
  const messages = useStore((state) => state.messages);
  const researchIds = useStore((state) => state.researchIds);
  const researchPlanIds = useStore((state) => state.researchPlanIds);
  const researchReportIds = useStore((state) => state.researchReportIds);
  const researchActivityIds = useStore((state) => state.researchActivityIds);
  const interruptMessage = useLastInterruptMessage();
  const waitingForFeedbackMessageId = useLastFeedbackMessageId();
  const responding = useStore((state) => state.responding);
  const generationPhase = useStore((state) => state.generationPhase);
  const isThinking = generationPhase === "thinking";
  const noOngoingResearch = useStore(
    (state) => state.ongoingResearchId === null,
  );
  const ongoingResearchIsOpen = useStore(
    (state) => state.ongoingResearchId === state.openResearchId,
  );
  const renderDebugSignatureRef = useRef<string>("");

  useEffect(() => {
    if (!isDeepResearchDebugEnabled()) return;

    const renderableSet = new Set(messageIds);
    const researchRootSet = new Set(researchIds);
    const hiddenDetails = rawMessageIds
      .map((id) => {
        const message = messages.get(id);
        if (!message) {
          return {
            id,
            reason: ["missing_message"],
          };
        }

        const trimmedContent = (message.content ?? "").trim();
        const isResearchRoot = researchRootSet.has(id);
        const boundToResearch =
          researchRootSet.has(message.id) ||
          Array.from(researchPlanIds.entries()).some(
            ([rid, planId]) => researchRootSet.has(rid) && planId === message.id,
          ) ||
          Array.from(researchReportIds.entries()).some(
            ([rid, reportId]) =>
              researchRootSet.has(rid) && reportId === message.id,
          ) ||
          Array.from(researchActivityIds.entries()).some(
            ([rid, ids]) => researchRootSet.has(rid) && ids.includes(message.id),
          );

        const isLocaleOnly =
          !!trimmedContent && /^[a-z]{2}(-[A-Z]{2})?$/.test(trimmedContent);
        const isEmptyContent =
          !trimmedContent &&
          !isResearchRoot &&
          message.agent !== "planner" &&
          message.agent !== "podcast";
        const passesMessageListItem =
          !isLocaleOnly &&
          !isEmptyContent &&
          (message.role === "user" ||
            message.role === "assistant" ||
            message.agent === "coordinator" ||
            message.agent === "podcast" ||
            isResearchRoot);

        const reason: string[] = [];
        if (!renderableSet.has(id)) reason.push("filtered_by_useRenderableMessageIds");
        if (!passesMessageListItem) {
          if (isLocaleOnly) {
            reason.push("filtered_locale_only_content");
          } else if (isEmptyContent) {
            reason.push("filtered_empty_content");
          } else {
            reason.push("filtered_message_list_item_guard");
          }
        }
        if (reason.length === 0) return null;

        return {
          id,
          role: message.role,
          agent: message.agent ?? null,
          contentLength: trimmedContent.length,
          isResearchRoot,
          boundToResearch,
          reason,
        };
      })
      .filter((entry): entry is NonNullable<typeof entry> => entry !== null);

    const signature = JSON.stringify({
      rawMessageIds,
      messageIds,
      researchIds,
      hiddenIds: hiddenDetails.map((item) => item.id),
    });
    if (signature === renderDebugSignatureRef.current) return;
    renderDebugSignatureRef.current = signature;

    debugDeepResearchStore("message-list render pipeline", {
      ...getDeepResearchDebugSnapshot(),
      rawMessageCount: rawMessageIds.length,
      renderableCount: messageIds.length,
      hiddenCount: hiddenDetails.length,
      rawMessageIds,
      renderableMessageIds: messageIds,
      hiddenDetails,
    });
  }, [
    messageIds,
    messages,
    rawMessageIds,
    researchActivityIds,
    researchIds,
    researchPlanIds,
    researchReportIds,
  ]);

  const handleToggleResearch = useCallback(() => {
    // Fix the issue where auto-scrolling to the bottom
    // occasionally fails when toggling research.
    const timer = setTimeout(() => {
      if (scrollContainerRef.current) {
        scrollContainerRef.current.scrollToBottom();
      }
    }, 500);
    return () => {
      clearTimeout(timer);
    };
  }, []);

  return (
    <ScrollContainer
      className={cn("flex h-full w-full flex-col overflow-hidden", className)}
      scrollShadowColor="#f9fafb"
      autoScrollToBottom
      ref={scrollContainerRef}
    >
      <ul className="mx-auto flex w-full max-w-4xl flex-col px-4 pt-6 pb-40">
        {messageIds.map((messageId) => (
          <MessageListItem
            key={messageId}
            messageId={messageId}
            waitForFeedback={waitingForFeedbackMessageId === messageId}
            interruptMessage={interruptMessage}
            onFeedback={onFeedback}
            onSendMessage={onSendMessage}
            onToggleResearch={handleToggleResearch}
          />
        ))}
      </ul>

    </ScrollContainer>
  );
}

import { MessageListItem } from "./message-list-item";

