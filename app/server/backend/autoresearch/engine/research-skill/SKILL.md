---
name: PathLab Research
description: Conduct pathology analysis, reproduction, or original scientific research. Use for autonomous investigations, publishable method research, strong full-data baselines, controlled experiments, evidence review and research deliverables.
---

# PathLab Research

Runtime contract: PathLab research harness, updated 2026-11-24.

## 1. Every task

- Call `get_research_context` first, and again after a user message or restart. `original_request`
  and `recent_instructions` are the user's words; `working_goal` is your interpretation and cannot
  add requirements. Budget, jobs, decisions and enabled connectors are there too. Wake-ups for
  finished jobs already carry the job results and strategy checkpoint: act on them without
  re-reading the context or reloading this skill.
- Call `set_task_scope(task_kind, report_policy, research_standard, current_goal)` from the user's
  intent. `analysis` computes on existing data/predictions, `experiment` trains or compares models,
  `document` produces files. `research_standard=scientific` for original method or discovery research
  (for example "a MICCAI paper"); `standard` for analysis, reproduction, downloads and writing.
  The latest user instruction wins. A scientific study stays `scientific` through every sub-step
  (data screening, scripts, analysis): change `task_kind` and `current_goal` instead. Only the
  user lowers it (quote them in `user_request`).
- Do what the task needs and no more: an analysis, download, registration or document can be the
  complete deliverable. Training, literature review and manuscripts are not implied.
- Act without routine confirmation. Repair ordinary failures yourself (code, imports, paths,
  arguments, memory, transient services; `install_dependencies` for Python packages) and rerun to
  verify. `request_help` is only for a verified external dependency (access, absent data, a user-only
  decision, budget) or at least two distinct failed repairs.
- Submit background jobs and end your turn; PathLab wakes you. Do not poll or sleep. Never submit a
  duplicate of an active or restart-recovered job.
- Deliverables are workspace files registered with `register_artifact`. Never fabricate data,
  labels, metrics, figures or citations. Use only enabled connectors for retrieval.

Load these references from this skill's base directory when the phase needs them:

| Reference | When |
| --- | --- |
| `references/scientific-records.md` | Writing protocol, decision, review and study-result records |
| `references/jobs-and-gpu.md` | Writing job scripts, GPU resources, restarts, dependencies |
| `references/data-and-models.md` | Acquiring/registering datasets, registering models |
| `references/analysis-results.md` | Publishing analysis results and predictions |
| `references/writing-and-skills.md` | Manuscripts, report templates and the installed skill catalog |

## 2. Scientific research: the paper loop

A scientific task succeeds when a result clears the publication bar the user named. A negative or
marginal result is recorded honestly, but it does not end the task while untested pitches and budget
remain. The harness enforces the gates below; plan with them instead of discovering them.

### 2.1 Pitch before protocol

1. **Inventory.** Read manifests; count real cases/patients, labels, splits and cached features.
   These counts are the full data sizes in the protocol `data` field.
2. **Field scan.** Find the strongest recent methods (2024–2026) on these or comparable public
   benchmarks, their reported numbers and their code. Prefer public benchmarks reviewers know.
   Find candidate datasets and benchmarks with the PathTrove tools (`pathtrove-best-data` skill):
   size, labels, licence and access route; confirm decision-critical values at the cited source.
3. **Pitches.** Write at least three structurally different paper pitches in `pitches.md`, each at
   the level of a paper abstract:
   - title and one-sentence claim (a new method, objective, architecture, training scheme or
     clinically meaningful capability — not "test whether X explains Y");
   - headline result: the table the paper would lead with — proposed method against the two or
     three strongest recent methods, on named datasets at full size, with the primary metric;
   - closest work and the concrete difference; novelty check (searches run and what they found);
   - why it should beat those baselines and the expected margin; cost.
   Do not pre-specify rival-explanation lists, controls or audits. Mechanism analysis is an
   ablation of a method that already wins.
4. **Rank.** Ask a separate-context subagent acting as a MICCAI area chair to compare the pitches
   pairwise for novelty, expected gain, feasibility with available data and cost. Select the best;
   the rest stay queued as protocol directions.
5. **Verifiability.** A new idea counts only if others can check it. Report the headline on a
   metric the field accepts; a new endpoint is welcome when it is validated and shown beside the
   standard one. Set `evaluation.resolution` to the smallest change one evaluation unit makes to the
   metric; with few cases, evaluate by cross-validation over all labelled cases instead of one small
   split. A bar below the resolution or below seed noise cannot be measured. Set
   `evaluation.best_possible` (1 for AUROC, 0 for an error rate; null if unbounded): pick an endpoint
   where published baselines leave at least 3 × `minimum_gain` below it.
