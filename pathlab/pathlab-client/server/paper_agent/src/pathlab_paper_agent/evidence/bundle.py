"""Build Phase 03 private/public evidence artifacts from M2 raw collection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pathlab_paper_agent.schemas import PaperConfig
from pathlab_paper_agent.storage import PaperRunPaths

from ..renderers.locked_block_renderer import LockedBlockRenderer
from .phi import PhiScrubber
from .topic import build_topic_context, topic_lines

_METRIC_NAME_RE = re.compile(
    r"(?:acc|accuracy|auc|auroc|f1|precision|recall|sensitivity|specificity|"
    r"balanced|loss|cindex|c_index|dice|iou|kaplan|p_value|pvalue|ci_)",
    re.IGNORECASE,
)
_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


@dataclass(frozen=True)
class EvidenceBuildResult:
    private_lock: dict[str, Any]
    public_evidence: dict[str, Any]
    experimental_log: str
    public_summaries: dict[str, dict[str, Any]]
    tables: dict[str, str]
    locked_blocks: dict[str, str]
    locked_blocks_by_template: dict[str, dict[str, str]]


def build_evidence_bundle(paths: PaperRunPaths, config: PaperConfig) -> EvidenceBuildResult:
    raw = _load_raw_collected(paths)
    idea_text = _load_idea_text(paths, config)
    scrubber = PhiScrubber()
    scrubber.observe(raw)
    scrubber.observe(idea_text)

    datasets = _dataset_rows(raw, scrubber)
    splits = _split_rows(raw, scrubber)
    models = _model_rows(raw, scrubber)
    analyses = _analysis_rows(raw, scrubber)
    external_validation = _external_validation_rows(raw, scrubber)
    missing_evidence = _missing_evidence(raw, scrubber)
    metrics = _metric_entries(raw, scrubber)
    topic = build_topic_context(
        raw=raw,
        datasets=datasets,
        models=models,
        config=config,
        idea_text=idea_text,
        scrubber=scrubber,
    )

    private_lock = {
        "version": 1,
        "paper_id": config.paper_id,
        "source_tasks": [task.model_dump(mode="json") for task in config.source_tasks],
        "selected_templates": [template.value for template in config.selected_templates],
        "collector": {
            "mode": raw.get("mode", "standalone_scaffold"),
            "status": raw.get("status", "missing"),
            "collected_at": raw.get("collected_at"),
            "errors": raw.get("collector_errors", []),
        },
        "metrics": metrics,
        "cohorts": datasets,
        "splits": splits,
        "models": models,
        "analyses": analyses,
        "external_validation": external_validation,
        "missing_evidence": missing_evidence,
        "topic": topic,
        "phi_mapping": scrubber.mapping(),
        "private_identifiers": scrubber.private_identifiers(),
        "raw_paths": sorted(scrubber.raw_paths),
        "provenance": {
            "mode": "phase03_from_raw_collected",
            "raw_collected_dir": "evidence/raw_collected",
            "generated_from": "collector_bundle.json",
        },
    }
    public_evidence = {
        "version": 1,
        "paper_id": config.paper_id,
        "title": config.title,
        "phi_scrubbed": True,
        "collector_status": private_lock["collector"]["status"],
        "source_task_count": len(config.source_tasks),
        "selected_templates": [template.value for template in config.selected_templates],
        "datasets": _public_dataset_rows(datasets),
        "splits": splits,
        "models": _public_rows(models),
        "metrics": [_public_metric(key, item) for key, item in metrics.items()],
        "external_validation": external_validation,
        "missing_evidence": missing_evidence,
        "topic": topic,
    }
    public_summaries = {
        "topic_summary.public.json": {"topic": public_evidence["topic"]},
        "dataset_summary.public.json": {"items": public_evidence["datasets"]},
        "model_summary.public.json": {"items": public_evidence["models"]},
        "analysis_summary.public.json": {
            "items": _public_rows(analyses),
            "metrics": public_evidence["metrics"],
        },
    }
    rendered_by_template = {
        template_id: LockedBlockRenderer(template_id=template_id).render(
            datasets=datasets,
            splits=splits,
            models=models,
            metrics=metrics,
            external_validation=external_validation,
            missing_evidence=missing_evidence,
        )
        for template_id in _selected_template_ids(config)
    }
    primary_rendered = rendered_by_template[_primary_template_id(config)]
    experimental_log = _render_experimental_log(config, private_lock, public_evidence)
    return EvidenceBuildResult(
        private_lock=private_lock,
        public_evidence=public_evidence,
        experimental_log=experimental_log,
        public_summaries=public_summaries,
        tables=primary_rendered.tables,
        locked_blocks=primary_rendered.locked_blocks,
        locked_blocks_by_template={
            template_id: rendered.locked_blocks
            for template_id, rendered in rendered_by_template.items()
        },
    )


def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_raw_collected(paths: PaperRunPaths) -> dict[str, Any]:
    raw_dir = paths.evidence_dir / "raw_collected"
    bundle = _load_json(raw_dir / "collector_bundle.json")
    if isinstance(bundle, dict) and bundle:
        return bundle
    return {
        "mode": "standalone_scaffold",
        "status": "missing",
        "source_tasks": _load_json(paths.source_tasks) if paths.source_tasks.exists() else [],
        "task_summaries": (_load_json(raw_dir / "task_summary.json") or {}).get("items", []),
        "dataset_summaries": (_load_json(raw_dir / "dataset_summary.json") or {}).get("items", []),
        "split_summaries": (_load_json(raw_dir / "split_summary.json") or {}).get("items", []),
        "model_summaries": (_load_json(raw_dir / "model_summary.json") or {}).get("items", []),
        "analysis_summaries": (_load_json(raw_dir / "analysis_summary.json") or {}).get("items", []),
        "external_validation_summary": _load_json(raw_dir / "external_validation_summary.json"),
        "qualitative_summaries": (_load_json(raw_dir / "qualitative_summary.json") or {}).get("items", []),
    }


def _load_idea_text(paths: PaperRunPaths, config: PaperConfig) -> str:
    if paths.idea.exists():
        return paths.idea.read_text(encoding="utf-8")
    return (config.user_idea or "").strip()


def _as_items(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    items = raw.get(key) or []
    return [item for item in items if isinstance(item, dict)]


def _safe_key(value: str) -> str:
    cleaned = _SAFE_KEY_RE.sub("_", value.strip()).strip("_")
    return cleaned or "item"


def _primary_template_id(config: PaperConfig) -> str:
    return _selected_template_ids(config)[0]


def _selected_template_ids(config: PaperConfig) -> list[str]:
    if not config.selected_templates:
        return ["miccai"]
    return [str(getattr(template, "value", template)) for template in config.selected_templates]


def _fmt_metric(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _dataset_rows(raw: dict[str, Any], scrubber: PhiScrubber) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in _as_items(raw, "dataset_summaries"):
        for cohort in summary.get("datasets") or []:
            if not isinstance(cohort, dict):
                continue
            rows.append(
                {
                    "task_id": summary.get("task_id"),
                    "role": summary.get("role", "main"),
                    "label": summary.get("label"),
                    "dataset_id": cohort.get("dataset_id"),
                    "name": scrubber.scrub(cohort.get("name")),
                    "task_type": cohort.get("task_type"),
                    "data_type": cohort.get("data_type"),
                    "aggregation_level": cohort.get("aggregation_level"),
                    "source_organ": scrubber.scrub(cohort.get("source_organ")),
                    "wsi_count": int(cohort.get("wsi_count") or 0),
                    "case_count": int(cohort.get("case_count") or 0),
                    "label_distribution": scrubber.scrub(cohort.get("label_distribution") or {}),
                    "split_distribution": scrubber.scrub(cohort.get("split_distribution") or {}),
                    "source_distribution": scrubber.scrub(cohort.get("source_distribution") or {}),
                    "vendors": scrubber.scrub(cohort.get("vendors") or []),
                    "magnifications": cohort.get("magnifications") or [],
                    "feature_extracted_count": int(cohort.get("feature_extracted_count") or 0),
                    "provenance": {
                        "raw_file": "evidence/raw_collected/dataset_summary.json",
                        "task_id": summary.get("task_id"),
                    },
                }
            )
    return rows


def _public_dataset_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in row.items()
            if key not in {"provenance", "dataset_id"} or key == "dataset_id"
        }
        for row in rows
    ]


def _public_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in row.items() if key != "provenance"} for row in rows]


def _split_rows(raw: dict[str, Any], scrubber: PhiScrubber) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in _as_items(raw, "split_summaries"):
        for bucket in summary.get("buckets") or []:
            if not isinstance(bucket, dict):
                continue
            rows.append(
                {
                    "task_id": summary.get("task_id"),
                    "role": summary.get("role", "main"),
                    "split": scrubber.scrub(bucket.get("split")),
                    "wsi_count": int(bucket.get("wsi_count") or 0),
                    "case_count": int(bucket.get("case_count") or 0),
                    "label_distribution": scrubber.scrub(bucket.get("label_distribution") or {}),
                }
            )
    return rows


def _model_rows(raw: dict[str, Any], scrubber: PhiScrubber) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in _as_items(raw, "model_summaries"):
        for model in summary.get("models") or []:
            if not isinstance(model, dict):
                continue
            rows.append(
                {
                    "task_id": summary.get("task_id"),
                    "role": summary.get("role", "main"),
                    "model_id": model.get("model_id"),
                    "model_name": scrubber.scrub(model.get("model_name")),
                    "classes": scrubber.scrub(model.get("classes") or []),
                    "feature_extractor": scrubber.scrub(model.get("feature_extractor")),
                    "aggregator": scrubber.scrub(model.get("aggregator")),
                    "is_default": model.get("is_default"),
                    "provenance": {
                        "raw_file": "evidence/raw_collected/model_summary.json",
                        "model_path": model.get("model_path"),
                        "config_path": model.get("config_path"),
                    },
                }
            )
    return rows


def _analysis_rows(raw: dict[str, Any], scrubber: PhiScrubber) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for summary in _as_items(raw, "analysis_summaries"):
        for analysis in summary.get("analyses") or []:
            if not isinstance(analysis, dict):
                continue
            rows.append(
                {
                    "task_id": summary.get("task_id"),
                    "role": summary.get("role", "main"),
                    "analysis_id": scrubber.scrub(analysis.get("analysis_id")),
                    "selected": analysis.get("analysis_id") == summary.get("selected_analysis_id"),
                    "results_count": analysis.get("results_count"),
                    "chart_kinds": sorted((analysis.get("chart_paths") or {}).keys()),
                    "provenance": {
                        "raw_file": "evidence/raw_collected/analysis_summary.json",
                        "analysis_dir": analysis.get("analysis_dir"),
                        "summary_path": analysis.get("summary_path"),
                        "results_path": analysis.get("results_path"),
                    },
                }
            )
    return rows


def _external_validation_rows(raw: dict[str, Any], scrubber: PhiScrubber) -> list[dict[str, Any]]:
    summary = raw.get("external_validation_summary") or {}
    rows = []
    for item in summary.get("items") or []:
        if isinstance(item, dict):
            rows.append(scrubber.scrub(item))
    return rows


def _missing_evidence(raw: dict[str, Any], scrubber: PhiScrubber) -> list[dict[str, Any]]:
    missing = raw.get("missing_evidence") or []
    return [scrubber.scrub(item) for item in missing if isinstance(item, dict)]


def _metric_entries(raw: dict[str, Any], scrubber: PhiScrubber) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for summary in _as_items(raw, "analysis_summaries"):
        task_id = str(summary.get("task_id") or "task")
        role = str(summary.get("role") or "main")
        selected_id = summary.get("selected_analysis_id")
        for analysis in summary.get("analyses") or []:
            if not isinstance(analysis, dict):
                continue
            if selected_id and analysis.get("analysis_id") != selected_id:
                continue
            for metric_name, value in _iter_metrics(analysis.get("summary") or {}):
                key = _safe_key(f"{role}.{metric_name}")
                suffix = 2
                unique = key
                while unique in entries:
                    unique = f"{key}_{suffix}"
                    suffix += 1
                entries[unique] = {
                    "key": unique,
                    "name": metric_name,
                    "value": value,
                    "formatted": _fmt_metric(value),
                    "task_id": task_id,
                    "role": role,
                    "analysis_id": scrubber.scrub(analysis.get("analysis_id")),
                    "provenance": {
                        "raw_file": "evidence/raw_collected/analysis_summary.json",
                        "summary_path": analysis.get("summary_path"),
                        "analysis_id": analysis.get("analysis_id"),
                    },
                }
    return entries


def _iter_metrics(payload: Any, prefix: str = "") -> list[tuple[str, float]]:
    metrics: list[tuple[str, float]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in {"chart_paths", "charts", "paths", "artifacts"}:
                continue
            path = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                if _METRIC_NAME_RE.search(path):
                    metrics.append((path, float(value)))
            elif isinstance(value, dict):
                metrics.extend(_iter_metrics(value, path))
    return metrics


def _public_metric(key: str, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": key,
        "name": item.get("name"),
        "formatted": item.get("formatted"),
        "task_id": item.get("task_id"),
        "role": item.get("role"),
        "analysis_id": item.get("analysis_id"),
    }


def _render_experimental_log(
    config: PaperConfig,
    private_lock: dict[str, Any],
    public_evidence: dict[str, Any],
) -> str:
    dataset_lines = [
        f"- {row.get('name') or row.get('dataset_id') or 'dataset'}: "
        f"{row.get('wsi_count', 0)} WSI / {row.get('case_count', 0)} cases"
        for row in public_evidence["datasets"]
    ]
    metric_lines = [
        f"- {metric['key']}: {metric.get('formatted')}"
        for metric in public_evidence["metrics"]
    ]
    if not dataset_lines:
        dataset_lines = ["- No dataset cohort evidence was available."]
    if not metric_lines:
        metric_lines = ["- No locked analysis metrics were available."]
    topic_section = "\n".join(topic_lines(public_evidence.get("topic")))
    missing_count = len(private_lock.get("missing_evidence") or [])
    return (
        "# Experimental Log\n\n"
        "## Run\n\n"
        f"- Paper ID: `{config.paper_id}`\n"
        f"- Title: {config.title or 'Untitled PathLab paper'}\n"
        f"- Collector status: {private_lock['collector']['status']}\n"
        f"- Missing evidence items: {missing_count}\n\n"
        "## Topic Context\n\n"
        + topic_section
        + "\n\n"
        "## Cohorts\n\n"
        + "\n".join(dataset_lines)
        + "\n\n## Locked Metrics\n\n"
        + "\n".join(metric_lines)
        + "\n\n## PHI Policy\n\n"
        "Public evidence, tables, and locked blocks are generated through the deterministic "
        "PHI scrubber. Raw paths, case identifiers, and institution names remain only in "
        "`evidence_lock.private.json`.\n"
    )
