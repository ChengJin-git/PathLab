import { useTranslation } from "react-i18next";
import i18n from "../../../i18n";

const labels = {
  title: ["Results analysis", "结果分析", "結果分析"],
  subtitle: [
    "Explore measured results. Configure, compare and reuse analyses.",
    "从已有结果出发，配置、比较并复用分析。",
    "從已有結果出發，設定、比較並重用分析。",
  ],
  sources: ["Experiments & results", "实验与结果", "實驗與結果"],
  search: ["Search results", "搜索实验与分析", "搜尋實驗與分析"],
  all: ["All sources", "全部来源", "全部來源"],
  training: ["Training", "训练", "訓練"],
  external: ["External validation", "外部验证", "外部驗證"],
  inference: ["Inference", "批量推理", "批次推理"],
  research: ["Research models", "研究模型", "研究模型"],
  experiment: ["Experiments", "研究实验", "研究實驗"],
  analysis: ["Published analyses", "已发布分析", "已發佈分析"],
  selected: ["selected", "已选择", "已選擇"],
  previous: ["Previous", "上一页", "上一頁"],
  next: ["Next", "下一页", "下一頁"],
  loading: ["Loading…", "加载中…", "載入中…"],
  retry: ["Retry", "重试", "重試"],
  empty: [
    "Select a result to begin",
    "选择结果，开始分析",
    "選擇結果，開始分析",
  ],
  emptyHint: [
    "Choose an existing experiment to inspect its results. Select several experiments to compare them, or start a new evaluation with a trained model.",
    "在左侧选择已有实验，查看指标和图表。选择多个实验可进行比较；需要在新数据上测试模型时，点击「新增评估」。",
    "在左側選擇已有實驗，查看指標及圖表。選擇多個實驗可進行比較；需要在新資料上測試模型時，點擊「新增評估」。",
  ],
  noSources: ["No matching results", "没有匹配的结果", "沒有符合的結果"],
  configure: ["Analysis settings", "分析配置", "分析設定"],
  overview: ["Overview", "结果概览", "結果概覽"],
  samples: ["Samples", "样本明细", "樣本明細"],
  samplePreview: ['View prediction', '查看预测', '查看預測'],
  attentionPreview: ['Attention / CAM', '注意力 / CAM 热图', '注意力 / CAM 熱圖'],
  riskScore: ['Risk score', '风险评分', '風險評分'],
  previewLayer: ['Mask layer', '掩码图层', '遮罩圖層'],
  history: ["History", "分析记录", "分析記錄"],
  run: ["Run analysis", "运行分析", "執行分析"],
  rerun: ["Use configuration", "复用配置", "重用設定"],
  cancel: ["Cancel", "取消", "取消"],
  delete: ["Delete", "删除", "刪除"],
  recipes: ["Saved recipes", "已保存方案", "已儲存方案"],
  save: ["Save recipe", "保存方案", "儲存方案"],
  recipeName: ["Recipe name", "方案名称", "方案名稱"],
  apply: ["Apply", "应用", "套用"],
  update: ["Update", "更新", "更新"],
  export: ["Export", "导出", "匯出"],
  exportInputs: ["Input snapshot", "输入快照", "輸入快照"],
  exportOriginal: [
    "Original evaluation output",
    "原始评估结果",
    "原始評估結果",
  ],
  caseNote: [
    "One sample per case; slide probabilities and risk scores are averaged within the case.",
    "每个病例作为一个样本，病例内取切片概率或风险分数的平均值。",
    "每個病例作為一個樣本，病例內取切片機率或風險分數的平均值。",
  ],
  ibsNote: [
    "IBS uses this evaluation cohort’s censoring distribution and the saved time grid.",
    "IBS 使用当前评估队列的删失分布及保存的时间网格。",
    "IBS 使用目前評估群組的設限分佈及儲存的時間網格。",
  ],
  segmentationNote: [
    "Segmentation metrics are averaged across images.",
    "分割指标为当前阈值下逐图像指标的宏平均。",
    "分割指標為目前閾值下逐圖像指標的宏平均。",
  ],
  recordedNote: [
    "Recorded metrics keep their original evaluation scope and are not recalculated by these settings.",
    "已记录指标保留原始评估范围，当前配置不会重新计算这些数值。",
    "已記錄指標保留原始評估範圍，目前設定不會重新計算這些數值。",
  ],
  partialGtNote: [
    "Ground truth is available for {{labelled}} of {{total}} samples. Performance metrics use labelled samples.",
    "{{total}} 个样本中有 {{labelled}} 个具有真实标签，性能指标仅使用有标签样本。",
    "{{total}} 個樣本中有 {{labelled}} 個具有真實標籤，表現指標只使用有標籤樣本。",
  ],
  split: ["Evaluation split", "评估范围", "評估範圍"],
  unit: ["Evaluation unit", "统计单位", "統計單位"],
  file: ["Image / slide", "图像 / 切片", "圖像 / 切片"],
  case: ["Patient / case", "患者 / 病例", "患者 / 病例"],
  positive: ["Positive class", "阳性类别", "陽性類別"],
  threshold: ["Decision threshold", "决策阈值", "決策閾值"],
  detectionIou: ['Matching IoU threshold', '匹配 IoU 阈值', '配對 IoU 閾值'],
  detectionHint: ['mAP uses all saved scores. Confidence and IoU adjust precision, recall, F1 and object matching.', 'mAP 使用全部已保存置信度；置信度和 IoU 阈值用于调整精确率、召回率、F1 及目标匹配。', 'mAP 使用全部已儲存信心值；信心值及 IoU 閾值用於調整精確率、召回率、F1 及目標配對。'],
  thresholdHint: ['Threshold changes reuse compact saved statistics; no model inference is needed.', '调整阈值复用已保存的紧凑统计，无需重新运行模型。', '調整閾值重用已儲存的精簡統計，無需重新執行模型。'],
  thresholdUnavailable: ['Generate predictions with threshold statistics to enable pixel threshold adjustment.', '请生成包含阈值统计的预测结果，以启用像素阈值调整。', '請產生包含閾值統計的預測結果，以啟用像素閾值調整。'],
  longRunning: ['Analysis continues in the background. Large cohorts and confidence intervals may take several minutes. You can leave and return from Background tasks or Results history.', '分析正在后台继续。大数据集或置信区间计算可能需要几分钟；你可以离开此页，稍后从后台任务或分析记录返回查看。', '分析正在背景繼續。大型資料集或信賴區間計算可能需要數分鐘；你可以離開此頁，稍後從背景任務或分析記錄返回查看。'],
  preparing: ['Preparing saved predictions', '读取已有预测', '讀取已有預測'],
  computing: ['Computing metrics', '计算指标', '計算指標'],
  bootstrap: ['Calculating confidence intervals', '计算置信区间', '計算信賴區間'],
  exporting: ['Saving results', '保存结果', '儲存結果'],
  average: ["Averaging", "平均方式", "平均方式"],
  metrics: ["Metrics", "指标", "指標"],
  charts: ["Charts", "图表", "圖表"],
  filters: ["Sample filters", "样本筛选", "樣本篩選"],
  grouping: ["Group by", "分组字段", "分組欄位"],
  none: ["None", "不分组", "不分組"],
  source: ["Organ / tissue source", "器官 / 组织来源", "器官 / 組織來源"],
  gender: ["Sex / gender", "性别", "性別"],
  age: ["Age", "年龄", "年齡"],
  age_band: ["Age decade", "年龄段（十岁）", "年齡組別（十歲）"],
  dataset_id: ["Dataset", "数据集", "資料集"],
  minimum: ["Minimum", "最小值", "最小值"],
  maximum: ["Maximum", "最大值", "最大值"],
  confidence: ["Maximum confidence", "置信度上限", "信心值上限"],
  errorsOnly: ["Misclassified samples only", "仅看错例", "只看錯誤預測"],
  interval: [
    "Bootstrap confidence interval",
    "Bootstrap 置信区间",
    "Bootstrap 信賴區間",
  ],
  level: ["Confidence level", "置信水平", "信賴水準"],
  repeats: ["Resamples", "重采样次数", "重抽樣次數"],
  seed: ["Random seed", "随机种子", "隨機種子"],
  resampleUnit: ["Resampling unit", "重采样单位", "重抽樣單位"],
  sample: ["Evaluation sample", "评估样本", "評估樣本"],
  assistant: ["Analysis assistant", "分析助手", "分析助手"],
  assistantHint: [
    "Ask about the selected results, change settings or request an analysis.",
    "针对当前结果提问、调整配置，或直接要求运行分析。",
    "針對目前結果提問、調整設定，或直接要求執行分析。",
  ],
  assistantPlaceholder: [
    "e.g. Add a calibration curve and Brier score, then run.",
    "例如：增加校准曲线和 Brier 指标，然后运行",
    "例如：加入校準曲線及 Brier 指標，然後執行",
  ],
  send: ["Send", "发送", "傳送"],
  stop: ["Stop", "停止", "停止"],
  newConversation: ["New conversation", "新对话", "新對話"],
  thinking: [
    "Reading context and preparing an answer…",
    "正在结合当前结果回答…",
    "正在根據目前結果回答…",
  ],
  handoff: [
    "Continue in the main assistant",
    "在首页继续深入分析",
    "在首頁繼續深入分析",
  ],
  generate: ["New evaluation", "新增评估", "新增評估"],
  model: ["Model", "模型", "模型"],
  dataset: ["Dataset", "数据集", "資料集"],
  uploads: ["Uploaded images", "已上传图像", "已上傳圖像"],
  internal: ["Existing task", "已有任务", "已有任務"],
  submit: ["Submit", "提交", "提交"],
  submitted: [
    "Submitted. Follow progress in Tasks.",
    "已提交，可在任务页查看进度。",
    "已提交，可在任務頁查看進度。",
  ],
  viewTask: ["View task", "查看任务", "查看任務"],
  close: ["Close", "关闭", "關閉"],
  recorded: ["Recorded metrics", "已记录指标", "已記錄指標"],
  noPredictions: [
    "Recorded metrics only; sample-level predictions are unavailable.",
    "当前仅有已记录指标，尚无逐样本预测。",
    "目前只有已記錄指標，尚無逐樣本預測。",
  ],
  noGt: ["No ground truth", "无 GT", "無 GT"],
  gt: ["with ground truth", "有 GT", "有 GT"],
  count: ["Samples", "样本数", "樣本數"],
  noRun: [
    "Configure an analysis and run it, or open a saved result.",
    "配置分析后运行，或打开已保存的分析记录。",
    "設定分析後執行，或開啟已儲存的分析記錄。",
  ],
  noHistory: ["No saved analyses", "暂无分析记录", "暫無分析記錄"],
  noSamples: [
    "No sample-level data in this result",
    "此结果没有逐样本数据",
    "此結果沒有逐樣本資料",
  ],
  queued: ["Queued", "排队中", "排隊中"],
  running: ["Computing", "计算中", "計算中"],
  completed: ["Completed", "已完成", "已完成"],
  failed: ["Failed", "失败", "失敗"],
  cancelled: ["Cancelled", "已取消", "已取消"],
  preview: ["Display settings", "展示设置", "顯示設定"],
  chartTitle: ["Chart title", "图表标题", "圖表標題"],
  color: ["Color", "颜色", "顏色"],
  show: ["Visible", "显示", "顯示"],
  view: ["Open", "打开", "開啟"],
  actual: ["Ground truth", "真实标签", "真實標籤"],
  predicted: ["Prediction", "预测", "預測"],
  disagreement: ["Disagreement", "预测分歧", "預測分歧"],
  overlap: ["Shared samples", "共同样本", "共同樣本"],
  cohortDifference: [
    "Different or unknown evaluation cohorts; descriptive comparison only.",
    "评估样本不同或未知，仅作描述性比较。",
    "評估樣本不同或未知，只作描述性比較。",
  ],
  sameCohort: ["Same evaluation samples", "相同评估样本", "相同評估樣本"],
  pendingChanges: [
    "Settings have changed. Run to calculate a new result.",
    "计算配置已变更，运行后生成新的结果。",
    "計算設定已變更，執行後產生新的結果。",
  ],
  saved: ["Saved", "已保存", "已儲存"],
  unavailable: ["Required data unavailable", "缺少所需数据", "缺少所需資料"],
  openCode: ["Executed source", "执行代码", "執行程式碼"],
  details: [
    "Published tables and figures",
    "已发布表格与图像",
    "已發佈表格與圖像",
  ],
  sourceHint: [
    "Select an experiment to view its results",
    "选择一个实验，直接查看已有结果",
    "選擇一個實驗，直接查看已有結果",
  ],
  compareMode: ["Compare experiments", "对比实验", "對比實驗"],
  exitCompare: ["Exit comparison", "退出对比", "退出對比"],
  compareHint: [
    "Select experiments with the same task type to compare their results.",
    "选择同类任务的实验，比较已有结果或添加对比分析。",
    "選擇同類任務的實驗，比較已有結果或加入對比分析。",
  ],
  addAnalysis: ["Add analysis", "添加分析", "加入分析"],
  addAnalysisHint: [
    "Calculate additional metrics or charts from the selected saved results.",
    "基于当前已有结果，补充指标、图表或分组分析。",
    "根據目前已有結果，補充指標、圖表或分組分析。",
  ],
  calculate: ["Calculate and save", "计算并保存", "計算並儲存"],
  classification: ["Classification", "分类", "分類"],
  survival: ["Survival", "生存预测", "存活預測"],
  segmentation: ["Segmentation", "分割", "分割"],
  detection: ['Detection', '检测', '檢測'],
  multitask: ["Multiple tasks", "多任务", "多任務"],
  custom: ["Custom analysis", "自定义分析", "自訂分析"],
  allTasks: ["All task types", "全部任务类型", "全部任務類型"],
  labelledPredictions: [
    "Predictions + ground truth",
    "预测 + 真实标签",
    "預測 + 真實標籤",
  ],
  predictionsOnly: ["Predictions only", "仅预测", "只有預測"],
  metricsOnly: ["Summary metrics only", "仅汇总指标", "只有彙總指標"],
  taskFacet: ["Analysis task", "分析子任务", "分析子任務"],
  allFacets: ["All task results", "全部子任务结果", "全部子任務結果"],
  incompatibleTasks: [
    "Select experiments with the same task type for this comparison.",
    "此对比需要选择相同任务类型的实验。",
    "此對比需要選擇相同任務類型的實驗。",
  ],
  viewHint: [
    "Choose an experiment to see its saved results. Use Add analysis when you need additional metrics or charts.",
    "选择实验即可查看已有结果。需要补充指标或图表时，使用「添加分析」。",
    "選擇實驗即可查看已有結果。需要補充指標或圖表時，使用「加入分析」。",
  ],
  advanced: ["Advanced settings", "高级设置", "進階設定"],
  analysisGoal: [
    "What would you like to understand?",
    "你想了解什么？",
    "你想了解甚麼？",
  ],
  overall: ["Overall performance", "整体表现", "整體表現"],
  overallHint: [
    "Key performance metrics and diagnostic charts.",
    "查看关键指标和诊断图表，快速了解模型表现。",
    "查看關鍵指標及診斷圖表，快速了解模型表現。",
  ],
  calibrationGoal: [
    "Are probabilities reliable?",
    "预测概率可靠吗？",
    "預測機率可靠嗎？",
  ],
  calibrationHint: [
    "Calibration, Brier score and precision–recall.",
    "用校准曲线、Brier 分数和 PR 曲线检查预测概率。",
    "用校準曲線、Brier 分數及 PR 曲線檢查預測機率。",
  ],
  subgroup: ["Performance across groups", "不同人群的表现", "不同群組的表現"],
  subgroupHint: [
    "Compare outcomes by sex, age or dataset.",
    "按性别、年龄或数据集分组，查看表现差异。",
    "按性別、年齡或資料集分組，查看表現差異。",
  ],
  uncertainty: [
    "How stable is the result?",
    "结果有多稳定？",
    "結果有多穩定？",
  ],
  uncertaintyHint: [
    "Estimate confidence intervals with patient-level resampling.",
    "通过患者级重采样，估计关键指标的置信区间。",
    "透過患者級重抽樣，估計關鍵指標的信賴區間。",
  ],
  distributionGoal: ["Inspect predictions", "查看预测分布", "查看預測分佈"],
  distributionHint: [
    "Explore prediction distributions without requiring labels.",
    "查看预测类别、置信度或风险分数的分布，无需真实标签。",
    "查看預測類別、信心值或風險分數的分佈，無需真實標籤。",
  ],
  comparisonGoal: [
    "Compare selected experiments",
    "比较已选实验",
    "比較已選實驗",
  ],
  comparisonHint: [
    "Compare recorded metrics and overlay compatible curves.",
    "并排查看指标，叠加可比较的曲线。",
    "並排查看指標，疊加可比較的曲線。",
  ],
  backgroundHint: [
    "Runs on the server using saved results. You can leave this page; the analysis will continue.",
    "使用已有结果在服务器后台计算。离开页面或关闭浏览器，分析仍会继续。",
    "使用已有結果在伺服器背景計算。離開頁面或關閉瀏覽器，分析仍會繼續。",
  ],
  startAnalysis: ["Start analysis", "开始分析", "開始分析"],
  backgroundRunning: [
    "Analysis continues in the background",
    "分析正在后台继续",
    "分析正在背景繼續",
  ],
  activeAnalyses: ["Background analyses", "后台分析", "背景分析"],
  cancelling: ["Cancelling", "正在取消", "正在取消"],
  comparisonRequired: [
    "Select at least two experiments to compare.",
    "请先选择至少两个实验进行对比。",
    "請先選擇至少兩個實驗進行對比。",
  ],
  selectionLimit: [
    "Select up to eight experiments.",
    "最多选择八个实验。",
    "最多選擇八個實驗。",
  ],
  clearSelection: ["Clear selection", "清空选择", "清除選擇"],
  experimentNumber: [
    "Experiment {{number}}",
    "实验 {{number}}",
    "實驗 {{number}}",
  ],
  evaluationHint: [
    "Run a trained model on your data. The completed result will appear in the experiment list.",
    "用已有模型测试数据，完成后结果会出现在左侧列表中。",
    "用已有模型測試資料，完成後結果會出現在左側清單中。",
  ],
  chooseModel: ["Choose a trained model", "选择已训练模型", "選擇已訓練模型"],
  chooseData: ["Choose evaluation data", "选择评估数据", "選擇評估資料"],
  evaluationMode: [
    "What would you like to do?",
    "你想进行哪种评估？",
    "你想進行哪種評估？",
  ],
  externalHint: [
    "Test on a labelled dataset and measure performance.",
    "在有真实标签的数据集上测试，计算模型性能。",
    "在有真實標籤的資料集上測試，計算模型表現。",
  ],
  inferenceHint: [
    "Predict an unlabelled dataset and inspect its output distribution.",
    "对无标签数据集进行预测，查看预测分布。",
    "對無標籤資料集進行預測，查看預測分佈。",
  ],
  uploadsHint: [
    "Select individual unlabelled images for prediction.",
    "选择单张或多张无标签图像进行预测。",
    "選擇單張或多張無標籤圖像進行預測。",
  ],
  internalHint: [
    "Generate missing predictions for the selected training task.",
    "为当前训练任务补充缺失的预测结果。",
    "為目前訓練任務補充缺少的預測結果。",
  ],
  startEvaluation: ["Start evaluation", "开始评估", "開始評估"],
  startInference: ["Start prediction", "开始预测", "開始預測"],
  searchModel: ["Search model names", "搜索模型名称", "搜尋模型名稱"],
  searchDataset: [
    "Search datasets or images",
    "搜索数据集或图像",
    "搜尋資料集或圖像",
  ],
  evaluationReady: [
    "The selected model will process the selected data as a background task.",
    "所选模型将在后台处理所选数据，可离开页面后再查看结果。",
    "所選模型將在背景處理所選資料，可離開頁面後再查看結果。",
  ],
  noOptions: ["No matching options", "暂无匹配选项", "暫無符合選項"],
  modelFirst: ["Select a model first", "请先选择模型", "請先選擇模型"],
  predictions: ["predictions", "条预测", "項預測"],
  test: ["Test split", "测试集", "測試集"],
  val: ["Validation split", "验证集", "驗證集"],
  train: ["Training split", "训练集", "訓練集"],
  unassigned: [
    "Unassigned / external data",
    "未划分 / 外部数据",
    "未劃分 / 外部資料",
  ],
  oof: ["Out-of-fold predictions", "交叉验证折外预测", "交叉驗證折外預測"],
  macro: ["Macro average", "宏平均", "宏平均"],
  micro: ["Micro average", "微平均", "微平均"],
  weighted: ["Weighted average", "加权平均", "加權平均"],
  binary: ["Positive class", "阳性类别", "陽性類別"],
  percentile: ["Percentile method", "百分位法", "百分位法"],
  metricHelp: [
    "Only metrics supported by the selected data are available.",
    "根据已有预测和真实标签，开放可计算的指标。",
    "根據已有預測及真實標籤，開放可計算的指標。",
  ],
  chartHelp: [
    "Choose charts to calculate. Appearance can be adjusted after calculation.",
    "选择要生成的图表，计算完成后可调整标题、颜色和范围。",
    "選擇要產生的圖表，計算完成後可調整標題、顏色及範圍。",
  ],
  assistantContext: [
    "Using the selected experiments and current analysis settings",
    "基于已选实验和当前分析配置",
    "根據已選實驗及目前分析設定",
  ],
  assistantExplain: [
    "Explain the current results",
    "解释当前结果",
    "解釋目前結果",
  ],
  assistantCalibration: [
    "Add calibration and Brier score",
    "添加校准分析和 Brier 指标",
    "加入校準分析及 Brier 指標",
  ],
  assistantCompare: [
    "Compare these experiments",
    "比较这些实验",
    "比較這些實驗",
  ],
  handoffHint: [
    "Your selected experiments and analysis settings will be included.",
    "将携带已选实验、分析配置和当前结果。",
    "將攜帶已選實驗、分析設定及目前結果。",
  ],
  analysisContext: ["Analysis context", "分析上下文", "分析上下文"],
  submittedAnalysis: ["Analysis submitted", "分析已提交", "分析已提交"],
  summaryOnly: ["Recorded result", "已有结果", "已有結果"],
  noAvailableMetrics: [
    "This source has no recorded metrics or sample predictions yet.",
    "此来源尚无已记录指标或逐样本预测。",
    "此來源尚無已記錄指標或逐樣本預測。",
  ],
  missingData: [
    "Required data or valid evaluation pairs are unavailable",
    "缺少所需数据或有效评估样本",
    "缺少所需資料或有效評估樣本",
  ],
  overlapReason: [
    "Training dataset overlap",
    "与训练数据重叠",
    "與訓練資料重疊",
  ],
  emptyReason: ["Dataset is empty", "数据集为空", "資料集為空"],
  labelsReason: [
    "Ground-truth classes do not match the model",
    "真实标签类别与模型不匹配",
    "真實標籤類別與模型不相符",
  ],
  labelledReason: [
    "Dataset already has ground truth; use external validation",
    "此数据集已有标签，请使用外部验证",
    "此資料集已有標籤，請使用外部驗證",
  ],
  segmentationReason: [
    "Segmentation ground-truth classes do not match the model",
    "分割标注类别与模型不匹配",
    "分割標註類別與模型不相符",
  ],
  pageNumber: ["Page {{number}}", "第 {{number}} 页", "第 {{number}} 頁"],
  provenance: ["Result details", "结果详情", "結果詳情"],
} as const;
const metricLabels: Record<string, readonly [string, string, string]> = {
  sample_count: ["Sample count", "样本数量", "樣本數量"],
  accuracy: ["Accuracy", "准确率", "準確率"],
  balanced_accuracy: ["Balanced accuracy", "平衡准确率", "平衡準確率"],
  precision: ["Precision", "精确率", "精確率"],
  sensitivity: ["Sensitivity / recall", "敏感度 / 召回率", "敏感度 / 召回率"],
  recall: ["Recall", "召回率", "召回率"],
  specificity: ["Specificity", "特异度", "特異度"],
  f1: ["F1 score", "F1 分数", "F1 分數"],
  mcc: ["MCC", "Matthews 相关系数", "Matthews 相關係數"],
  weighted_kappa: [
    "Quadratic weighted kappa",
    "二次加权 Kappa",
    "二次加權 Kappa",
  ],
  auc: ["ROC AUC", "ROC AUC", "ROC AUC"],
  average_precision: [
    "Average precision (AP)",
    "平均精确率（AP）",
    "平均精確率（AP）",
  ],
  brier: ["Brier score", "Brier 分数", "Brier 分數"],
  log_loss: ["Log loss", "对数损失", "對數損失"],
  mean_confidence: ["Mean confidence", "平均置信度", "平均信心值"],
  entropy: ["Predictive entropy", "预测熵", "預測熵"],
  c_index: ["C-index", "一致性指数", "一致性指數"],
  integrated_brier_score: [
    "Integrated Brier score",
    "综合 Brier 分数",
    "綜合 Brier 分數",
  ],
  mean_risk: ["Mean risk score", "平均风险分数", "平均風險分數"],
  iou: ["IoU", "交并比（IoU）", "交並比（IoU）"],
  miou: ["mIoU", "平均交并比", "平均交並比"],
  dice: ["Dice", "Dice 系数", "Dice 係數"],
  pixel_accuracy: ["Pixel accuracy", "像素准确率", "像素準確率"],
  pixel_precision: ["Pixel precision", "像素精确率", "像素精確率"],
  pixel_recall: ["Pixel recall", "像素召回率", "像素召回率"],
  pixel_f1: ["Pixel F1", "像素 F1", "像素 F1"],
};
const chartLabels: Record<string, readonly [string, string, string]> = {
  roc: ["ROC curve", "ROC 曲线", "ROC 曲線"],
  pr: ["Precision–recall curve", "精确率–召回率曲线", "精確率–召回率曲線"],
  confusion: ["Confusion matrix", "混淆矩阵", "混淆矩陣"],
  calibration: ["Calibration curve", "校准曲线", "校準曲線"],
  threshold: ["Threshold analysis", "阈值分析", "閾值分析"],
  confidence: ["Confidence distribution", "置信度分布", "信心值分佈"],
  distribution: ["Prediction distribution", "预测类别分布", "預測類別分佈"],
  km: ["Kaplan–Meier curve", "生存曲线", "存活曲線"],
  risk: ["Risk distribution", "风险分布", "風險分佈"],
  segmentation: ["Per-image segmentation", "逐图像分割指标", "逐圖像分割指標"],
  comparison: ["Metric comparison", "指标对比", "指標比較"],
  disagreement: ["Prediction disagreement", "预测分歧", "預測分歧"],
  loss: ["Training curves", "训练曲线", "訓練曲線"],
  loss_curve: ["Loss curve", "损失曲线", "損失曲線"],
  iou_curve: ["IoU curve", "IoU 曲线", "IoU 曲線"],
  dice_curve: ["Dice curve", "Dice 曲线", "Dice 曲線"],
  per_class_iou: ["Per-class IoU", "各类别 IoU", "各類別 IoU"],
  per_class_dice: ["Per-class Dice", "各类别 Dice", "各類別 Dice"],
};
for (const [index, language] of ["en-US", "zh-CN", "zh-HK"].entries()) {
  i18n.addResourceBundle(
    language,
    "translation",
    {
      resultsWorkbench: {
        ...Object.fromEntries(
          Object.entries(labels).map(([key, value]) => [key, value[index]]),
        ),
        metricLabels: Object.fromEntries(
          Object.entries(metricLabels).map(([key, value]) => [
            key,
            value[index],
          ]),
        ),
        chartLabels: Object.fromEntries(
          Object.entries(chartLabels).map(([key, value]) => [
            key,
            value[index],
          ]),
        ),
      },
    },
    true,
    true,
  );
}
export type TextKey = keyof typeof labels;
export function useResultText() {
  const { t, i18n } = useTranslation();
  const index = i18n.language.startsWith("zh")
    ? i18n.language === "zh-HK" || i18n.language.includes("TW")
      ? 2
      : 1
    : 0;
  const text = (key: TextKey, values: Record<string, string | number> = {}) =>
    t(`resultsWorkbench.${key}`, {
      defaultValue: labels[key][index],
      ...values,
    });
  return {
    language: i18n.language,
    text,
    metric: (key: string, fallback?: string) =>
      t(`resultsWorkbench.metricLabels.${key.replace(/^macro_/, "")}`, {
        defaultValue:
          metricLabels[key.replace(/^macro_/, "")]?.[index] || fallback || key,
      }),
    chart: (key: string) =>
      t(`resultsWorkbench.chartLabels.${key}`, {
        defaultValue: chartLabels[key]?.[index] || key,
      }),
    split: (value: string) =>
      ["train", "val", "test", "unassigned", "oof"].includes(value)
        ? text(value as TextKey)
        : value.startsWith("fold_")
          ? `${text("experimentNumber", { number: Number(value.slice(5)) + 1 })} · OOF`
          : value,
    reason: (value: string | null) => {
      const key = (
        {
          "Training dataset overlap": "overlapReason",
          "Dataset is empty": "emptyReason",
          "Ground-truth classes do not match the model": "labelsReason",
          "Dataset already has ground truth; use external validation":
            "labelledReason",
          "Segmentation ground-truth classes do not match the model":
            "segmentationReason",
        } as Record<string, TextKey>
      )[value || ""];
      return key ? text(key) : value;
    },
    note: (value: string) => {
      const key = (
        {
          "One sample per dataset/case; classification probabilities and survival risk are averaged across slides.":
            "caseNote",
          "IBS uses the evaluation cohort censoring distribution and the saved probability time grid.":
            "ibsNote",
          "Segmentation metrics are macro averages of saved per-image metrics.":
            "segmentationNote",
          "Recorded metrics retain their original evaluation scope. Configuration changes do not recalculate these values.":
            "recordedNote",
        } as Record<string, TextKey>
      )[value];
      const counts = value.match(
        /^Ground truth available for (\d+)\/(\d+) samples;/,
      );
      return key
        ? text(key)
        : counts
          ? text("partialGtNote", { labelled: counts[1], total: counts[2] })
          : value;
    },
  };
}
export type ResultText = ReturnType<typeof useResultText>["text"];
