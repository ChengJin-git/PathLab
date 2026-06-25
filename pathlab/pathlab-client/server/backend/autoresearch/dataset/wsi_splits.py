"""Deterministic train/val/test split builder for raw WSI label files.

Plan-2026-04-30 data-readiness Task 4: when a user mounts (or acquisition
prepares) raw WSI + labels but no ``splits.json``, generate one
deterministically before MIL/survival training is allowed. Without this,
``raw_wsi_ready`` would lie — ``classification_template.py`` reads
``SPLITS_FILE`` directly and would crash.

Column aliases are intentionally generous so PANDA-style headers
(``image_id``, ``isup_grade``) just work without the user re-naming
columns. Empty / underspecified labels surface as ``ValueError`` with
a stable code so readiness can render an actionable note.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable


SLIDE_ID_COLUMNS = (
    "slide_id", "wsi_id", "image_id", "case_id",
    "slide", "filename", "file",
)
LABEL_COLUMNS = ("label", "class", "grade", "isup_grade", "gleason_score")
SPLIT_COLUMNS = ("split", "fold", "set")
# Plan-2026-04-30 data-readiness review P2-6: survival aliases.
TIME_COLUMNS = (
    "survival_time", "time", "duration",
    "days_to_event", "days_to_death", "days_to_last_follow_up",
)
EVENT_COLUMNS = ("event_status", "event", "censor", "vital_status")

_VALID_SPLIT_VALUES = {"train", "val", "validation", "test"}


def _normalize_split(value: str) -> str:
    v = (value or "").strip().lower()
    if v == "validation":
        return "val"
    return v


def _read_label_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV/TSV/JSON rows and normalize column aliases.

    Returns rows with keys ``slide_id``, ``label``, and optional ``split``.
    Skips rows where slide_id or label is empty.
    """
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text())
        if isinstance(raw, dict) and "rows" in raw:
            raw = raw["rows"]
        if not isinstance(raw, list):
            return []
        rows = [r for r in raw if isinstance(r, dict)]
    else:
        with path.open("r", newline="", encoding="utf-8") as fh:
            sample = fh.read(2048)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(fh, dialect=dialect)
            rows = list(reader)

    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slide = ""
        for key in SLIDE_ID_COLUMNS:
            if row.get(key):
                slide = str(row[key]).strip()
                break
        label = ""
        for key in LABEL_COLUMNS:
            if row.get(key) is not None and str(row[key]).strip() != "":
                label = str(row[key]).strip()
                break
        if not slide or not label:
            continue
        rec: dict[str, str] = {"slide_id": slide, "label": label}
        for key, value in row.items():
            if key and value is not None:
                rec.setdefault(str(key).strip(), str(value).strip())
        for key in SPLIT_COLUMNS:
            if row.get(key):
                rec["split"] = _normalize_split(str(row[key]))
                break
        out.append(rec)
    return out


def _encode_labels(slide_to_label: dict[str, str]) -> dict[str, int]:
    """Map raw label values to integer IDs.

    If every label parses as an integer (e.g. ISUP grades 0..5), preserve
    the numeric value — that's what downstream MIL templates expect for
    grading targets. Otherwise fall back to sorted-order encoding.
    """
    values = list(slide_to_label.values())
    try:
        return {sid: int(lab) for sid, lab in slide_to_label.items()}
    except (ValueError, TypeError):
        pass
    distinct = sorted(set(values))
    encoder = {v: i for i, v in enumerate(distinct)}
    return {sid: encoder[lab] for sid, lab in slide_to_label.items()}


def _split_map_from_rows(rows: Iterable[dict[str, str]]) -> dict[str, str] | None:
    """Honor an existing ``split`` column if present and complete; else None."""
    split_map: dict[str, str] = {}
    saw_any = False
    for row in rows:
        sp = row.get("split", "")
        if not sp:
            return None  # incomplete coverage → fall back to deterministic
        if sp not in _VALID_SPLIT_VALUES and sp != "val":
            return None
        if sp == "validation":
            sp = "val"
        split_map[row["slide_id"]] = sp
        saw_any = True
    return split_map if saw_any else None


