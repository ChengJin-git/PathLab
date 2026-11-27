"""Publish the platform's deterministic evaluation outputs in the unified catalog."""

from datetime import datetime
import asyncio
import json
from uuid import uuid5, NAMESPACE_URL

from backend.database.models import ResultAnalysis
from .contracts import AnalysisConfig, METRIC_BY_ID, CHART_BY_ID
from .sources import index_task, public_source
from .compute import series


def native_result(summary, source):
    metrics = {}
    for key, value in summary.get("metrics", {}).items():
        canonical = key.removeprefix("macro_")
        definition = METRIC_BY_ID.get(canonical, {})
        interval = (summary.get("bootstrap_ci") or {}).get("metrics_ci", {}).get(
            key
        ) or {}
        metrics[key] = {
            "value": value,
            "label": key,
            "unit": definition.get("unit", ""),
            "ci_lower": interval.get("lower"),
            "ci_upper": interval.get("upper"),
        }
    charts = {}
    data = summary.get("chart_data") or {}
    if data.get("roc_curve"):
        charts["roc"] = {
            "kind": "line",
            "series": [
                series(key, value["fpr"], value["tpr"], metric=value.get("auc"))
                for key, value in data["roc_curve"].get("data", {}).items()
            ],
        }
    if data.get("confusion_matrix"):
        cm = data["confusion_matrix"]
        matrix = [[0] * len(cm["classes"]) for _ in cm["classes"]]
        for predicted, actual, count in cm["data"]:
            matrix[actual][predicted] = count
        charts["confusion"] = {
            "kind": "matrix",
            "classes": cm["classes"],
            "matrix": matrix,
        }
    for key in ("loss_curve", "iou_curve", "dice_curve"):
        curve = data.get(key)
        if not curve:
            continue
        folds = curve.get("folds", {}) if curve.get("is_kfold") else {"": curve}
        lines = []
        for fold, values in folds.items():
            for name, points in values.items():
                if (
                    name != "epochs"
                    and isinstance(points, list)
                    and len(points) == len(values.get("epochs", []))
                ):
                    lines.append(
                        {
                            "name": f"{fold} {name}".strip(),
                            "x": values["epochs"],
                            "y": points,
                        }
                    )
        charts["loss" if key == "loss_curve" else key] = {
            "kind": "line",
            "series": lines,
        }
    if data.get("km_curve"):
        km = data["km_curve"]
        charts["km"] = {
            "kind": "line",
            "step": True,
            "series": [
                {"name": key, "x": value["times"], "y": value["probs"]}
                for key, value in km.items()
                if isinstance(value, dict) and "times" in value
            ],
        }
    for key in ("per_class_iou", "per_class_dice"):
        if data.get(key):
            value = data[key]
            charts[key] = {
                "kind": "bar",
                "categories": value["classes"],
                "series": [{"name": key, "y": value["means"]}],
            }
    groups = []
    for name, values in summary.get("class_metrics", {}).items():
        groups.append(
            {"group": name, "count": values.get("support"), "metrics": values}
        )
    folds = summary.get("kfold_training") or {}
    for name, stats in folds.get("aggregated", {}).items():
        metrics[f"fold_mean.{name}"] = {
            "value": stats.get("mean"),
            "label": f"{name} · fold mean",
            "unit": METRIC_BY_ID.get(name, {}).get("unit", ""),
            "std": stats.get("std"),
        }
    for name, fold in folds.get("folds", {}).items():
        groups.append(
            {"group": name, "count": None, "metrics": fold.get("val_metrics", {})}
        )
    return {
        "schema_version": "pathlab-workbench-v1",
        "method_version": "native-evaluation",
        "comparisons": [],
        "results": [
            {
                "source_id": source.source_id,
                "title": source.title,
                "revision": source.revision,
                "count": summary.get("num_samples"),
                "gt_count": summary.get("num_samples"),
                "metrics": metrics,
                "charts": charts,
                "groups": groups,
                "samples": [],
                "notes": [summary["description"]] if summary.get("description") else [],
            }
        ],
    }


async def publish_native(db, task_id, timestamp, summary):
    from backend.database.models import ResultSource

    await index_task(db, task_id)
    source = await db.get(ResultSource, f"task:{task_id}")
    if not source:
        return
    identity = "analysis_" + uuid5(NAMESPACE_URL, f"{task_id}/{timestamp}").hex
    if await db.get(ResultAnalysis, identity):
        return
    payload = native_result(summary, source)
    payload["native_artifact"] = {"task_id": task_id, "analysis_id": timestamp}
    config = AnalysisConfig(
        source_ids=[source.source_id],
        split="test"
        if "test" in source.details.get("splits", [])
        else "oof"
        if "oof" in source.details.get("splits", [])
        else "unassigned",
        unit=source.details.get("unit", "file"),
        metrics=summary.get("requested_metrics", []),
        charts=[
            {"id": key} for key in payload["results"][0]["charts"] if key in CHART_BY_ID
        ],
    )
    created = datetime.fromisoformat(
        summary["timestamp"].replace("Z", "+00:00")
    ).replace(tzinfo=None)
    db.add(
        ResultAnalysis(
            analysis_id=identity,
            user_id=str(summary.get("submitted_by") or source.user_id),
            title=source.title[:200],
            config=config.model_dump(),
            sources=[public_source(source)],
            status="completed",
            result=payload,
            created_at=created,
            finished_at=created,
        )
    )
    await db.flush()
    from backend.common.config import Config
    from .runs import run_directory

    native = (
        Config.get_uploads_dir()
        / "logs"
        / "analysis"
        / task_id
        / timestamp
        / "results.json"
    )

    def save_samples():
        if not native.is_file():
            return
        original = json.loads(native.read_text())
        rows = original.get("wsi_results", [])
        directory = run_directory(identity)
        directory.mkdir(parents=True, exist_ok=True)
        offsets = []
        with (directory / "samples.jsonl").open("wb") as output:
            for i, row in enumerate(rows):
                if i % 50 == 0:
                    offsets.append(output.tell())
                item = {
                    key: row.get(key)
                    for key in ("wsi_id", "filename", "case_id", "label", "pred")
                }
                item.update(
                    source_id=source.source_id,
                    source_title=source.title,
                    confidence=(row.get("probs") or {}).get(row.get("pred")),
                )
                output.write((json.dumps(item, ensure_ascii=False) + "\n").encode())
        (directory / "sample-index.json").write_text(
            json.dumps({"offsets": offsets, "count": len(rows)})
        )

    await asyncio.to_thread(save_samples)
