# PaperOrchestra 详解：把"AI 写论文"和"AI 做研究"切开

> 整理日期：2026-05-03
> 论文：Song, Song, Pfister, Yoon. *PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing*. [arXiv:2604.05018](https://arxiv.org/abs/2604.05018), Google Cloud AI Research, 2026.04.
> 项目页：[yiwen-song.github.io/paper_orchestra](https://yiwen-song.github.io/paper_orchestra/)
> 社区实现（最有影响力）：[Ar9av/PaperOrchestra](https://github.com/Ar9av/PaperOrchestra)（327★ / 41 fork，2026-04 持续更新）

> 本文是 [`paper-generation-survey.md`](paper-generation-survey.md) §2.5.1 的展开版。如果只看一篇 2026 年的"AI 写论文"工作，看这一篇就够了——因为它是第一个把**"AI 写论文" ≠ "AI 做研究"**这条边界明确切开、并把每条边各做到目前最强的系统。

---

## 0. 速览

| 维度 | PaperOrchestra 的取舍 |
|------|------------------------|
| **类别** | C 类：写作自动化（不跑实验、不写综述，把人做完的研究写成论文） |
| **输入** | Idea Summary + Experimental Log（含真实数表和 metric）+ LaTeX 模板 + 投稿规则 |
| **输出** | 投稿级 LaTeX 手稿（abstract / 方法 / 实验 / 引言 / Related Work / 结论 + 图 + 表 + bib） |
| **架构** | 5 个 agent 串并行（Outline → {Plotting ‖ Literature Review} → Section Writing → Content Refinement） |
| **Backbone** | Gemini-3.1-Pro（5 个 agent）+ Gemini-3-Flash（10 路并发文献搜索） |
| **图生成** | PaperBanana（外部独立工作，[dwzhu-pku/PaperBanana](https://github.com/dwzhu-pku/PaperBanana)）：Retriever / Planner / Stylist / Visualizer / Critic 五智能体闭环 |
| **引用校验** | Semantic Scholar API + Levenshtein ≥ 0.7 + 时间截断 + S2 paperId 去重；**池子里 ≥ 90% 必须真出现在正文** |
| **评审循环** | Content Refinement 用 AgentReview（外部 2024 论文）当 quality gate，**单调收敛**：分数严格上升或平局且子项非负退化才接受，最多 3 轮 |
| **端到端时间** | 39.6 分钟 / 篇，60–70 次 LLM 调用 |
| **Benchmark** | **PaperWritingBench**：200 篇 seed（CVPR 2025 × 100 + ICLR 2025 × 100），强制双栏 vs 单栏适配；**预先擦除作者身份和原始引用** |
| **关键结果** | Lit-review 质量胜 v2 50–68%（人评）/ 88–99%（自动）；综合质量胜 v2 14–38%（人评）/ 39–86%（自动）；Citation F1 vs v2: 29.7% vs 17.2%（CVPR） |

**一句话定位**：**论文写作和实验执行应该解耦优化，不该绑在一个 agent 里**——这是 PaperOrchestra 用 +39~86% 胜率证明的判断。

---

## 1. 这是什么 / 解决什么问题

### 1.1 它解决的问题

写学术论文是一项**"事实已经齐了，但合成需要技巧"**的工作。一个研究者通常已经有：

- 一个核心想法（idea summary）。
- 一堆跑出来的实验数据（数表、metric、figure 数据）。
- 一份要投的会议模板（CVPR 双栏 / ICLR 单栏 / NeurIPS 单栏…）。
- 一份投稿规则（页数限制、deadline、格式要求）。

但要把这些拼成一篇 8–10 页、引用 60+ 篇文献、figure 5–10 张、claim 严谨、narrative 有起承转合的投稿稿——往往是科研里最磨人的一步。**很多研究的 idea 和实验做完两个月后还在写**。

PaperOrchestra 的目标就是把这一步压缩到 **40 分钟、60–70 次 LLM 调用**。

### 1.2 与 A、B 类的边界

```
                           ┌─ A. 纯综述/报告 ──── 输入只有"主题"，靠已发表文献
                           │   STORM, AutoSurvey, SurveyX, Deep Research...
                           │
论文自动生成 ─────────────┼─ C. 写作自动化 ────── 输入是"人完成的科研材料"
                           │   ★ PaperOrchestra ★
                           │
                           └─ B. AI Scientist ──── 自己生成 idea + 跑实验 + 写
                                Sakana v2, Carl, AI-Researcher, DeepScientist...
```

PaperOrchestra 的设计哲学一句话：**只要"事实"是人产生的，AI 就不能改写它**。这把 hallucination 风险锁定在两个有限的层面：

- **引用层**：用 Semantic Scholar API 校验每一篇引文存在。
- **表达层**：用 AgentReview 检查论述是否清晰、有没有越权 claim。

**实验数字**（accuracy、F1、p-value、ablation 数据）从输入的 experimental log 里**机械抽取**，绝对不允许 LLM 改写——这是 PaperOrchestra 和 CycleResearcher 的根本区别。CycleResearcher 不跑实验、模型直接生成"看起来像 ICLR 论文"的数字，本质是产出像论文的文本；PaperOrchestra 要求人**必须先做完实验**，是产出真论文。

### 1.3 与其它 C 类工作的关系

到 2026 年 5 月为止，C 类只有两个公开工作：

| 工作 | 产品形态 | 颗粒度 | 触发 |
|------|----------|--------|------|
| **PaperOrchestra** (Google, 2026.04) | 一次性 batch 生成完整论文 | 整篇 | 给完整输入 |
| **LLM4Papers** ([Kording Lab, 2024](https://kordinglab.com/2024/06/03/llm4papers)，详见 [`llm4papers.md`](llm4papers.md)) | 异步合作者、git 协作 | 单行 | LaTeX 注释 `% @ai:` |

**这两条不冲突，是互补的**：PaperOrchestra 出第一版完整稿（heavy lifting），LLM4Papers 风格的工具做逐句精修（fine tuning）。两者结合可能是真实的产业部署形态。

---

## 2. 输入 / 输出（一个最小例子）

### 2.1 输入

```
inputs/
├── idea.md                          # Sparse Idea 格式 (paper §3.1)
│                                      "we propose X to address Y; the key
│                                       observation is Z; we evaluate on D"
│
├── experimental_log.md              # 投影到 markdown 的实验日志 (App. D.3)
│                                      数表 + metric + 关键定性观察
│
├── template.tex                     # 比如 NeurIPS 2025 single-column template
└── conference_guidelines.md         # 页数 / deadline / 格式 rules
```

`idea.md` 大致长这样（Sparse Idea 格式）：

```markdown
## Core idea
We propose <Method X>, a <category> approach to <task Y>.
The motivating observation is that <Z>.

## Why it matters
<one paragraph on the gap in literature this fills>

## How it works (concept-level)
<a few bullets — no equations needed at this stage>

## Evaluation strategy
<datasets, baselines, metrics>
```

`experimental_log.md` 是关键——这是**整篇论文里所有数字的唯一真源**：

```markdown
## Setup
- Backbone: ResNet-50 (ImageNet pretrained)
- Datasets: CIFAR-100, ImageNet-1k
- Optimizer: AdamW, lr=1e-4, weight_decay=0.05

## Results — Table 1: Main comparison
| Method     | CIFAR-100 (acc) | ImageNet (acc) |
|------------|----------------:|---------------:|
| Baseline   | 76.2            | 75.1           |
| +OurMethod | **78.9**        | **76.4**       |

## Ablation — Table 2: ...
...

## Qualitative observations
- The method was particularly effective on rare classes (>40% improvement
  on classes with <50 training samples).
- Failure mode: ...
```

### 2.2 输出

40 分钟后：

```
final/
├── paper.tex                        # 投稿级 LaTeX
├── paper.pdf                        # 已编译 PDF
├── refs.bib                         # 全部经 S2 校验的引用
├── figures/                         # 全部生成的图（含 caption）
│   ├── fig1_method.png              # 概念图（PaperBanana）
│   ├── fig1_method.txt              # caption
│   ├── fig2_main_results.pdf        # 数据图（matplotlib）
│   └── ...
└── provenance.json                  # 输入哈希 + 最终输出哈希（社区实现增强）
```

---

## 3. 5-agent 架构详解

```
inputs/                                  ← 用户提供
   │
   ▼
┌────────────────────────────────────────────────┐
│ Step 1: Outline Agent                          │
│ - 一次 LLM 调用                                 │
│ - 读 idea + log + template + guidelines        │
│ - 输出 outline.json                            │
│   {                                            │
│     "plotting_plan": [...],                    │
│     "macro_lit_search": [...],                 │
│     "micro_lit_clusters": [...],               │
│     "section_plan": [                          │
│       {"section": "Method",                    │
│        "citation_hints": ["Adam", "ResNet"]},  │
│       ...                                      │
│     ]                                          │
│   }                                            │
└────────────────────┬───────────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼   并行                  ▼   并行
┌─────────────────────┐  ┌─────────────────────────┐
│ Step 2: Plotting    │  │ Step 3: Literature      │
│ ~20–30 LLM 调用     │  │   Review                │
│                     │  │ ~20–30 LLM 调用          │
│ 数据图：             │  │                         │
│  matplotlib 微服务   │  │ 1. 10 路并发 web 搜索    │
│  从 log 抽数字       │  │    (Gemini-3-Flash)     │
│  booktabs LaTeX 表   │  │ 2. Semantic Scholar    │
│                     │  │    验证 (1 QPS 串行)：   │
│ 概念图：             │  │    - Levenshtein ≥ 0.7  │
│  PaperBanana        │  │    - 时间截断           │
│  (扩散 + VLM 评)    │  │    - paperId 去重       │
│                     │  │ 3. 起草 Intro + RW      │
│ Caption: LLM 生成    │  │ 4. ≥ 90% 检索池强制      │
│                     │  │    出现在正文           │
│ → figures/          │  │                         │
│   captions.json     │  │ → refs.bib              │
│                     │  │ → drafts/intro_rw.tex   │
└──────────┬──────────┘  └────────────┬────────────┘
           │                          │
           └────────────┬─────────────┘
                        ▼
        ┌─────────────────────────────────────┐
        │ Step 4: Section Writing             │
        │ 1 次多模态 LLM 调用                  │
        │ - 读 outline + figures + bib + log  │
        │ - 写 abstract / 方法 / 实验 / 结论    │
        │ - 实验数字从 log 直接拷贝            │
        │ - 表格 booktabs 风格                 │
        │ - 嵌入图片占位 + caption             │
        │ → drafts/paper.tex                  │
        └────────────────┬────────────────────┘
                         ▼
        ┌─────────────────────────────────────┐
        │ Step 5: Content Refinement          │
        │ ~5–7 LLM 调用，最多 3 轮             │
        │ - AgentReview 模拟同行评审           │
        │ - 单调收敛接受准则：                 │
        │   分数严格上升 OR 平局且子项无负退化  │
        │ - 不达标就 revert 到上版              │
        │ → final/paper.tex                   │
        └─────────────────────────────────────┘
```

下面拆每个 agent。

### 3.1 Outline Agent（Step 1）

**1 次 LLM 调用，但是这次是整个流水线最关键的一步。**

- **输入**：4 份文件（idea / log / template / guidelines）拼成一个长 prompt。
- **输出**：一个**结构化 JSON** outline，里面包含：
  - `plotting_plan`：每张图的 figure_id、类型（empirical / conceptual）、source data、design objective。
  - `macro_lit_search`：给 Introduction 用的"宏观语境"检索查询（领域全景）。
  - `micro_lit_clusters`：给 Related Work 用的"微观方法簇"检索查询（按 method 类型分簇）。
  - `section_plan`：每个 section 的写作计划，**外加 citation_hints 字段**——明确指出"这一段要提到 dataset X、optimizer Y、baseline Z，对应的引文要分别引到哪类文献"。

> **`citation_hints` 是整个 PaperOrchestra 最被低估的设计**。它把"要引什么"的决策**前置到大纲阶段**，而不是写正文时再补。这意味着：
>
> 1. Step 3 检索时已经知道 Step 4 要引什么类型的文献，可以精确定向；
> 2. Step 4 写正文时不会有"想引但找不到"的窘境；
> 3. ≥ 90% 的引用强制覆盖率有了出处——大纲就规定了这些引用必须出现。

### 3.2 Plotting Agent（Step 2，与 Step 3 并行）

Plotting Agent 处理两类截然不同的图，**用了完全不同的工程路径**：

#### 3.2.1 数据图（empirical plots）

- 来源：experimental_log 里的真实数字。
- 实现：通过一个 Python 微服务（matplotlib 等）渲染。
- **关键约束**：metric 直接从 log 抽，**不允许 LLM 改写或重算**。
- 表格用 booktabs 标准 LaTeX。

社区实现里 `extract_metrics.py`、`render_matplotlib.py` 是确定性脚本——LLM 只生成 plot spec（JSON 描述），具体渲染是机械执行。这种"LLM 出意图、脚本出像素"的拆分让 figure 的可信度可审计。

#### 3.2.2 概念图（conceptual diagrams）

- 实现：调外部独立工作 **PaperBanana**（[Zhu et al., 2026](https://github.com/dwzhu-pku/PaperBanana)）。
- PaperBanana 自己是一个 5-agent 系统：
  - **Retriever**：从精选参考图库里挑结构相似的范例（按"图的结构和类型"匹配，不是按主题相似度）。
  - **Planner**：把方法内容 + 沟通意图翻译成详细文字描述（in-context learning）。
  - **Stylist**：套上从参考图库自动合成的"学术美学指南"。
  - **Visualizer**：把文字描述送给图像生成模型（扩散）出图。
  - **Critic**：VLM 评图——评价语义和视觉是否符合目标，反馈给 Planner 重写描述。
- **默认迭代 3 轮**（Visualizer ↔ Critic 闭环）。
- PaperBanana 自己的 benchmark：**PaperBananaBench, 292 个 NeurIPS 2025 方法图**。
- **Stylist 的副作用**：实验显示它提升 conciseness 和 aesthetics，但**轻微伤害 faithfulness**（为了好看会省略技术细节）；Critic 在迭代里把 faithfulness 找回来——这是个反复出现的"美 vs 准"平衡。
- 主要失败模式：**连接错误**（连错节点或多余连接），Critic 经常识别不到——是 foundation model 的盲区。

#### 3.2.3 Caption

- LLM 直接根据每张图的 design objective + source data 单独生成。

### 3.3 Literature Review Agent（Step 3，与 Step 2 并行）

这是最工程化的一步：**LLM 出意图、API 出真理**。

```python
# 伪代码
for query in outline.macro_lit_search + outline.micro_lit_clusters:
    # 步骤 1：10 路并发 LLM web search
    candidates = parallel_web_search(query, n=10, model="gemini-3-flash")
    # 每路返回 5-10 个候选标题

    # 步骤 2：Semantic Scholar 校验（1 QPS 串行）
    for title in candidates:
        s2_paper = semantic_scholar_search(title)
        if s2_paper is None:
            drop(title)  # 编的，丢
        elif levenshtein(title, s2_paper.title) < 0.7:
            drop(title)  # 不匹配，丢
        elif s2_paper.year > submission_cutoff:
            drop(title)  # 时间不对，丢
        elif s2_paper.paperId in seen_ids:
            drop(title)  # 已有，丢
        else:
            citation_pool.add(s2_paper)

# 步骤 3：起草 Intro + Related Work
intro_rw = llm.draft(outline.section_plan, citation_pool)

# 步骤 4：硬约束 — 强制 ≥ 90% 池子内的文献出现在 intro_rw
assert citation_coverage(intro_rw, citation_pool) >= 0.90
```

**为什么用 Levenshtein 0.7 而不是精确匹配**：LLM 经常把标题轻微改写（比如改大小写、改连字符）。0.7 既能容错也不会误纳。社区实现里有个 `--substring-bypass` 软覆盖，处理 Linformer 这类短标题的 false-negative case——这是论文没解决的边角。

**为什么 ≥ 90% 强制引用率**：防止 LLM 编一长串"装样子"的 bib 但正文不引。这是 review 时最容易被察觉的造假特征。

**discovery 并行 + verification 串行**：S2 公共 endpoint 限制 1 QPS，硬性约束。

### 3.4 Section Writing Agent（Step 4）

**只有 1 次 LLM 调用，但是这次是多模态调用——同时输入文字 outline + 图片 figures + bib + 实验 log。**

输出整篇论文的剩余部分（除了 Step 3 已经写好的 Intro + Related Work）：abstract / 方法 / 实验 / 结论。

**关键约束**：
- **数字直接拷贝**：从 experimental_log 抽数字到正文表格，**不让 LLM 改写或重新计算**。
- **图片占位 + caption**：把 Step 2 生成的图按 figure_id 嵌入正文。
- **booktabs 表格风格**。
- **强制每个 `\cite{KEY}` 在 refs.bib 里有定义**（社区实现的 `orphan_cite_gate.py` 机械检查）。

### 3.5 Content Refinement Agent（Step 5）

**用 [AgentReview](https://aclanthology.org/2024.emnlp-main.359/)（Jin et al., EMNLP 2024）当 quality gate**——AgentReview 自己是一个用 LLM 模拟同行评审的独立系统。

迭代逻辑（论文里写得很硬）：

```
for iter in 1..3:
    snapshot(paper.tex → iter{iter}/paper.tex)   # 物理拷贝，不是符号
    review = AgentReview(paper.tex)
    new_paper = llm.revise(paper.tex, review.feedback)
    new_review = AgentReview(new_paper)

    # 单调收敛接受准则
    if new_review.overall > review.overall:
        accept(new_paper)                         # 严格上升
    elif new_review.overall == review.overall \
         and net_subaxis_delta(new_review, review) >= 0:
        accept(new_paper)                         # 平局且子项非负退化
    else:
        revert(paper.tex ← iter{iter}/paper.tex)  # 真物理 revert
```

**这条单调收敛规则是整个系统的"安全阀"**——防止 refinement 越改越差。如果 LLM 拍脑袋"把这一段写得更花哨"导致整体分数跌了，立即 revert。

社区实现里 `score_delta.py` + `snapshot.py` 把这条规则机械化：snapshot 是真实文件拷贝，revert 是真实文件回滚——不是 in-memory 的 if-else。

---

## 4. 关键支撑组件（外部依赖）

PaperOrchestra 不是自给自足，它依赖三个**独立的、可单独引用**的外部工作：

| 组件 | 作者 | 用途 | 论文 |
|------|------|------|------|
| **PaperBanana** | Zhu et al., 2026 (PKU) | 概念图生成（Step 2 后端） | [github.com/dwzhu-pku/PaperBanana](https://github.com/dwzhu-pku/PaperBanana) |
| **AgentReview** | Jin et al., EMNLP 2024 | 模拟同行评审（Step 5 quality gate） | [aclanthology.org/2024.emnlp-main.359](https://aclanthology.org/2024.emnlp-main.359/) |
| **Semantic Scholar API** | Allen AI | 文献校验（Step 3 verification） | [api.semanticscholar.org](https://api.semanticscholar.org/) |

这种**"组件即论文"的依赖设计**很值得借鉴——它让 PaperOrchestra 的每一步都可以单独被换、被审计、被改进，而不是一个不透明的 monolith。

---

## 5. PaperWritingBench：评测设计

200 篇 seed 论文：

| 来源 | 数量 | 排版 |
|------|------|------|
| CVPR 2025 接收论文 | 100 | 双栏 |
| ICLR 2025 接收论文 | 100 | 单栏 |

**关键设计选择**：故意选两个排版不同的会议，强迫系统适配不同 LaTeX 模板，避免"只能写某种格式"的过拟合。

**反向工程过程**（这是 benchmark 的精髓）：

```
对每篇接收论文 P:
  1. 抽取 P 的 figure 和 raw 数字
  2. 反向写 idea.md（推测作者写论文前可能有的 idea summary）
  3. 反向写 experimental_log.md（推测作者跑实验后可能有的 log）
  4. 提取 P 的会议 LaTeX 模板和 guidelines
  5. ★ 关键：擦除所有作者身份信息和引用信息 ★
  6. 把 (idea, log, template, guidelines) 喂给系统
  7. 把生成的论文与 P 对比
```

**为什么要擦除作者身份和引用**：防止系统通过 pretraining 记忆"哎我见过这篇"而走捷径。这条**强制评估的是真正的"合成 + 校验"能力，不是检索 + 模仿**。

但作者也老实承认（论文 §6）：**Anti-Leakage Prompting 不能保证消除预训练数据泄漏**——这是个"我们尽力但解决不了"的开放问题。

---

## 6. 评测结果（关键数字）

### 6.1 评测裁判

| 类型 | Judges |
|------|--------|
| 自动 | AgentReview、Gemini-3.1-Pro、ScholarPeer、GPT-5 |
| 人工 | 11 位 AI 研究者，180 对论文 paired comparison |

### 6.2 综合质量（Overall Paper Quality）

| 对比 | 指标 | 结果 |
|------|------|------|
| vs Single Agent | 自动 SxS | **+52% 至 +88%** |
| vs AI Scientist v2 | 自动 SxS | **+39% 至 +86%** |
| vs AI baselines | 人评胜率 | **+14% 至 +38%** |
| vs 人类原作 | 人评 lit 综合 | **43% 平/胜**（人类自然占多） |

### 6.3 文献综述质量（Lit Review Quality）

| 系统 | 自动 (Gemini-3.1-Pro judge) |
|------|----------:|
| Single Agent | 43% |
| AI Scientist v2 | 45% |
| **PaperOrchestra** | **78%** |

人评下 PaperOrchestra 比 baseline **+50% 到 +68%**（绝对胜率 margin）。

### 6.4 引用准确性（Citation F1，CVPR）

| 系统 | F1 | P1 Recall（"good-to-cite" 文献） |
|------|---:|---:|
| Single Agent | 28.0% | ~3% |
| AI Scientist v2 | 17.2% | ~3% |
| **PaperOrchestra** | **29.7%** | **~16%** |

**P1 Recall 提升 5×** 是最有说服力的数字——baseline 系统只引"必引"（P0）文献，而 PaperOrchestra 真正覆盖了"该引"的更广文献池。

### 6.5 引用数量

| 系统 | 平均引用数 |
|------|---:|
| AI baselines | 9.75–14.18 |
| **PaperOrchestra** | **45.73–47.98** |
| 人类原作 | ~59 |

PaperOrchestra 接近人类引用密度，baseline 系统差一个数量级。

### 6.6 Refinement 收益

| 指标 | refine 前 | refine 后 | Δ |
|------|---:|---:|---:|
| CVPR 模拟接受率 | — | — | **+19%** |
| ICLR 模拟接受率 | — | — | **+22%** |

---

## 7. 7 个值得抄的工程决策

按重要性排：

### 7.1 Outline 阶段就标好 citation hints

把"要引什么类型的文献"决策**前置到大纲**，让后续 retrieval 和 writing 都有靶子。这是为什么 PaperOrchestra 能做到 ≥ 90% 引用整合率，而不会出现 baseline 那种"想到就引、引不到就编"的局面。

### 7.2 ≥ 90% 强制引用率

机械约束：池子里的文献必须真出现在正文里。**直接砍死了"装样子的 bib"** 这一类假阳性 citation 行为。

### 7.3 Levenshtein 0.7 + 时间截断 + S2 paperId 去重的三重 verification

每条引用过三道关：相似度（防 LLM 编标题）、时间（防引用未来论文）、去重（防同一篇重复入池）。**Levenshtein 0.7 的取值是个工程经验**——精确匹配会误杀，0.5 会误纳。

### 7.4 单调收敛 refinement

Step 5 的 accept-or-revert 规则是整个流水线最反"LLM 暴走"的设计。LLM 改一版必须**严格不退化**才能接受，否则物理 revert 文件——不是 in-memory 的"如果不好就忽略"，而是真的把 .tex 拷回去。

### 7.5 数字从 log 拷贝、不让 LLM 算

实验数字从 experimental_log 机械抽取到正文表格。这是 PaperOrchestra 和 CycleResearcher 的根本区别——前者拒绝让 LLM 改 metric，后者直接让 LLM 编 metric。

### 7.6 Anti-Leakage Prompting

每个 agent 都有"防止跨 agent 输出污染"的 prompt 约束。但作者**老实承认这只是 aspirational**——pretraining 数据泄漏不能保证消除。社区实现额外加了 `anti_leakage_check.py` 这种**机械 grep**（搜作者名、邮箱、所属机构）作为补强。

### 7.7 物理 snapshot + 物理 revert

Step 5 的每一轮 refinement 都做物理文件拷贝，revert 是真把文件回滚。在 LLM 系统里这是少见的"敢用文件系统状态、不全靠 in-memory"的设计——好处是出问题可以 git diff 调。

---

## 8. 社区实现 [Ar9av/PaperOrchestra](https://github.com/Ar9av/PaperOrchestra)

> 327★ / 41 fork（2026-04 持续更新）。这是 PaperOrchestra 在工程社区的**事实标准实现**——比 Google 自己的官方代码（暂未开源）影响力更大。

### 8.1 核心设计哲学

社区实现做了一个**和原论文不同的工程取舍**：**不嵌入 LLM SDK、不要求 API key**——把 LLM 推理全部委托给宿主 coding agent（Claude Code / Cursor / Antigravity / Cline / Aider / OpenCode）。

| 角色 | Google 官方思路 | Ar9av 社区实现 |
|------|----------------|---------------|
| LLM 推理 | 直接调 Vertex AI（Gemini-3.1-Pro） | 让宿主 agent 用自己的模型 |
| Web 搜索 | 直接调 Google 搜索 | 用宿主的 web search 工具 |
| API 凭证 | 必须配置 Google Cloud 凭证 | **零 API key 也能跑** |
| 适用范围 | 锁定 Google 生态 | 任何带 LLM + web 工具的 agent |

**理由**（社区文档原话）：

> 1. **Pluggability**: A coding agent already has an LLM (its own).
> 2. **Security**: No API keys means no secret management.
> 3. **Honesty**: 确定性部分（Levenshtein、dedup、citation gates、BibTeX 格式、JSON schema 校验）容易复刻、永不出错；不确定部分（写作、搜索、判断）属于宿主 LLM。**装作能"包装 LLM 让它确定"是骗自己**。

### 8.2 Skill 包结构

```
skills/
├── paper-orchestra/                  # orchestrator
├── outline-agent/                    # Step 1
├── plotting-agent/                   # Step 2
├── literature-review-agent/          # Step 3
├── section-writing-agent/            # Step 4
├── content-refinement-agent/         # Step 5
├── paper-writing-bench/              # §3 评测 harness
├── paper-autoraters/                 # App. F.3 autoraters
└── agent-research-aggregator/        # 额外的 pre-pipeline 工作（见 8.4）
```

每个 skill 都是：
- `SKILL.md`：宿主 agent 读的指令文档（含 YAML frontmatter + TRIGGER 子句让 skill loader 自动调用）。
- `references/`：原论文 Appendix F 的逐字 prompt + JSON schema + rubric + halt rule。
- `scripts/`：**纯确定性** Python 助手（无网络、无 LLM、无 API key）。

### 8.3 「确定性 vs 委托」严格分线

社区实现最有教育意义的部分是这张分线表：

| 关注点 | 委托给宿主 LLM | 确定性脚本 |
|--------|---------|---------|
| 把输入合成大纲 | ✓ outline-agent SKILL.md | — |
| Outline schema 校验 | — | `validate_outline.py` |
| 候选论文 web 搜索 | ✓ literature-review-agent SKILL.md | — |
| 标题模糊匹配 (Levenshtein) | — | `levenshtein_match.py` |
| 时间截断比较 | — | `check_cutoff.py` |
| 按 S2 paperId 去重 | — | `dedupe_by_id.py` |
| BibTeX 条目格式化 | — | `bibtex_format.py` |
| ≥ 90% 引用覆盖检查 | — | `citation_coverage.py` |
| 起草 Intro + Related Work | ✓ literature-review-agent SKILL.md | — |
| 生成 matplotlib 代码 | ✓ plotting-agent SKILL.md | — |
| 渲染 JSON plot spec | — | `render_matplotlib.py` |
| VLM 评图 | ✓ plotting-agent SKILL.md（宿主 vision） | — |
| 单次多模态 section 写作 | ✓ section-writing-agent SKILL.md | — |
| 从 markdown 表格抽 metric | — | `extract_metrics.py` |
| LaTeX 大括号/环境 sanity | — | `latex_sanity.py` |
| Orphan-cite gate | — | `orphan_cite_gate.py` |
| Anti-leakage grep | — | `anti_leakage_check.py` |
| 模拟同行评审 | ✓ content-refinement-agent SKILL.md | — |
| Accept/revert 决策 | — | `score_delta.py` |
| Worklog 追加 | — | `apply_worklog.py` |
| 迭代 snapshot | — | `snapshot.py` |
| Citation F1 计算 | — | `compute_f1.py` |
| LitReview Quality 评分 | ✓ paper-autoraters SKILL.md | — |

**这张分线表本身就是研究"agent 系统应该怎么切分确定性边界"的范本**——任何在做 agentic 工程的人都该读一遍。

### 8.4 `agent-research-aggregator`：上游接口

社区实现额外做的一个**论文里没有的 skill**：把"散落在 Claude Code / Cursor / Antigravity / OpenClaw 等 coding agent 缓存里的实验记录"自动整合成 PaperOrchestra 需要的 `idea.md` + `experimental_log.md`。

```
[.claude/]  [.cursor/]  [.antigravity/]  [.openclaw/]
      │            │              │               │
      └────────────┴──────────────┴───────────────┘
                        │
       Phase 1: Discovery  (deterministic)
       Phase 2: Extraction (LLM — per batch, ~50 KB)
       Phase 3: Synthesis  (LLM — one call)
       Phase 4: Formatting (deterministic)
                        │
             ┌──────────┴──────────┐
      workspace/inputs/      workspace/ara/
        idea.md                aggregation_report.md
        experimental_log.md    discovered_logs.json
                               raw_experiments.json
                               synthesis.json
```

**为什么这个有意义**：研究者用 Claude Code / Cursor 跑实验时，完整的实验过程其实**已经在 agent 缓存里了**——但格式太散，没法直接拿去写论文。这个 aggregator 做了 PaperOrchestra 不愿意做的"前一步脏活"。

实战意义：**研究者可能根本不需要写 experimental_log.md，agent 历史就是 log**。

### 8.5 论文外的工程加固

社区实现明确标注了**对论文的额外加固**（在 `docs/paper-fidelity.md` 里逐项列出）：

| 脚本 | 用途 | 为什么加 |
|------|------|----------|
| `anti_leakage_check.py` | grep 最终稿里的作者名、邮箱、所属机构 | 论文的 Anti-Leakage Prompt 是 aspirational，这是机械 enforcement |
| `orphan_cite_gate.py` | 每个 `\cite{KEY}` 必须在 refs.bib 里有 entry | Section Writing prompt 要求这个，这里机械执行 |
| `citation_coverage.py` | ≥ 90% 引用整合率检查 | App. D.3 规定，这里机械执行 |
| `snapshot.py` | 物理拷贝 paper.tex | halt 规则需要真 rollback，不是符号 |
| `provenance.json` | 输入和最终输出的哈希 | 复现性，论文外 |
| `levenshtein_match.py --substring-bypass` | 短候选标题的软覆盖 | 处理论文没解决的 Linformer false-negative |

**这些是加分项，删掉任何一个仍然是忠实的 PaperOrchestra 实现**——但加上让实现在实践中更鲁棒。

---

## 9. 局限与开放问题

作者在论文 §6 自己列了几条：

### 9.1 Pretraining 数据泄漏不能保证消除

Anti-Leakage Prompting 是缓解，不是根除。在 PaperWritingBench 上系统可能"碰巧"记住过 seed 论文——这是个**评测真实性的边界条件**。社区实现的 `anti_leakage_check.py` 是缓解之一，但仍是治标。

### 9.2 PaperBanana 的 connection 错误

概念图里"连错节点 / 多余连接"的失败模式 Critic 检测不到——是 foundation model 盲区。这是**整个系统最薄弱的一环**：表格和数据图的可靠性靠确定性脚本保证，但概念图的语义正确性目前只能靠人审。

### 9.3 不写综述、不跑实验、不 ideate

PaperOrchestra 明确把作者身份让给人——它不写综述（A 类范畴）、不跑实验（B 类范畴）、不生成 idea。**它的 score 优势是建立在"已经有真实素材"的基础上的**，这一点放回到"AI 是否能独立做研究"的问题上是回避而非回答。

### 9.4 仅在 ML 领域验证

PaperWritingBench 只覆盖 CVPR + ICLR。其他领域（生物、物理、社科）的有效性未知，作者承认是 future work。但论文也指出**框架本身领域无关**——"applicable beyond AI to any scientific domain where research notes and results must be authoritatively synthesized"。

### 9.5 时间和成本

39.6 分钟、60–70 次 LLM 调用、每次 Gemini-3.1-Pro 不便宜——按 Vertex AI 定价单次跑约 $1–$3。**比 Sakana v2 的 $6–$15 单篇便宜，但比 Deep Research 单次（< $1）贵**。

---

## 10. 与其他工作的关系

```
颗粒度：细  ────────────────────────────────────────────────────────  粗
       ▲                                                              ▲
   LLM4Papers     Cursor/Copilot     ★ PaperOrchestra ★    Sakana v2
   (单行替换)     (整段补全)         (整篇起草)            (论文 + 实验)

                  非自治 ◄────────────────────► 自治
```

| 维度 | LLM4Papers | PaperOrchestra | Sakana v2 |
|------|------------|----------------|-----------|
| 跑实验 | ❌ | ❌ | ✅ |
| 写整篇 | ❌（局部） | ✅ | ✅ |
| 真实数字 | n/a（不动数字） | **从用户 log 抽** | LLM 跑实验产出 |
| Hallucination 风险 | 局部、可见 | 引用层（可校验）+ 表达层 | 全方位（含数字层） |
| 用户责任 | 完全保留 | 完全保留 | 模糊 |
| ICLR 接收记录 | n/a | n/a（不用投） | 1/3（v2 那次实验） |

**关键观察**：PaperOrchestra 在自动 SxS 上把 v2 打了 +39~86%——这暗示 **v2 的"写作"环节是它最弱的一环**（v2 强在 BFTS 跑实验）。如果把 v2 的"做研究"和 PaperOrchestra 的"写论文"拼起来——v2 做实验、PaperOrchestra 写——可能比 v2 自己写效果好得多。**这是 2026 下半年 / 2027 年的明显 follow-up 方向**。

---

## 11. 借鉴到 PathLab 的具体路径

PathLab 的场景**天然就是 C 类**：医生 / pipeline 已经做完所有"实验"（病理图像、模型推断、survival metric、heatmap），AI 只负责把它们组织成可读的报告。

### 11.1 5-agent 重映射

| PaperOrchestra agent | PathLab 重映射 | 关键约束 |
|----------------------|----------------|---------|
| Outline Agent | 报告骨架生成（病人信息 / 标本描述 / 显微所见 / AI 模型推断 / 结论 / 参考文献） | 模板化，按报告类型选骨架 |
| Plotting Agent | DZI thumbnail / heatmap overlay / KM 曲线 | **数字直接从 case 数据库取，绝不让 LLM 改写 metric** |
| Literature Review Agent | 病理领域 literature retrieval（PaperQA2 风格 + PathLab 已有 PDF RAG + PubMed/S2 校验） | **Levenshtein 校验 + DOI 校验防止编造引用** |
| Section Writing Agent | 自然语言部分（镜下所见、推断结论的解释） | 数字 / 分级 / 分期 全部机械抽取，**LLM 只动自然语言** |
| Content Refinement Agent | 多维自检：事实一致性 / 引用支撑 / 临床表述合规 / 病理术语规范 | 单调收敛、不达标 revert |

### 11.2 必须直接搬过来的工程实践

1. **citation hints 前置**：报告大纲阶段就标"这一段需要引哪类临床指南 / 文献"。
2. **数字机械抽取**：grade、stage、metric、概率值全部从 case 数据库 pin-point 取，LLM 只能引用、不能改写。
3. **≥ X% 强制引用率**：根据报告类型（诊断 / 治疗建议）调整阈值，但**机械检查必须有**。
4. **单调收敛 refinement**：任何 AI 改动必须有外部 anchor 评分，**不能让 LLM 自己决定何时停**。
5. **物理 snapshot**：每一轮改动都留版本，方便审计和回滚——医疗合规场景下这是必需而非可选。
6. **Anti-leakage**：报告里不能出现"在训练集里见过的"案例 ID、患者姓名、机构信息——必须有机械 grep。

### 11.3 一定要避开的坑

- ❌ **不要用统一 prompt 锁死风格**（LLM4Papers 那种"nature neuroscience 风格"），改成按报告类型动态拼。
- ❌ **不要让 LLM 决定该引哪些文献**（pretraining 记忆里的医学事实风险太高），必须接 PathLab 已有 PDF RAG + 外部医学数据库校验。
- ❌ **不要照搬 39.6 分钟的端到端时间**——病理报告对实时性要求高，要做并行 + 分段流式。

### 11.4 起步方式

社区实现 [Ar9av/PaperOrchestra](https://github.com/Ar9av/PaperOrchestra) 已经把全部 prompt + JSON schema + 确定性脚本开源了，**可以直接 fork 改**：

1. 把 `outline-agent` 的输出 schema 改成病理报告骨架。
2. 把 `literature-review-agent` 的 S2 endpoint 改成 PubMed / 医学指南 corpus。
3. 把 `section-writing-agent` 的 prompt 改成病理报告风格。
4. 把 `content-refinement-agent` 的 review rubric 改成临床合规多维表。
5. 保留 `orphan_cite_gate.py` / `citation_coverage.py` / `anti_leakage_check.py` / `snapshot.py` 这几个机械检查脚本——它们和领域无关，是通用工程加固。

---

## 12. References

### 主资源

- Song, Y., Song, Y., Pfister, T., Yoon, J. *PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing*. [arXiv:2604.05018](https://arxiv.org/abs/2604.05018), Google Cloud AI Research, 2026-04.
- 项目页：[yiwen-song.github.io/paper_orchestra](https://yiwen-song.github.io/paper_orchestra/)
- 社区实现（事实标准）：[Ar9av/PaperOrchestra](https://github.com/Ar9av/PaperOrchestra)（327★，2026-04 持续更新，零 API key）
- 社区文档亮点：[`docs/architecture.md`](https://github.com/Ar9av/PaperOrchestra/blob/main/docs/architecture.md)、[`docs/paper-fidelity.md`](https://github.com/Ar9av/PaperOrchestra/blob/main/docs/paper-fidelity.md)

### 外部依赖（独立工作）

- Zhu et al. *PaperBanana: Automating Academic Illustration For AI Scientists*. 2026. [github.com/dwzhu-pku/PaperBanana](https://github.com/dwzhu-pku/PaperBanana)，[项目页](https://dwzhu-pku.github.io/PaperBanana/)
- Jin et al. *AgentReview: Exploring Peer Review Dynamics with LLM Agents*. EMNLP 2024. [aclanthology.org/2024.emnlp-main.359](https://aclanthology.org/2024.emnlp-main.359/)
- Semantic Scholar API: [api.semanticscholar.org](https://api.semanticscholar.org/)

### 相关二次报道

- [MarkTechPost: Google AI Research Introduces PaperOrchestra](https://www.marktechpost.com/2026/04/08/google-ai-research-introduces-paperorchestra-a-multi-agent-framework-for-automated-ai-research-paper-writing/)
- [Inside Google's PaperOrchestra (Sharing Science)](https://medium.com/a-microbiome-scientist-at-large/paperorchestra-5ebb1f6e0b16)
- [emergentmind paper page](https://www.emergentmind.com/papers/2604.05018)
- [alphaXiv overview](https://www.alphaxiv.org/overview/2604.05018)
- [Nerd Level Tech: Google's 5-Agent AI Writes Research Papers](https://nerdleveltech.com/paperorchestra-google-multi-agent-ai-writes-research-papers)

### 引用本文的位置

- [`paper-generation-survey.md`](paper-generation-survey.md) §0 TL;DR、§1 边界图、§2.5 写作自动化、§8 横评表、§9.3 PathLab 借鉴、§10 References
- [`llm4papers.md`](llm4papers.md) §6 产品形态光谱、§8 借鉴到 PathLab
