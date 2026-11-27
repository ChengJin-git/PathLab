import { useTranslation } from "react-i18next";

const messages = {
  title: ["Upload data", "上传数据", "上傳資料"],
  subtitle: [
    "Bring images and their labels into one research dataset.",
    "将图像与标签整理为可用于研究的数据集。",
    "將影像與標籤整理為可用於研究的資料集。",
  ],
  setup: ["Dataset setup", "配置数据集", "設定資料集"],
  addFiles: ["Files & labels", "添加文件与标签", "新增檔案與標籤"],
  steps: ["Upload steps", "上传步骤", "上傳步驟"],
  basics: ["Dataset details", "基本信息", "基本資訊"],
  basicsHint: [
    "Give this collection a name and choose its image type.",
    "为这份图像集合命名，并选择图像类型。",
    "為這份影像集合命名，並選擇影像類型。",
  ],
  imageType: ["Image type", "图像类型", "影像類型"],
  patchHint: [
    "Cropped or standalone images",
    "裁剪图像或独立显微图像",
    "裁剪影像或獨立顯微影像",
  ],
  wsiHint: [
    "Scanned whole-slide images",
    "病理切片的全视野扫描",
    "病理切片的全視野掃描",
  ],
  optional: ["Optional", "选填", "選填"],
  multipleTasks: ["Select one or more", "可多选", "可複選"],
  taskHint: [
    "Select the labels you plan to use. You can add more later.",
    "选择计划使用的标签类型，后续也可补充。",
    "選擇計劃使用的標籤類型，之後亦可補充。",
  ],
  classificationLabel: ["Class labels", "类别标签", "類別標籤"],
  survivalLabel: ["Follow-up outcomes", "随访结局", "隨訪結局"],
  segmentationLabel: ["Polygons / masks", "轮廓 / 掩膜", "輪廓 / 遮罩"],
  detectionLabel: ["Bounding boxes", "目标框", "目標框"],
  appendExisting: [
    "Add to an existing dataset",
    "追加到已有数据集",
    "新增至現有資料集",
  ],
  selectedDataset: ["Selected dataset", "当前数据集", "目前資料集"],
  preview: ["Import overview", "本次导入", "本次匯入"],
  unnamed: ["Untitled dataset", "待命名的数据集", "尚未命名的資料集"],
  prepareNext: ["What to prepare", "接下来准备", "接下來準備"],
  imageFiles: ["Image files", "图像文件", "影像檔案"],
  labelFiles: [
    "Labels & sample information",
    "标签与样本信息",
    "標籤與樣本資訊",
  ],
  imageFilesHint: [
    "Select files or an entire folder in the next step.",
    "下一步可选择文件，或直接拖入整个文件夹。",
    "下一步可選擇檔案，或直接拖入整個資料夾。",
  ],
  labelsHint: [
    "CSV for sample details; COCO JSON for spatial annotations.",
    "样本信息使用 CSV；分割与检测标注使用 COCO JSON。",
    "樣本資訊使用 CSV；分割與檢測標註使用 COCO JSON。",
  ],
  laterHint: [
    "Images first. Labels can follow.",
    "可先上传图像，稍后补充标签。",
    "可先上傳影像，稍後補充標籤。",
  ],
  visibility: ["Dataset access", "数据集可见性", "資料集可見性"],
  privateHint: [
    "Only you and administrators can access this dataset.",
    "仅你和管理员可以访问此数据集。",
    "只有你和管理員可以存取此資料集。",
  ],
  publicHint: [
    "All signed-in users can access this dataset.",
    "所有已登录用户均可访问此数据集。",
    "所有已登入使用者均可存取此資料集。",
  ],
  readyHint: [
    "Your settings can be edited later.",
    "这些信息可在数据仓库中继续编辑。",
    "這些資訊可在資料庫中繼續編輯。",
  ],
  filesSubtitle: [
    "Add images, then complete the labels you have.",
    "添加图像，按需补充已有的标签与样本信息。",
    "新增影像，按需補充現有標籤與樣本資訊。",
  ],
  dropHint: [
    "Drag files or folders here, or choose them below.",
    "拖入文件或文件夹，也可以点击下方按钮选择。",
    "拖入檔案或資料夾，亦可點選下方按鈕選擇。",
  ],
  formats: ["Supported formats", "支持格式", "支援格式"],
  selectedFiles: ["Selected files", "已选文件", "已選檔案"],
  noMatches: [
    "No files match this search.",
    "没有匹配的文件。",
    "沒有符合的檔案。",
  ],
  sampleFields: ["Sample fields", "样本字段", "樣本欄位"],
  chooseAttachment: ["Choose file", "选择文件", "選擇檔案"],
  replaceAttachment: ["Replace", "更换", "更換"],
  csvHint: [
    "Match images by filename. Include labels, case IDs or follow-up data.",
    "按文件名匹配图像，可包含类别、病例 ID 与随访信息。",
    "按檔案名稱配對影像，可包含類別、病例 ID 與隨訪資訊。",
  ],
  spatialHint: [
    "Import annotations for this task as COCO JSON.",
    "导入此任务的 COCO JSON 标注。",
    "匯入此任務的 COCO JSON 標註。",
  ],
  attachmentsHint: [
    "Add the files you have; each label type is saved separately.",
    "按需添加文件，不同任务的标签分别保存。",
    "按需新增檔案，不同任務的標籤分別儲存。",
  ],
  submitHint: [
    "Upload progress stays available in Background tasks.",
    "上传进度可在「后台进度」中查看。",
    "上傳進度可在「背景進度」中查看。",
  ],
  creating: ["Saving setup…", "正在保存…", "正在儲存…"],
  appendTitle: ["Add to dataset", "追加数据", "新增資料"],
  appendSubtitle: [
    "Add new images or enrich the labels of images already here.",
    "补充新的图像，或完善已有图像的任务与标签。",
    "補充新的影像，或完善現有影像的任務與標籤。",
  ],
  appendImages: ["New images", "新增图像", "新增影像"],
  appendImagesHint: [
    "Add files to this collection",
    "向此数据集添加图像文件",
    "向此資料集新增影像檔案",
  ],
  appendLabels: ["Tasks & labels", "补充任务与标签", "補充任務與標籤"],
  appendLabelsHint: [
    "Label existing images or add a task",
    "为已有图像补标签或新增任务",
    "為現有影像補標籤或新增任務",
  ],
  existingSamples: ["Existing images", "已有图像", "現有影像"],
  labelCoverage: ["Current label coverage", "已有标签情况", "現有標籤情況"],
  newTask: ["New task", "新增任务", "新增任務"],
  datasetLookup: ["Loading datasets…", "正在载入数据集…", "正在載入資料集…"],
  datasetFailed: [
    "Datasets could not be loaded. Retry before submitting.",
    "数据集未能载入，请重试后提交。",
    "資料集未能載入，請重試後提交。",
  ],
  chooseDataset: [
    "Select the existing dataset explicitly to append; names may repeat.",
    "追加数据请明确选择已有数据集，名称可能重复。",
    "追加資料請明確選取已有資料集，名稱可能重複。",
  ],
  searchFiles: [
    "Search selected filenames",
    "搜索已选文件名",
    "搜尋已選檔案名稱",
  ],
  pageSize: ["Files per page", "每页文件数", "每頁檔案數"],
  goToPage: ["Go to page", "跳转页码", "跳轉頁碼"],
  selectPage: ["Select this page", "选择本页", "選取本頁"],
  chooseFiles: ["Choose files", "选择文件", "選取檔案"],
  chooseFolder: ["Choose folder", "选择文件夹", "選取資料夾"],
  missingCase: [
    "Case-level data requires the original case ID for each file; generated IDs cannot establish patient grouping.",
    "病例级数据需要每个文件的原始病例 ID，自动生成的 ID 无法建立患者分组。",
    "病例級資料需要每個檔案的原始病例 ID，自動產生的 ID 無法建立患者分組。",
  ],
  invalidSurvival: [
    "Survival time must be finite and non-negative; status must be 0 or 1.",
    "生存时间必须为非负有限数值，状态只能是 0 或 1。",
    "存活時間必須為非負有限數值，狀態只能是 0 或 1。",
  ],
  invalidAge: [
    "Age must be a non-negative whole number.",
    "年龄必须为非负整数。",
    "年齡必須為非負整數。",
  ],
  invalidSplit: [
    "Split must be train, val or test. Keep every case in a single split.",
    "划分只能是 train、val 或 test，同一病例必须在同一个划分中。",
    "劃分只能是 train、val 或 test，同一病例必須在同一個劃分中。",
  ],
  mixedTypes: [
    "Upload WSI and patch images as separate datasets with compatible task types.",
    "全切片图像和图像块请分开上传到任务类型兼容的数据集。",
    "全切片圖像和圖像塊請分開上傳至任務類型相容的資料集。",
  ],
  missingAssociated: [
    "Add the matching MRXS data folder or TMAP data files before submitting.",
    "请补齐同名 MRXS 数据文件夹或 TMAP 数据文件后提交。",
    "請補齊同名 MRXS 資料夾或 TMAP 資料檔案後提交。",
  ],
  duplicateNames: [
    "Different selected files have the same filename. Rename them before uploading to one dataset.",
    "选中的不同文件存在同名，请重命名后再上传到同一个数据集。",
    "選取的不同檔案存在同名，請重新命名後再上傳至同一資料集。",
  ],
  duplicateCheck: [
    "Existing-file check is unavailable; files are retained and the server will validate at upload.",
    "暂时无法核对已有文件；已保留所选文件，上传时服务端会再次校验。",
    "暫時無法核對已有檔案；已保留所選檔案，上傳時伺服器會再次驗證。",
  ],
  xlsUnsupported: [
    "Save legacy .xls files as .xlsx or CSV before uploading.",
    "请先将旧版 .xls 另存为 .xlsx 或 CSV 后上传。",
    "請先將舊版 .xls 另存為 .xlsx 或 CSV 後上傳。",
  ],
  invalidCsv: [
    "The metadata table has malformed rows or duplicate filenames. Correct it before submitting.",
    "元数据表存在格式错误或重复文件名，请修正后提交。",
    "中繼資料表存在格式錯誤或重複檔案名稱，請修正後提交。",
  ],
  segmentationOnly: [
    "Segmentation accepts patch images and matching COCO JSON files.",
    "分割仅支持图像块及匹配的 COCO JSON 文件。",
    "分割僅支援圖像塊及匹配的 COCO JSON 檔案。",
  ],
  duplicateMasks: [
    "Segmentation images or JSON files have duplicate stems. Keep one matching pair per image.",
    "分割图像或 JSON 存在重复主文件名，请为每张图像保留唯一匹配。",
    "分割圖像或 JSON 存在重複主檔案名稱，請為每張圖像保留唯一配對。",
  ],
} as const;
export function useUploadText() {
  const { i18n } = useTranslation();
  const language = i18n?.language || "en-US";
  const index = /HK|TW|Hant/i.test(language)
    ? 2
    : language.startsWith("zh")
      ? 1
      : 0;
  return (key: keyof typeof messages) => messages[key][index];
}
