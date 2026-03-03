// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import React from "react";

import { useMessage, useStore } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";
import { LoadingAnimation } from "../../../components/deep-research/loading-animation";
import { Markdown } from "../../../components/deep-research/markdown";

import {
  CrawlToolCall,
  MCPToolCall,
  PythonToolCall,
  RetrieverToolCall,
  WebSearchToolCall,
} from "./blocks/tool-calls";

// Performance optimization constants
const MAX_ANIMATED_ITEMS = 10; // Only animate first 10 items
const ANIMATION_DELAY_MULTIPLIER = 0.05; // Reduced delay between animations

export function ResearchActivitiesBlock({
  className,
  researchId,
}: {
  className?: string;
  researchId: string;
}) {
  const activityIds = useStore((state) =>
    state.researchActivityIds.get(researchId),
  )!;
  const ongoing = useStore((state) => state.ongoingResearchId === researchId);

  return (
    <>
      <ul className={cn("flex flex-col py-4", className)}>
        {activityIds.map(
          (activityId, i) => {
            if (i === 0) return null;

            // Performance optimization: limit animations for large lists
            const shouldAnimate = i < MAX_ANIMATED_ITEMS;
            const animationDelay = shouldAnimate ? Math.min(i * ANIMATION_DELAY_MULTIPLIER, 0.5) : 0;

            return (
              <motion.li
                key={activityId}
                style={{ transition: shouldAnimate ? "all 0.3s ease-out" : "none" }}
                initial={shouldAnimate ? { opacity: 0, y: 24 } : { opacity: 1, y: 0 }}
                animate={{ opacity: 1, y: 0 }}
                transition={shouldAnimate ? {
                  duration: 0.3, // Reduced from 0.4
                  delay: animationDelay,
                  ease: "easeOut",
                } : undefined}
              >
                <ActivityMessage messageId={activityId} />
                <ActivityListItem messageId={activityId} />
                {i !== activityIds.length - 1 && <hr className="my-8" />}
              </motion.li>
            );
          },
        )}
      </ul>
      {ongoing && <LoadingAnimation className="mx-4 my-12" />}
    </>
  );
}

const ActivityMessage = React.memo(({ messageId }: { messageId: string }) => {
  const message = useMessage(messageId);
  if (message?.agent && message.content) {
    if (message.agent !== "reporter" && message.agent !== "planner") {
      return (
        <div className="px-4 py-2">
          <Markdown animated checkLinkCredibility>
            {message.content}
          </Markdown>
        </div>
      );
    }
  }
  return null;
});
ActivityMessage.displayName = "ActivityMessage";

const ActivityListItem = React.memo(({ messageId }: { messageId: string }) => {
  const message = useMessage(messageId);
  if (message) {
    if (!message.isStreaming && message.toolCalls?.length) {
      const toolCallComponents = message.toolCalls
        .filter(toolCall => !(typeof toolCall.result === "string" && toolCall.result?.startsWith("Error")))
        .map(toolCall => {
          if (toolCall.name === "web_search") {
            return <WebSearchToolCall key={toolCall.id} toolCall={toolCall} />;
          } else if (toolCall.name === "crawl_tool") {
            return <CrawlToolCall key={toolCall.id} toolCall={toolCall} />;
          } else if (toolCall.name === "python_repl_tool") {
            return <PythonToolCall key={toolCall.id} toolCall={toolCall} />;
          } else if (toolCall.name === "local_search_tool") {
            return <RetrieverToolCall key={toolCall.id} toolCall={toolCall} />;
          } else {
            return <MCPToolCall key={toolCall.id} toolCall={toolCall} />;
          }
        });

      if (toolCallComponents.length > 0) {
        return <>{toolCallComponents}</>;
      }
    }
  }
  return null;
});
ActivityListItem.displayName = "ActivityListItem";


