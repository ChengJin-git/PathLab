import { useTranslations } from "../../../lib/deep-research/i18n";
// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT


import {
  Check,
  Copy,
  Pencil,
  Undo2,
  X,
  Download,
  FileText,
  FileCode,
  FileImage,
  FileType,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ScrollContainer } from "../../../components/deep-research/scroll-container";
import { Tooltip } from "../../../components/deep-research/tooltip";
import { Button } from "../../../components/ui/button";
import { Card } from "../../../components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../../../components/ui/dropdown-menu";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../../../components/ui/tabs";
import { useReplay } from "../../../lib/deep-research/replay";
import { closeResearch, useStore } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";

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
  const { isReplay } = useReplay();
  useEffect(() => {
    if (hasReport) {
      setActiveTab("report");
    }
  }, [hasReport]);

  const [editing, setEditing] = useState(false);
  const handleEdit = useCallback(() => {
    setEditing((editing) => !editing);
  }, []);

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

  return (
    <div className={cn("h-full w-full", className)}>
      <Card className="relative h-full w-full pt-4">
        <Tabs
          className="flex h-full w-full flex-col"
          value={activeTab}
          onValueChange={(value) => setActiveTab(value)}
        >
          <div className="px-4 sm:px-6">
            <div className="mb-2 flex w-full flex-wrap items-center justify-end gap-1 sm:gap-2">
              {hasReport && !reportStreaming && (
                <>
                  <Tooltip title={t("edit")}>
                    <Button
                      className="text-gray-400"
                      size="icon"
                      variant="ghost"
                      disabled={isReplay}
                      onClick={handleEdit}
                    >
                      {editing ? <Undo2 /> : <Pencil />}
                    </Button>
                  </Tooltip>
                  <Tooltip title={t("copy")}>
                    <Button
                      className="text-gray-400"
                      size="icon"
                      variant="ghost"
                      onClick={handleCopy}
                    >
                      {copied ? <Check /> : <Copy />}
                    </Button>
                  </Tooltip>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        className="text-gray-400"
                        size="icon"
                        variant="ghost"
                        title={t("downloadReport")}
                      >
                        <Download />
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
                  className="text-gray-400"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    closeResearch();
                  }}
                >
                  <X />
                </Button>
              </Tooltip>
            </div>
          </div>
          <div className="flex w-full justify-center px-4 sm:px-6">
            <TabsList className="max-w-full">
              <TabsTrigger
                className="whitespace-nowrap px-4 sm:px-8"
                value="report"
                disabled={!hasReport}
              >
                {t("report")}
              </TabsTrigger>
              <TabsTrigger className="whitespace-nowrap px-4 sm:px-8" value="activities">
                {t("activities")}
              </TabsTrigger>
            </TabsList>
          </div>
          <TabsContent
            className="h-full min-h-0 flex-grow px-8"
            value="report"
            forceMount
            hidden={activeTab !== "report"}
          >
            <ScrollContainer
              className="h-full px-5 pb-10"
              scrollShadowColor="#ffffff"
              autoScrollToBottom={!hasReport || reportStreaming}
            >
              {reportId && researchId && (
                <ResearchReportBlock
                  className="mt-4"
                  researchId={researchId}
                  messageId={reportId}
                  editing={editing}
                />
              )}
            </ScrollContainer>
          </TabsContent>
          <TabsContent
            className="h-full min-h-0 flex-grow px-8"
            value="activities"
            forceMount
            hidden={activeTab !== "activities"}
          >
            <ScrollContainer
              className="h-full pb-10"
              scrollShadowColor="#ffffff"
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
