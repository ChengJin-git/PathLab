// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "../../../components/ui/badge";
import { cn } from "../../../lib/utils";

export function ConversationStarter({
  className,
}: {
  className?: string;
}) {
  const { t } = useTranslation();

  return (
    <div
      className={cn(
        "flex min-h-[calc(100vh-16rem)] w-full flex-col items-center justify-center pt-6 pb-12",
        className,
      )}
    >
      <div className="mx-auto mt-6 mb-4 w-full max-w-3xl rounded-[32px] border border-gray-200/70 bg-white/75 px-6 py-10 text-center shadow-sm backdrop-blur-sm sm:px-10">
        <div className="mb-3 flex items-center justify-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 shadow-lg">
            <Sparkles className="h-7 w-7 text-white" />
          </div>
        </div>
        <div className="mb-4 flex justify-center">
          <Badge className="border-indigo-100 bg-indigo-50 text-indigo-700 hover:bg-indigo-100">
            Beta
          </Badge>
        </div>
        <h1 className="bg-gradient-to-r from-gray-900 via-gray-700 to-gray-900 bg-clip-text text-3xl font-bold text-transparent">
          {t("aiChat.scenarioCards.deepResearch.welcomeTitle")}
        </h1>
        <p className="mx-auto mt-2 max-w-2xl text-base text-gray-500">
          {t("aiChat.scenarioCards.deepResearch.welcomeDescription")}
        </p>
      </div>
    </div>
  );
}
