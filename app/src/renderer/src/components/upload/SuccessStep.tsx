import React from "react";
import { useTranslation } from "react-i18next";
import { CheckCircle2, Database } from "lucide-react";
import { Card } from "../ui/card";
import { Button } from "../ui/button";

export interface SuccessStepProps {
  datasetName: string;
  splitUploadSuccess: string | null;
  fromAIChat: boolean;
  onNavigate: () => void;
  onReset: () => void;
}

export const SuccessStep: React.FC<SuccessStepProps> = ({
  datasetName,
  splitUploadSuccess,
  fromAIChat,
  onNavigate,
  onReset,
}) => {
  const { t } = useTranslation();
  return (
    <div
      data-testid="success-step-root"
      className="mx-auto flex max-w-3xl flex-col items-center justify-center py-8 sm:py-16"
    >
      <Card className="w-full overflow-hidden rounded-xl border-slate-200 bg-white shadow-none">
        <div className="grid grid-cols-1 md:grid-cols-2 min-h-[300px]">
          <div className="bg-slate-50/60 p-6 sm:p-8 flex flex-col justify-center items-center text-center border-b md:border-b-0 md:border-r border-slate-100">
            <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-xl border border-emerald-100 flex items-center justify-center mb-5">
              <CheckCircle2 className="w-6 h-6" />
            </div>

            <h2 className="text-xl font-semibold text-slate-900 mb-2 tracking-tight">
              {t("uploadComponents.successStep.importSuccessful")}
            </h2>
            <p className="text-sm sm:text-slate-500 mb-6 sm:mb-8 max-w-[240px] leading-relaxed">
              {t("uploadComponents.successStep.datasetUpdatedSuccessfully")}
            </p>

            <div className="flex flex-col gap-3 w-full max-w-xs">
              <Button
                size="lg"
                className="upload-primary w-full"
                onClick={onNavigate}
              >
                {fromAIChat
                  ? t("uploadComponents.successStep.goToChat")
                  : t("uploadComponents.successStep.goToDashboard")}
              </Button>
              <Button
                variant="outline"
                className="w-full rounded-lg border-slate-200 text-sm text-slate-600 shadow-none"
                onClick={onReset}
              >
                {t("uploadComponents.successStep.uploadMore")}
              </Button>
            </div>
          </div>

          <div className="p-6 sm:p-10 flex flex-col justify-center bg-white relative">
            <h3 className="text-[10px] sm:text-xs font-bold text-slate-900 uppercase tracking-widest mb-4 sm:mb-6 border-b border-slate-100 pb-3">
              {t("uploadComponents.successStep.datasetSummary")}
            </h3>

            <div className="space-y-4 sm:space-y-6">
              <div>
                <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                  {t("uploadComponents.successStep.targetDataset")}
                </div>
                <div className="text-base sm:text-lg font-bold text-slate-900 truncate flex items-center gap-2">
                  <Database className="w-4 h-4 text-blue-500" />
                  {datasetName}
                </div>
              </div>

              <div>
                <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1.5">
                  {t("uploadComponents.successStep.action")}
                </div>
                <div className="text-xs sm:text-sm font-medium text-slate-700 bg-slate-50 inline-block px-3 py-1 rounded-md border border-slate-200">
                  {t("uploadComponents.successStep.metadataSplitUpdate")}
                </div>
              </div>

              {splitUploadSuccess && (
                <div>
                  <div className="text-[9px] sm:text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-2">
                    {t("uploadComponents.successStep.importResult")}
                  </div>
                  <div className="text-xs sm:text-sm text-slate-600 bg-green-50/50 p-3 sm:p-4 rounded-xl border border-green-100 leading-relaxed text-wrap break-words">
                    {splitUploadSuccess}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};
