import type { WorkbenchCommand } from "../api/workbench";

export function commandLanguage(language: string): "en-US" | "zh-CN" | "zh-HK" {
  return language.startsWith("zh")
    ? /HK|TW|Hant/i.test(language)
      ? "zh-HK"
      : "zh-CN"
    : "en-US";
}

// Immediate first paint before the paginated, localized server catalog arrives.
const primary = {
  experiment: [
    [
      "Autonomous exploration",
      "Clarify your goal, then confirm research, analysis or experiments.",
    ],
    ["自主探索", "先梳理需求，确认后开展调研、分析或实验。"],
    ["自主探索", "先梳理需求，確認後開展調研、分析或實驗。"],
  ],
  literature: [
    ["Literature research", "Search, read and synthesize research literature."],
    ["文献研究", "检索、阅读并综合研究文献。"],
    ["文獻研究", "檢索、閱讀並綜合研究文獻。"],
  ],
  analyze: [
    [
      "Results analysis",
      "Analyze referenced data and measured experimental results.",
    ],
    ["结果分析", "分析引用的数据和实测实验结果。"],
    ["結果分析", "分析引用的資料和實測實驗結果。"],
  ],
  report: [
    [
      "Research report",
      "Write a research report from experiments and verified evidence.",
    ],
    ["研究报告", "基于实验与已核实证据撰写研究报告。"],
    ["研究報告", "根據實驗與已核實證據撰寫研究報告。"],
  ],
  ask: [
    ["Discuss", "Discuss the task without sending execution instructions."],
    ["讨论", "讨论当前任务，不发送执行指令。"],
    ["討論", "討論目前任務，不傳送執行指令。"],
  ],
} as const;

export function localizePrimaryCommand(
  command: WorkbenchCommand,
  language: string,
): WorkbenchCommand {
  const entries = primary[command.id as keyof typeof primary];
  if (!entries) return command;
  const index = { "en-US": 0, "zh-CN": 1, "zh-HK": 2 }[
    commandLanguage(language)
  ];
  return {
    ...command,
    name: entries[index][0],
    description: entries[index][1],
  };
}
