import { useTranslation } from "react-i18next";
import type { AutoResearchEvent } from "../../types/autoresearch";
import type { ResearchMessage } from "./researchActivity";

const actions = {
  search_sources: ["Search relevant sources", "查找相关资料", "查找相關資料"],
  search_literature: ["Find published evidence", "查找文献证据", "查找文獻證據"],
  review_evidence: ["Review the available evidence", "核查已有证据", "核查已有證據"],
  read_source: ["Read the source material", "阅读来源内容", "閱讀來源內容"],
  download_source: ["Download the source document", "下载原始文档", "下載原始文件"],
  search_data: ["Find suitable datasets", "查找合适的数据资源", "查找合適的資料資源"],
  prepare_data: ["Prepare data for analysis", "准备分析数据", "準備分析資料"],
  download_data: ["Obtain the requested data", "获取所需数据", "取得所需資料"],
  analyze: ["Analyze the data", "开展数据分析", "開展資料分析"],
  experiment: ["Run the planned experiment", "执行计划中的实验", "執行計劃中的實驗"],
  check_results: ["Check the results", "检查运行结果", "檢查執行結果"],
  stop_work: ["Stop the current work", "停止当前工作", "停止目前工作"],
  plan: ["Refine the research plan", "完善研究计划", "完善研究計劃"],
  write_report: ["Prepare the research report", "整理研究报告", "整理研究報告"],
  save_file: ["Save the deliverable", "保存交付文件", "儲存交付檔案"],
  publish_results: ["Organize results for reuse", "整理可复用的研究结果", "整理可重用的研究結果"],
  summarize: ["Summarize the findings", "总结研究发现", "總結研究發現"],
  request_help: ["Describe the help needed", "说明需要补充的协助", "說明需要補充的協助"],
  work: ["Continue the research", "推进研究工作", "推進研究工作"],
} as const;

export interface ResearchProgressStep {
  id: string;
  action: keyof typeof actions;
  status: "running" | "completed" | "failed" | "interrupted";
  description?: string;
  language?: string;
}

function step(value: Record<string, unknown>, id: string, running: boolean): ResearchProgressStep | undefined {
  if (typeof value.action !== "string" || !Object.hasOwn(actions, value.action)) return;
  const status = value.status === "failed" || value.status === "interrupted" || value.status === "completed"
    ? value.status : running ? "running" : "interrupted";
  return { id, action: value.action as ResearchProgressStep["action"], status,
    description: typeof value.description === "string" ? value.description.slice(0, 120) : undefined,
    language: typeof value.language === "string" ? value.language : undefined };
}

/** Consume only the public receipt schema; no tool-name/input/output rendering. */
export function researchProgress(events: AutoResearchEvent[], running: boolean): ResearchProgressStep[] {
  const result: ResearchProgressStep[] = [];
  for (const event of events) {
    if (event.kind === "native_work") continue;
    if (event.kind === "message") {
      const message = event.message as unknown as ResearchMessage;
      for (const [index, part] of (message.content || []).entries()) {
        if (part.type !== "activity") continue;
        const item = step(part, `${message.id}:${part.id || index}`, running);
        if (item) result.push(item);
      }
    } else {
      const item = step(event, `${event.kind}:${event.job_id || event.seq}`, running);
      if (item) result.push(item);
    }
  }
  return result;
}

export function useResearchProgressText() {
  const { i18n } = useTranslation();
  const locale = i18n.language || "en-US";
  const language = locale.startsWith("zh") ? /HK|TW|Hant/i.test(locale) ? "zh-HK" : "zh-CN" : "en-US";
  const index = language === "zh-CN" ? 1 : language === "zh-HK" ? 2 : 0;
  return (item: ResearchProgressStep) => {
    const description = item.description?.trim();
    // Switching UI locale is immediate; never call a model to translate progress.
    // Search queries may be English, but Chinese action descriptions must be Chinese.
    return description && item.language === language && (index === 0 || /[\u3400-\u9fff]/.test(description))
      ? description : actions[item.action][index];
  };
}
