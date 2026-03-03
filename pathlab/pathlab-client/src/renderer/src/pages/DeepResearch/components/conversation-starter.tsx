// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";

import { cn } from "../../../lib/utils";

export function ConversationStarter({
  className,
  onSend: _onSend,
}: {
  className?: string;
  onSend?: (message: string) => void;
}) {
  const { t } = useTranslation();

  return (
    <div
      className={cn(
        "flex min-h-[calc(100vh-16rem)] w-full flex-col items-center justify-center pt-6 pb-12",
        className,
      )}
    >
      <div className="mx-auto mt-6 mb-4 w-full max-w-4xl text-center">
        <div className="mb-3 flex items-center justify-center gap-2">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-primary-500 to-primary-600 shadow-lg">
            <Sparkles className="h-7 w-7 text-white" />
          </div>
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
