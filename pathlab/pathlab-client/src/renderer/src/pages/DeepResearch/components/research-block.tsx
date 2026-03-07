import { useTranslations } from "../../../lib/deep-research/i18n";
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT


import {
  Check,
  Copy,
  X,
  Download,
  FileText,
  FileCode,
  FileImage,
  FileType,
  Sparkles,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ScrollContainer } from "../../../components/deep-research/scroll-container";
import { Tooltip } from "../../../components/deep-research/tooltip";
import { Badge } from "../../../components/ui/badge";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../../../components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../../components/ui/tabs";
  import { closeResearch, useResearchMessage, useStore } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";

  import { parsePlannerPayload } from "./utils";
import { useReportExporter } from "./use-report-exporter";
import { ResearchActivitiesBlock } from "./research-activities-block";
import { ResearchReportBlock } from "./research-report-block";

export function ResearchBlock({
  className,
  researchId = null,
}: {
  className?: string;
  researchId: string | null;
}) {
  // @ts-ignore - i18n shim
  const t = useTranslations("chat.research");
  const reportId = useStore((state) =>
    researchId ? state.researchReportIds.get(researchId) : undefined,
  );
  const [activeTab, setActiveTab] = useState("activities");
  const hasReport = useStore((state) =>
    researchId ? state.researchReportIds.has(researchId) : false,
  );
  const reportStreaming = useStore((state) =>
    reportId ? (state.messages.get(reportId)?.isStreaming ?? false) : false,
  );
  const researchMessage = useResearchMessage(researchId ?? "");
  const researchRunStatus = useStore((state) =>
    researchId ? state.researchRunStatus.get(researchId) : undefined,
  );
  const ongoing = useStore((state) => state.ongoingResearchId === researchId);
  useEffect(() => {
    if (hasReport) {
      setActiveTab("report");
    }
  }, [hasReport]);

  const {
    isDownloading,
    copied,
    handleCopy,
    handleDownloadMarkdown,
    handleDownloadHTML,
    handleDownloadPDF,
    handleDownloadWord,
    handleDownloadImage,
  } = useReportExporter(reportId, researchId ?? undefined);

  // When the research id changes, set the active tab to activities
  useEffect(() => {
    if (!hasReport) {
      setActiveTab("activities");
    }
  }, [hasReport, researchId]);

  const title = useMemo(() => {
    if (!researchMessage) {
      return t("deepResearch");
    }
    const parsed = parsePlannerPayload(researchMessage.content ?? "");
    return parsed?.title?.trim() || t("deepResearch");
  }, [researchMessage, t]);

  const statusLabel = useMemo(() => {
    if (hasReport) {
      return reportStreaming ? t("generatingReport") : t("reportGenerated");
    }
    if (researchRunStatus === "cancelled") {
      return t("researchCancelled");
    }
    if (researchRunStatus === "error") {
      return t("researchFailedNetwork");
    }
    if (ongoing || researchRunStatus === "running") {
      return t("researching");
    }
    return t("activities");
  }, [hasReport, ongoing, reportStreaming, researchRunStatus, t]);

  const statusClassName = useMemo(() => {
    if (hasReport && !reportStreaming) {
      return "border-emerald-100 bg-emerald-50 text-emerald-700 hover:bg-emerald-100";
    }
    if (ongoing || reportStreaming || researchRunStatus === "running") {
      return "border-primary-100 bg-primary-50 text-primary-700 hover:bg-primary-100";
    }
    if (researchRunStatus === "cancelled") {
      return "border-gray-200 bg-gray-100 text-gray-600 hover:bg-gray-200";
    }
    if (researchRunStatus === "error") {
      return "border-amber-100 bg-amber-50 text-amber-700 hover:bg-amber-100";
    }
    return "border-gray-200 bg-gray-100 text-gray-600 hover:bg-gray-200";
  }, [hasReport, ongoing, reportStreaming, researchRunStatus]);

  return (
    <div className={cn("h-full w-full", className)}>
      <Card className="relative h-full w-full overflow-hidden border-gray-200/70 bg-white/90 shadow-sm backdrop-blur-sm">
        <Tabs
          className="flex h-full w-full flex-col"
          value={activeTab}
          onValueChange={(value) => setActiveTab(value)}
        >
          <div className="border-b border-gray-100/80 bg-gradient-to-b from-gray-50/90 to-white px-4 py-4 sm:px-6">
            <div className="flex flex-col gap-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 shadow-lg">
                      <Sparkles className="h-5 w-5 text-white" />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-lg font-semibold text-gray-900">{title}</div>
                      <div className="mt-2">
                        <Badge className={statusClassName}>{statusLabel}</Badge>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap items-center justify-end gap-1 sm:gap-2">
                  {hasReport && !reportStreaming && (
                    <>
                      <Tooltip title={t("copy")}>
                        <Button
                          className="rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                          size="icon"
                          variant="ghost"
                          onClick={handleCopy}
                        >
                          {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                        </Button>
                      </Tooltip>
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            className="rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                            size="icon"
                            variant="ghost"
                            title={t("downloadReport")}
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem onClick={handleDownloadMarkdown}>
                            <FileText className="mr-2 h-4 w-4" />
                            {t("downloadMarkdown")}
                          </DropdownMenuItem>
                          <DropdownMenuItem onClick={handleDownloadHTML}>
                            <FileCode className="mr-2 h-4 w-4" />
                            {t("downloadHTML")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={handleDownloadPDF}
                            disabled={isDownloading}
                          >
                            <FileType className="mr-2 h-4 w-4" />
                            {t("downloadPDF")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={handleDownloadWord}
                            disabled={isDownloading}
                          >
                            <FileText className="mr-2 h-4 w-4" />
                            {t("downloadWord")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onClick={handleDownloadImage}
                            disabled={isDownloading}
                          >
                            <FileImage className="mr-2 h-4 w-4" />
                            {t("downloadImage")}
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    </>
                  )}
                  <Tooltip title={t("close")}>
                    <Button
                      className="rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                      size="icon"
                      variant="ghost"
                      onClick={() => {
                        closeResearch();
                      }}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </Tooltip>
                </div>
              </div>
              <div className="flex w-full justify-center">
                <TabsList className="max-w-full rounded-full bg-gray-100/80 p-1 shadow-inner">
                  <TabsTrigger
                    className="whitespace-nowrap rounded-full px-4 sm:px-6 data-[state=active]:bg-white data-[state=active]:text-gray-900"
                    value="report"
                    disabled={!hasReport}
                  >
                    {t("report")}
                  </TabsTrigger>
                  <TabsTrigger
                    className="whitespace-nowrap rounded-full px-4 sm:px-6 data-[state=active]:bg-white data-[state=active]:text-gray-900"
                    value="activities"
                  >
                    {t("activities")}
                  </TabsTrigger>
                </TabsList>
              </div>
            </div>
          </div>
          <TabsContent
            className="h-full min-h-0 flex-grow px-4 pb-4 pt-2 sm:px-6"
            value="report"
            forceMount
            hidden={activeTab !== "report"}
          >
            <ScrollContainer
              className="h-full pb-8"
              scrollShadowColor="#f8fafc"
              autoScrollToBottom={!hasReport || reportStreaming}
            >
              {reportId && researchId && (
                <ResearchReportBlock
                  className="mt-4"
                  researchId={researchId}
                  messageId={reportId}
                />
              )}
            </ScrollContainer>
          </TabsContent>
          <TabsContent
            className="h-full min-h-0 flex-grow px-4 pb-4 pt-2 sm:px-6"
            value="activities"
            forceMount
            hidden={activeTab !== "activities"}
          >
            <ScrollContainer
              className="h-full pb-8"
              scrollShadowColor="#f8fafc"
              autoScrollToBottom={!hasReport || reportStreaming}
            >
              {researchId && (
                <ResearchActivitiesBlock
                  className="mt-4"
                  researchId={researchId}
                />
              )}
            </ScrollContainer>
          </TabsContent>
        </Tabs>
      </Card>
    </div>
  );
}
