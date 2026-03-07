// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { ChevronRight, Search, BookOpenText, Brain, Code2 } from "lucide-react";
import React, { useMemo, useState, useCallback } from "react";

import { useTranslations } from "../../../lib/deep-research/i18n";
import { useMessage, useStore } from "../../../lib/deep-research/store";
import { stripResearchMeta } from "../../../lib/deep-research/utils";
import { cn } from "../../../lib/utils";
import { LoadingAnimation } from "../../../components/deep-research/loading-animation";
import { Markdown } from "../../../components/deep-research/markdown";
import type { Message } from "../../../lib/deep-research/messages";

import {
  CrawlToolCall,
  MCPToolCall,
  PythonToolCall,
  RetrieverToolCall,
  WebSearchToolCall,
} from "./blocks/tool-calls";

const EMPTY_ACTIVITY_IDS: string[] = [];

/** Check if a message has visible content (text after META strip, or tool calls). */
function hasVisibleContent(msg: Message | undefined): boolean {
  if (!msg) return false;
  const agent = msg.agent ?? "";
  if (agent === "reporter" || agent === "planner") return false;
  if (stripResearchMeta(msg.content)) return true;
  if (!msg.isStreaming && msg.toolCalls?.length) return true;
  return false;
}

// --- Grouping logic ---

interface ActivityGroup {
  agent: string;
  activityIds: string[];
}

function groupActivitiesByAgent(
  activityIds: string[],
  messages: Map<string, Message>,
): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  let current: ActivityGroup | null = null;

  // Skip index 0 (plan message)
  for (let i = 1; i < activityIds.length; i++) {
    const id = activityIds[i];
    const msg = messages.get(id);
    const agent = msg?.agent ?? "researcher";

    // Skip reporter/planner — shown separately; skip empty stubs
    if (agent === "reporter" || agent === "planner") continue;
    if (!hasVisibleContent(msg)) continue;

    if (!current || current.agent !== agent) {
      current = { agent, activityIds: [id] };
      groups.push(current);
    } else {
      current.activityIds.push(id);
    }
  }
  return groups;
}

const AGENT_META: Record<string, { icon: React.ReactNode }> = {
  researcher: {
    icon: <Search size={15} className="text-blue-500" />,
  },
  analyst: {
    icon: <Brain size={15} className="text-purple-500" />,
  },
  coder: {
    icon: <Code2 size={15} className="text-orange-500" />,
  },
};

function getAgentMeta(agent: string, t: (key: string, params?: Record<string, unknown>) => string) {
  switch (agent) {
    case "researcher":
      return { ...AGENT_META.researcher, label: t("activityAgentResearcher") };
    case "analyst":
      return { ...AGENT_META.analyst, label: t("activityAgentAnalyst") };
    case "coder":
      return { ...AGENT_META.coder, label: t("activityAgentCoder") };
    default:
      return {
        icon: <BookOpenText size={15} className="text-gray-500" />,
        label: agent.charAt(0).toUpperCase() + agent.slice(1),
      };
  }
}

// --- Summary computation ---

function useGroupSummary(
  activityIds: string[],
  messages: Map<string, Message>,
  t: (key: string, params?: Record<string, unknown>) => string,
): string {
  return useMemo(() => {
    let searches = 0;
    let crawls = 0;
    let pyRuns = 0;
    let mcpCalls = 0;
    let retrieves = 0;

    let visibleCount = 0;
    for (const id of activityIds) {
      const msg = messages.get(id);
      if (!msg) continue;
      if (hasVisibleContent(msg)) visibleCount++;
      if (!msg.toolCalls) continue;
      for (const tc of msg.toolCalls) {
        if (tc.name === "web_search") searches++;
        else if (tc.name === "crawl_tool") crawls++;
        else if (tc.name === "python_repl_tool") pyRuns++;
        else if (tc.name === "local_search_tool") retrieves++;
        else mcpCalls++;
      }
    }

    const parts: string[] = [];
    if (searches > 0) parts.push(t("activitySummarySearch", { count: searches }));
    if (crawls > 0) parts.push(t("activitySummaryPageRead", { count: crawls }));
    if (retrieves > 0) parts.push(t("activitySummaryRetrieval", { count: retrieves }));
    if (pyRuns > 0) parts.push(t("activitySummaryCodeRun", { count: pyRuns }));
    if (mcpCalls > 0) parts.push(t("activitySummaryToolCall", { count: mcpCalls }));

    if (parts.length > 0) return parts.join(t("activitySummarySeparator"));
    return visibleCount > 0
      ? t("activitySummaryActivity", { count: visibleCount })
      : "";
  }, [activityIds, messages, t]);
}

