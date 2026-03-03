import { useCallback, useRef } from "react";

import { LoadingAnimation } from "../../../components/deep-research/loading-animation";
import { useCitations, useMessage } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";
import { ReportLayout } from "./blocks/report-layout";

export function ResearchReportBlock({
  className,
  researchId,
  messageId,
  editing,
}: {
  className?: string;
  researchId: string;
  messageId: string;
  editing: boolean;
}) {
  const message = useMessage(messageId);
  const citations = useCitations(researchId);

  return (
    <div className={cn("w-full pt-4 pb-8", className)}>
      <ReportLayout
        content={message?.content ?? ""}
        citations={citations}
      />
      {message?.isStreaming && <LoadingAnimation className="my-12" />}
    </div>
  );
}
