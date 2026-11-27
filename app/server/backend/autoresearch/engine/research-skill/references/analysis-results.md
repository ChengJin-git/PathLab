# Publishing analysis results

After running analysis code, write `analysis-results.json` (≤ 2 MiB) and call
`publish_analysis(path="analysis-results.json")`. Values must be measured. Paths are relative to the
session workspace; job outputs are under `runs/<job_id>/output/...`.

```json
{"schema_version":"pathlab-analysis-v1","title":"Group comparison","summary":"Measured findings and limitations","source_files":["scores.csv"],"code_path":"analyze.py","metrics":{"group_A.mean":{"value":0.8,"label":"Group A mean","ci_lower":0.73,"ci_upper":0.89}},"tables":[{"title":"Groups","columns":["Group","N"],"rows":[["A",3],["B",3]]}],"figures":[{"path":"comparison.png","title":"Measured group means","caption":"Error bars show the measured confidence interval."}],"chart_data":{}}
```

- Multi-task outputs declare `tasks: [{id, title, task_type, metric_keys, chart_keys}]` with real
  task types (classification, survival, segmentation, custom).
- Reusable interactive charts under `chart_data`:
  - `confusion_matrix`: `{classes, data: [[predIndex, trueIndex, count], ...]}`
  - `roc_curve`: `{classes, data: {label: {fpr, tpr, auc}}}`
  - `km_curve`: `{high_risk: {times, probs}, low_risk: {times, probs}, cutoff, c_index?}`
  - `loss_curve`: `{epochs, loss, val_loss?, accuracy?, val_accuracy?}`
  Other plots (calibration, decision curves, forest plots, Bland–Altman) are real PNG figures.
  No arbitrary JS or ECharts options.
- For reusable CPU re-analysis on `/results`, add
  `predictions: {path: "predictions.jsonl", task_type, classes, unit}`. Each JSONL record has
  `sample_id`, `split`, optional `dataset_id`, `case_id`, `wsi_id`, `label`, `pred`, `probs`,
  `age`, `gender`, `source`; survival adds `risk_score`, `event_time`, `event_status`, optional
  `surv_probs`, `bin_edges`; segmentation adds per-image `metrics`. Limits: 500,000 rows / 256 MiB.
