"""CPU subprocess entry point. Frozen input and exact configuration remain exportable."""

import json
from pathlib import Path
import sys

from .compute import compute_source, compare, finite, series
from .contracts import AnalysisConfig


def main(directory):
    directory = Path(directory)
    try:
        payload = json.loads((directory / "input.json").read_text())
        config = AnalysisConfig.model_validate(payload["config"])
        results = []
        sample_offsets = []
        sample_count = 0
        def report(value, phase):
            temporary = directory / "progress.tmp"
            temporary.write_text(json.dumps({"progress": value, "phase": phase}))
            temporary.replace(directory / "progress.json")

        for source_index, source in enumerate(payload["sources"]):
            def source_progress(ratio, phase="computing"):
                report(10 + int(85 * (source_index + ratio) / len(payload["sources"])), phase)
            source_progress(0)
            facet = next(
                (
                    task
                    for task in source["details"].get("facets", [])
                    if task.get("id") == config.facet_id
                ),
                None,
            )
            if source["details"].get("prediction_count") and (
                not facet or facet["task_type"] == source["task_type"]
            ):
                result = compute_source(source, source["rows"], config, progress=source_progress)
            else:
                result = {
                    "source_id": source["source_id"],
                    "title": source["title"],
                    "revision": source["revision"],
                    "count": None,
                    "gt_count": None,
                    "metrics": {
                        key: source["details"]
                        .get("metrics", {})
                        .get(
                            key,
                            {
                                "value": None,
                                "reason": "No sample-level predictions are available to calculate this metric",
                            },
                        )
                        for key in config.metrics
                    },
                    "charts": {},
                    "groups": [],
                    "samples": [],
                    "notes": [
                        "Recorded metrics retain their original evaluation scope. Configuration changes do not recalculate these values."
                    ],
                }
            history = source.get("training_history")
            if history:
                folds = (
                    history.get("folds", {})
                    if history.get("is_kfold")
                    else {"": history}
                )
                curves = []
                for fold, record in folds.items():
                    for name, values in record.get("history", {}).items():
                        if (
                            isinstance(values, list)
                            and values
                            and all(isinstance(v, (int, float)) for v in values)
                        ):
                            curves.append(
                                series(
                                    f"{fold} {name}".strip(),
                                    range(1, len(values) + 1),
                                    values,
                                )
                            )
                result["charts"]["loss"] = {"kind": "line", "series": curves}
            with (directory / "samples.jsonl").open("ab") as output:
                for sample in result.pop("_samples", []):
                    if sample_count % 50 == 0:
                        sample_offsets.append(output.tell())
                    output.write(
                        (
                            json.dumps(
                                finite(
                                    {
                                        **sample,
                                        "source_id": source["source_id"],
                                        "source_title": source["title"],
                                    }
                                ),
                                ensure_ascii=False,
                            )
                            + "\n"
                        ).encode()
                    )
                    sample_count += 1
            results.append(result)
        if config.facet_id:
            for result, source in zip(results, payload["sources"]):
                facet = next(
                    (
                        task
                        for task in source["details"].get("facets", [])
                        if task.get("id") == config.facet_id
                    ),
                    None,
                )
                if facet:
                    result["metrics"] = {
                        key: value
                        for key, value in result["metrics"].items()
                        if key in facet.get("metric_keys", [])
                    }
        report(96, "exporting")
        (directory / "sample-index.json").write_text(
            json.dumps({"offsets": sample_offsets, "count": sample_count})
        )
        import hashlib

        output = {
            "schema_version": "pathlab-workbench-v1",
            "method_version": "2",
            "input_sha256": hashlib.sha256(
                (directory / "input.json").read_bytes()
            ).hexdigest(),
            "results": results,
            "comparisons": compare(results, config),
        }
        (directory / "result.json").write_text(
            json.dumps(finite(output), ensure_ascii=False, allow_nan=False)
        )
    except Exception as exc:
        (directory / "error.json").write_text(json.dumps({"error": str(exc)[:1000]}))
        raise


if __name__ == "__main__":
    main(sys.argv[1])
