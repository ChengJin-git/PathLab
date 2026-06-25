"""TCGA/GDC label resolution data skill.

This module is intentionally deterministic: an LLM may help select a
``LabelSpec``, but the emitted label values must come from TCGA/GDC metadata,
TCGA project IDs, or TCGA barcodes with provenance.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Iterable

from ..types import DatasetRecord, TaskProfile
from ..wsi_splits import build_classification_splits_from_labels
from .tcga_molecular import MolecularMutationResolver
from .types import LabelResolutionResult, LabelSpec

_SLIDE_SUFFIXES = (".svs", ".tif", ".tiff", ".ndpi", ".mrxs", ".scn")
_TCGA_DIAGNOSTIC_SLIDE_RE = re.compile(r"(?:^|-)DX\d+(?:[.-])", re.IGNORECASE)
_TCGA_CASE_RE = re.compile(r"^(TCGA-[A-Z0-9]{2}-[A-Z0-9]{4})", re.IGNORECASE)
_TCGA_SAMPLE_CODE_RE = re.compile(r"^TCGA-[A-Z0-9]{2}-[A-Z0-9]{4}-(\d{2})", re.IGNORECASE)

_TCGA_PROJECT_LABELS = {
    "TCGA-LUAD": "LUAD",
    "TCGA-LUSC": "LUSC",
}
_SAMPLE_TYPE_BY_CODE = {
    "01": "Primary Solid Tumor",
    "02": "Recurrent Solid Tumor",
    "03": "Primary Blood Derived Cancer",
    "06": "Metastatic",
    "10": "Blood Derived Normal",
    "11": "Solid Tissue Normal",
}
_MOLECULAR_MUTATION_GENES = ("EGFR", "KRAS", "TP53", "BRAF", "IDH1", "IDH2")


class TCGALabelResolutionSkill:
    """Resolve task-shaped labels for TCGA raw WSI cohorts."""

    name = "tcga_label_resolution"

    def can_handle(
        self,
        profile: TaskProfile,
        selected_records: Iterable[DatasetRecord],
    ) -> bool:
        if profile.task_type != "mil_classification":
            return False
        return any(_project_id(record) for record in selected_records)

    def plan(
        self,
        profile: TaskProfile,
        selected_records: Iterable[DatasetRecord],
    ) -> LabelSpec:
        records = list(selected_records)
        target_gene = _molecular_mutation_gene(profile)
        if target_gene:
            return LabelSpec(
                task_name=f"tcga_{target_gene.lower()}_mutation",
                label_type="molecular_mutation",
                target_gene=target_gene,
                fields=[target_gene],
                source_priority=[
                    "local_molecular_table",
                    "gdc_masked_somatic_mutation",
                ],
                join_key="case_submitter_id",
                split_group="case_submitter_id",
                min_coverage=0.8,
            )
        mapping = {
            project_id: _project_label(project_id)
            for project_id in (_project_id(r) for r in records)
            if project_id
        }
        return LabelSpec(
            task_name=_task_name(profile, mapping),
            label_type="project_subtype",
            class_mapping=mapping,
            source_priority=["cases.project.project_id", "tcga_barcode"],
            split_group="case_submitter_id",
        )

    def resolve(
        self,
        *,
        profile: TaskProfile,
        selected_records: list[DatasetRecord],
        raw_roots: dict[str, Path],
        workspace_root: Path,
        merged_wsi_dir: Path,
        label_spec: LabelSpec | None = None,
    ) -> LabelResolutionResult:
        label_spec = label_spec or self.plan(profile, selected_records)
        if label_spec.label_type == "molecular_mutation":
            return self._resolve_molecular_mutation(
                profile=profile,
                selected_records=selected_records,
                raw_roots=raw_roots,
                workspace_root=workspace_root,
                merged_wsi_dir=merged_wsi_dir,
                label_spec=label_spec,
            )
        if label_spec.label_type != "project_subtype":
            return _failed(label_spec, reason=f"unsupported_label_type:{label_spec.label_type}")

        prepared_root = Path(workspace_root) / ".dataset" / "mil_classification"
        labels_file = prepared_root / "labels.csv"
        splits_file = prepared_root / "splits.json"
        provenance_file = prepared_root / "label_provenance.json"
        patient_groups_file = prepared_root / "patient_groups.json"
        merged_wsi_dir = Path(merged_wsi_dir)
        prepared_root.mkdir(parents=True, exist_ok=True)
        merged_wsi_dir.mkdir(parents=True, exist_ok=True)

        prefixes = [f"{label}__" for label in label_spec.class_mapping.values() if label]
        _clear_prefixed_links(merged_wsi_dir, prefixes)

        rows: list[dict[str, str]] = []
        warnings: list[str] = []
        for record in selected_records:
            project_id = _project_id(record)
            label = label_spec.class_mapping.get(project_id) or _project_label(project_id)
            raw_value = raw_roots.get(record.dataset_id)
            raw_root = Path(raw_value) if raw_value is not None else None
            if not project_id or not label:
                warnings.append(f"missing_project_label:{record.dataset_id}")
                continue
            if raw_root is None or not raw_root.is_dir():
                warnings.append(f"missing_raw_root:{record.dataset_id}:{raw_root}")
                continue

            for slide in _diagnostic_or_all_slides(raw_root):
                dest = merged_wsi_dir / f"{label}__{slide.name}"
                _link_or_copy(slide, dest)
                slide_id = dest.stem
                case_id = _case_id_from_name(slide.name) or slide_id
                rows.append({
                    "slide_id": slide_id,
                    "label": label,
                    "case_id": case_id,
                    "project_id": project_id,
                    "file_name": slide.name,
                    "sample_type": _sample_type_from_name(slide.name),
                })

        rows.sort(key=lambda row: row["slide_id"])
        if not rows:
            return _failed(label_spec, reason="no_labeled_slides")

        with labels_file.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "slide_id", "label", "case_id", "project_id",
                    "file_name", "sample_type",
                ],
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)

        build_classification_splits_from_labels(
            labels_file,
            splits_file,
            group_column="case_id",
        )

        groups = {row["slide_id"]: row["case_id"] for row in rows}
        patient_groups_file.write_text(
            json.dumps({"split_group": "case_submitter_id", "groups": groups}, indent=2),
            encoding="utf-8",
        )

        class_counts = dict(Counter(row["label"] for row in rows))
        coverage = 1.0
        provenance = {
            "skill": self.name,
            "label_type": label_spec.label_type,
            "label_semantics": "tcga_project_subtype",
            "label_spec": label_spec.to_dict(),
            "n_slides": len(rows),
            "n_labeled": len(rows),
            "label_coverage": coverage,
            "class_counts": class_counts,
            "field_sources": {
                "label": "cases.project.project_id",
                "case_id": "tcga_barcode_submitter_id",
                "sample_type": "tcga_barcode_sample_type_code",
            },
            "warnings": warnings,
        }
        provenance_file.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

        return LabelResolutionResult(
            status="prepared",
            label_type=label_spec.label_type,
            label_semantics="tcga_project_subtype",
            wsi_dir=str(merged_wsi_dir),
            labels_file=str(labels_file),
            splits_file=str(splits_file),
            provenance_file=str(provenance_file),
            patient_groups_file=str(patient_groups_file),
            n_slides=len(rows),
            n_labeled=len(rows),
            label_coverage=coverage,
            class_counts=class_counts,
        )


    def _resolve_molecular_mutation(
        self,
        *,
        profile: TaskProfile,
        selected_records: list[DatasetRecord],
        raw_roots: dict[str, Path],
        workspace_root: Path,
        merged_wsi_dir: Path,
        label_spec: LabelSpec,
    ) -> LabelResolutionResult:
        target_gene = _normalize_gene(label_spec.target_gene)
        if not target_gene:
            return _failed(label_spec, reason="molecular_target_gene_missing")

        prepared_root = Path(workspace_root) / ".dataset" / "mil_classification"
        labels_file = prepared_root / "labels.csv"
        splits_file = prepared_root / "splits.json"
        provenance_file = prepared_root / "label_provenance.json"
        patient_groups_file = prepared_root / "patient_groups.json"
        merged_wsi_dir = Path(merged_wsi_dir)
        prepared_root.mkdir(parents=True, exist_ok=True)
        merged_wsi_dir.mkdir(parents=True, exist_ok=True)

        prefixes = [
            f"{_project_label(_project_id(record))}__"
            for record in selected_records
            if _project_id(record)
        ]
        _clear_prefixed_links(merged_wsi_dir, prefixes)

        slide_entries: list[dict[str, object]] = []
        warnings: list[str] = []
        for record in selected_records:
            project_id = _project_id(record)
            project_label = _project_label(project_id)
            raw_value = raw_roots.get(record.dataset_id)
            raw_root = Path(raw_value) if raw_value is not None else None
            if not project_id or not project_label:
                warnings.append(f"missing_project_label:{record.dataset_id}")
                continue
            if raw_root is None or not raw_root.is_dir():
                warnings.append(f"missing_raw_root:{record.dataset_id}:{raw_root}")
                continue
            for slide in _diagnostic_or_all_slides(raw_root):
                case_id = _case_id_from_name(slide.name)
                if not case_id:
                    warnings.append(f"missing_case_id:{slide.name}")
                    continue
                slide_entries.append({
                    "record": record,
                    "slide": slide,
                    "project_id": project_id,
                    "project_label": project_label,
                    "case_id": case_id,
                })

        if not slide_entries:
            return _failed(label_spec, reason="no_labeled_slides")

        case_ids = sorted({str(entry["case_id"]) for entry in slide_entries})
        molecular = MolecularMutationResolver().resolve(
            target_gene=target_gene,
            raw_roots=raw_roots,
            case_ids=case_ids,
        )
        if molecular.status != "prepared":
            return _failed(label_spec, reason=molecular.reason)
        warnings.extend(molecular.warnings)

        rows: list[dict[str, str]] = []
        missing_cases: list[str] = []
        for entry in slide_entries:
            case_id = str(entry["case_id"])
            label = molecular.case_labels.get(case_id, "")
            if not label:
                missing_cases.append(case_id)
                continue
            slide = entry["slide"]
            assert isinstance(slide, Path)
            dest = merged_wsi_dir / f"{entry['project_label']}__{slide.name}"
            _link_or_copy(slide, dest)
            rows.append({
                "slide_id": dest.stem,
                "label": label,
                "case_id": case_id,
                "project_id": str(entry["project_id"]),
                "file_name": slide.name,
                "sample_type": _sample_type_from_name(slide.name),
                "target_gene": target_gene,
                "molecular_source": molecular.source_kind,
            })

        rows.sort(key=lambda row: row["slide_id"])
        coverage = len(rows) / len(slide_entries) if slide_entries else 0.0
        if coverage < label_spec.min_coverage:
            return _failed(
                label_spec,
                reason=(
                    "molecular_label_coverage_below_threshold:"
                    f"{target_gene}:{coverage:.3f}<{label_spec.min_coverage:.3f}"
                ),
            )
        class_counts = dict(Counter(row["label"] for row in rows))
        if len(class_counts) < 2:
            return _failed(label_spec, reason=f"molecular_single_class:{target_gene}")

        with labels_file.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "slide_id", "label", "case_id", "project_id", "file_name",
                    "sample_type", "target_gene", "molecular_source",
                ],
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)

        build_classification_splits_from_labels(
            labels_file,
            splits_file,
            group_column="case_id",
        )

        groups = {row["slide_id"]: row["case_id"] for row in rows}
        patient_groups_file.write_text(
            json.dumps({"split_group": "case_submitter_id", "groups": groups}, indent=2),
            encoding="utf-8",
        )
        provenance = {
            "skill": self.name,
            "label_type": label_spec.label_type,
            "label_semantics": f"tcga_molecular_mutation:{target_gene}",
            "target_gene": target_gene,
            "label_spec": label_spec.to_dict(),
            "source_path": molecular.source_path,
            "source_kind": molecular.source_kind,
            "n_slides": len(slide_entries),
            "n_labeled": len(rows),
            "label_coverage": coverage,
            "class_counts": class_counts,
            "join_key": "case_submitter_id",
            "missing_cases": sorted(set(missing_cases)),
            "field_sources": {
                "label": f"molecular mutation table gene={target_gene}",
                "case_id": "tcga_barcode_submitter_id",
            },
            "warnings": warnings,
        }
        provenance_file.write_text(json.dumps(provenance, indent=2), encoding="utf-8")

        return LabelResolutionResult(
            status="prepared",
            label_type=label_spec.label_type,
            label_semantics=f"tcga_molecular_mutation:{target_gene}",
            wsi_dir=str(merged_wsi_dir),
            labels_file=str(labels_file),
            splits_file=str(splits_file),
            provenance_file=str(provenance_file),
            patient_groups_file=str(patient_groups_file),
            n_slides=len(slide_entries),
            n_labeled=len(rows),
            label_coverage=coverage,
            class_counts=class_counts,
        )


def _failed(label_spec: LabelSpec, *, reason: str) -> LabelResolutionResult:
    return LabelResolutionResult(
        status="failed",
        label_type=label_spec.label_type,
        label_semantics="",
        wsi_dir="",
        labels_file="",
        splits_file="",
        provenance_file="",
        patient_groups_file="",
        n_slides=0,
        n_labeled=0,
        label_coverage=0.0,
        class_counts={},
        reason=reason,
    )


def _task_name(profile: TaskProfile, mapping: dict[str, str]) -> str:
    if {"LUAD", "LUSC"}.issubset(set(mapping.values())):
        return "tcga_nsclc_subtype"
    return f"tcga_{profile.prediction_target or 'project_subtype'}"


def _molecular_mutation_gene(profile: TaskProfile) -> str:
    text = " ".join([
        profile.prediction_target or "",
        " ".join(profile.required_label_keywords or []),
        " ".join(profile.dataset_keywords or []),
    ])
    compact = re.sub(r"[^a-z0-9]+", " ", text.lower())
    for gene in _MOLECULAR_MUTATION_GENES:
        if gene.lower() in compact.split():
            return gene
    for gene in _MOLECULAR_MUTATION_GENES:
        if profile.prediction_target.lower() == gene.lower():
            return gene
    return ""


def _normalize_gene(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()


def _project_id(record: DatasetRecord) -> str:
    value = str(getattr(record.download, "remote_id", "") or "").strip().upper()
    if re.fullmatch(r"TCGA-[A-Z0-9]{2,12}", value):
        return value
    for text in [record.dataset_id, record.name, " ".join(record.tags or [])]:
        match = re.search(r"\bTCGA-[A-Z0-9]{2,12}\b", str(text or ""), re.IGNORECASE)
        if match:
            return match.group(0).upper()
    return ""


def _project_label(project_id: str) -> str:
    if not project_id:
        return ""
    return _TCGA_PROJECT_LABELS.get(project_id, project_id.removeprefix("TCGA-"))


def _is_wsi(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in _SLIDE_SUFFIXES


def _is_diagnostic_slide(path: Path) -> bool:
    return bool(_TCGA_DIAGNOSTIC_SLIDE_RE.search(path.name))


def _diagnostic_or_all_slides(raw_root: Path) -> list[Path]:
    slides = sorted(p for p in Path(raw_root).rglob("*") if _is_wsi(p))
    diagnostic = [p for p in slides if _is_diagnostic_slide(p)]
    if diagnostic:
        return diagnostic
    # Tests and manually mounted non-TCGA fixtures may not use TCGA barcode
    # names. Real TCGA barcodes with no DX slide should fail closed.
    if any(_case_id_from_name(p.name) for p in slides):
        return []
    return slides


def _case_id_from_name(name: str) -> str:
    match = _TCGA_CASE_RE.match(name or "")
    return match.group(1).upper() if match else ""


def _sample_type_from_name(name: str) -> str:
    match = _TCGA_SAMPLE_CODE_RE.match(name or "")
    if not match:
        return ""
    return _SAMPLE_TYPE_BY_CODE.get(match.group(1), match.group(1))


def _link_or_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        if dest.exists() or dest.is_symlink():
            dest.unlink()
        os.symlink(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def _clear_prefixed_links(root: Path, prefixes: list[str]) -> None:
    if not prefixes or not root.exists():
        return
    for path in root.iterdir():
        if path.is_file() or path.is_symlink():
            if any(path.name.startswith(prefix) for prefix in prefixes):
                try:
                    path.unlink()
                except OSError:
                    pass
