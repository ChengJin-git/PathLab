import { useTranslation } from "react-i18next";
const labels = {
  labelsLater: [
    "Labels can be added now or later. Select a filename to complete it.",
    "标签可现在填写或稍后补充，点击文件名即可定位。",
    "標籤可現在填寫或稍後補充，點選檔案名稱即可定位。",
  ],
  overview: ["Dataset overview", "数据概览", "資料概覽"],
  tasks: ["Tasks & labels", "任务与标签", "任務與標籤"],
  taskHint: [
    "One image collection can support several tasks. Adding a task keeps existing labels.",
    "同一份图像可支持多种任务，新增任务会保留已有标签。",
    "同一份影像可支援多種任務，新增任務會保留現有標籤。",
  ],
  description: ["About this dataset", "数据集描述", "資料集描述"],
  descriptionHint: [
    "What was collected, how it was prepared, and what it can be used for.",
    "描述采集内容、处理方式及适用研究目标。",
    "描述採集內容、處理方式及適用研究目標。",
  ],
  details: ["Additional metadata", "详细信息", "詳細資訊"],
  institution: ["Institution / source", "采集机构 / 来源", "採集機構 / 來源"],
  stain: ["Stain / modality", "染色 / 成像方式", "染色 / 成像方式"],
  license: ["License / permitted use", "许可 / 使用范围", "授權 / 使用範圍"],
  source_url: ["Source URL", "来源链接", "來源連結"],
  time_unit: ["Follow-up time unit", "随访时间单位", "隨訪時間單位"],
  label_definition: ["Label definitions", "标签定义", "標籤定義"],
  addField: ["Add metadata field", "添加信息字段", "新增資訊欄位"],
  field: ["Field", "字段", "欄位"],
  value: ["Value", "内容", "內容"],
  edit: ["Edit details", "编辑信息", "編輯資訊"],
  append: ["Add data or labels", "追加数据或标签", "新增資料或標籤"],
  images: ["Image files", "图像文件", "影像檔案"],
  labels: [
    "Labels for existing images",
    "补充已有图像的标签",
    "補充現有影像標籤",
  ],
  importHint: [
    "Match images by filename. Import class labels, follow-up outcomes and additional metadata together; spatial annotations are selected per task.",
    "通过文件名匹配图像。可同时导入分类标签、随访结局和其他信息；分割与检测标注分别选择文件。",
    "透過檔案名稱配對影像。可同時匯入分類標籤、隨訪結局及其他資訊；分割與檢測標註分別選取檔案。",
  ],
  table: ["Sample metadata (CSV)", "样本信息（CSV）", "樣本資訊（CSV）"],
  tableHint: [
    "filename, label, event_time, event_status, case_id, age, gender, split. Other columns are saved as sample metadata.",
    "filename、label、event_time、event_status、case_id、age、gender、split。其他列保存为样本信息。",
    "filename、label、event_time、event_status、case_id、age、gender、split。其他欄位儲存為樣本資訊。",
  ],
  coco: [
    "Annotation file (COCO JSON)",
    "标注文件（COCO JSON）",
    "標註檔案（COCO JSON）",
  ],
  save: ["Save", "保存", "儲存"],
  cancel: ["Cancel", "取消", "取消"],
  import: ["Import labels", "导入标签", "匯入標籤"],
  saved: ["Saved", "已保存", "已儲存"],
  complete: ["Labelled", "标签完整", "標籤完整"],
  partial: ["Partly labelled", "标签待补充", "標籤待補充"],
  unlabelled: ["No labels yet", "尚无标签", "尚無標籤"],
  patch: ["Image patches", "图像块", "圖像塊"],
  wsi: ["Whole-slide images", "整张切片", "整張切片"],
  classification: ["Classification", "分类", "分類"],
  survival: ["Survival", "生存分析", "存活分析"],
  segmentation: ["Segmentation", "分割", "分割"],
  detection: ["Detection", "检测", "檢測"],
  empty: ["No description yet", "尚未填写描述", "尚未填寫描述"],
  preview: ["Import preview", "导入预览", "匯入預覽"],
} as const;
export function useDatasetText() {
  const { i18n } = useTranslation();
  const language = i18n.resolvedLanguage || i18n.language || "en";
  const index = /HK|TW|Hant/i.test(language)
    ? 2
    : language.startsWith("zh")
      ? 1
      : 0;
  return (key: keyof typeof labels) => labels[key][index];
}
