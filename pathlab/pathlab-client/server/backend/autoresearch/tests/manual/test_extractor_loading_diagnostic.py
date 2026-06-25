"""Manual diagnostic: verify every registered PathLab extractor can instantiate.

This test is intentionally skipped during normal pytest runs because it loads
large model checkpoints. Run explicitly with:

    RUN_EXTRACTOR_LOAD_DIAGNOSTIC=1 \
    python -m pytest tests/manual/test_extractor_loading_diagnostic.py -s

It writes a JSON report to ``output/extractor_loading_diagnostic.json`` by
default. The diagnostic mirrors the agent contract: training scripts import
``common.extractors.registry.get_extractor`` from ``domain/templates``.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_TEMPLATES = REPO_ROOT / "domain" / "templates"
DEFAULT_CKPT_ROOT = DOMAIN_TEMPLATES / "common" / "extractors" / "checkpoints"
REPORT_PATH = Path(
    os.environ.get(
        "EXTRACTOR_LOAD_REPORT",
        str(REPO_ROOT / "output" / "extractor_loading_diagnostic.json"),
    )
)
IMAGE_NET_BASELINES = {"resnet50", "vit_l_16"}


def _registry_keys() -> list[str]:
    code = r"""
from common.extractors.registry import _EXTRACTOR_LAZY_REGISTRY
print('\n'.join(_EXTRACTOR_LAZY_REGISTRY.keys()))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DOMAIN_TEMPLATES)
    proc = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _chmod_tree(root: Path, mode: int) -> None:
    if not root.exists():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.chmod(mode)
        except OSError:
            pass
    try:
        root.chmod(mode)
    except OSError:
        pass


def _mirror_default_checkpoints_readonly() -> Path:
    """Build a read-only checkpoint root using symlinks to installed files.

    The sandbox binds ``common/`` read-only, so missing checkpoints cannot be
    materialized into the default checkpoint tree during an agent run. This
    mirror prevents the diagnostic from accidentally downloading or writing
    files into the repository while preserving the same set of installed files.
    """
    tmp = Path(tempfile.mkdtemp(prefix="autoresearch-extractor-ckpts-"))
    if DEFAULT_CKPT_ROOT.is_dir():
        for model_dir in DEFAULT_CKPT_ROOT.iterdir():
            if not model_dir.is_dir():
                continue
            dst_model = tmp / model_dir.name
            dst_model.mkdir(parents=True, exist_ok=True)
            for src in model_dir.rglob("*"):
                # Hidden cache folders are not part of the runtime contract.
                if any(part.startswith(".") for part in src.relative_to(model_dir).parts):
                    continue
                rel = src.relative_to(model_dir)
                dst = dst_model / rel
                if src.is_dir():
                    dst.mkdir(parents=True, exist_ok=True)
                    continue
                if src.is_file() or src.is_symlink():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        dst.symlink_to(src.resolve())
                    except FileExistsError:
                        pass
    _chmod_tree(tmp, 0o555)
    return tmp


def _cleanup_readonly_tree(root: Path) -> None:
    _chmod_tree(root, 0o755)
    shutil.rmtree(root, ignore_errors=True)