// --- Components ---

export function ResearchActivitiesBlock({
  className,
  researchId,
}: {
  className?: string;
  researchId: string;
}) {
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.research");
  const activityIds = useStore((state) =>
    state.researchActivityIds.get(researchId) ?? EMPTY_ACTIVITY_IDS,
  );
  const messages = useStore((state) => state.messages);
  const ongoing = useStore((state) => state.ongoingResearchId === researchId);

  const groups = useMemo(
    () => groupActivitiesByAgent(activityIds, messages),
    [activityIds, messages],
  );

  // Track which groups are expanded.
  // Default: only the last group is expanded; during streaming the last group stays open.
  const [manualExpanded, setManualExpanded] = useState<Record<number, boolean>>({});

  const toggleGroup = useCallback((index: number) => {
    setManualExpanded((prev) => ({ ...prev, [index]: !prev[index] }));
  }, []);

  const isGroupExpanded = useCallback(
    (index: number): boolean => {
      // If user has explicitly toggled, respect that
      if (manualExpanded[index] !== undefined) return manualExpanded[index];
      // Only one group → always expand
      if (groups.length === 1) return true;
      // Research complete → expand all groups so user can review everything
      if (!ongoing) return true;
      // During streaming, only expand the last (active) group
      if (index === groups.length - 1) return true;
      return false;
    },
    [manualExpanded, groups.length, ongoing],
  );

  if (groups.length === 0 && !ongoing) {
    return null;
  }

  return (
    <div className={cn("flex flex-col gap-2 py-4", className)}>
      {groups.map((group, gi) => (
        <ActivityGroupSection
          key={`${group.agent}-${gi}`}
          group={group}
          t={t}
          messages={messages}
          expanded={isGroupExpanded(gi)}
          onToggle={() => toggleGroup(gi)}
          isLast={gi === groups.length - 1}
          ongoing={ongoing && gi === groups.length - 1}
        />
      ))}
      {ongoing && <LoadingAnimation className="mx-4 my-12" />}
    </div>
  );
}

const ActivityGroupSection = React.memo(({
  group,
  t,
  messages,
  expanded,
  onToggle,
  isLast,
  ongoing,
}: {
  group: ActivityGroup;
  t: (key: string, params?: Record<string, unknown>) => string;
  messages: Map<string, Message>;
  expanded: boolean;
  onToggle: () => void;
  isLast: boolean;
  ongoing: boolean;
}) => {
  const meta = getAgentMeta(group.agent, t);
  const summary = useGroupSummary(group.activityIds, messages, t);

  return (
    <div className="rounded-lg border border-border/50 overflow-hidden">
      {/* Group header — always visible */}
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors",
          "hover:bg-accent/50",
          expanded && "bg-accent/30",
        )}
      >
        <ChevronRight
          size={14}
          className={cn(
            "text-muted-foreground shrink-0 transition-transform duration-200",
            expanded && "rotate-90",
          )}
        />
        {meta.icon}
        <span className="text-sm font-medium">{meta.label}</span>
        <span className="text-muted-foreground text-xs ml-auto">{summary}</span>
      </button>

      {/* Group content — only rendered when expanded */}
      {expanded && (
        <div className="border-t border-border/50">
          <ul className="flex flex-col divide-y divide-border/50">
            {group.activityIds.map((activityId) => (
              <ActivityItem key={activityId} messageId={activityId} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
});
ActivityGroupSection.displayName = "ActivityGroupSection";

const ActivityItem = React.memo(({ messageId }: { messageId: string }) => {
  const message = useMessage(messageId);
  if (!message || !hasVisibleContent(message)) return null;

  return (
    <li className="py-2">
      <ActivityMessage messageId={messageId} />
      <ActivityListItem messageId={messageId} />
    </li>
  );
});
ActivityItem.displayName = "ActivityItem";

const ActivityMessage = React.memo(({ messageId }: { messageId: string }) => {
  const message = useMessage(messageId);
  if (!message?.content) return null;
  const agent = message.agent ?? "";
  if (agent === "reporter" || agent === "planner") return null;
  const cleanContent = stripResearchMeta(message.content);
  if (!cleanContent) return null;

  return (
    <div className="px-4 py-2">
      <Markdown animated checkLinkCredibility>
        {cleanContent}
      </Markdown>
    </div>
  );
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