6. **Protocol.** `directions` are the pitches; `evaluation.minimum_gain` is the smallest improvement
   in the primary metric over the strongest closest baseline that would make the paper worth
   submitting (for example 0.02 AUROC). Give the closest baseline its published `reference` result.
   A pitch that exploits a phenomenon names it in `premise` (a mechanism step and its metrics.json
   key, in primary-metric units); otherwise `premise: null`. Measure the premise first: a method
   cannot recover more than the effect it removes.
   Then `record_study_protocol`.

If the user names a topic or method, pitches are variants of that topic. If the user only names a
venue, choose topics where available data and compute give a realistic path to the bar.

### 2.2 Full data first

- Stages run exploration → validation → confirmation. Exploration is a smoke test: the code runs,
  the loss falls, outputs are well formed. It never decides whether an idea works. At most three
  exploration runs per pitch are accepted before that pitch runs at full scale.
- Validation steps use the full train and evaluation sets declared in `data`; confirmation evaluates
  on the full held-out or external set. Subset validation is rejected.
- **Reproduce first.** Before any full-scale method run, a run of the closest published method
  must come within 5% of its published `reference`, on the study data or on the reference's own
  benchmark when the data are new. A pipeline that cannot reproduce a known result cannot verify a
  new one; the usual causes are reduced inputs, missing features or an untuned setup.
- Keep input fidelity: do not pool, subsample or shrink inputs to save time when the signal may be
  small or rare.
- **Repeats.** Validation method and closest-baseline steps need at least 3 independent repeats
  (seeds); one job may train several and report `primary_by_replicate`. The bar counts only when the
  mean gain also exceeds twice its standard error.

### 2.3 Iterate toward the bar

After each full-data result, compare against the strongest baseline:

- **Gain ≥ `minimum_gain`:** replicate, ablate the key components, confirm on held-out or external
  data, run the reviewer, then write.
- **Promising but below the bar:** improve the method itself — representation, objective,
  architecture, training, optimization or hyperparameter tuning. Tuning on development data is
  ordinary method development, not selection bias; only the held-out test is locked. Tune the
  baseline with the same budget.
- **No headroom:** a direction can be ruled out (`contradicted`) only after at least 3 tried
  candidates and full-scale repeats. Then pivot.
- **Repeated failure means the frame is wrong.** After 3 pitches fail under one evaluation, data and
  baseline set, new pitches under that frame are rejected. Check baseline reproduction, headroom,
  seed noise and input fidelity, then change the frame yourself — new cohort, harder endpoint or
  evaluation that still answers the user's question (PathTrove, Data Repo). The user's question, not
  the first dataset, is the scope.

Measure progress by the best full-scale gain, not by audits, receipts or repaired scripts. Do not
run single-factor diagnostics on a handful of cases, re-verify unchanged inputs, or stack
micro-variants of one idea. Check splits, leakage, labels and test isolation once and reuse the
check. After each batch write one short entry in `research-log.md`: bar, best gain so far, next
batch. Limitations that do not threaten the main conclusion are written up, not chased.

### 2.4 Stopping and budget

- `write` is accepted only when the harness-measured full-scale gain of the selected pitch over the
  strongest closest baseline is at least `minimum_gain` and every required step has completed runs.
- `finish_research` with `partial` or `no_result` on a scientific task is accepted only when the
  user asked you to stop — quote their words in `user_stop`. Only after two frames fail, call
  `request_help(reason="direction")` with the measured results and two or three concrete options
  (new frame, new pitches, more budget) and let the user choose.
- Plan the whole study up front from measured pilot costs. When it needs more time or attempts,
  call `request_help(reason="budget")` early, stating the next pitch or batch and the amount. The
  user expects to extend budget; running out is a pause, not an outcome.
- Integrity: patient-level splits, no selection on the held-out test, honest reporting of every
  negative result in the ledger and the paper.

## 3. Analysis and document tasks

Use existing data, predictions (`predictions_path` JSONL in selected task references) and normal
platform tools. Run custom analysis code on CPU in the sandbox or with `submit_computation` for long
work; these never consume experiment attempts. Publish measured results with `publish_analysis`
(see `references/analysis-results.md`). Count each patient once using `case_id` and the task's
aggregation level, never mix train and held-out predictions, and treat a missing split or attribute
as unknown. `report_policy=summary` unless the user asked for a formal paper.

## 4. Finishing

Call `finish_research` with `completed`, `partial` or `no_result` and an evidence-grounded summary
naming the real files. If the user can supply a missing prerequisite, use `request_help` instead.
On Continue, re-read files and manifests, preserve user edits, inspect existing jobs, and resume
rather than restart.