def _load_one_extractor(name: str, ckpt_root: Path, timeout: int) -> dict:
    child_code = r'''
import json
import os
import sys
import time
import traceback

name = os.environ["EXTRACTOR_UNDER_TEST"]
pretrained = os.environ.get("EXTRACTOR_PRETRAINED", "1") == "1"
started = time.time()
try:
    from common.extractors.registry import get_extractor
    extractor = get_extractor(name, pretrained=pretrained)
    result = {
        "name": name,
        "status": "loaded",
        "class": type(extractor).__name__,
        "output_dim": getattr(extractor, "output_dim", None),
        "spatial_output_dim": getattr(extractor, "spatial_output_dim", None),
        "default_image_size": getattr(extractor, "default_image_size", None),
        "duration_sec": round(time.time() - started, 3),
    }
except Exception as exc:
    result = {
        "name": name,
        "status": "failed",
        "error_type": type(exc).__name__,
        "error": str(exc),
        "traceback_tail": "\n".join(traceback.format_exc().splitlines()[-12:]),
        "duration_sec": round(time.time() - started, 3),
    }
print("RESULT_JSON=" + json.dumps(result, sort_keys=True))
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DOMAIN_TEMPLATES)
    env["PATHLAB_CKPT_DIR"] = str(ckpt_root)
    # The diagnostic should report current local readiness, not download new
    # model files from the internet while testing.
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["EXTRACTOR_UNDER_TEST"] = name
    # Avoid downloading ImageNet baseline weights. Pathology extractors ignore
    # this flag and use their checkpoint_manager paths.
    env["EXTRACTOR_PRETRAINED"] = "0" if name in IMAGE_NET_BASELINES else "1"

    started = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, "-c", child_code],
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "status": "timeout",
            "error_type": "TimeoutExpired",
            "error": f"timed out after {timeout}s",
            "stdout_tail": (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else "",
            "duration_sec": round(time.time() - started, 3),
        }

    parsed = None
    for line in reversed(proc.stdout.splitlines()):
        if line.startswith("RESULT_JSON="):
            parsed = json.loads(line.removeprefix("RESULT_JSON="))
            break
    if parsed is None:
        parsed = {
            "name": name,
            "status": "failed",
            "error_type": "NoResultJSON",
            "error": f"subprocess exit={proc.returncode}; no RESULT_JSON marker found",
            "duration_sec": round(time.time() - started, 3),
        }
    parsed["returncode"] = proc.returncode
    parsed["stdout_tail"] = proc.stdout[-4000:]
    parsed["stderr_tail"] = proc.stderr[-4000:]
    return parsed


def _compact_failure(result: dict) -> str:
    lines = str(result.get("error") or result.get("traceback_tail") or "").splitlines()
    first_line = lines[0] if lines else "<no error message>"
    if len(first_line) > 240:
        first_line = first_line[:237] + "..."
    return f"{result.get('name')}: {result.get('error_type')} - {first_line}"


def _expected_missing_names() -> set[str]:
    return {
        n.strip()
        for n in os.environ.get("EXTRACTOR_EXPECT_MISSING", "").split(",")
        if n.strip()
    }


@pytest.mark.skipif(
    os.environ.get("RUN_EXTRACTOR_LOAD_DIAGNOSTIC") != "1",
    reason="manual heavy extractor-loading diagnostic; set RUN_EXTRACTOR_LOAD_DIAGNOSTIC=1",
)
def test_all_registered_extractors_load_from_agent_common_contract():
    names = [n.strip() for n in os.environ.get("EXTRACTOR_NAMES", "").split(",") if n.strip()]
    if not names:
        names = _registry_keys()

    timeout = int(os.environ.get("EXTRACTOR_LOAD_TIMEOUT", "240"))
    ckpt_root = _mirror_default_checkpoints_readonly()
    results = []
    try:
        for name in names:
            result = _load_one_extractor(name, ckpt_root, timeout=timeout)
            results.append(result)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        _cleanup_readonly_tree(ckpt_root)

    report = {
        "mode": "agent_common_contract_readonly_checkpoints",
        "repo_root": str(REPO_ROOT),
        "domain_templates": str(DOMAIN_TEMPLATES),
        "default_checkpoint_root": str(DEFAULT_CKPT_ROOT),
        "hf_home": os.environ.get("HF_HOME", ""),
        "names": names,
        "results": results,
    }
    expected_missing = _expected_missing_names()
    failed = []
    expected_unavailable = []
    for result in results:
        if result.get("status") == "loaded":
            continue
        if (
            result.get("name") in expected_missing
            and result.get("error_type") == "FileNotFoundError"
        ):
            result["availability"] = "expected_missing_checkpoint"
            expected_unavailable.append(result)
            continue
        failed.append(result)

    report["expected_missing"] = sorted(expected_missing)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote extractor loading report: {REPORT_PATH}")

    assert not failed, (
        "Unexpected extractor load failures; full report: "
        f"{REPORT_PATH}\n"
        + "\n".join(_compact_failure(r) for r in failed)
    )
    if expected_unavailable:
        print(
            "Expected missing checkpoints: "
            + ", ".join(r["name"] for r in expected_unavailable)
        )
