"""
Parse Section 7 Model Configuration JSON from research final_report and map to
PathLab create_training_task parameters. Prefer the `training` block when present.
"""
from __future__ import annotations

import json
from typing import Any

# Keys passed through from Section 7 "training" block to create_training_task.
# wsi_ids, task_name must come from user/agent; task_description optional.
_TRAINING_KEYS = (
    "task_type", "data_level", "tile_size", "stride", "level",
    "feature_extractor", "feature_batch_size", "epochs", "learning_rate", "aggregator",
)


def _strip_markdown_json(text: str) -> str:
    if not (text or "").strip():
        return ""
    s = text.strip()
    if "```" not in s:
        return s
    i = s.find("```")
    rest = s[i + 3 :].lstrip()
    if rest.lower().startswith("json"):
        rest = rest[4:].lstrip()
    j = rest.find("```")
    return (rest[: j].strip() if j >= 0 else rest.strip()) or s


def parse_model_config_from_report(final_report: str) -> dict | None:
    """
    Extract the Section 7 JSON (or the last ```json block) from final_report.
    Returns the parsed dict or None if not found/invalid.
    """
    if not (final_report or "").strip():
        return None
    # Prefer "## 7." or "## 7 " then first ```json
    s = final_report
    low = s.lower()
    i = low.find("## 7.")
    if i < 0:
        i = low.find("## 7 ")
    if i >= 0:
        s = s[i:]
    # Find first ```json or ```
    for sep in ("```json", "```"):
        j = s.find(sep)
        if j >= 0:
            rest = s[j + len(sep) :].lstrip()
            end = rest.find("```")
            raw = (rest[: end].strip() if end >= 0 else rest.strip()) or ""
            if raw:
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    pass
    # Fallback: last ```...``` block in full text
    raw = _strip_markdown_json(final_report)
    if raw and (raw.startswith("{") or "{" in raw):
        try:
            start = raw.find("{")
            if start >= 0:
                # Find matching } (simple)
                depth = 0
                for k, c in enumerate(raw[start:], start):
                    if c == "{":
                        depth += 1
                    elif c == "}":
                        depth -= 1
                        if depth == 0:
                            return json.loads(raw[start : k + 1])
        except json.JSONDecodeError:
            pass
    return None


def model_config_to_training_params(research_json: dict | None) -> dict:
    """
    Map research Section 7 JSON to create_training_task–style params (no wsi_ids, task_name).
    Prefer research_json["training"] when present; else derive from model_architecture,
    data_requirements, training_config. Result is passed as initial_training_params.
    """
    if not research_json or not isinstance(research_json, dict):
        return {}

    # Prefer "training" block (Section 7 aligned with PathLab)
    t = research_json.get("training")
    if isinstance(t, dict):
        out = {}
        pre = t.get("preprocessing") or {}
        model = t.get("model") or {}
        for k in _TRAINING_KEYS:
            v = t.get(k)
            if v is None and k in ("tile_size", "stride", "level", "feature_extractor", "feature_batch_size"):
                v = pre.get(k) if isinstance(pre, dict) else None
            if v is None and k in ("epochs", "learning_rate", "aggregator"):
                v = model.get(k) if isinstance(model, dict) else None
            if v is not None:
                out[k] = v
        if out:
            return out

    # Fallback: map from model_architecture, data_requirements, training_config
    out = {}

    # task_type + data_level from high-level task_type or label_schema
    tt = (research_json.get("task_type") or "").lower()
    if "patch-level" in tt:
        out["task_type"] = "classification" if "segment" not in tt else "segmentation"
        out["data_level"] = "patch"
    elif "pixel-level" in tt or "segmentation" in tt:
        out["task_type"] = "segmentation"
        out["data_level"] = "wsi"
    else:
        out["task_type"] = "classification"
        out["data_level"] = "wsi"

    # data_requirements
    dr = research_json.get("data_requirements") or {}
    if isinstance(dr, dict):
        out.setdefault("tile_size", int(dr.get("patch_size") or dr.get("tile_size") or 512))
        out.setdefault("stride", int(dr.get("patch_stride") or dr.get("stride") or 512))
        out.setdefault("level", int(dr.get("level") or 0))

    # model_architecture
    ma = research_json.get("model_architecture") or {}
    if isinstance(ma, dict):
        fe = (ma.get("feature_extractor") or "").strip().lower()
        if fe:
            _fe_map = {"ctranspath": "conch", "pathoclip": "patho_clip"}
            fe = _fe_map.get(fe, fe)
            out.setdefault("feature_extractor", fe if fe in (
                "resnet50","uni","conch","phikon","virchow","plip","patho_clip","vit_l_16",
                "uni2","phikon2","virchow2","conch15","openmidnight","mSTAR","GPFM",
                "H-Optimus-0","H-Optimus-1"
            ) else "resnet50")
        ag = (ma.get("aggregator") or "").strip().lower()
        if ag and ag in ("abmil", "meanmil", "maxmil"):
            out.setdefault("aggregator", ag)

    # training_config
    tc = research_json.get("training_config") or {}
    if isinstance(tc, dict):
        out.setdefault("epochs", int(tc.get("epochs") or 10))
        lr = tc.get("learning_rate")
        if lr is not None:
            out["learning_rate"] = float(lr)
        else:
            out.setdefault("learning_rate", 1e-4)
        out.setdefault("feature_batch_size", int(tc.get("batch_size") or tc.get("feature_batch_size") or 256))

    # Ensure required-like defaults
    out.setdefault("tile_size", 512)
    out.setdefault("stride", 512)
    out.setdefault("level", 0)
    out.setdefault("feature_extractor", "resnet50")
    out.setdefault("feature_batch_size", 256)
    out.setdefault("epochs", 10)
    out.setdefault("learning_rate", 1e-4)
    out.setdefault("aggregator", "abmil")

    return out
