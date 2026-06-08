"""Local TCGA molecular label parsing helpers."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

_TABLE_SUFFIXES = {".csv", ".tsv", ".txt", ".maf"}
_TABLE_NAME_TOKENS = (
    "mutation", "mutations", "molecular", "maf", "somatic", "variant", "variants",
)
_CASE_COLUMNS = (
    "case_id", "submitter_id", "patient_id", "bcr_patient_barcode",
    "tumor_sample_barcode", "Tumor_Sample_Barcode", "sample_id", "Sample_ID",
)
_GENE_COLUMNS = ("gene", "Gene", "hugo_symbol", "Hugo_Symbol", "symbol", "Symbol")
_VARIANT_COLUMNS = (
    "variant_classification", "Variant_Classification", "mutation",
    "Mutation", "variant", "Variant", "effect", "Effect",
)
_POSITIVE_VALUES = {
    "1", "true", "yes", "y", "positive", "pos", "mut", "mutant", "mutated",
    "mutation", "altered", "missense_mutation", "nonsense_mutation",
    "frame_shift_del", "frame_shift_ins", "in_frame_del", "in_frame_ins",
    "splice_site", "translation_start_site", "nonstop_mutation",
}
_NEGATIVE_VALUES = {
    "0", "false", "no", "n", "negative", "neg", "wt", "wildtype", "wild_type",
    "wild-type", "none", "not_mutated", "unmutated",
}
_SILENT_VARIANTS = {
    "", "silent", "intron", "igr", "rna", "3'utr", "5'utr", "3utr", "5utr",
    "flank", "targeted_region", "unknown",
}
_TCGA_CASE_RE = re.compile(r"^(TCGA-[A-Z0-9]{2}-[A-Z0-9]{4})", re.IGNORECASE)


@dataclass(frozen=True)
class MolecularMutationLabelResult:
    status: str
    target_gene: str
    case_labels: dict[str, str] = field(default_factory=dict)
    source_path: str = ""
    source_kind: str = ""
    reason: str = ""
    warnings: list[str] = field(default_factory=list)


class MolecularMutationResolver:
    """Resolve binary mutant/wildtype case labels from local TCGA tables."""

    def resolve(
        self,
        *,
        target_gene: str,
        raw_roots: dict[str, Path],
        case_ids: list[str],
    ) -> MolecularMutationLabelResult:
        gene = _normalize_gene(target_gene)
        if not gene:
            return MolecularMutationLabelResult(
                status="failed",
                target_gene="",
                reason="molecular_target_gene_missing",
            )
        tables = _find_candidate_tables(raw_roots)
        if not tables:
            return MolecularMutationLabelResult(
                status="failed",
                target_gene=gene,
                reason=f"molecular_table_not_found:{gene}",
            )

        gene_missing = False
        last_warnings: list[str] = []
        for table in tables:
            parsed = _parse_table(table, gene=gene, case_ids=case_ids)
            last_warnings.extend(parsed.warnings)
            if parsed.status == "prepared":
                return parsed
            if parsed.reason == f"molecular_gene_not_found:{gene}":
                gene_missing = True
            elif parsed.reason.startswith("molecular_label_conflict"):
                return parsed

        reason = f"molecular_gene_not_found:{gene}" if gene_missing else f"molecular_table_unusable:{gene}"
        return MolecularMutationLabelResult(
            status="failed",
            target_gene=gene,
            reason=reason,
            warnings=last_warnings,
        )


def _find_candidate_tables(raw_roots: dict[str, Path]) -> list[Path]:
    roots: list[Path] = []
    for raw in raw_roots.values():
        raw_path = Path(raw)
        for candidate in (raw_path.parent, raw_path, raw_path.parent.parent):
            if candidate.is_dir() and candidate not in roots:
                roots.append(candidate)

    out: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        visited = 0
        try:
            iterator = root.rglob("*")
            for path in iterator:
                visited += 1
                if visited > 4096:
                    break
                if not path.is_file():
                    continue
                if path.suffix.lower() not in _TABLE_SUFFIXES:
                    continue
                name = path.name.lower()
                if not any(token in name for token in _TABLE_NAME_TOKENS):
                    continue
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    out.append(path)
        except OSError:
            continue
    return sorted(out)


def _parse_table(
    path: Path,
    *,
    gene: str,
    case_ids: list[str],
) -> MolecularMutationLabelResult:
    rows = _read_rows(path)
    if not rows:
        return MolecularMutationLabelResult(
            status="failed",
            target_gene=gene,
            reason=f"molecular_table_empty:{path.name}",
        )
    fieldnames = {str(k or "") for row in rows for k in row.keys()}
    gene_col = _first_existing(fieldnames, _GENE_COLUMNS)
    if gene_col:
        return _parse_long_table(path, rows, gene=gene, gene_col=gene_col, case_ids=case_ids)
    return _parse_wide_table(path, rows, gene=gene)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as fh:
        sample = fh.read(4096)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
        except csv.Error:
            dialect = csv.excel_tab if path.suffix.lower() in {".tsv", ".maf", ".txt"} else csv.excel
        return [dict(row) for row in csv.DictReader(fh, dialect=dialect)]


def _parse_wide_table(
    path: Path,
    rows: list[dict[str, str]],
    *,
    gene: str,
) -> MolecularMutationLabelResult:
    fieldnames = {str(k or "") for row in rows for k in row.keys()}
    target_col = _target_status_column(fieldnames, gene)
    if not target_col:
        return MolecularMutationLabelResult(
            status="failed",
            target_gene=gene,
            reason=f"molecular_gene_not_found:{gene}",
        )

    labels: dict[str, str] = {}
    warnings: list[str] = []
    for row in rows:
        case_id = _case_id_from_row(row)
        if not case_id:
            warnings.append(f"missing_case_id:{path.name}")
            continue
        label = _label_from_value(row.get(target_col, ""))
        if not label:
            continue
        previous = labels.get(case_id)
        if previous and previous != label:
            return MolecularMutationLabelResult(
                status="failed",
                target_gene=gene,
                reason=f"molecular_label_conflict:{gene}:{case_id}",
                source_path=str(path),
                source_kind="local_molecular_table",
            )
        labels[case_id] = label

    if not labels:
        return MolecularMutationLabelResult(
            status="failed",
            target_gene=gene,
            reason=f"molecular_no_labeled_cases:{gene}",
            source_path=str(path),
            source_kind="local_molecular_table",
            warnings=warnings,
        )
    return MolecularMutationLabelResult(
        status="prepared",
        target_gene=gene,
        case_labels=labels,
        source_path=str(path),
        source_kind="local_molecular_table",
        warnings=warnings,
    )


def _parse_long_table(
    path: Path,
    rows: list[dict[str, str]],
    *,
    gene: str,
    gene_col: str,
    case_ids: list[str],
) -> MolecularMutationLabelResult:
    variant_col = _first_existing({str(k or "") for row in rows for k in row.keys()}, _VARIANT_COLUMNS)
    target_seen = False
    mutated_cases: set[str] = set()
    warnings: list[str] = []
    for row in rows:
        row_gene = _normalize_gene(row.get(gene_col, ""))
        if row_gene != gene:
            continue
        target_seen = True
        case_id = _case_id_from_row(row)
        if not case_id:
            warnings.append(f"missing_case_id:{path.name}")
            continue
        variant_value = row.get(variant_col, "") if variant_col else "mutation"
        if _is_non_silent_variant(variant_value):
            mutated_cases.add(case_id)

    if not target_seen:
        return MolecularMutationLabelResult(
            status="failed",
            target_gene=gene,
            reason=f"molecular_gene_not_found:{gene}",
            source_path=str(path),
            source_kind="local_maf_table",
            warnings=warnings,
        )

    labels = {
        case_id: ("mutant" if case_id in mutated_cases else "wildtype")
        for case_id in case_ids
    }
    return MolecularMutationLabelResult(
        status="prepared",
        target_gene=gene,
        case_labels=labels,
        source_path=str(path),
        source_kind="local_maf_table",
        warnings=warnings,
    )


def _first_existing(fieldnames: set[str], aliases: tuple[str, ...]) -> str:
    lower_to_original = {f.lower(): f for f in fieldnames}
    for alias in aliases:
        found = lower_to_original.get(alias.lower())
        if found:
            return found
    return ""


def _target_status_column(fieldnames: set[str], gene: str) -> str:
    norm_gene = _compact(gene)
    candidates: list[str] = []
    for field in fieldnames:
        compact = _compact(field)
        if compact == norm_gene:
            candidates.append(field)
        elif compact.startswith(norm_gene) and any(tok in compact for tok in ("mutation", "mut", "status")):
            candidates.append(field)
    return sorted(candidates, key=lambda s: (len(s), s))[0] if candidates else ""


def _case_id_from_row(row: dict[str, str]) -> str:
    for key in _CASE_COLUMNS:
        for actual, value in row.items():
            if actual.lower() != key.lower():
                continue
            case_id = _case_id_from_value(value)
            if case_id:
                return case_id
    for value in row.values():
        case_id = _case_id_from_value(value)
        if case_id:
            return case_id
    return ""


def _case_id_from_value(value: object) -> str:
    text = str(value or "").strip().upper()
    match = _TCGA_CASE_RE.match(text)
    return match.group(1) if match else ""


def _label_from_value(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    norm = re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")
    if norm in _POSITIVE_VALUES:
        return "mutant"
    if norm in _NEGATIVE_VALUES:
        return "wildtype"
    if "mutat" in norm and "not" not in norm and "unmut" not in norm:
        return "mutant"
    return ""


def _is_non_silent_variant(value: object) -> bool:
    norm = re.sub(r"[^a-z0-9']+", "_", str(value or "").lower()).strip("_")
    if norm in _SILENT_VARIANTS:
        return False
    return bool(norm)


def _normalize_gene(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).upper()


def _compact(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
