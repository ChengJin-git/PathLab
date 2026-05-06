# 自动科研项目文章生成机制对比

> Source: [https://app.notion.com/p/353a952ab13d810f94affb7aad22cf1a](https://app.notion.com/p/353a952ab13d810f94affb7aad22cf1a)
> Exported from Notion API: 2026-05-02

---

整理时间：2026-05-01。重点关注文章生成，不展开一般 AI 写作工具。

## 核心判断

- 如果目标是文章生成，PaperOrchestra 最值得拆：它不冒险自动做实验，而是把已有 idea summary 和 experimental log 写成 submission-ready LaTeX manuscript。
- AI-Scientist-v2、Agent Laboratory、AI-Researcher 更偏“自动科研”：文章生成只是 research pipeline 的最后一步。
- SurveyX、InteractiveSurvey 更适合综述生成，核心问题是文献覆盖、结构组织和引用质量。
- 真正落地时，建议把“实验/证据生成”和“论文写作”分层，避免模型为了写得好而夸大结果。
## 核心对比表

| 项目 | 生成范式 | 输入 | 文章生成流程 | 引用/证据处理 | 输出 | 强项 | 主要短板 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AI-Scientist-v2 | 自主科研 -> 写论文 | 研究方向、配置、模型/API、GPU 环境 | 生成 hypothesis -> agentic tree search 规划实验 -> 写/跑代码 -> 分析结果 -> 写 manuscript | Semantic Scholar 做 literature search、novelty/citation；可跳过 citation phase | 代码、实验结果、论文草稿/LaTeX | 最接近全自动科研，能自己探索实验路径 | 成功率不稳定；论文质量不一定高；会执行 LLM 写的代码，有安全和复现风险 |
| Agent Laboratory | 人类给 idea，Agent 做研究助理 | 人类研究想法、配置、数据/任务 | Literature Review -> Experimentation -> Report Writing；paper-solver 从实验结果和代码写报告 | 用 arXiv/外部检索做文献综述；引用质量依赖检索和人工反馈 | research report、代码仓库 | 流程清晰，适合“我有 idea，让 Agent 帮我实现+写报告” | 更偏 ML 实验助理；最终论文需要人工强审 |
| AI-Researcher | 自主科研系统 | idea/prompt、参考论文、实验环境 | research agent 负责想法和实验，paper agent 负责组织论文文本 | 依赖参考论文和检索；强调 benchmark/evaluation | 代码、实验结果、论文/报告 | research agent 和 paper agent 分离，便于改造 | 项目较重；内容质量强依赖输入 prompt 和实验可执行性 |
| PaperOrchestra | 已有研究材料 -> submission-ready paper | idea summary、experimental log、LaTeX template、venue guideline | Outline Agent -> Plotting Agent -> Literature Review Agent -> Section Writing Agent -> Content Refinement Agent | Literature Review Agent 做 web search，并用 Semantic Scholar 验证候选论文，构建 citation graph | 完整 LaTeX manuscript、表格、图、概念图、PDF | 最专注文章生成；从零散实验记录写成完整论文的设计最好 | 不负责真正做实验；官方主要是论文/项目页，开源可看社区实现 |
| Ar9av/PaperOrchestra | PaperOrchestra 社区 skill 实现 | idea.md、experimental_log.md、模板、指南 | 按 PaperOrchestra 五阶段拆成 skills；aggregator 可把散乱 agent 记录整理成输入 | BibTeX、去重、Levenshtein 校验、coverage gate、LaTeX sanity check | LaTeX paper | 适合研究 PaperOrchestra 的可执行流程；能接 Claude Code/Cursor 等 coding agent | 非官方实现；质量取决于宿主 agent 和搜索能力 |
| SurveyX | 自动综述生成 | 标题、关键词、本地 Markdown 参考文献；完整版有在线检索 | 文献处理 -> outline -> content generation -> post refine -> LaTeX generation | 开源离线版只能基于上传参考文献；完整版有检索、过滤、文献库 | survey.pdf、LaTeX、outline JSON | 综述生成流程完整，能直接出 PDF | 开源版缺在线搜索和多模态解析；更适合 survey，不适合实验论文 |
| InteractiveSurvey | 交互式综述生成 | 用户主题、偏好、交互反馈 | 生成初始综述 -> 用户交互调整方向/结构 -> 个性化内容生成 | 偏个性化文献组织；依赖检索和用户反馈 | survey/report | 人在环，适合边探索边写综述 | 自动化程度低于全自动系统；不是实验论文 writer |
| Open Academic Paper Machine | Claude Code 插件式论文流水线 | 题目/研究主题 | Idea Evaluation -> Reconnaissance -> Framing -> Structure -> Production -> Assembly -> LaTeX/PDF -> Verification -> Revision | citation verification、paper-vs-code audit、source check | arXiv-style LaTeX/PDF | 工程化，覆盖搜索-写作-排版-核查-修订全链路 | 更像工具链/插件实验，学术基准弱于 PaperOrchestra/AI-Scientist |

## 文章生成机制拆解

| 阶段 | AI-Scientist-v2 | Agent Laboratory | AI-Researcher | PaperOrchestra | SurveyX / InteractiveSurvey |
| --- | --- | --- | --- | --- | --- |
| 研究想法 | 自动生成/筛选 hypothesis | 人类给 idea 为主 | 人类 prompt + agent 扩展 | 已有 idea summary，不负责发明研究 | 用户给主题/关键词 |
| 文献检索 | Semantic Scholar，用于 novelty 和 citation | arXiv/外部检索做 literature review | 参考论文 + 检索 | Literature Review Agent 专门检索，并验证引用 | 文献库/上传文献/在线版检索 |
| 实验执行 | 自动写代码、跑实验、分析 | mle-solver 写/改 ML 代码，迭代实验 | research agent 做实验实现 | 不做实验，只消费 experimental log | 不做实验 |
| 论文大纲 | 根据实验树和结果生成 | 报告写作阶段生成 | paper agent 生成 | Outline Agent 生成结构化 outline | 先生成 survey outline |
| 正文生成 | 根据实验和发现写 manuscript | paper-solver 从 code/results 写 report | paper agent 写论文 | Section Writing Agent 写完整 LaTeX sections | 分章节生成综述内容 |
| 图表生成 | 基于实验结果生成图表 | 根据实验结果整理图表 | 基于实验产物 | Plotting Agent 生成统计图和概念图 | 主要是文本和 LaTeX，开源版图像能力有限 |
| 引用生成 | citation phase + Semantic Scholar | 检索文献后插入引用 | 基于参考论文/检索 | API-grounded citations、citation graph | 基于上传/检索文献 |
| 质量迭代 | tree search + self-reflection | 多阶段 human feedback 可介入 | agent 迭代 | Content Refinement Agent 模拟 peer review 后修稿 | post refine / 交互式修改 |
| 排版 | LaTeX/PDF | LaTeX/report | 论文/报告格式 | venue-specific LaTeX template | LaTeX + PDF |

## 优先级建议

| 目标 | 最值得看 | 原因 |
| --- | --- | --- |
| 研究怎么自动写完整论文 | PaperOrchestra | 把写作问题定义得最清楚：从 idea summary + experimental log 到 LaTeX paper |
| 研究怎么自动做实验再写论文 | AI-Scientist-v2 | 端到端程度最高，包含 hypothesis、实验、分析、manuscript |
| 做能落地的科研助理 | Agent Laboratory | 人类给 idea，Agent 做文献、实验、报告，比较实用 |
| 做自动综述产品 | SurveyX + InteractiveSurvey + AutoSurvey | 这条线最成熟，输入主题/文献，输出 survey |
| 做论文写作工具链 | Open Academic Paper Machine / PaperDebugger | 贴近日常写作、排版、验证、修订流程 |
| 做引用可靠性模块 | PaSa / PaperSearchQA / SoPaper-Evidence | 不主写论文，但能补自动写作最弱的“找真文献、证据 grounding” |

## 一句话总结

AI-Scientist-v2 解决的是“研究是否能被自动发现”；PaperOrchestra 解决的是“研究材料如何被写成论文”；SurveyX/InteractiveSurvey 解决的是“文献如何被组织成综述”。如果主线是文章生成，应优先拆 PaperOrchestra，再看 Agent Laboratory 的 paper-solver 和 SurveyX 的 outline/content/refine/LaTeX 流程。

# 纯 Paper 生成项目

这里的“纯 paper 生成”分三类：Material-to-Paper（已有 idea/实验日志/结果表，系统写成完整论文）、Topic-to-Draft（只给题目，系统检索文献并生成 research draft）、Survey Generator（专门生成综述论文）。

- 最贴近真正 manuscript writer 的是 PaperOrchestra：它不自动做实验，而是把已有研究材料写成 submission-ready LaTeX manuscript。
- Topic-to-Draft 类更方便，但更容易出现引用幻觉、贡献夸大和事实不稳。
- Survey Generator 类更成熟，但主要适合综述，不适合方法/实验论文。
## 项目对比

| 项目 | 类型 | 输入 | 输出 | 是否做实验 | 生成流程 | 判断 |
| --- | --- | --- | --- | --- | --- | --- |
| PaperOrchestra | Material-to-Paper | idea summary、experimental log、LaTeX template、venue guideline | submission-ready LaTeX manuscript、表格、图、PDF | 否 | Outline Agent -> Plotting Agent -> Literature Review Agent -> Section Writing Agent -> Content Refinement Agent | 最正统的纯 paper 生成工作：把已有研究材料写成完整论文 |
| Ar9av/PaperOrchestra | PaperOrchestra 社区实现 / skill pack | idea.md、experimental_log.md、模板、指南；也可从 agent cache 提取 | LaTeX paper | 否 | 按 PaperOrchestra 五阶段拆成 skills；宿主 agent 负责 LLM、搜索、编译 | 适合动手复现 PaperOrchestra 思路，但不是官方实现 |
| Open Academic Paper Machine | Topic-to-Paper 工具链 | 研究主题/题目 | arXiv-style LaTeX/PDF | 基本不做真实实验，偏写作链路 | Idea Evaluation -> Literature Search -> Framing -> Structure -> Production -> LaTeX/PDF -> Verification -> Revision | 产品化链路完整，适合看搜索-写作-排版-核查-修订 |
| OpenDraft | Topic-to-Draft / Thesis Writer | 主题、文档类型、语言、引用风格 | PDF、Word、LaTeX 草稿 | 否 | 19 个 agents：research、structure、compose、validate、refine、polish | 更像论文/学位论文初稿生成器；适合参考多 agent 写作分工 |
| Local Research Paper Generator | Topic-to-Paper 本地版 | idea + 本地 LM Studio 模型 | LaTeX paper | 有一点 live experiments / code execution | literature search、hypothesis、code experiment、section drafting、LaTeX compile | 本地私有化 paper generator，但质量和成熟度需要实测 |
| SurveyX | Survey Paper Generator | 标题、关键词、本地 Markdown 参考文献；完整版有在线检索 | survey.pdf、LaTeX、outline JSON | 否 | outline -> content generation -> post refine -> LaTeX generation | 如果 paper 是综述，SurveyX 很直接 |
| InteractiveSurvey | Interactive Survey Generator | 主题、用户偏好、交互反馈 | personalized survey/report | 否 | 初稿 -> 用户交互调整 -> 个性化综述生成 | 适合边探索边生成综述，不是一键实验论文 |
| AutoSurvey | Survey Paper Generator | 主题、文献库/检索结果 | survey draft | 否 | retrieval -> outline -> subsection drafting -> integration/refinement -> evaluation | 学术上更扎实的自动综述基线，虽是 2024 但仍值得对比 |

## 项目链接

| 项目 | 链接 |
| --- | --- |
| PaperOrchestra paper/project | https://arxiv.org/abs/2604.05018 / https://yiwen-song.github.io/paper_orchestra/ |
| Ar9av/PaperOrchestra | https://github.com/Ar9av/PaperOrchestra |
| Open Academic Paper Machine | https://github.com/TobiasBlask/open-paper-machine |
| OpenDraft | https://github.com/federicodeponte/opendraft |
| Local Research Paper Generator | https://github.com/schmitt-steven/Paper-Generator |
| SurveyX | https://github.com/IAAR-Shanghai/SurveyX |
| InteractiveSurvey | https://github.com/TechnicolorGUO/InteractiveSurvey |
| AutoSurvey | https://github.com/AutoSurveys/AutoSurvey |

## 优先级

| 优先级 | 项目 | 原因 |
| --- | --- | --- |
| 1 | PaperOrchestra | 最纯的“已有研究材料 -> 完整论文”框架，问题定义非常清楚 |
| 2 | Ar9av/PaperOrchestra | 可执行的社区版，能看 prompt、schema、验证 gate、LaTeX 流程 |
| 3 | Open Academic Paper Machine | 最像产品化 paper writer，覆盖写作、排版、引用验证、修订 |
| 4 | OpenDraft | 多 agent 写作分工很细，适合参考 topic-to-draft 架构 |
| 5 | SurveyX / AutoSurvey | 如果目标是综述论文生成，这条线比实验论文生成更成熟 |

## 一句话结论

如果“纯 paper 生成”指不自动做实验、只负责把已有研究材料写成论文，目前最值得拆的是 PaperOrchestra；如果指输入一个题目就生成整篇文章，更接近 OpenDraft / Open Academic Paper Machine / SurveyX，但要重点防引用幻觉和贡献夸大。