def _deterministic_split(
    slide_ids: list[str],
    *,
    seed: int = 42,
) -> dict[str, str]:
    """Hash-based stable split with non-empty guarantee.

    Plan-2026-04-30 data-readiness review P1-5: independent per-slide
    hashing can leave val/test empty for small n. Sort slides by hash,
    then assign by index → train ~70%, val ~15%, test ~15%, AND every
    split has at least one slide when ``len(slide_ids) >= 3``.
    """
    if not slide_ids:
        return {}
    ranked = sorted(
        slide_ids,
        key=lambda s: hashlib.sha256(f"{seed}:{s}".encode()).digest(),
    )
    n = len(ranked)
    out: dict[str, str] = {}
    if n == 1:
        out[ranked[0]] = "train"
        return out
    if n == 2:
        out[ranked[0]] = "train"
        out[ranked[1]] = "val"
        return out
    # n >= 3: guaranteed non-empty splits.
    n_test = max(1, n // 7)        # ~15%, at least 1
    n_val = max(1, n // 7)
    n_train = n - n_val - n_test
    if n_train < 1:
        # Pathological tiny n; rebalance to keep at least 1 in each.
        n_train, n_val, n_test = 1, 1, n - 2
    cursor = 0
    for sid in ranked[cursor : cursor + n_train]:
        out[sid] = "train"
    cursor += n_train
    for sid in ranked[cursor : cursor + n_val]:
        out[sid] = "val"
    cursor += n_val
    for sid in ranked[cursor:]:
        out[sid] = "test"
    return out


def _deterministic_group_split(
    rows: Iterable[dict[str, str]],
    *,
    group_column: str,
    seed: int = 42,
) -> tuple[dict[str, str], dict[str, str]]:
    """Assign all slides from the same group to the same split."""
    slide_to_group: dict[str, str] = {}
    groups: dict[str, list[str]] = {}
    for row in rows:
        slide_id = row["slide_id"]
        group = str(row.get(group_column) or "").strip() or slide_id
        slide_to_group[slide_id] = group
        groups.setdefault(group, []).append(slide_id)
    if len(groups) < 3:
        raise ValueError("too_few_split_groups")

    group_split = _deterministic_split(list(groups), seed=seed)
    split_map: dict[str, str] = {}
    for group, slide_ids in groups.items():
        split = group_split.get(group, "train")
        for slide_id in slide_ids:
            split_map[slide_id] = split
    return split_map, slide_to_group


def build_classification_splits_from_labels(
    labels_file: str | Path,
    output_file: str | Path,
    *,
    seed: int = 42,
    group_column: str = "",
) -> Path:
    """Read ``labels_file`` and write a deterministic ``splits.json``.

    Raises ``ValueError("no_labeled_slides")`` for empty input,
    ``ValueError("too_few_labeled_slides")`` if there are fewer than 3
    labeled rows (downstream MIL templates need every split populated).
    """
    rows = _read_label_rows(Path(labels_file))
    if not rows:
        raise ValueError("no_labeled_slides")
    if len(rows) < 3:
        raise ValueError("too_few_labeled_slides")

    slide_to_label = {row["slide_id"]: row["label"] for row in rows}
    labels = _encode_labels(slide_to_label)

    slide_to_group: dict[str, str] = {}
    if group_column:
        split_map, slide_to_group = _deterministic_group_split(
            rows,
            group_column=group_column,
            seed=seed,
        )
    else:
        explicit = _split_map_from_rows(rows)
        split_map = explicit or _deterministic_split(list(labels.keys()), seed=seed)

    payload = {
        "train": [sid for sid, sp in split_map.items() if sp == "train"],
        "val": [sid for sid, sp in split_map.items() if sp == "val"],
        "test": [sid for sid, sp in split_map.items() if sp == "test"],
        "labels": labels,
    }
    if slide_to_group:
        payload["split_groups"] = slide_to_group

    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out


# ----------------------------------------------------- P2-6: survival splits


def _read_survival_label_rows(path: Path) -> list[dict[str, str]]:
    """Read labels with slide_id + time + event aliases.

    Plan-2026-04-30 data-readiness review P2-6: same generosity for
    column aliases as the classification reader, so PANDA / TCGA-style
    survival headers (``image_id`` + ``days_to_event`` + ``vital_status``)
    just work.
    """
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text())
        if isinstance(raw, dict) and "rows" in raw:
            raw = raw["rows"]
        rows = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
    else:
        with path.open("r", newline="", encoding="utf-8") as fh:
            sample = fh.read(2048)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",\t")
            except csv.Error:
                dialect = csv.excel
            rows = list(csv.DictReader(fh, dialect=dialect))

    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slide = ""
        for key in SLIDE_ID_COLUMNS:
            if row.get(key):
                slide = str(row[key]).strip()
                break
        time_value = ""
        for key in TIME_COLUMNS:
            if row.get(key) is not None and str(row[key]).strip() != "":
                time_value = str(row[key]).strip()
                break
        event_value = ""
        for key in EVENT_COLUMNS:
            if row.get(key) is not None and str(row[key]).strip() != "":
                event_value = str(row[key]).strip()
                break
        if not slide or not time_value or not event_value:
            continue
        rec: dict[str, str] = {
            "slide_id": slide,
            "time": time_value,
            "event": event_value,
        }
        for key in SPLIT_COLUMNS:
            if row.get(key):
                rec["split"] = _normalize_split(str(row[key]))
                break
        out.append(rec)
    return out


