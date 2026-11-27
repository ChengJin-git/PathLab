# Scientific study records

Call `get_study_schema` for the exact JSON schemas. The service validates structure, counts and
fingerprints; it does not certify scientific merit.

## Protocol (`study-protocol.json` → `record_study_protocol`)

- `question`, `hypothesis`, `falsification` (the full-scale result that kills the selected pitch),
  `contribution`, `budget_rationale`, `evidence_files`, `evaluation_files`.
- `directions`: at least three paper pitches — `id`, `title`, `claim`, `headline_result`,
  `closest_work`, `novelty_check`, `expected_gain`, `cost`, `premise` (`step_id` of a mechanism
  step and its metrics.json `metric` measuring the exploited effect in primary-metric units, or null). `selected_direction` and
  `selection_reason` name the pitch being executed.
- `data`: verified full sizes — `name`, `unit`, `train_units`, `evaluation_units`.
- `baselines`: `id`, `name`, `role` (`sanity` or `closest`), `source`, `rationale`, optional
  `reference` (`metric`, `value`, `direction`, `dataset`, `citation`): a published result on
  comparable data. `reference.metric` is the metrics.json key the baseline run reports for it.
- `evaluation`: `metric` (flattened metrics.json key), `direction` (`maximize`/`minimize`),
  `primary_contrast`, `success_rule`, `uncertainty`, `split_policy`, `minimum_gain`, `resolution`
  (smallest change one evaluation unit makes to the metric), `best_possible` (the metric's best
  value, or null when unbounded).
- `stages`: ordered exploration, validation, confirmation — `id`, `kind`, `max_experiments`,
  `max_job_seconds`, `advance_when`, `stop_when`. Attempt caps count queued and failed attempts;
  later validation/confirmation attempts are reserved.
- `steps`: `id`, `role` (sanity/baseline/method/ablation/replication/mechanism), `question`,
  `stage_id`, `scale`, `direction_id` (not needed for baseline/sanity), optional `baseline_id`,
  `required`. `scale` has `dataset`, `unit`, `train_units`, `evaluation_units`, `repeats`,
  `input_coverage`, `optimization`.

Rules the service enforces:

- A required closest-baseline step in a validation stage, and a closest baseline with a `reference`.
- `minimum_gain` is at least `resolution`.
- Validation method and closest-baseline steps have `repeats` of at least 3.
- Full-scale method runs need a completed run of a closest baseline, on any step (use a step on the
  reference's benchmark for new data), whose candidate mean reproduces its `reference` within 5%.
- Full-scale method, ablation and replication runs need a frame that can show `minimum_gain`: the
  closest baseline's repeated mean at least 3 × `minimum_gain` from `best_possible`, its seed spread
  resolvable with ≤10 repeats per arm, and the step's `repeats` at least the number that spread needs.
- A pitch with a `premise` runs full-scale only after the premise step has measured an effect of at
  least `minimum_gain`.
- After 3 pitches are ruled out under unchanged `evaluation`, `data` and `baselines`, adding pitches
  requires changing one of them. `request_help(reason="direction")` is accepted only after two such
  frames are exhausted.
- Validation steps use the full `train_units` (or 0 for inference-only) and full
  `evaluation_units` of their dataset; confirmation steps evaluate on the full set.
- A required method step at validation or confirmation.
- Changing the selected pitch or budget keeps unchanged comparison fingerprints; changing a
  comparison, scale or evaluator needs new evidence. Retire superseded steps.

## Submissions

Each `submit_experiment` config carries `study_step`, `candidate_id`, `operation` and
`parent_run_id`. `draft` starts a candidate (no parent); `improve` forks a new candidate from a
completed run; `debug` keeps a failed/cancelled parent's candidate; `scale` and `replicate` keep a
completed parent's candidate (replicate keeps the same comparison and scale).

Write `study-result.json` beside `metrics.json`: `unit`, measured `train_units`,
`evaluation_units`, `replicate_ids`, `input_coverage`, `optimization`, and `primary_by_replicate`
(replicate ID → primary metric) when one job trains several repeats. Count executed inputs, not
planned ones. Replicate IDs are independent training repeats; a deterministic method uses one ID
with `repeats=1`. Validation and confirmation runs, baselines included, must emit the primary metric.

If equivalent completed repeats have different candidate IDs, link them with
`record_replication_group` (`id`, `step_id`, `run_ids`, `rationale`, `evidence_files`) instead of
retraining.

## Decisions (`record_research_decision`)

`id`, `direction_id`, `action` (keep/discard/repair/pivot), `assessment`
(supported/contradicted/inconclusive/invalid), `scope` (candidate/direction), `next_operation`
(draft/improve/debug/scale/replicate/analyze/finish), `run_ids`, `observation`, `interpretation`,
`next_action`, `evidence_files`. Failed execution is `invalid`, not a negative result. A
direction-level `supported`/`contradicted` needs completed target-scale validation evidence.
Judge a pitch against its claim: a full-scale result with no realistic path to `minimum_gain`
after fair tuning is `contradicted`; it needs at least 3 tried candidates in the direction.
Decisions are append-only.

## Review (`record_study_review`)

`decision` (iterate/pivot/write/blocked), `rationale`, `goal_met`, `conclusion`, `unresolved`,
`completed_steps` (step ID → completed run IDs), `evidence_files`, `figure_paths`, `reviewer`.
The response reports `publication_gain`: the best full-scale mean over independent repeats of the
selected pitch's method steps against the strongest closest baseline, with its standard error and
`missing` reasons. `bar_met` needs at least 3 repeats per arm and a gain of at least `minimum_gain`
and above twice the standard error. `write` needs `goal_met`, no unresolved items, runs for every
required step at planned scale, measured decisions for the cited runs, and `bar_met`. Use the installed `nature-reviewer` (separate context when possible)
before writing.
