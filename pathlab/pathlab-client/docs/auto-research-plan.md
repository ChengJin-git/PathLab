# Auto Research Agent — 总体规划

> 最后更新：2026-04-01
> 对标：AI-Scientist v1/v2, AI-Researcher, Biomni, Karpathy AutoResearch, PantheonOS

---

## 架构概览

```
用户输入
  │
  ▼
coordinator ──LLM──→ 识别任务类型 + 选择 skill(或 none) + 决定路由
  │
  ├─ direct（明确指令）→ code_agent 直接执行
  │                      → analyzer → verifier → router
  │                      → reporter(简短摘要，不调 LLM)
  │
  ├─ research（探索性）→ literature_review ──OpenAlex──→ experiment_planner
  │                      → human_review → code_agent/experiment_executor
  │                      → analyzer → verifier → router(迭代/停止)
  │                      → reporter(学术报告，调 LLM)
  │
  ▼
code_agent:
  LLM 选 skill 模版(或 none=自由写) → 写完整脚本
  → 安全检查(SecurityAnalyzer) → 沙箱执行(Apptainer > Docker > subprocess)
  → 失败？→ StuckDetector + 纠错循环(最多 3 次) → 重跑
  → 成功？→ ratchet(git commit/reset)
  → 历史超长？→ Condenser(LLM 摘要压缩)
  │
  ▼
results_analyzer → verifier(sanity check) → iteration_router
  │                                          ├→ 继续迭代
  ▼                                          └→ reporter → 报告
knowhow 自动入库（闭环学习）
```

---

## Phase 1: 后端核心 ✅

| 模块 | 状态 |
|------|:---:|
| LangGraph 11 节点 graph | ✅ |
| 8 个 PathLab API 工具 | ✅ |
| DB Models + Repository | ✅ |
| FastAPI 路由 + SSE streaming | ✅ |
| ExperimentMonitor 后台轮询 | ✅ |

## Phase 2: 能力扩展 ✅

| 模块 | 状态 |
|------|:---:|
| **Code Agent** — RatchetManager + code_agent_node | ✅ |
| **沙箱** — Docker + Apptainer + subprocess fallback | ✅ |
| **Know-How Store** — 硬编码规则 + PathBench 导入 + 闭环入库 | ✅ |
| **Structured Output** — Pydantic 校验 + 重试 + Qwen thinking 剥离 | ✅ |
| **Standalone CLI** — 交互式 REPL + 聊天 + 任务执行 + session logging | ✅ |

## Phase 2.5: 短期升级 ✅

| 模块 | 状态 |
|------|:---:|
| **OpenAlex 文献检索** — 双策略搜索 + LLM method-metric 提取 + 滚雪球 | ✅ |
| **Verifier 节点** — 5 项 sanity check，graph 已集成 | ✅ |
| **Planner 方向感知** — explored_directions + 排除已试组合 | ✅ |
| **Coordinator 路由** — research vs direct，跳过不需要的步骤 | ✅ |
| **Skill 系统** — 5 个 YAML skill + SkillRegistry + 模板注册 | ✅ |
| **PathLab 代码复用** — 8 aggregators + 20 extractors + preprocessing 直接复制 | ✅ |
| **沙箱 streaming + 早期失败检测** — Popen 逐行读取，30s 内检测 ImportError | ✅ |
| **执行纠错循环** — stderr 喂回 LLM，最多 3 次修复重跑 | ✅ |
| **Checkpoint 缓存** — PATHLAB_CKPT_DIR + HF_HOME 共享缓存 | ✅ |
| **实时进度显示** — code_agent 各阶段 print 到终端 | ✅ |

## Phase 2.7: OpenHands 借鉴 + 流程优化 ✅

| 模块 | 状态 |
|------|:---:|
| **StuckDetector** — 纠错循环卡死检测(连续相同错误提前终止) | ✅ |
| **Condenser** — `code_history` LLM 摘要压缩(keep_first + summarize + keep_recent) | ✅ |
| **统一沙箱入口** — `TrainingSandbox` ABC + `get_sandbox()` 工厂（batch 路径统一） | ✅ |
| **SecurityAnalyzer** — AST+regex 脚本安全检查(HIGH 拒绝/MEDIUM 警告) | ✅ |
| **Direct 任务精简** — reporter 对 direct 任务输出简短摘要，不调 LLM | ✅ |
| **自由实验模式** — skill="none" 时 LLM 从零写代码，无模版约束 | ✅ |
| **Feature 路径规范** — output_dir/pt_files/model_name/ 保存 | ✅ |

---

## 待做：Code Agent 改进

| 改进 | 优先级 | 状态 | 预估 |
|------|:---:|:---:|------|
| 错误模式记忆（error_type/pattern 注入 prompt） | P1 | ✅ | — |
| 纠错循环 StuckDetector（重复错误提前终止） | P0 | ✅ | — |
| 实验历史 Condenser（`code_history` 的 LLM 摘要压缩） | P0 | ✅ | — |
| 执行前安全检查 SecurityAnalyzer（AST+regex） | P1 | ✅ | — |
| 分步执行 Quick Check（先跑 2 epoch 验证） | P2 | ✅ | — |
| 结构化 diff 编辑（大脚本只输出 patch） | P3 | ✅ | — |

## 待做：沙箱改进

