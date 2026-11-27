"""Localized, metadata-only command catalog. Skill source instructions stay intact."""

from functools import lru_cache

from backend.autoresearch.engine.builtin_skills import catalog

# Each entry is (English name/summary, simplified Chinese, traditional Chinese).
LABELS = {
    "experiment": (
        ("Autonomous exploration", "Clarify your goal, then confirm research, analysis or experiments."),
        ("自主探索", "先梳理需求，确认后开展调研、分析或实验。"),
        ("自主探索", "先梳理需求，確認後開展調研、分析或實驗。"),
    ),
    "literature": (
        ("Literature research", "Search, read and synthesize research literature."),
        ("文献研究", "检索、阅读并综合研究文献。"),
        ("文獻研究", "檢索、閱讀並綜合研究文獻。"),
    ),
    "analyze": (
        (
            "Results analysis",
            "Analyze referenced data and measured experimental results.",
        ),
        ("结果分析", "分析引用的数据和实测实验结果。"),
        ("結果分析", "分析引用的資料和實測實驗結果。"),
    ),
    "report": (
        (
            "Research report",
            "Write a research report from experiments and verified evidence.",
        ),
        ("研究报告", "基于实验与已核实证据撰写研究报告。"),
        ("研究報告", "根據實驗與已核實證據撰寫研究報告。"),
    ),
    "ask": (
        ("Discuss", "Discuss the task without sending execution instructions."),
        ("讨论", "讨论当前任务，不发送执行指令。"),
        ("討論", "討論目前任務，不傳送執行指令。"),
    ),
    "pathlab-research": (
        (
            "Pathology research",
            "Carry out evidence-grounded pathology research from data to results.",
        ),
        ("病理研究", "从数据到结果，开展有证据支持的病理研究。"),
        ("病理研究", "從資料到結果，進行有證據支持的病理研究。"),
    ),
    "pathlab-mil-classification": (
        (
            "WSI multiple-instance learning",
            "Train and compare whole-slide multiple-instance classification methods.",
        ),
        ("全切片多实例分类", "训练并比较全切片多实例学习分类方法。"),
        ("全切片多實例分類", "訓練並比較全切片多實例學習分類方法。"),
    ),
    "pathlab-patch-classification": (
        (
            "Patch classification",
            "Classify image patches using frozen feature embeddings.",
        ),
        ("图像块分类", "使用冻结特征向量进行病理图像块分类。"),
        ("圖像塊分類", "使用凍結特徵向量進行病理圖像塊分類。"),
    ),
    "pathlab-survival-analysis": (
        (
            "Survival analysis",
            "Model case-level survival and evaluate censored outcomes.",
        ),
        ("生存分析", "构建病例级生存模型，评估含删失的结局。"),
        ("存活分析", "建立病例層級存活模型，評估含設限的結局。"),
    ),
    "pathlab-patch-segmentation": (
        (
            "Patch segmentation",
            "Train pixel-level segmentation from images and annotated masks.",
        ),
        ("图像块分割", "基于图像与标注掩膜训练像素级分割模型。"),
        ("圖像塊分割", "根據影像與標註遮罩訓練像素層級分割模型。"),
    ),
    "pathlab-feature-extraction": (
        (
            "Feature extraction",
            "Detect tissue, tile whole slides and extract frozen features.",
        ),
        ("特征提取", "执行组织检测、从全切片图像提取图像块与冻结特征提取。"),
        ("特徵擷取", "執行組織偵測、從全切片圖像提取圖像塊與凍結特徵擷取。"),
    ),
    "pathlab-external-test": (
        (
            "External validation",
            "Evaluate a fixed model on an independent external cohort.",
        ),
        ("外部验证", "在独立外部队列上评估固定模型。"),
        ("外部驗證", "在獨立外部隊列上評估固定模型。"),
    ),
    "nature-academic-search": (
        (
            "Academic search",
            "Search multiple literature sources, manage citations and build evidence-backed search strategies.",
        ),
        ("学术检索", "检索多源文献、管理引文，制定有证据支持的检索策略。"),
        ("學術檢索", "檢索多來源文獻、管理引文，制定有證據支持的檢索策略。"),
    ),
    "nature-citation": (
        (
            "Claim-to-citation matching",
            "Find and verify Nature/CNS-family references supporting manuscript claims.",
        ),
        ("论据引文匹配", "查找并核验支撑论文论点的 Nature／CNS 系列文献。"),
        ("論據引文配對", "尋找並核驗支持論文論點的 Nature／CNS 系列文獻。"),
    ),
    "nature-data": (
        (
            "Data and code availability",
            "Prepare availability statements, dataset access plans and FAIR metadata.",
        ),
        ("数据与代码可用性", "撰写可用性声明，规划数据获取、共享与 FAIR 元数据。"),
        ("資料與程式碼可用性", "撰寫可用性聲明，規劃資料取得、共享與 FAIR 中繼資料。"),
    ),
    "nature-downloader": (
        (
            "Academic full-text retrieval",
            "Retrieve accessible full papers and supplementary materials through authorized sources.",
        ),
        ("学术全文获取", "通过可访问或已授权的来源获取论文全文及补充材料。"),
        ("學術全文取得", "透過可存取或已授權的來源取得論文全文及補充資料。"),
    ),
    "nature-experiment-log": (
        (
            "Experiment log",
            "Turn notes, images and recordings into structured Markdown experiment records.",
        ),
        ("实验日志", "将笔记、图片与录音整理为结构化 Markdown 实验记录。"),
        ("實驗日誌", "將筆記、圖片與錄音整理為結構化 Markdown 實驗紀錄。"),
    ),
    "nature-figure": (
        (
            "Scientific figures",
            "Create, refine and audit publication-ready scientific plots and multi-panel figures.",
        ),
        ("科研绘图", "创建、修改与审查可投稿的科研图表和多面板图。"),
        ("科研繪圖", "建立、修改與審查可投稿的科研圖表和多面板圖。"),
    ),
    "nature-image2ppt": (
        (
            "Images to editable slides",
            "Reconstruct slide screenshots and image-only presentations as editable PowerPoint objects.",
        ),
        (
            "图片转可编辑幻灯片",
            "将幻灯片截图和图片型演示文稿还原为可编辑的 PowerPoint 对象。",
        ),
        (
            "圖片轉可編輯投影片",
            "將投影片截圖和圖片型簡報還原為可編輯的 PowerPoint 物件。",
        ),
    ),
    "nature-literature-pipeline": (
        (
            "Literature discovery pipeline",
            "Search, rank, deeply read and organize literature into a structured research digest.",
        ),
        ("文献发现流程", "检索、评分、精读与归档文献，形成结构化研究综述。"),
        ("文獻發現流程", "檢索、評分、精讀與歸檔文獻，形成結構化研究綜述。"),
    ),
    "nature-paper-card": (
        (
            "Paper reading card",
            "Extract a paper's methods, evidence, limitations and research ideas into a reading card.",
        ),
        ("论文精读卡", "梳理论文的方法、证据、局限与研究启发，生成精读卡。"),
        ("論文精讀卡", "梳理論文的方法、證據、限制與研究啟發，產生精讀卡。"),
    ),
    "nature-paper-to-patent": (
        (
            "Paper to patent draft",
            "Develop evidence-grounded Chinese patent drafts and technical disclosures from research.",
        ),
        ("论文转专利草案", "基于研究材料撰写有证据支持的中文专利草案与技术交底书。"),
        ("論文轉專利草案", "根據研究資料撰寫有證據支持的中文專利草案與技術揭露文件。"),
    ),
    "nature-paper-trans": (
        (
            "Layout-preserving paper translation",
            "Translate English paper PDFs into simplified Chinese while retaining page layout.",
        ),
        ("论文保版式翻译", "将英文论文 PDF 翻译为简体中文，尽量保留原始页面版式。"),
        ("論文保留版面翻譯", "將英文論文 PDF 翻譯為簡體中文，盡量保留原始頁面版面。"),
    ),
    "nature-paper-xray": (
        (
            "Paper deep dive",
            "Explain how a study was designed, including its methods, equations and evidence chain.",
        ),
        ("论文深度拆解", "解释研究设计、方法推导、公式与证据链，深入理解论文。"),
        ("論文深度拆解", "解釋研究設計、方法推導、公式與證據鏈，深入理解論文。"),
    ),
    "nature-paper2ppt": (
        (
            "Paper to presentation",
            "Build Chinese academic presentations with source figures and speaker notes.",
        ),
        ("论文转学术汇报", "基于论文制作中文学术演示文稿，包含原文图表与演讲备注。"),
        ("論文轉學術簡報", "根據論文製作中文學術簡報，包含原文圖表與講者備註。"),
    ),
    "nature-paper2word": (
        (
            "Manuscript to Word",
            "Compile academic Markdown into formatted Word documents with equations, tables and references.",
        ),
        (
            "论文转 Word",
            "将学术 Markdown 转为规范排版的 Word，保留公式、表格与参考文献。",
        ),
        (
            "論文轉 Word",
            "將學術 Markdown 轉為規範排版的 Word，保留公式、表格與參考文獻。",
        ),
    ),
    "nature-polishing": (
        (
            "Academic polishing",
            "Polish, translate or shorten academic prose while preserving facts and evidence boundaries.",
        ),
        ("学术润色", "润色、翻译或精简学术文字，保留事实、术语与证据边界。"),
        ("學術潤飾", "潤飾、翻譯或精簡學術文字，保留事實、術語與證據界線。"),
    ),
    "nature-proposal-writer": (
        (
            "Research proposal",
            "Draft and review research proposals, project applications and study plans.",
        ),
        ("研究计划撰写", "起草与审查研究计划、开题报告及科研项目申请书。"),
        ("研究計劃撰寫", "起草與審查研究計劃、開題報告及科研計劃申請書。"),
    ),
    "nature-reader": (
        (
            "Bilingual paper reader",
            "Read papers with aligned Chinese-English text, figures, tables and equations.",
        ),
        ("双语论文阅读", "对照中英文阅读论文，结合原文图表、公式与来源回答问题。"),
        ("雙語論文閱讀", "對照中英文閱讀論文，結合原文圖表、公式與來源回答問題。"),
    ),
    "nature-ref-verifier": (
        (
            "Reference verification",
            "Cross-check authors, titles, years, pages and DOIs against multiple bibliographic sources.",
        ),
        ("参考文献核验", "通过多源交叉验证核对作者、标题、年份、页码与 DOI。"),
        ("參考文獻核驗", "透過多來源交叉驗證核對作者、標題、年份、頁碼與 DOI。"),
    ),
    "nature-response": (
        (
            "Peer-review response",
            "Draft point-by-point reviewer responses, revision letters and manuscript revision packages.",
        ),
        ("审稿意见回复", "撰写逐点审稿回复、返修信与论文修改材料。"),
        ("審稿意見回覆", "撰寫逐點審稿回覆、修訂信與論文修改資料。"),
    ),
    "nature-reviewer": (
        (
            "Manuscript peer review",
            "Review scientific significance, methodological validity and major or minor concerns.",
        ),
        ("模拟同行评审", "评估科学意义、方法有效性及论文中的主要与次要问题。"),
        ("模擬同儕評審", "評估科學意義、方法有效性及論文中的主要與次要問題。"),
    ),
    "nature-shared": (
        (
            "Shared research references",
            "Supporting references used by other Nature Skills; not a standalone workflow.",
        ),
        (
            "共享研究参考资料",
            "供其他 Nature Skills 使用的辅助参考资料，不作为独立任务流程。",
        ),
        (
            "共享研究參考資料",
            "供其他 Nature Skills 使用的輔助參考資料，不作為獨立任務流程。",
        ),
    ),
    "nature-social-science": (
        (
            "Social science research",
            "Develop research questions, literature arguments and evidence plans for social science studies.",
        ),
        ("社会科学研究", "构思研究问题、梳理文献论证并规划社会科学研究的证据路径。"),
        ("社會科學研究", "構思研究問題、梳理文獻論證並規劃社會科學研究的證據路徑。"),
    ),
    "nature-statistics": (
        (
            "Statistical review",
            "Review experimental units, replication, uncertainty, tests and statistical reporting.",
        ),
        ("统计审查", "审查实验单位、重复设计、不确定性、统计检验与结果报告。"),
        ("統計審查", "審查實驗單位、重複設計、不確定性、統計檢定與結果報告。"),
    ),
    "nature-writing": (
        (
            "Scientific writing",
            "Draft and restructure scientific arguments, manuscript sections and submission materials.",
        ),
        ("科学论文写作", "起草与重构科学论证、论文章节及投稿材料。"),
        ("科學論文寫作", "起草與重構科學論證、論文章節及投稿資料。"),
    ),
    "humanizer": (
        (
            "Natural English editing",
            "Make English prose more natural while preserving meaning and the author's voice.",
        ),
        ("英文自然表达", "改善英文中的模板化表达，保留原意与作者风格。"),
        ("英文自然表達", "改善英文中的模板化表達，保留原意與作者風格。"),
    ),
    "humanizer-zh": (
        (
            "Natural Chinese editing",
            "Remove formulaic wording and repetition from Chinese prose without changing facts.",
        ),
        ("中文自然表达", "减少中文中的空话、重复与模板化措辞，同时保留事实。"),
        ("中文自然表達", "減少中文中的空話、重複與模板化措辭，同時保留事實。"),
    ),
    "pathtrove": (
        (
            "PathTrove",
            "Search the PathTrove catalogue of public pathology datasets, challenges and benchmarks.",
        ),
        ("PathTrove", "检索 PathTrove 计算病理公开数据集、挑战赛与基准目录。"),
        ("PathTrove", "檢索 PathTrove 計算病理公開資料集、挑戰賽與基準目錄。"),
    ),
    "pathtrove-data": (
        (
            "Pathology dataset lookup",
            "Check a dataset's size, labels, licence, access route and label files.",
        ),
        ("病理数据集查询", "查询数据集规模、标注、许可、获取方式与标签文件。"),
        ("病理資料集查詢", "查詢資料集規模、標註、授權、取得方式與標籤檔案。"),
    ),
    "pathtrove-best-data": (
        (
            "Dataset recommendation",
            "Recommend public pathology datasets and benchmarks for a research need.",
        ),
        ("数据集推荐", "根据研究需求推荐公开病理数据集与基准。"),
        ("資料集推薦", "根據研究需求推薦公開病理資料集與基準。"),
    ),
}

PRIMARY = {
    "experiment": "pathlab-research",
    "literature": "nature-literature-pipeline",
    "analyze": "nature-statistics",
    "report": "nature-writing",
    "ask": None,
}


@lru_cache(maxsize=3)
def commands(language: str) -> list[dict]:
    index = {"en-US": 0, "zh-CN": 1, "zh-HK": 2}[language]
    entries = [
        (key, skill, "chat" if key == "ask" else "research")
        for key, skill in PRIMARY.items()
    ]
    entries.extend(
        (item["id"], item["id"], "research")
        for item in catalog()
        if item["id"] not in {"pathlab-research", "nature-shared"}
    )
    return [
        dict(
            id=key,
            skill_id=skill,
            mode=mode,
            name=LABELS[key][index][0],
            description=LABELS[key][index][1],
            search_text=" ".join(
                [key, *[" ".join(pair) for pair in LABELS[key]]]
            ).lower(),
        )
        for key, skill, mode in entries
    ]