def _coerce_event_to_int(raw: str) -> int:
    """Normalize event status to 0/1.

    Accepts: ``0``/``1``, ``Alive``/``Dead``, ``alive``/``deceased``,
    ``censored``/``event``, ``True``/``False``.
    """
    s = (raw or "").strip().lower()
    truthy = {"1", "true", "dead", "deceased", "event", "yes", "y"}
    falsy = {"0", "false", "alive", "censored", "no", "n"}
    if s in truthy:
        return 1
    if s in falsy:
        return 0
    try:
        return int(float(s) > 0)
    except (ValueError, TypeError):
        return 0


def build_survival_splits_from_labels(
    labels_file: str | Path,
    output_file: str | Path,
    *,
    seed: int = 42,
) -> Path:
    """Read survival labels and write a deterministic survival ``splits.json``.

    Output schema (mirrors what ``common/data_loader.load_survival_data``
    expects + what readiness validates):

    .. code-block:: json

        {
          "train": ["s1", "s2", ...],
          "val": [...],
          "test": [...],
          "survival_times": {"s1": 234.0, ...},
          "event_status": {"s1": 1, ...}
        }

    Raises ``ValueError("no_labeled_slides")`` for empty input,
    ``ValueError("too_few_labeled_slides")`` for fewer than 3 rows.
    """
    rows = _read_survival_label_rows(Path(labels_file))
    if not rows:
        raise ValueError("no_labeled_slides")
    if len(rows) < 3:
        raise ValueError("too_few_labeled_slides")

    times: dict[str, float] = {}
    events: dict[str, int] = {}
    for row in rows:
        try:
            times[row["slide_id"]] = float(row["time"])
        except (ValueError, TypeError):
            continue
        events[row["slide_id"]] = _coerce_event_to_int(row["event"])

    if len(times) < 3:
        raise ValueError("too_few_labeled_slides")

    explicit = _split_map_from_rows(rows)
    split_map = explicit or _deterministic_split(list(times.keys()), seed=seed)

    payload = {
        "train": [sid for sid, sp in split_map.items() if sp == "train"],
        "val": [sid for sid, sp in split_map.items() if sp == "val"],
        "test": [sid for sid, sp in split_map.items() if sp == "test"],
        "survival_times": times,
        "event_status": events,
    }
    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out