| 改进 | 优先级 | 状态 | 预估 |
|------|:---:|:---:|------|
| 统一沙箱入口 `get_sandbox()` + `TrainingSandbox`（BaseWorkspace 风格） | P1 | ✅ | — |
| Apptainer 资源限制（--memory 64G + --cpus 16） | P1 | ✅ | — |
| 容器复用池（纠错循环零启动开销） | P2 | ✅ | — |
| 交互式沙箱 / ReAct 代理（实验性代码已存在，API/CLI 未暴露） | P3 | ⚠️ | 1-2 天收尾 |

## 待做：架构升级 (Phase 3)

| 改进 | 优先级 | 状态 | 预估 |
|------|:---:|:---:|------|
| Tree Search 实验管理（4-stage progressive） | P1 | ❌ | 3-4 周 |
| LaTeX 论文生成（分 section + VLM 图表） | P2 | ❌ | 3-4 周 |
| Automated Reviewer（建议导向，非 accept/reject） | P2 | ❌ | 2 周 |

## 待做：长期演进 (Phase 4)

| 方向 | 状态 |
|------|:---:|
| 跨领域 Know-How（放射/超声/通用 CV） | ❌ |
| Self-Evolving Prompt（根据历史成败进化） | ❌ |
| Multi-Agent 协作（Planner + Code + Reviewer） | ❌ |
| SLURM + Enroot 集成（多节点训练） | ❌ |

---

## 当前文件清单（核心文件，行数为近似值）

```
server/backend/auto_research/
├── cli.py                     ~560 lines   交互式 REPL + 聊天 + session logging
├── builder.py                  ~95 lines   LangGraph 11 节点
├── nodes.py                  ~1020 lines   coordinator(路由) + 8 功能节点 + direct report
├── types.py                   ~115 lines   AutoResearchState
├── prompts.py                 ~470 lines   所有 prompts（含 diff / interactive）
├── structured_output.py       ~305 lines   Pydantic 校验 + 重试 + thinking 剥离
├── code_agent.py             ~1540 lines   Code Agent + Ratchet + Quick Check + diff + interactive branch
├── interactive_agent.py       ~540 lines   实验性 ReAct 交互式代理
├── verifier.py                ~190 lines   结果验证 sanity check
├── literature.py              ~380 lines   OpenAlex API 文献检索 + method extraction
├── knowhow.py                 ~740 lines   Know-How Store + PathBench 导入
├── tools.py                   ~470 lines   8 个 PathLab API 工具
├── monitor.py                 ~250 lines   ExperimentMonitor
├── sandbox.py                 ~420 lines   DockerSandbox + persistent container reuse
├── sandbox_base.py            ~175 lines   TrainingSandbox ABC + CommandResult + get_sandbox 工厂
├── apptainer_sandbox.py       ~530 lines   ApptainerSandbox + execute_command + persistent instance
├── script_safety.py            ~90 lines   SecurityAnalyzer (AST + regex)
├── server.py                  ~470 lines   FastAPI API
├── skills/
│   ├── __init__.py + base_skill.py         SkillRegistry + Skill dataclass
│   ├── mil_classification.yaml             WSI 分类
│   ├── survival_analysis.yaml              生存分析
│   ├── feature_extraction.yaml             特征提取 (pt_files/model_name/ 规范)
│   ├── patch_classification.yaml           Patch 分类
│   └── patch_segmentation.yaml             Patch 分割
├── templates/
│   ├── classification_template.py          基于 PathLab 真实代码
│   ├── survival_template.py
│   ├── feature_extraction_template.py      output: pt_files/{model}/ + h5_files/
│   └── common/                             PathLab 代码复用（aggregators / extractors / preprocessing）
│       ├── aggregators/  (8 个: ABMIL, CLAM-SB/MB, TransMIL, DSMIL, ...)
│       ├── extractors/   (20 个: UNI, UNI2, CONCH, Virchow, ...)
│       ├── preprocessing/ (TissueSegmenter, WSITiler, coords)
│       ├── feature_dataset.py, dataset.py
│       ├── loss.py, metrics.py, survival_losses.py
│       └── data_splitter.py
└── .env.superpod                           SuperPod 环境配置
```

## 对标矩阵

| 维度 | 状态 | 对标 |
|------|:---:|------|
| 任务路由（research vs direct） | ✅ | — |
| 文献检索（OpenAlex） | ✅ | AI-Researcher |
| 经验积累（Know-How DB 闭环） | ✅ | **已领先** |
| 结果验证（Verifier） | ✅ | AIGS |
| 沙箱安全（Apptainer） | ✅ | **已领先** |
| 输出校验（Pydantic + 重试） | ✅ | Instructor |
| 执行纠错（error → LLM fix → rerun） | ✅ | OpenCode/Claude Code |
| 早期失败检测（30s 内拦截） | ✅ | — |
| Skill 系统（YAML 声明式） | ✅ | Biomni KnowHow |
| 纠错刹车（StuckDetector） | ✅ | OpenHands SDK |
| 历史压缩（Condenser） | ✅ | OpenHands SDK |
| 脚本安全（SecurityAnalyzer） | ✅ | OpenHands SDK |
| 搜索策略 | 线性迭代 | AI-Scientist v2 (tree) |
| 论文生成 | Markdown | AI-Scientist v2 (LaTeX) |

## 核心原则

1. **验证优先于生成** — Verifier 在 iteration_router 之前
2. **Know-How DB 是护城河** — 每次实验都入库，越用越强
3. **纠错优于丢弃** — 执行失败喂回 LLM 修复，不浪费 GPU 时间
4. **Domain > General** — 病理领域最强的自动化研究平台
