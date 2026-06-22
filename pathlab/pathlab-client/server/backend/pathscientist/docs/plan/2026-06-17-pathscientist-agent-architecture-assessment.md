# PathScientist — Agent Architecture Assessment

> Date: 2026-06-17
> Status: Architecture note (reference)
> Question: *Is PathScientist, as currently built, an "agent"?*
> Method: control-flow re-read + a 5-claim adversarial verification pass (each claim a reviewer tried to **refute**
>   against the code; all 5 returned **holds**). Evidence line numbers are against `pathscientistv0.1.0dev`
>   (the orchestration spine is identical on `fix-pathscientist-persist-web-sessions`).
> Paths are relative to `server/backend/pathscientist/`.

## TL;DR

**PathScientist is a deterministic, LLM-augmented research *pipeline* with a genuine code *agent* embedded inside one
of its stages.** It is *not* an autonomous research agent at the top level, and it is *not* a dumb script either.

- **Outer research orchestration = a deterministic finite-state machine.** The stage sequence and the execution plan
  are decided by hardcoded Python rules; the LLM never selects the next stage.
- **Inner execution stage = a real tool-using agent.** Inside `STAGE_EXECUTION`, an OpenHands ReAct agent with 10 tools
  autonomously writes/runs/debugs experiments in a closed feedback loop.
- The LLM appears at the orchestration level only as **slot-filling extraction/judgment at fixed nodes**, and every
  such output is **clamped to a closed registry / enum / confidence gate** before a deterministic rule consumes it.

So the precise label is: **"a bounded code agent orchestrated by a deterministic, LLM-augmented workflow."**

## 1. The two layers

### Layer A — Outer orchestration: a deterministic FSM (NOT an agent)
`run_research_session` (`runner.py:1860`) is a hardcoded linear driver:
```
create_agent/create_conversation
  → director.advance() (intake→grounding)              # ResearchDirector, pure FSM
  → if stage==ACQUISITION: _run_acquisition_stage()
  → readiness → build_execution_plan()
  → while stage==EXECUTION: conversation.send_message(brief); conversation.run()   # ← the agent
  → state.advance('review') → director.advance()       # review = deterministic
  → _run_synthesis_stage()
```
- `ResearchDirector.advance()` (`director.py:68-203`) is **pure if/else** on `state.stage`, `stop_reason`,
  `iteration_index >= max_iterations`, `review_decision`, `approval_status`. No LLM call. Its docstring even states
  "the director does NOT execute anything — it only advances state."
- The legal stage graph is a **fixed dict** `ALLOWED_STAGE_TRANSITIONS` (`types.py:43-52`); `state.advance()` raises on
  any undeclared transition (`types.py:165-194`).
- The REVIEW decision (`continue_execution` vs `enter_synthesis`) is computed by `review.py:_decision()`
  (`review.py:53-56`) **deterministically** from `stop_reason`/`iteration_index` — its file header literally reads
  "Deterministic review stage". **No LLM writes it** (repo-wide, the only writer is `review.py:247`).

### Layer B — Inner execution stage: a genuine agent (YES, an agent)
Inside the `while stage==EXECUTION` loop, `conversation.run()` (`runner.py:2116`, also `run.py:166`, `cli.py:382`)
drives an OpenHands `LocalConversation` ReAct loop (`agent.py:304-354`, `stuck_detection=True`) with **10 tools**:
`TerminalTool, FileEditorTool, RunExperimentTool, ValidateScriptTool, RatchetCommitTool, RatchetRevertTool,
GetMetricsTool, GetWorkspaceInfoTool, SkillBrowserTool, CheckpointTool`.
Closed-loop feedback is concrete:
- `run_experiment` returns metrics + logs + **error-classifier fix hints** to the LLM (`run_experiment.py:1008-1042`,
  `error_classifier.py:123-141`).
- `iteration_state` enforces a validate→quick_check→full ordering and a budget (`iteration_state.py:125-213`).
- `ratchet_commit/revert` gates consume the prior run's metrics/error_type/run_id (`ratchet.py:440-568`).
The LLM freely chooses which tool to call each turn — this layer is genuinely agentic.

## 2. Where the LLM actually sits (three roles)

| Role | Where | Agentic? |
|---|---|---|
| **True agent controller** | the execution-stage `conversation.run()` loop | ✅ yes |
| **Slot-filling function at fixed nodes** | `objective_extractor`, `grounding`, `external_request`, `llm_task_profile`, `discovery_llm_extractor`, `extractor_selector`, `mil_selector`, `synthesis`, `ui_summary` | ❌ "call LLM → parse JSON → normalize"; fills a slot, does not control flow |
| **Top-level controller** | — | ❌ **does not exist** |

**The one place LLM output reaches the orchestration *spine*** is skill selection: `grounding._llm_select_skill` produces
`selected_skill` and `stop_after_skill`, which are *inputs* to `build_execution_plan` (so they influence which plan
template is built and where it truncates), plus `external_request` produces the `external_test_enabled` boolean. **But:**
- `selected_skill` is adopted only if it is in the closed skill registry; unknown picks fall back deterministically
  (`grounding.py:982-989`).
- `stop_after_skill` is validated against `_valid_stop_boundaries`; unknown is forced to `''` (`grounding.py:698-704`).
- `external_request.enabled` requires the LLM boolean **AND** `_conf_at_least("medium")` (`external_request.py`).
- extractor/MIL picks are reverted if not in the fixed catalog/tier (`extractor_selector.py:218-226`, `mil_selector.py:201`).
- LLM `task_type`/`confidence` are clamped to fixed enums (`llm_task_profile.py:162-164`, `discovery_llm_extractor.py:99-101`).

