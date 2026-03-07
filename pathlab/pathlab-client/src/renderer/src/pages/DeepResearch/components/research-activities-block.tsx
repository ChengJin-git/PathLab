// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { ChevronRight, Search, BookOpenText, Brain, Code2 } from "lucide-react";
import React, { useMemo, useState, useCallback } from "react";

import { useTranslations } from "../../../lib/deep-research/i18n";
import { useMessage, useStore } from "../../../lib/deep-research/store";
import { stripInternalToolReplayContent, stripResearchMeta } from "../../../lib/deep-research/utils";
import { cn } from "../../../lib/utils";
import { LoadingAnimation } from "../../../components/deep-research/loading-animation";
import { Markdown } from "../../../components/deep-research/markdown";
import type { Message } from "../../../lib/deep-research/messages";

import {
  CrawlToolCall,
  hasToolExecutionEvidence,
  MCPToolCall,
  PythonToolCall,
  RetrieverToolCall,
  WebSearchToolCall,
} from "./blocks/tool-calls";

const EMPTY_ACTIVITY_IDS: string[] = [];

/** Check if a message has visible content (text after META strip, or tool calls). */
function hasVisibleContent(msg: Message | undefined, reportId?: string): boolean {
  if (!msg) return false;
  const agent = msg.agent ?? "";
  if (agent === "planner") return false;
  if (agent === "reporter" && msg.id === reportId) return false;
  const visibleText = stripInternalToolReplayContent(stripResearchMeta(msg.content ?? ""));
  if (visibleText) return true;
  if (msg.toolCalls?.some(hasToolExecutionEvidence)) return true;
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
  reportId?: string,
): ActivityGroup[] {
  const groups: ActivityGroup[] = [];
  let current: ActivityGroup | null = null;

  // Skip index 0 (plan message)
  for (let i = 1; i < activityIds.length; i++) {
    const id = activityIds[i];
    const msg = messages.get(id);
    const agent = msg?.agent ?? "researcher";

    // Skip planner content. Reporter drafts stay visible here until they are bound as the formal report.
    if (agent === "planner") continue;
    if (!hasVisibleContent(msg, reportId)) continue;

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
    case "reporter":
      return { ...AGENT_META.analyst, label: t("activityAgentAnalyst") };
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
        if (!hasToolExecutionEvidence(tc)) continue;
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
  const ongoingFromStore = useStore((state) => state.ongoingResearchId === researchId);
  const reportId = useStore((state) => state.researchReportIds.get(researchId));
  const reportMessage = useStore((state) =>
    reportId ? state.messages.get(reportId) : undefined,
  );
  const hasCompletedReport = useMemo(() => {
    const visibleContent = stripResearchMeta(reportMessage?.content ?? "").trim();
    return !!reportId && visibleContent.length > 0 && !(reportMessage?.isStreaming ?? false);
  }, [reportId, reportMessage]);
  const ongoing = ongoingFromStore && !hasCompletedReport;

  const groups = useMemo(
    () => groupActivitiesByAgent(activityIds, messages, reportId),
    [activityIds, messages, reportId],
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
    <div className={cn("flex flex-col gap-3 py-4", className)}>
      {groups.map((group, gi) => (
        <ActivityGroupSection
          key={`${group.agent}-${gi}`}
          group={group}
          reportId={reportId}
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
  reportId,
  t,
  messages,
  expanded,
  onToggle,
  isLast,
  ongoing,
}: {
  group: ActivityGroup;
  reportId?: string;
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
    <div className="overflow-hidden rounded-2xl border border-gray-200/70 bg-white shadow-sm">
      {/* Group header — always visible */}
      <button
        type="button"
        onClick={onToggle}
        className={cn(
          "flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors",
          "hover:bg-gray-50",
          expanded && "bg-gray-50/80",
        )}
      >
        <ChevronRight
          size={14}
          className={cn(
            "mt-1 shrink-0 text-gray-400 transition-transform duration-200",
            expanded && "rotate-90",
          )}
        />
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-100">
          {meta.icon}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
            <span className="text-sm font-semibold text-gray-900">{meta.label}</span>
            {summary && <span className="text-xs text-gray-500 sm:text-right">{summary}</span>}
          </div>
        </div>
      </button>

      {/* Group content — only rendered when expanded */}
      {expanded && (
        <div className="border-t border-gray-100 bg-gray-50/50">
          <ul className="flex flex-col divide-y divide-gray-100">
            {group.activityIds.map((activityId) => (
              <ActivityItem key={activityId} messageId={activityId} reportId={reportId} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
});
ActivityGroupSection.displayName = "ActivityGroupSection";

const ActivityItem = React.memo(({ messageId, reportId }: { messageId: string; reportId?: string }) => {
  const message = useMessage(messageId);
  if (!message || !hasVisibleContent(message, reportId)) return null;

  return (
    <li className="px-2 py-2.5 sm:px-3">
      <ActivityMessage messageId={messageId} reportId={reportId} />
      <ActivityListItem messageId={messageId} />
    </li>
  );
});
ActivityItem.displayName = "ActivityItem";

const ActivityMessage = React.memo(({ messageId, reportId }: { messageId: string; reportId?: string }) => {
  const message = useMessage(messageId);
  if (!message?.content) return null;
  const agent = message.agent ?? "";
  if (agent === "planner") return null;
  if (agent === "reporter" && message.id === reportId) return null;
  const cleanContent = stripInternalToolReplayContent(stripResearchMeta(message.content));
  if (!cleanContent) return null;

  return (
    <div className="rounded-xl border border-gray-200/80 bg-white px-4 py-3 shadow-sm">
      <Markdown
        className="prose-slate max-w-none prose-sm
          prose-p:my-2 prose-p:leading-7 prose-p:text-gray-700
          prose-headings:mt-4 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-gray-900
          prose-ul:my-3 prose-ul:list-disc prose-ul:pl-6
          prose-ol:my-3 prose-ol:list-decimal prose-ol:pl-6
          prose-li:my-1.5 prose-li:leading-7 prose-li:text-gray-700
          prose-code:rounded prose-code:bg-gray-100 prose-code:px-1.5 prose-code:py-0.5 prose-code:text-xs prose-code:text-gray-800 prose-code:before:content-none prose-code:after:content-none
          prose-pre:my-3 prose-pre:rounded-xl prose-pre:bg-gray-900 prose-pre:p-4 prose-pre:text-gray-100
          prose-a:no-underline prose-hr:my-4 prose-strong:text-gray-900"
        animated
        checkLinkCredibility
      >
        {cleanContent}
      </Markdown>
    </div>
  );
});
ActivityMessage.displayName = "ActivityMessage";

const ActivityListItem = React.memo(({ messageId }: { messageId: string }) => {
  const message = useMessage(messageId);
  if (message) {
    if (message.toolCalls?.length) {
      const toolCallComponents = message.toolCalls
        .filter(hasToolExecutionEvidence)
        .map(toolCall => {
          if (toolCall.name === "web_search") {
            return (
              <WebSearchToolCall
                key={toolCall.id}
                toolCall={toolCall}
                messageIsStreaming={Boolean(message.isStreaming)}
                messageFinishReason={message.finishReason}
              />
            );
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
