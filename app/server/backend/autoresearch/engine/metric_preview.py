"""Bounded metric previews for workbench pages; full metrics are served per run on demand."""

import re

PREVIEW_KEYS = 24
HEADLINE = re.compile(r'auc|accuracy|f1|c_index|dice|iou|loss', re.IGNORECASE)


def metric_preview(metrics: dict | None, primary: str | None = None) -> dict:
    """Keep the keys the workbench shows: the primary metric, the first entries (job notices),
    the first numbers (run cards) and headline metrics (comparison table), in original order."""
    metrics = metrics or {}
    if len(metrics) <= PREVIEW_KEYS:
        return metrics
    keys = list(metrics)
    chosen = dict.fromkeys(key for key in [primary] if key in metrics)
    chosen.update(dict.fromkeys(keys[:4]))
    numbers = [key for key in keys if isinstance(metrics[key], (int, float)) and not isinstance(metrics[key], bool)]
    chosen.update(dict.fromkeys(numbers[:8]))
    position = {key: index for index, key in enumerate(keys)}
    headline = sorted((key for key in keys if HEADLINE.search(key) and not key.startswith('train')),
                      key=lambda key: (not key.startswith('test'), key.count('.'), position[key]))
    for key in headline:
        if len(chosen) >= PREVIEW_KEYS:
            break
        chosen[key] = None
    return {key: metrics[key] for key in keys if key in chosen}


def primary_metric(config: dict | None) -> str | None:
    return ((config or {}).get('study_evaluation') or {}).get('metric')


def preview_experiment(run: dict) -> dict:
    metrics = run.get('metrics') or {}
    return {**run, 'metrics': metric_preview(metrics, primary_metric((run.get('config') or {}).get('config'))),
            'metrics_total': len(metrics)}


def preview_job(job: dict) -> dict:
    result = job.get('result') or {}
    if not result.get('metrics'):
        return job
    primary = primary_metric((job.get('payload') or {}).get('config'))
    return {**job, 'result': {**result, 'metrics': metric_preview(result['metrics'], primary),
                              'metrics_total': len(result['metrics'])}}