That is the architectural spine: **every LLM output at the orchestration level is validated against a closed
registry/enum/gate, then consumed by deterministic Python.** The plan's *step set and ordering* are pure Python
branching on filesystem/manifest readiness + the (registry-clamped) skill + config flags (`execution_plan.py:417-622`);
no LLM emits, reorders, or rewrites steps. Post-construction, the runner only bumps an integer `current_step` cursor and
backfills concrete `features_dir`/`model_path` discovered on disk (`runner.py:679-714, 758-802`).

> Correction to an earlier informal claim: the REVIEW continue/stop decision is **not** LLM-driven — it is
> deterministic. The genuinely LLM-influenced orchestration joints are skill selection and the external-enabled flag,
> both registry/gate-clamped. The outer loop is therefore *more* deterministic than "LLM decides review" would imply.

## 3. The agent's action space is bounded to a stage

The four orchestration stages — acquisition, data-readiness, grounding, synthesis — are **main-program functions**
(`_run_acquisition_stage`, `_prepare_data_readiness_and_execution_plan`, `_run_synthesis_stage` in `runner.py`;
grounding via `director.advance → ground_objective`). They are **not** in the agent's tool set, and no tool re-enters
the runner/director (`tools/*` import only stateless helpers `metrics_utils`/`external_contract`). `SkillBrowserTool`
only swaps the in-workspace template baseline; it does not invoke a stage. **The agent has bounded autonomy *within* a
stage, not over the research flow.**

## 4. Where it sits on the spectrum

```
scripted/DAG ───── workflow + LLM nodes ──[ OUTER layer ]── LLM-planned ── autonomous agent ──[ INNER layer ]
```
PathScientist is a **dumbbell**: the outer research flow is at "workflow + LLM nodes" (left of centre); the inner
code-execution layer is a real "autonomous agent" (right). Calling the *whole system* "an autonomous research agent"
overstates it; calling it "a script" understates the inner loop.

## 5. The key insight: this is *deliberate* constraint, not a missing feature

The contract gates documented in the remediation plan (ratchet's fail-closed gates, the data-protocol lock, the
synthetic-data gate, the integrity guard) exist **precisely to override/veto the agent's autonomous decisions with
deterministic rules.** The system is engineered to *limit* agent autonomy in exchange for auditability and
reproducibility — which is the right trade-off for an evidence-grounded scientific tool. This matches the project's own
[master plan](2026-04-05-pathscientist-master-plan.md): Layer 2 "Code Agent" is the most mature part; Layer 3 "Research
Orchestrator" is explicitly a stage machine.

## 6. What it would take to make the *whole system* agentic — and whether to

To move the outer layer rightward you would:
1. **Let an LLM plan the stages/plan** instead of the fixed `director.advance()` FSM + templated `build_execution_plan`
   (dynamic, LLM-generated/mutated plans).
2. **Unify the action space** — expose acquisition / readiness / grounding / synthesis as agent *tools* so the agent
   itself decides "acquire more data vs. retrain", rather than the runner sequencing them.
3. **Put the outer layer in a feedback loop**, not a one-pass linear driver.

**Recommendation: mostly don't.** Each step directly weakens the deterministic integrity guarantees this system depends
on. The real design question is not "make it more of an agent" but **"which joints deserve agent autonomy and which
must keep deterministic guardrails"** — and the current boundary (execution = agentic; orchestration + integrity =
deterministic) is a defensible answer. Targeted places where a little more LLM-driven control could help without losing
auditability: (a) replanning when readiness/acquisition fails (today a grounding failure with no task_profile falls
through deterministically — see remediation `C-EXT`/`E-ROBUST`), and (b) letting the agent request a specific next stage
under a gate. Treat those as scoped experiments, not a paradigm change.

## Appendix — adversarial verification results

All five claims were checked by an independent reviewer instructed to **refute** them; all returned **holds**.

| Claim | Verdict | Key evidence |
|---|---|---|
| **C1** Stage transitions are deterministic; LLM never selects the next stage | holds | `director.advance()` pure if/else (`director.py:68-203`); `ALLOWED_STAGE_TRANSITIONS` fixed (`types.py:43-52`); `enter_synthesis/continue_execution` written only in `review.py`/`director.py` |
| **C2** Execution plan is built deterministically, not LLM-generated | holds | `build_execution_plan` pure branching (`execution_plan.py:417-622`); runner only bumps cursor + backfills disk paths (`runner.py:679-714,758-802`) |
| **C3** LLM is a node/judgment function, not the top-level controller | holds | every LLM output clamped to registry/enum/confidence gate before deterministic consumption (grounding/selectors/task-profile); **review_decision is deterministic, not LLM** |
| **C4** Inner code agent is a real tool-using agent with closed-loop feedback | holds | 10-tool OpenHands Agent (`agent.py:304-317`); metrics+error hints fed back (`run_experiment.py:1008-1042`); ratchet/iteration gates (`ratchet.py:440-568`) |
| **C5** Agent's action space excludes the orchestration stages | holds | stages are runner functions, not tools; no tool re-enters runner/director (`agent.py:306-317` vs `runner.py` stage fns) |

Two refinements surfaced (neither refutes the thesis): the LLM-selected `selected_skill`/`stop_after_skill` influence
plan *content* (registry-bounded), slightly broader than "review/external only"; and the REVIEW decision is
deterministic, not LLM-driven — making the outer loop more deterministic, not less.
