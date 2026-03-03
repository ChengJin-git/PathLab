import { useTranslations } from "../../../lib/deep-research/i18n";
// Research statistics bar: shows token usage and response time


import { Clock, Cpu, Zap } from "lucide-react";
import { useEffect, useState } from "react";

import { Tooltip } from "../../../components/deep-research/tooltip";
import {
  useTokenUsage,
  useResponseTiming,
  useStore,
} from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";

function formatDuration(ms: number): string {
  if (ms < 1000) {
    return `${ms}ms`;
  }
  const seconds = ms / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds.toFixed(0)}s`;
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1)}M`;
  }
  if (n >= 1_000) {
    return `${(n / 1_000).toFixed(1)}K`;
  }
  return n.toLocaleString();
}

export function ResearchStatsBar({ className }: { className?: string }) {
  // @ts-ignore - i18n shim
const t = useTranslations("chat.stats");
  const tokenUsage = useTokenUsage();
  const responseTiming = useResponseTiming();
  const responding = useStore((state) => state.responding);
  const [showDetails, setShowDetails] = useState(false);

  // Calculate elapsed time
  const elapsedMs = (() => {
    if (responseTiming?.durationMs != null) {
      return responseTiming.durationMs;
    }
    if (responding && responseTiming?.startTime) {
      return Date.now() - responseTiming.startTime;
    }
    return null;
  })();

  // Don't show if there's nothing to display
  if (!tokenUsage && !elapsedMs) {
    return null;
  }

  return (
    <div className={cn("w-full", className)}>
      {/* Main stats bar */}
      <div
        className={cn(
          "bg-muted/40 flex items-center justify-between gap-4 rounded-lg px-4 py-1.5 text-xs",
          "border border-transparent transition-colors",
          showDetails && "border-border/50",
        )}
      >
        <div className="flex items-center gap-4">
          {/* Response time */}
          {elapsedMs != null && (
            <Tooltip title={t("responseTime")}>
              <div className="text-muted-foreground flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" />
                <span className="font-medium">
                  {responding ? (
                    <TickingTimer startTime={responseTiming!.startTime} />
                  ) : (
                    formatDuration(elapsedMs)
                  )}
                </span>
              </div>
            </Tooltip>
          )}

          {/* Total tokens */}
          {tokenUsage && (
            <>
              <Tooltip title={t("totalTokens")}>
                <div className="text-muted-foreground flex items-center gap-1.5">
                  <Zap className="h-3.5 w-3.5" />
                  <span className="font-medium">
                    {formatNumber(tokenUsage.totalTokens)} tokens
                  </span>
                </div>
              </Tooltip>

              {/* LLM calls */}
              <Tooltip title={t("llmCalls")}>
                <div className="text-muted-foreground flex items-center gap-1.5">
                  <Cpu className="h-3.5 w-3.5" />
                  <span className="font-medium">
                    {tokenUsage.totalCalls} calls
                  </span>
                </div>
              </Tooltip>
            </>
          )}
        </div>

        {/* Toggle details */}
        {tokenUsage && (
          <button
            className="text-muted-foreground hover:text-foreground cursor-pointer text-xs underline-offset-2 transition-colors hover:underline"
            onClick={() => setShowDetails(!showDetails)}
          >
            {showDetails ? "−" : t("byAgent")}
          </button>
        )}
      </div>

      {/* Expandable detail section */}
      {showDetails && tokenUsage && (
        <div className="bg-muted/20 mt-1 rounded-lg px-4 py-2 text-xs">
          {/* Input / Output breakdown */}
          <div className="text-muted-foreground mb-2 flex gap-6">
            <span>
              {t("promptTokens")}:{" "}
              <span className="text-foreground font-medium">
                {formatNumber(tokenUsage.totalPromptTokens)}
              </span>
            </span>
            <span>
              {t("completionTokens")}:{" "}
              <span className="text-foreground font-medium">
                {formatNumber(tokenUsage.totalCompletionTokens)}
              </span>
            </span>
          </div>

          {/* Per-agent breakdown */}
          <div className="space-y-1">
            {Object.entries(tokenUsage.byAgent).map(([agent, stats]) => (
              <div
                key={agent}
                className="text-muted-foreground flex items-center justify-between"
              >
                <span className="capitalize">{agent}</span>
                <span className="font-mono tabular-nums">
                  {formatNumber(stats.total_tokens)} tokens · {stats.calls}{" "}
                  calls
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Live ticking timer that updates every second while responding */
function TickingTimer({ startTime }: { startTime: number }) {
  const [, setTick] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  return <>{formatDuration(Date.now() - startTime)}</>;
}
