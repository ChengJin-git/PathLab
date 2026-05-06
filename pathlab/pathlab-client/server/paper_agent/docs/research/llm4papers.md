# LLM4Papers 详解：把 LLM 接进 Overleaf 当异步合作者

> 整理日期：2026-05-03
> 项目：[KordingLab/llm4papers](https://github.com/KordingLab/llm4papers)（UPenn Kording Lab + Duke Argus Lab）
> 作者：Richard Lange、Konrad Kording
> 公布：2023-06 创建，2024-06-03 首次公开介绍 ([Kording Lab blog](https://kordinglab.com/2024/06/03/llm4papers) / [Argus Lab mirror](https://arguslab.pratt.duke.edu/2024/06/03/llm4papers.html))
> License：Apache-2.0；Python；Poetry 管理；25★ / 1 fork（截至 2026-05）

> 本文是 [`paper-generation-survey.md`](paper-generation-survey.md) 中 §2.5.3 的展开版。LLM4Papers 在那篇综述里只占一段，但它代表的是一种与 PaperOrchestra **正好相反**的产品形态——**最细颗粒度、最不打扰人的 LLM 写作辅助**。这种形态的工程取舍很值得单独剖。

---

## 0. 速览

| 维度 | LLM4Papers 的取舍 |
|------|-------------------|
| **目标** | 让 LLM 像"安静的合作者"一样异步编辑同一篇 LaTeX 论文 |
| **触发方式** | 在 `.tex` 里写一条 LaTeX 注释 `% @ai: <command>` |
| **作用粒度** | 单行替换（`LineRange = (start, end)`），不是 chat、不是整段、不是整篇 |
| **集成方式** | 不写编辑器插件，直接克隆 Overleaf 的 git remote → 改文件 → 推回去 |
| **同步性** | 后台轮询，**异步**（默认 10 秒一次）；用户感觉不到 |
| **调度策略** | 没事就放慢轮询（线性退避到 6 小时），有事立刻恢复 |
| **避撞机制** | 用户最近 10 秒在改的行，AI 不动它 |
| **历史可追溯** | AI 的提交带独立的 git author（默认 "AI assistant"），用 `git log` 直接看到谁写的 |
| **真实状态** | **作者自己写"absolutely cannot overstate how un-production-ready"，仍然是研究 demo** |

**一句话定位**：**它是"LLM 当异步合作者"这个 idea 的最干净的开源参考实现**——不靠插件、不靠 webhook、不重发明编辑器，全部建在 Overleaf 已有的 git 协议之上。

---

## 1. 这是什么 / 不是什么

**它是**：
- 一个后台 Python 服务（`poetry run python3 llm4papers/service.py`），盯着一组 Overleaf 项目的 git remote，发现 `% @ai:` 注释就调 LLM、改文件、推回去。
- 一组**协议化抽象**：`PaperRemote`（文档来源）、`EditorAgent`（LLM 后端）、`PaperManager`（轮询调度）——每一层都可以换实现。
- 一个**多人 git 协作的隐形参与者**：你 commit、AI 也 commit，行如另一个有点慢但是不打架的同事。

**它不是**：
- ❌ **不是端到端论文生成器**——它不写大纲、不做文献综述、不画图、不生成 abstract。每次只换一行。
- ❌ **不是 chat 界面**——没有对话窗口；唯一的"对话"是 AI 把你的 `% @ai: ...` 改成 `% @user: ...`，让你回写。
- ❌ **不是已发表论文**——没有 arXiv 没有 conference paper，**只是一篇 blog post + 一个 repo**。
- ❌ **不是产品级工具**——README 的 warning 是逐字引用：「**Do not use this on important documents!** Don't use this on documents you care about. And if you want to use this on something important, don't.」

> 把 LLM4Papers 拿来用是危险的，但**把它拿来读源码是值得的**。它整个 src 不到 2000 行，是研究"如何让 LLM 不打扰人地协作"的好教材。

---

## 2. 一个最小例子（从用户视角）

你在 Overleaf 里写论文，写到一半：

```latex
The brain is weird. % @ai: formalize this
```

10 秒钟之后，下次 git pull（或 Overleaf 自动同步）回来，你的文件变成了：

```latex
% The brain is weird. % -ai-: formalize this
The mammalian brain exhibits a number of properties that distinguish it
from artificial neural networks, including ... % @user:
```

发生了什么：

1. 后台 service 每 10 秒 `git pull` 你的 Overleaf 项目。
2. 它扫所有 `.tex` 文件，找含 `@ai:` 的行。
3. 找到了上面那行，提取 request_text = `formalize this`。
4. 检查这一行最近 10 秒内你有没有改过——**没有**，可以动。
5. 把这一行 ± 10 行作为 context 喂给 GPT-3.5-turbo。
6. LLM 输出新文本，service 把原行注释掉（`% ` 前缀）、附加新文本、把 `@ai:` 改写成 `-ai-:` 防止递归触发，再把 `% @ai:` 改成 `% @user:` 给你回信用。
7. 用 git author = `AI assistant <dummy@agi.ai>` 提交并推回 Overleaf。
8. 你下一次打开 Overleaf，新文本就在那里。

**整个交互没有 popup、没有 sidebar、没有 review diff 弹窗**——纯粹靠 LaTeX 注释 + git 历史。

---

## 3. 架构剖析

整个项目结构小到可以一屏列完：

```
llm4papers/
├── service.py             # 10 行入口：组装 manager + remote + agent，调 poll()
├── models.py              # Pydantic schema：DocumentRange / EditTrigger / EditResult
├── config.example.py      # 5 个全局参数（context_radius / 轮询间隔 / 是否保留原行）
├── editor_agents/         # LLM 后端
│   ├── EditorAgent.py     #   Protocol: get_available_edits / edit
│   ├── OpenAIChatEditorAgent.py  # GPT-3.5-turbo 实现（用 microsoft/guidance）
│   └── prompts.py         #   一个 prompt：BASIC_v1
├── paper_remote/          # 文档来源
│   ├── PaperRemote.py     #   Protocol: refresh / get_lines / is_edit_ok / perform_edit
│   ├── OverleafGitPaperRemote.py  # 主实现
│   ├── MultiDocumentPaperRemote.py
│   └── InMemoryPaperRemote.py     # 测试用
└── paper_manager/         # 调度
    ├── PaperManager.py
    └── JSONFilePaperManager.py    # JSON 存论文清单，poll 循环
```

### 3.1 `service.py`（整个程序的全部入口）

```python
from llm4papers.config import Settings
from llm4papers.paper_manager.JSONFilePaperManager import JSONFilePaperManager
from llm4papers.paper_remote import OverleafGitPaperRemote

manifest_file = sys.argv[-1] if sys.argv[-1].endswith(".json") else Settings().json_manifest_file
manager = JSONFilePaperManager(manifest_file)
manager.register_paper_remote_class(OverleafGitPaperRemote)
manager.poll(interval=Settings().polling_interval_sec)
```

读完这 10 行就掌握了系统：**一个 manager + 一组论文 remote + 一个轮询循环**。其他的全是 Protocol 实现细节。

### 3.2 数据模型（`models.py`）

```python
DocumentID = Hashable                       # 一般是文件名
RevisionID = Hashable                       # git 用 commit hash
LineRange = tuple[int, int]                 # 行范围（start, end），开区间右

class DocumentRange(BaseModel):             # 「哪个文件的哪几行」
    doc_id: DocumentID
    revision_id: RevisionID
    selection: LineRange

class EditTrigger(BaseModel):               # 「这是个待编辑任务」
    input_ranges: list[DocumentRange]
    output_ranges: list[DocumentRange]
    request_text: str                       # 用户写的那句 "formalize this"

class EditType(str, Enum):
    replace = "replace"
    comment = "comment"

class EditResult(BaseModel):                # 「LLM 决定怎么改」
    type: EditType
    range: DocumentRange
    content: str
```

注意 input_ranges 和 output_ranges 是分开的 list——为后续"读 A 几行，写到 B 几行"留了余地（比如根据 abstract 改 conclusion）。当前实现里两者总是相同。

### 3.3 PaperRemote 协议

```python
class PaperRemote(Protocol):
    current_revision_id: RevisionID
    def refresh(self): ...
    def get_lines(self, doc_id: DocumentID) -> list[str]: ...
    def list_doc_ids(self) -> list[DocumentID]: ...
    def is_edit_ok(self, edit: EditTrigger) -> bool: ...
    def perform_edit(self, edit: EditResult) -> bool: ...
```

主实现是 `OverleafGitPaperRemote`：把 Overleaf 项目克隆到 `/tmp/<reposlug>`，refresh 等于 `git pull --force`，perform_edit 等于改文件后 `git commit + git push`。

**鉴权**：把 username/password 注入到 git URL 里（`https://user:pass@git.overleaf.com/...`）。简陋但能工作。

**git author**：每次 refresh 时把 git config user.name/email 改成"AI assistant"，所以 AI 的 commit 在 Overleaf 历史里和人类 commit 是清晰区分的。

### 3.4 EditorAgent 协议 + 触发逻辑

```python
class EditorAgent(Protocol):
    def get_available_edits(self, paper: PaperRemote) -> Iterable[EditTrigger]: ...
    def edit(self, paper: PaperRemote, edit: EditTrigger) -> Iterable[EditResult]: ...
```

`OpenAIChatEditorAgent.get_available_edits` 的实现非常直接：

```python
for doc_id in paper.list_doc_ids():
    for i, line in enumerate(paper.get_lines(doc_id)):
        if "@ai:" in line:
            yield EditTrigger(...)         # 这一行需要 LLM 处理
```

**没有 NLP，没有 regex 大全，就是字符串子串匹配**。设计哲学：触发器要明显、可见、用户可控。

### 3.5 Prompt（唯一一个）

`prompts.py` 里只有 `ChatPrompts.BASIC_v1`，用 [microsoft/guidance](https://github.com/guidance-ai/guidance) 模板语言写。系统消息直接抄过来感受一下：

> You are a helpful academic assistant. You are helping a well-educated professor at a prestigious university edit an important research paper to be submitted to **nature neuroscience** with an audience of math-inclined PhD students of neuroscience in mind. As an assistant your focus is on **brevity** (you like text to feel snappy and to the point) and **precision** (you want to make sure that the text is clear). When a text segment contains multiple sentences, you are particularly mindful of **narrative structure** (ideas need to be motivated before they are introduced, they need to be clearly summarized, and the reader needs to find a take-away message at the end). Also keep in mind that your edit should not remove any creative aspects introduced by the writer, such as personal notes.

User message的关键约束：

> Remember to change the `"% @ai: [command]"` comment to `"% @user: [comments]"` when you are done. Only respond with the changed text; do not include comments or suggestions.

**两条很关键的工程小技巧**：
1. **角色锁死**：直接把 prompt 锁定为 nature neuroscience 风格 + neuroscience PhD 听众。这是个研究项目，作者就是 neuroscience 的，他们没打算做通用工具——但作为模板，**先把 voice 和 audience 写死，比让 LLM 猜风格强得多**。
2. **回信约定**：让 LLM 把 `@ai:` 注释改成 `@user:`，**形成轻量级"会话线程"**。用户下次再写 `@ai:` 接在后面就是续聊。

### 3.6 调度循环（`JSONFilePaperManager.poll`）

```python
while True:
    if self.poll_once():                    # 找到并执行了至少一条 edit
        current_interval = interval         # 重置到默认（10s）
    else:
        current_interval = strat_lambda(current_interval)  # 退避
    time.sleep(current_interval)
```

退避策略 `linear_threshold` = `lambda x: x + interval if x < 21600 else 21600`：每次空轮询多加 10 秒，封顶 6 小时。**含义**：
- 你正在写论文 → 它 10 秒响应一次。
- 你下班了，明天再来 → 它会逐步退到几小时一轮，省 API 调用。
- 你回来 commit 一下 → 触发到一次 edit，立刻回到 10 秒。

这个细节小，但是表达了一种态度：**"安静地等"是 LLM 助手的核心德行**。

---

## 4. 五个最值得抄的工程决策

按重要性排：

### 4.1 「让人先动完，再动手」检测（`_too_close_to_human_edits`）

```python
sec_since_last_commit = (now - last_commit_date).total_seconds()
if sec_since_last_commit > 10:
    return False                            # 用户已经"放手"，AI 可以介入

# 否则查最近 N 个 commit 的 diff，看 AI 想改的行是否被人类改过
total_diff = repo.git.diff(f"HEAD~{last_n}", filename, unified=0)
for git_line_range in _diff_to_ranges(total_diff):
    if _ranges_overlap(git_line_range, line_range):
        return True                         # 就是这行人在改，别动
```

**这是整个项目最被低估的设计**。任何"AI agent 编辑文档"系统都要解决"用户和 AI 同时在写"的竞争问题。LLM4Papers 的解法不是 OT、不是 CRDT、不是 lock——只是问"用户 10 秒内动过这行没？"。简陋但是**和 git 协作模型完全自洽**，零额外协议。

### 4.2 「保留原文为注释」（`retain_originals_as_comments`）

```python
if Settings().retain_originals_as_comments:
    original_lines = lines[doc_range.selection[0] : doc_range.selection[1]]
    prefix_lines = [f"% {line.split('@ai')[0]}\n" if "@ai" in line else f"% {line}"
                    for line in original_lines]
    edited = "".join(prefix_lines) + edited
```

AI 不是覆盖你的原文，而是**把原文注释掉再写新版**。两个收益：
1. 你 git diff 一眼看到改了什么，不需要切到上一版；
2. 你不满意可以直接删掉新版、把 `% ` 删掉就还原了，不用走 `git revert`。

### 4.3 「防自我递归」

```python
edited = edited.replace("@ai:", "-ai-:")
```

LLM 输出文本里如果有 `@ai:`（哪怕在引号里），下次扫描会再次触发，无限循环。一行 `replace` 解决。**这是个反复在 agentic 系统里被忘记的 bug**——多数人加了输出过滤、忘了输出可能含触发关键词。

### 4.4 「轮询，不要 webhook」

Overleaf 没有 outbound webhook。LLM4Papers 没有重发明 push notification——直接每 10 秒 pull 一次。**90% 的"实时协作"问题用 polling 都够用**，剩下的 10% 才上 webhook。

### 4.5 协议化的 EditorAgent / PaperRemote

`EditorAgent` 和 `PaperRemote` 都是 Python `Protocol`（结构子类型）。这意味着：
- 想换 GPT 为 Claude / 本地模型 → 只实现 `get_available_edits` 和 `edit` 两个方法。
- 想换 Overleaf 为 Notion / Google Docs / 本地文件 → 实现 `PaperRemote` 协议。
- 想做 unit test → 用 `InMemoryPaperRemote`（仓库里已经有，1340 字节）。

`WriteOutDigitsEditorAgent`（把 "1" 改成 "one"）是个非 LLM 测试 agent，验证 protocol 抽象本身能跑——非常实用的测试模式。

---

## 5. 它能干什么 / 干不了什么

**实测好用的场景**（README + blog 列出的）：
- ✅ Rephrasing 单句
- ✅ Formalizing 表达（口语 → 学术）
- ✅ 改公式格式
- ✅ Spell check
- ✅ 检查文本流（针对一段话给建议）
- ✅ Readability / clarity 微调

**它做不了的**：
- ❌ 写综述 / Related Work（没有检索能力，纯靠 LLM 参数知识 → hallucination）
- ❌ 写新段落（限定 line-level，不能扩展行数）
- ❌ 改公式或图（只动 `.tex` 文本，不碰 .pdf / 图源）
- ❌ 跨段一致性（context 窗只有 ±10 行）
- ❌ 引用核验（没接 Semantic Scholar 等 API）
- ❌ 多 agent 协同（只有一个 `EditorAgent`，没有 reviewer / planner）

**两个明示的限制**（来自 blog）：

> AI has some well-known failures and limitations. **Hallucination and plagiarism are two of the most common, and the best way to avoid these is to use the AI as an editorial tool, not as a replacement for human thought.**

作者很清楚自己在做什么：**这是 editor 不是 author**。

---

## 6. 在产品形态光谱中的位置

LLM4Papers 和 [`paper-generation-survey.md`](paper-generation-survey.md) 里讨论的其它系统对比：

```
颗粒度：细  ──────────────────────────────────────────────────────  粗
       ▲                                                            ▲
   LLM4Papers     Cursor/Copilot     PaperOrchestra    Sakana v2
   (单行替换)     (整段补全)         (整篇起草)        (写论文 + 跑实验)
                                                                    ▼
人主导 ◄─────────────────────────────────────────────────► AI 主导
```

| 维度 | LLM4Papers | Cursor / Copilot | PaperOrchestra | Sakana v2 |
|------|------------|------------------|----------------|-----------|
| 触发 | LaTeX 注释 | IDE 内 chat / cmd-K | 一次性输入 idea + log | 给个 topic |
| 粒度 | 单行 | 段 / 函数 | 整篇 LaTeX 论文 | 完整研究 |
| 与人共存 | 异步、git 同 repo | 同步、同窗口 | batch，不交互 | 完全自主 |
| 跑实验 | 否 | 否 | 否（用人提供的日志） | 是 |
| Hallucination 风险 | 局部，可见 | 局部，可见 | 引用层，被 API 校验 | 全方位 |
| 用户责任 | 完全保留 | 完全保留 | 完全保留 | 模糊 |

LLM4Papers 是**"AI 辅助"光谱里最保守的一端**：粒度最细、人介入最深、AI 自由度最低。这种取舍在 2024 年看起来"过于谨慎"，但放回 2026 年——经历了 NeurIPS 2025 的伪造引用风波之后——反而**变成了一个值得复活的设计哲学**。

---

## 7. 当前状态（看清楚再决定要不要用）

- **最后一次提交**：`pushed_at = 2024-06-03`。距今 (2026-05) 接近两年，**项目实质上停滞**。
- **依赖陈旧**：用的是 `microsoft/guidance` 老 API（已经几次破坏性更新过）；OpenAI 调的是 `gpt-3.5-turbo`（2026 年已过气）。
- **README 自带 disclaimer**：作者没把它当工具卖，是研究 demo。
- **没有维护者**：25 stars、1 fork——典型的"灵感项目"规模。

**所以**：
- ❌ 不要直接 fork 来用。
- ✅ 适合**作为参考实现读源码**，把里面的 protocol 设计 + 避撞机制 + git 协作模型搬到自己的工具里。
- ✅ 适合**作为 PaperOrchestra 的对照组**讨论：如果你不想承担 PaperOrchestra 那种"整篇起草"的工程复杂度和事实风险，LLM4Papers 是最简单的备选。

---

## 8. 借鉴到 PathLab 的可能用法

PathLab 已经有 PDF RAG 的 chat 助手（产品形态偏 chat）。LLM4Papers 给我们一个**完全不同**的产品形态参考：**把 LLM 嵌入到病理报告草稿编辑流里，而不是让医生切到对话窗**。

具体场景：

1. **病理报告 LaTeX / Markdown 模板里的局部润色**
   - 医生写 `这例肿瘤分化差。% @ai: formalize`
   - AI 改成"该病例镜下肿瘤细胞分化程度低，呈片状排列，核异型显著……"
   - 完全不动结构数据（grade、stage、metric），只改自然语言描述。
   - 颗粒度匹配病理报告"医生写要点 + AI 润色"的真实工作流。

2. **可借鉴的具体机制**：
   - `PaperRemote` 协议 → 改成 `ReportRemote`：对接 PathLab 已有的 case 文档存储。
   - `EditorAgent` 协议 → 用 PathLab 已有的 LLM 接口实现一个；保留 `WriteOutDigitsEditorAgent` 风格的非 LLM 测试 agent。
   - `_too_close_to_human_edits` 避撞 → 改成"医生过去 30 秒内编辑过的字段，AI 不动"。
   - `retain_originals_as_comments` → 在病理报告里非常重要，**任何 AI 改动都必须留 audit trail 给后续审阅医生**。
   - 异步轮询 → 不必照搬，但可借鉴"安静等待、忙时响应"的退避哲学。

3. **要避开的 LLM4Papers 局限**：
   - 不要走"系统 prompt 锁死风格"路线（neuroscience 风格在 PathLab 不适用）；改成按报告类型动态拼 prompt。
   - 必须接病理领域的引用 / 知识源（指南、paper、case lib），不要让 LLM 凭参数记忆生成医学事实。

4. **和 PaperOrchestra 路线的关系**：
   - PaperOrchestra 风格：医生输入完整 case + 模型推断结果，AI 一次性出整篇报告。
   - LLM4Papers 风格：医生写报告主体，AI 在标注的位置做局部润色 / formalize。
   - **这两条不冲突，是互补的**：可以 batch 出第一版（PaperOrchestra 思路），然后医生用 LLM4Papers 思路逐句精修。

---

## 9. References & 文件清单

### 主要资源

- GitHub repo: [KordingLab/llm4papers](https://github.com/KordingLab/llm4papers)
- Blog post（主版本）: [Lange & Kording, "LLMs for Paper Writing", 2024-06-03](https://kordinglab.com/2024/06/03/llm4papers)
- Blog post（镜像）: [Argus Lab, Duke](https://arguslab.pratt.duke.edu/2024/06/03/llm4papers.html)

### 仓库结构（最后一次提交：2024-06-03）

```
llm4papers/
├── Dockerfile                          # 264 bytes
├── README.md                           # 2,058 bytes
├── pyproject.toml                      # 497 bytes
├── poetry.lock                         # 129,723 bytes
├── llm4papers/
│   ├── __init__.py
│   ├── service.py                      # 523 bytes，10 行入口
│   ├── models.py                       # 607 bytes
│   ├── logger.py                       # 108 bytes
│   ├── config.example.py               # 1,016 bytes
│   ├── editor_agents/
│   │   ├── EditorAgent.py              # 3,022 bytes（含 Protocol + WriteOutDigitsEditorAgent）
│   │   ├── OpenAIChatEditorAgent.py    # 4,272 bytes
│   │   ├── prompts.py                  # 2,383 bytes（一个 BASIC_v1 prompt）
│   │   ├── test_DigitsEditorAgent.py   # 642 bytes
│   │   └── test_EditorAgent.py         # 490 bytes
│   ├── paper_manager/
│   │   ├── __init__.py                 # 509 bytes
│   │   └── JSONFilePaperManager.py     # 4,902 bytes
│   └── paper_remote/
│       ├── __init__.py                 # 286 bytes
│       ├── PaperRemote.py              # 2,620 bytes（Protocol 定义）
│       ├── MultiDocumentPaperRemote.py # 2,853 bytes
│       ├── OverleafGitPaperRemote.py   # 14,937 bytes（最复杂的一个文件）
│       ├── InMemoryPaperRemote.py      # 2,721 bytes（测试用）
│       ├── test_InMemoryPaperRemote.py # 1,340 bytes
│       └── test_OverleafGitPaperRemote.py  # 10,772 bytes
└── test_data/
```

总代码量约 **42 KB Python（含测试）**——名副其实的"小工具"。

### 引用本文的位置

- [`paper-generation-survey.md`](paper-generation-survey.md) §0、§2.5.3、§8 横评表、§10 References
