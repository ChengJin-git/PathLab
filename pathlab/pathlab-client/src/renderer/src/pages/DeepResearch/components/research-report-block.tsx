import { LoadingAnimation } from "../../../components/deep-research/loading-animation";
import { Skeleton } from "../../../components/ui/skeleton";
import { useCitations, useMessage } from "../../../lib/deep-research/store";
import { cn } from "../../../lib/utils";
import { ReportLayout } from "./blocks/report-layout";

function ReportSkeleton() {
  return (
    <div className="flex flex-col gap-6 px-4 py-8 animate-in fade-in duration-300">
      {/* Title */}
      <Skeleton className="h-8 w-3/4" />
      {/* Subtitle / date */}
      <Skeleton className="h-4 w-1/3" />
      {/* Section heading */}
      <div className="mt-4 flex flex-col gap-3">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-5/6" />
      </div>
      {/* Another section */}
      <div className="mt-2 flex flex-col gap-3">
        <Skeleton className="h-6 w-2/5" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-4/5" />
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    </div>
  );
}

export function ResearchReportBlock({
  className,
  researchId,
  messageId,
}: {
  className?: string;
  researchId: string;
  messageId: string;
}) {
  const message = useMessage(messageId);
  const citations = useCitations(researchId);
  const hasContent = (message?.content ?? "").trim().length > 0;

  return (
    <div className={cn("w-full pt-4 pb-8", className)}>
      {hasContent ? (
        <ReportLayout
          content={message?.content ?? ""}
          citations={citations}
        />
      ) : (
        <ReportSkeleton />
      )}
      {message?.isStreaming && <LoadingAnimation className="my-12" />}
    </div>
  );
}
