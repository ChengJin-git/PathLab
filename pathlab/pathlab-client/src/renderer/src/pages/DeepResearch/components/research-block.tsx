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
  FileSearch,
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
import { stripResearchMeta } from "../../../lib/deep-research/utils";
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
  const reportMessage = useStore((state) =>
    reportId ? state.messages.get(reportId) : undefined,
  );
  const reportStreaming = useStore((state) =>
    reportId ? (state.messages.get(reportId)?.isStreaming ?? false) : false,
  );
  const researchMessage = useResearchMessage(researchId ?? "");
  const researchRunStatus = useStore((state) =>
    researchId ? state.researchRunStatus.get(researchId) : undefined,
  );
  const ongoingFromStore = useStore((state) => state.ongoingResearchId === researchId);
  const hasCompletedReport = useMemo(() => {
    if (!hasReport) return false;
    const visibleContent = stripResearchMeta(reportMessage?.content ?? "").trim();
    return visibleContent.length > 0 && !reportStreaming;
  }, [hasReport, reportMessage, reportStreaming]);
  const ongoing = ongoingFromStore && !hasCompletedReport;

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

  useEffect(() => {
    setActiveTab(hasReport ? "report" : "activities");
  }, [researchId, hasReport]);

  useEffect(() => {
    if (hasCompletedReport) {
      setActiveTab("report");
    }
  }, [hasCompletedReport, reportId, researchId]);

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
    if (hasCompletedReport) {
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
  }, [hasCompletedReport, ongoing, reportStreaming, researchRunStatus]);

  const downloadMenuItemClassName =
    "min-w-0 cursor-pointer gap-3 rounded-md px-4 py-2 text-sm text-gray-700 transition-colors whitespace-normal break-words hover:bg-gray-50 hover:text-gray-900 focus:bg-gray-50 focus:text-gray-900 sm:whitespace-nowrap";

  return (
    <div className={cn("h-full w-full min-w-0 max-w-full", className)}>
      <Card className="relative h-full w-full min-w-0 max-w-full overflow-hidden border-gray-200/70 bg-white/90 shadow-sm backdrop-blur-sm">
        <Tabs
          className="flex h-full w-full min-w-0 flex-col"
          value={activeTab}
          onValueChange={(value) => setActiveTab(value)}
        >
          <div className="border-b border-gray-100/80 bg-gradient-to-b from-gray-50/90 to-white px-3 py-3 sm:px-6 sm:py-4">
            <div className="flex flex-col gap-3 sm:gap-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex items-start gap-2.5 sm:gap-3">
                    <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 shadow-lg sm:h-10 sm:w-10">
                      <Sparkles className="h-4.5 w-4.5 text-white sm:h-5 sm:w-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="truncate text-base font-semibold text-gray-900 sm:text-lg">{title}</div>
                      <div className="mt-1.5 sm:mt-2">
                        <Badge className={statusClassName}>{statusLabel}</Badge>
                      </div>
                    </div>
                  </div>
                </div>
                <div className="flex w-full flex-wrap items-center justify-end gap-1 sm:w-auto sm:gap-2">
                  {hasCompletedReport && (
                    <>
                      <Button
                        className="rounded-full text-gray-400 hover:bg-gray-100 hover:text-gray-700"
                        size="icon"
                        variant="ghost"
                        onClick={handleCopy}
                      >
                        {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                      </Button>
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
                        <DropdownMenuContent
                          align="end"
                          className="min-w-0 w-[calc(100vw-2rem)] max-w-[220px] rounded-lg border-gray-200 bg-white py-1 shadow-lg sm:w-auto sm:min-w-[160px]"
                          collisionPadding={16}
                          sideOffset={6}
                        >
                          <DropdownMenuItem
                            className={downloadMenuItemClassName}
                            onClick={handleDownloadMarkdown}
                          >
                            <FileText className="mr-2 h-4 w-4" />
                            {t("downloadMarkdown")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className={downloadMenuItemClassName}
                            onClick={handleDownloadHTML}
                          >
                            <FileCode className="mr-2 h-4 w-4" />
                            {t("downloadHTML")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className={downloadMenuItemClassName}
                            onClick={handleDownloadPDF}
                            disabled={isDownloading}
                          >
                            <FileType className="mr-2 h-4 w-4" />
                            {t("downloadPDF")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className={downloadMenuItemClassName}
                            onClick={handleDownloadWord}
                            disabled={isDownloading}
                          >
                            <FileText className="mr-2 h-4 w-4" />
                            {t("downloadWord")}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            className={downloadMenuItemClassName}
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
              <div className="flex w-full justify-center overflow-x-auto">
                <TabsList className="w-full max-w-full rounded-full bg-gray-100/80 p-1 shadow-inner sm:w-fit">
                  <TabsTrigger
                    className="whitespace-nowrap rounded-full px-3 py-1.5 text-sm text-gray-600 data-[state=active]:bg-white data-[state=active]:text-gray-900 data-[state=active]:shadow-sm sm:px-6"
                    value="activities"
                  >
                    <FileSearch className="h-4 w-4" />
                    {t("activities")}
                  </TabsTrigger>
                  <TabsTrigger
                    className="whitespace-nowrap rounded-full px-3 py-1.5 text-sm text-gray-600 data-[state=active]:bg-white data-[state=active]:text-gray-900 data-[state=active]:shadow-sm disabled:cursor-not-allowed disabled:border-transparent disabled:bg-transparent disabled:text-gray-300 disabled:opacity-100 disabled:shadow-none sm:px-6"
                    value="report"
                      disabled={!hasReport}
                  >
                    <FileText className="h-4 w-4" />
                    {t("report")}
                  </TabsTrigger>
                </TabsList>
              </div>
            </div>
          </div>
          <TabsContent
            className="h-full min-h-0 flex-grow px-3 pb-3 pt-1.5 sm:px-6 sm:pb-4 sm:pt-2"
            value="activities"
            forceMount
            hidden={activeTab !== "activities"}
          >
            <ScrollContainer
              className="h-full pb-6 sm:pb-8"
              scrollShadowColor="#f8fafc"
              autoScrollToBottom={!hasCompletedReport}
            >
              {researchId && (
                <ResearchActivitiesBlock
                  className="mt-3 sm:mt-4"
                  researchId={researchId}
                />
              )}
            </ScrollContainer>
          </TabsContent>
          <TabsContent
            className="h-full min-h-0 flex-grow px-3 pb-3 pt-1.5 sm:px-6 sm:pb-4 sm:pt-2"
            value="report"
            forceMount
            hidden={activeTab !== "report"}
          >
            <ScrollContainer
              className="h-full pb-6 sm:pb-8"
              scrollShadowColor="#f8fafc"
              autoScrollToBottom={!hasCompletedReport}
            >
              {reportId && researchId && (
                <ResearchReportBlock
                  className="mt-3 sm:mt-4"
                  researchId={researchId}
                  messageId={reportId}
                />
              )}
            </ScrollContainer>
          </TabsContent>
        </Tabs>
      </Card>
    </div>
  );
}
