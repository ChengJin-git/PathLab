import { HeroDemoScenario, CapabilityCardData } from '../../types/landing'

export const HERO_DEMO_SCENARIO_EN: HeroDemoScenario = {
  prompt: "I want to train a model to extract tumor regions from the latest breast cancer slides, export ROC curve.",
  intent: [
    { label: "Data Source", value: "BRCA001", emphasized: true },
    { label: "Task Type", value: "Tumor Extraction" },
    { label: "Model", value: "Pathology FM", emphasized: true },
    { label: "Magnification", value: "40x", emphasized: true }
  ],
  config: [
    { label: "Input Directory", value: "/data/BRCA001/latest/" },
    { label: "Output Directoy", value: "/results/tumor_extraction/" },
    { label: "Batch Size", value: "32" },
    { label: "Export Metrics", value: "ROC, Confusion Matrix" }
  ],
  splitOptions: ["Train/Test (80/20)", "K-Fold (K=5)", "None"],
  defaultSplit: "Train/Test (80/20)",
  run: {
    readyLabel: "Start Task",
    queueingLabel: "Queueing...",
    runningLabel: "Running Task...",
    progressTarget: 68,
    ctaLabel: "View Results"
  }
}

export const HERO_DEMO_SCENARIO_ZH: HeroDemoScenario = {
  prompt: "我要训练一个模型提取我最新乳腺癌切片中的肿瘤区域，并导出 ROC 曲线。",
  intent: [
    { label: "数据源", value: "BRCA001", emphasized: true },
    { label: "任务类型", value: "肿瘤提取" },
    { label: "模型", value: "病理大模型", emphasized: true },
    { label: "放大倍率", value: "40x", emphasized: true }
  ],
  config: [
    { label: "输入目录", value: "/data/BRCA001/latest/" },
    { label: "输出目录", value: "/results/tumor_extraction/" },
    { label: "批次大小", value: "32" },
    { label: "导出指标", value: "ROC, 混淆矩阵" }
  ],
  splitOptions: ["训练/测试 (80/20)", "K折交叉验证 (K=5)", "无"],
  defaultSplit: "训练/测试 (80/20)",
  run: {
    readyLabel: "启动任务",
    queueingLabel: "排队中...",
    runningLabel: '正在运行任务...',
    progressTarget: 100,
    ctaLabel: '查看结果'
  }
}

export const HERO_DEMO_SCENARIO_ZH_HK: HeroDemoScenario = {
  prompt: '我想訓練一个模型提取我最新乳腺癌切片中的肿瘤区域，並匯出 ROC 曲線。',
  config: [
    { label: '輸入目錄', value: '/data/BRCA001/latest/' },
    { label: '預處理管線', value: '標準化 + 切塊 (256x256)' },
    { label: '推斷引擎', value: 'ONNX Runtime (GPU:0)' },
    { label: '輸出指標', value: 'ROC, AUC, F1-Score' }
  ],
  intent: [
    { label: '數據源', value: 'BRCA001', emphasized: true },
    { label: '任務類型', value: '腫瘤提取' },
    { label: '模型', value: '病理大模型', emphasized: true },
    { label: '放大倍率', value: '40x' }
  ],
  splitOptions: ["訓練/測試 (80/20)", "K折交叉驗證 (K=5)", "無"],
  defaultSplit: "訓練/測試 (80/20)",
  run: {
    readyLabel: '執行配置任務',
    queueingLabel: '正在分配運算資源...',
    runningLabel: '正在執行任務...',
    progressTarget: 100,
    ctaLabel: '檢視結果'
  }
}

export const CAPABILITY_CARDS_ZH: CapabilityCardData[] = [
  {
    title: "任务监控",
    description: "实时追踪任务执行进度与容器日志",
  },
  {
    title: "结果查看器",
    description: "直观评估模型性能",
  },
  {
    title: "数据与文件",
    description: "无缝接入 SVS / DICOM 多格式病理图像",
  }
]

export const CAPABILITY_CARDS_ZH_HK: CapabilityCardData[] = [
  {
    title: "任務監控",
    description: "即時追蹤任務執行進度與容器日誌",
  },
  {
    title: "結果查看器",
    description: "直觀評估模型性能",
  },
  {
    title: "數據與文件",
    description: "無縫接入 SVS / DICOM 多格式病理影像",
  }
]

export const CAPABILITY_CARDS_EN: CapabilityCardData[] = [
  {
    title: "Task Monitoring",
    description: "Track pipeline progress and container logs in real-time",
  },
  {
    title: "Results Viewer",
    description: "Intuitively evaluate model performance",
  },
  {
    title: "Data & Files",
    description: "Seamlessly connect SVS / DICOM and multi-format medical images",
  }
]
