"""Deterministic Jinja2 renderer for evidence-locked LaTeX blocks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_DEFAULT_TEMPLATE_ID = "miccai"
_SUPPORTED_TEMPLATE_IDS = {"miccai", "nature_scientific_reports"}
_LATEX_CMD_SPLIT_RE = re.compile(r"[^A-Za-z]+")
_DIGIT_WORDS = {
    "0": "Zero",
    "1": "One",
    "2": "Two",
    "3": "Three",
    "4": "Four",
    "5": "Five",
    "6": "Six",
    "7": "Seven",
    "8": "Eight",
    "9": "Nine",
}


@dataclass(frozen=True)
class LockedBlockRenderResult:
    """Rendered deterministic tables and locked blocks for one template family."""

    template_id: str
    tables: dict[str, str]
    locked_blocks: dict[str, str]


def latex_cmd_key(value: str) -> str:
    """Return a letters-only suffix that is legal inside LaTeX command names."""
    spelled = "".join(_DIGIT_WORDS.get(ch, ch) for ch in value)
    parts = _LATEX_CMD_SPLIT_RE.split(spelled)
    cleaned = "".join(part.capitalize() for part in parts if part)
    return cleaned or "Item"


def letters_suffix(index: int) -> str:
    """Return A, B, ..., Z, AA, AB... using letters only."""
    if index <= 0:
        raise ValueError("suffix index must be positive")
    chars: list[str] = []
    value = index
    while value:
        value -= 1
        chars.append(chr(ord("A") + value % 26))
        value //= 26
    return "".join(reversed(chars))


def latex_escape(value: Any) -> str:
    """Escape a value with the same deterministic policy used by Phase 03."""
    text = "" if value is None else str(value)
    return (
        text.replace("\\", r"\textbackslash{}")
        .replace("&", r"\&")
        .replace("%", r"\%")
        .replace("$", r"\$")
        .replace("#", r"\#")
        .replace("_", r"\_")
        .replace("{", r"\{")
        .replace("}", r"\}")
    )


def _template_id_value(template_id: Any | None) -> str:
    value = getattr(template_id, "value", template_id) or _DEFAULT_TEMPLATE_ID
    return str(value)


def _template_root() -> Path:
    return Path(str(resources.files("pathlab_paper_agent") / "templates" / "locked_blocks"))


def _ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else f"{text}\n"


def _distribution_text(payload: Any) -> str:
    if not isinstance(payload, dict) or not payload:
        return "--"
    return ", ".join(f"{key}: {value}" for key, value in sorted(payload.items()))


class LockedBlockRenderer:
    """Render paper-facing locked blocks without consulting an LLM.

    M5 owns only template selection and deterministic rendering. Section order is
    handled later by the venue template renderer and section-writing milestones.
    """

    def __init__(self, template_id: Any | None = None, *, template_root: Path | None = None) -> None:
        self.template_id = _template_id_value(template_id)
        if self.template_id not in _SUPPORTED_TEMPLATE_IDS:
            known = ", ".join(sorted(_SUPPORTED_TEMPLATE_IDS))
            raise ValueError(f"Unknown locked-block template {self.template_id!r}. Known templates: {known}")
        self.template_root = template_root or _template_root()
        self.template_dir = self.template_root / self.template_id
        if not self.template_dir.is_dir():
            raise FileNotFoundError(f"Locked-block template directory missing: {self.template_dir}")
        self._env = self._build_env()

    def render(
        self,
        *,
        datasets: list[dict[str, Any]],
        splits: list[dict[str, Any]],
        models: list[dict[str, Any]],
        metrics: dict[str, dict[str, Any]],
        external_validation: list[dict[str, Any]],
        missing_evidence: list[dict[str, Any]],
    ) -> LockedBlockRenderResult:
        """Render tables and locked blocks from already-scrubbed evidence rows."""
        return LockedBlockRenderResult(
            template_id=self.template_id,
            tables=self.render_tables(
                datasets=datasets,
                splits=splits,
                metrics=metrics,
                external_validation=external_validation,
            ),
            locked_blocks=self.render_locked_blocks(
                datasets=datasets,
                models=models,
                metrics=metrics,
                external_validation=external_validation,
                missing_evidence=missing_evidence,
            ),
        )

    def render_tables(
        self,
        *,
        datasets: list[dict[str, Any]],
        splits: list[dict[str, Any]],
        metrics: dict[str, dict[str, Any]],
        external_validation: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Render deterministic booktabs tables consumed by venue templates."""
        dataset_rows = [["Dataset", "WSI", "Cases", "Labels"]]
        dataset_rows.extend(
            [
                row.get("name") or row.get("dataset_id") or "dataset",
                row.get("wsi_count", 0),
                row.get("case_count", 0),
                _distribution_text(row.get("label_distribution")),
            ]
            for row in datasets
        )
        if len(dataset_rows) == 1:
            dataset_rows.append(["No cohort evidence", 0, 0, "--"])

        metric_rows = [["Metric", "Value", "Task"]]
        metric_rows.extend(
            [item.get("name"), item.get("formatted"), item.get("task_id")]
            for item in metrics.values()
        )
        if len(metric_rows) == 1:
            metric_rows.append(["No locked metrics", "--", "--"])

        split_rows = [["Split", "WSI", "Cases", "Labels"]]
        split_rows.extend(
            [
                row.get("split"),
                row.get("wsi_count", 0),
                row.get("case_count", 0),
                _distribution_text(row.get("label_distribution")),
            ]
            for row in splits
        )
        if len(split_rows) == 1:
            split_rows.append(["No split evidence", 0, 0, "--"])

        ext_rows = [["Task", "Status", "Total WSI"]]
        ext_rows.extend(
            [row.get("task_id"), row.get("status"), row.get("total_wsi") or "--"]
            for row in external_validation
        )
        if len(ext_rows) == 1:
            ext_rows.append(["No external validation", "--", "--"])

        return {
            "table_1_dataset.tex": self._render_tabular(dataset_rows, columns="llll"),
            "table_2_main_results.tex": self._render_tabular(metric_rows, columns="lll"),
            "table_3_per_class.tex": self._render_tabular(split_rows, columns="llll"),
            "table_4_ablation.tex": self._render_tabular(
                [["Ablation", "Status"], ["No ablation evidence", "--"]]
            ),
            "table_5_external_validation.tex": self._render_tabular(ext_rows, columns="lll"),
        }

    def render_locked_blocks(
        self,
        *,
        datasets: list[dict[str, Any]],
        models: list[dict[str, Any]],
        metrics: dict[str, dict[str, Any]],
        external_validation: list[dict[str, Any]],
        missing_evidence: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Render deterministic locked-block snippets for section agents."""
        total_wsi = sum(int(row.get("wsi_count") or 0) for row in datasets)
        total_cases = sum(int(row.get("case_count") or 0) for row in datasets)
        model_bits = []
        for model in models:
            desc = model.get("model_name") or model.get("model_id") or "model"
            extractor = model.get("feature_extractor")
            aggregator = model.get("aggregator")
            if extractor or aggregator:
                desc = (
                    f"{desc} ({extractor or 'feature extractor not recorded'}, "
                    f"{aggregator or 'aggregator not recorded'})"
                )
            model_bits.append(str(desc))
        metric_bits = [f"{item.get('name')}: {item.get('formatted')}" for item in metrics.values()]
        external_bits = []
        for row in external_validation:
            task = row.get("label") or row.get("task_id") or "external validation"
            status = row.get("status") or "unknown"
            extval_wsi = row.get("total_wsi")
            analysis_status = row.get("analysis_status")
            desc = f"{task}: {status}"
            if extval_wsi is not None:
                desc = f"{desc}, {extval_wsi} WSI"
            if analysis_status:
                desc = f"{desc}, analysis {analysis_status}"
            external_bits.append(desc)
        missing_note = (
            f"{len(missing_evidence)} missing evidence item(s) remain."
            if missing_evidence
            else "No blocking missing evidence item was reported by the collector."
        )
        return {
            "dataset_block.tex": self._render(
                "dataset_block.tex.j2",
                total_wsi=total_wsi,
                total_cases=total_cases,
            ),
            "method_block.tex": self._render(
                "method_block.tex.j2",
                model_text=(
                    "; ".join(latex_escape(item) for item in model_bits)
                    if model_bits
                    else "No trained model evidence was available."
                ),
            ),
            "results_block.tex": self._render(
                "results_block.tex.j2",
                metric_text=(
                    "; ".join(latex_escape(item) for item in metric_bits)
                    if metric_bits
                    else "No locked analysis metrics were available."
                ),
            ),
            "metrics_macros.tex": self.render_metrics_macros(metrics),
            "external_block.tex": self._render(
                "external_block.tex.j2",
                external_text=(
                    "; ".join(latex_escape(item) for item in external_bits)
                    if external_bits
                    else "No external validation evidence was available."
                ),
            ),
            "evidence_gaps.tex": self._render(
                "evidence_gaps.tex.j2",
                missing_note=latex_escape(missing_note),
            ),
        }

    def render_metrics_macros(self, metrics: dict[str, dict[str, Any]]) -> str:
        """Render metric macros while preserving letters-only LaTeX command names."""
        seen: set[str] = set()
        macro_lines: list[str] = []
        for key, item in metrics.items():
            base = latex_cmd_key(key)
            cmd = base
            suffix = 0
            while cmd in seen:
                suffix += 1
                cmd = f"{base}{letters_suffix(suffix)}"
            seen.add(cmd)
            macro_lines.append(f"\\newcommand{{\\metric{cmd}}}{{{latex_escape(item.get('formatted'))}}}")
        return self._render("metrics_macros.tex.j2", macro_lines=macro_lines)

    def _build_env(self) -> Environment:
        env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=False,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        env.filters["latex_row"] = lambda row: " & ".join(latex_escape(value) for value in row)
        return env

    def _render(self, name: str, **context: Any) -> str:
        rendered = self._env.get_template(name).render(**context)
        return _ensure_trailing_newline(rendered)

    def _render_tabular(self, rows: list[list[Any]], *, columns: str = "ll") -> str:
        return self._render("tabular.tex.j2", rows=rows, columns=columns)
