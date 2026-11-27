"""Versioned prediction contract shared by model registration and all inference paths."""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import signal
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT = "pathlab-predictor-v1"
MANIFEST = "predictor.json"
WORKER = Path(__file__).resolve().parents[1] / "ai/research_predictor_worker.py"


class PredictionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runtime: Literal["sklearn", "torch_mlp", "python"]
    activation: Literal["relu", "gelu", "tanh"] | None = None
    task_type: Literal[
        "wsi_classification",
        "patch_classification",
        "wsi_survival",
        "patch_segmentation",
        "patch_detection",
    ]
    input_kind: Literal["features", "image"] = "features"
    classes: list[str] = Field(default_factory=list, max_length=1024)
    pooling: Literal["tile_mean", "tile_mean_then_slide_mean", "none"]
    score_method: Literal["predict_proba", "sigmoid_decision", "softmax_decision"] = (
        "predict_proba"
    )
    entrypoint: str | None = None
    config: dict = Field(default_factory=dict)
    preprocessing: dict = Field(default_factory=dict)
    feature_cache_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{8,64}$")
    image_size: int = Field(default=256, ge=16, le=2048)
    time_bins: list[float] = Field(default_factory=list)

    @model_validator(mode="after")
    def task_contract(self):
        if self.task_type.endswith("classification") and len(self.classes) < 2:
            raise ValueError("Classification requires ordered class labels")
        if self.runtime == "torch_mlp" and self.activation is None:
            raise ValueError(
                "Declare the trained Torch activation; use a Python adapter for other architectures"
            )
        if self.task_type in {"patch_segmentation", "patch_detection"} and (
            not self.classes or self.input_kind != "image"
        ):
            raise ValueError("Segmentation requires named channels and image input")
        if self.input_kind == "image" and (
            self.runtime != "python" or self.pooling != "none"
        ):
            raise ValueError(
                "Image predictors require a Python adapter with explicit preprocessing"
            )
        if (
            self.task_type in {"wsi_survival", "patch_segmentation", "patch_detection"}
            and self.runtime != "python"
        ):
            raise ValueError("This task requires its own Python prediction adapter")
        if self.task_type.startswith("wsi") and self.input_kind != "features":
            raise ValueError("WSI predictors consume extracted feature bags")
        if self.task_type.startswith("patch") and self.input_kind != "image":
            raise ValueError(
                "Patch predictors must include their image preprocessing in the adapter"
            )
        if any(not math.isfinite(v) for v in self.time_bins) or any(
            b <= a for a, b in zip(self.time_bins, self.time_bins[1:])
        ):
            raise ValueError(
                "Survival time_bins must be finite and strictly increasing"
            )
        return self


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class PredictorProcess:
    """One sandbox process per loaded model; no host pickle loading or credentials."""

    def __init__(
        self,
        model_path: Path,
        config: dict,
        adapter_dir: Path | None = None,
        device="cpu",
    ):
        from backend.autoresearch.runtime.sandbox import (
            _resolve_apptainer_bin,
            _resolve_default_image,
        )
        from backend.common.config import Config

        runtime_root = Config.get_autoresearch_dir() / "prediction-runtime"
        runtime_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="predictor-", dir=runtime_root
        )
        root = Path(self.temporary.name)
        self.root = root
        self.spec = config["_prediction"]
        device = str(device)
        use_gpu = device.startswith('cuda') and config["_prediction"]["runtime"] == "python"
        visible_gpu = ""
        if use_gpu:
            from backend.common.gpu_utils import sandbox_visible_device

            visible_gpu = sandbox_visible_device(
                int(device.split(":")[-1]) if ":" in device else 0
            )
        (root / "config.json").write_text(
            json.dumps({**config, "device": "cuda:0" if use_gpu else "cpu"})
        )
        self.log = (root / "worker.log").open("w+b")
        self.lock = threading.Lock()
        self.process = None
        self.container_name = None
        try:
            command = [
                _resolve_apptainer_bin(),
                "exec",
                "--contain",
                "--no-home",
                "--cleanenv",
                "--no-mount",
                "cwd,bind-paths",
                "--writable-tmpfs",
                "--pwd",
                "/tmp",
                "--bind",
                f"{model_path.resolve()}:/model.bin{model_path.suffix}:ro",
                "--bind",
                f"{root / 'config.json'}:/config.json:ro",
                "--bind",
                f"{root}:/exchange:rw",
                "--bind",
                f"{WORKER}:/worker.py:ro",
            ]
            if adapter_dir:
                command += ["--bind", f"{adapter_dir.resolve()}:/adapter:ro"]
            if use_gpu:
                command += ["--nv"]
            command += [
                _resolve_default_image(),
                "python",
                "/worker.py",
                "/model.bin" + model_path.suffix,
                "/config.json",
            ]
            from backend.autoresearch.runtime import container_backend
            command, env, self.container_name = container_backend.prepare(command, {
                    "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                    "HOME": os.environ.get("HOME", ""),
                    "APPTAINERENV_CUDA_VISIBLE_DEVICES": visible_gpu,
                    "APPTAINERENV_OMP_NUM_THREADS": "2",
                    "APPTAINERENV_OPENBLAS_NUM_THREADS": "2",
                })
            if self.container_name:
                command.insert(2, '--interactive')
            self.process = subprocess.Popen(
                command,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.log,
                text=True,
                bufsize=1,
                start_new_session=os.name != 'nt',
            )
            self.responses = queue.Queue()
            def read_lines():
                try:
                    while line := self.process.stdout.readline(65537):
                        self.responses.put(line)
                        if len(line) > 65536:
                            return
                finally:
                    self.responses.put(None)
            threading.Thread(target=read_lines, daemon=True).start()
            self.metadata = self._read()
        except BaseException:
            self.close()
            raise

    def _read(self):
        try:
            line = self.responses.get(timeout=90)
        except queue.Empty:
            raise TimeoutError('Research predictor timed out') from None
        if line is None:
            raise ValueError('Research predictor could not load this model')
        if len(line) > 65536:
            raise ValueError('Invalid predictor control response')
        value = json.loads(line)
        if value.get("error"):
            raise ValueError(
                f"Research predictor rejected the input ({str(value['error'])[:80]})"
            )
        return value

    def predict(self, features):
        return self._request(features, {})

    def predict_bag(self, features, patch_counts):
        return self._request(features, {"patch_counts": patch_counts})

    def _request(self, inputs, context):
        import numpy as np

        with self.lock:
            try:
                array = np.asarray(inputs)
                if array.nbytes > 512 * 1024**2:
                    raise ValueError(
                        "Prediction input exceeds 512 MiB; reduce the input batch"
                    )
                np.save(self.root / "input.npy", array, allow_pickle=False)
                self.process.stdin.write(json.dumps(context) + "\n")
                self.process.stdin.flush()
                self._read()
                import zipfile

                with zipfile.ZipFile(self.root / "output.npz") as archive:
                    if (
                        sum(item.file_size for item in archive.infolist())
                        > 512 * 1024**2
                    ):
                        raise ValueError("Prediction output exceeds 512 MiB")
                with np.load(self.root / "output.npz", allow_pickle=False) as output:
                    from backend.ai.research_predictor_worker import validate_output

                    return validate_output(
                        {key: output[key].copy() for key in output.files},
                        self.spec,
                        array.shape,
                    )
            except BaseException:
                self.close()
                raise

    def close(self):
        from backend.autoresearch.runtime.container_backend import remove_container_sync
        remove_container_sync(self.container_name)
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    if os.name == 'nt': self.process.terminate()
                    else: os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt': self.process.kill()
                    else: os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait()
            for stream in [self.process.stdin, self.process.stdout]:
                if stream:
                    stream.close()
        self.log.close()
        self.temporary.cleanup()


def prepare_predictor(
    model_path: Path,
    feature_extractor: str,
    prediction: dict,
    adapter_dir: Path | None = None,
) -> dict:
    spec = PredictionSpec.model_validate(prediction)
    if len(set(spec.classes)) != len(spec.classes) or any(
        not c.strip() for c in spec.classes
    ):
        raise ValueError(
            "Prediction classes must be unique nonempty labels in model-output order"
        )
    if spec.runtime == "python":
        if (
            not adapter_dir
            or not spec.entrypoint
            or Path(spec.entrypoint).is_absolute()
            or not (adapter_dir / spec.entrypoint)
            .resolve()
            .is_relative_to(adapter_dir.resolve())
            or not (adapter_dir / spec.entrypoint).is_file()
        ):
            raise ValueError(
                "Python prediction requires an entrypoint within its adapter directory"
            )
    elif spec.pooling == "none":
        raise ValueError(
            "Unpooled feature bags require a Python adapter or native aggregator"
        )
    config = {**spec.config, "_prediction": spec.model_dump()}
    process = PredictorProcess(model_path, config, adapter_dir)
    try:
        metadata = process.metadata
        actual = metadata["model_classes"]
        if (
            spec.task_type.endswith("classification")
            and actual != spec.classes
            and actual != list(range(len(spec.classes)))
        ):
            raise ValueError(
                "Declared classes do not match the classifier output order"
            )
        if (
            metadata.get("positive_label")
            and spec.classes[-1] != metadata["positive_label"]
        ):
            raise ValueError("Positive label does not match the model output order")
        if spec.input_kind == "image":
            import numpy as np

            process.predict(
                np.zeros((spec.image_size, spec.image_size, 3), dtype=np.uint8)
            )
        elif spec.pooling == "none":
            process.predict_bag([[0.0] * metadata["feature_dim"]], [1])
        else:
            process.predict([[0.0] * metadata["feature_dim"]])
        return {
            "contract": CONTRACT,
            "model_file": model_path.name,
            "sha256": file_hash(model_path),
            "feature_extractor": feature_extractor,
            "feature_dim": metadata["feature_dim"],
            "classes": spec.classes,
            "pooling": spec.pooling,
            "runtime": spec.runtime,
            "task_type": spec.task_type,
            "input_kind": spec.input_kind,
            "time_bins": spec.time_bins,
            "preprocessing": spec.preprocessing,
            "feature_cache_hash": spec.feature_cache_hash,
            "config": config,
            "adapter": "adapter" if adapter_dir else None,
            "adapter_hashes": {
                str(path.relative_to(adapter_dir)): file_hash(path)
                for path in adapter_dir.rglob("*")
                if path.is_file() and "__pycache__" not in path.parts
            }
            if adapter_dir
            else {},
        }
    finally:
        process.close()


def save_manifest(directory: Path, manifest: dict):
    path = directory / MANIFEST
    temporary = path.with_suffix(".json.partial")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


def read_manifest(directory: Path) -> dict | None:
    path = directory / MANIFEST
    if not path.is_file():
        return None
    manifest = json.loads(path.read_text())
    if (
        manifest.get("contract") != CONTRACT
        or Path(manifest["model_file"]).name != manifest["model_file"]
        or manifest["model_file"] in {".", "..", ""}
    ):
        raise ValueError("Invalid model prediction contract")
    spec = PredictionSpec.model_validate(manifest["config"]["_prediction"])
    if any(
        manifest[key] != getattr(spec, key)
        for key in ["task_type", "input_kind", "classes", "pooling", "runtime"]
    ):
        raise ValueError(
            "Prediction manifest disagrees with its validated task specification"
        )
    return manifest


class ResearchPredictor:
    """Task-aware prediction: probabilities, survival outputs or segmentation masks."""

    def __init__(self, directory: Path, device="cpu"):
        self.manifest = read_manifest(directory)
        if not self.manifest:
            raise ValueError("Missing prediction contract")
        model_path = directory / self.manifest["model_file"]
        if file_hash(model_path) != self.manifest["sha256"]:
            raise ValueError("Model has changed since prediction validation")
        for name, digest in self.manifest.get("adapter_hashes", {}).items():
            path = directory / "adapter" / name
            if (
                not path.resolve().is_relative_to((directory / "adapter").resolve())
                or file_hash(path) != digest
            ):
                raise ValueError("Prediction adapter changed since validation")
        self.process = PredictorProcess(
            model_path,
            self.manifest["config"],
            directory / "adapter" if self.manifest.get("adapter") else None,
            device=device,
        )
        self.device = device

    def predict_features(self, features, patch_counts=None):
        import torch

        values = features.detach().float().cpu()
        if values.ndim == 3 and values.shape[0] == 1:
            values = values[0]
        if (
            values.ndim != 2
            or values.shape[1] != self.manifest["feature_dim"]
            or not torch.isfinite(values).all()
        ):
            raise ValueError("Feature dimensions do not match the trained model")
        counts = patch_counts if patch_counts is not None else [len(values)]
        if not counts or any(n <= 0 for n in counts) or sum(counts) != len(values):
            raise ValueError("Invalid slide boundaries for case pooling")
        # Equal slide contribution, not a tile-count-weighted case mean.
        if self.manifest["pooling"] == "none":
            return self.process.predict_bag(values.numpy(), counts)
        pooled = (
            values.mean(0)
            if self.manifest["pooling"] == "tile_mean"
            else torch.stack([slide.mean(0) for slide in values.split(counts)]).mean(0)
        )
        return self.process.predict(pooled.unsqueeze(0).numpy())

    def predict_image(self, image):
        return self.process.predict(image)

    def close(self):
        self.process.close()


def predict_bag(model_path: str, aggregator: str, classes: list[str], features, device):
    """Single-slide entry shared by queued and direct inference endpoints."""
    import torch

    from backend.ai.aggregators import get_aggregator

    directory = Path(model_path).parent
    if read_manifest(directory):
        predictor = ResearchPredictor(directory, device)
        try:
            if predictor.manifest["classes"] != classes:
                raise ValueError("Classifier class order mismatch")
            result = predictor.predict_features(features)
            return torch.as_tensor(result["probabilities"], device=device).clamp_min(
                1e-30
            ).log(), None
        finally:
            predictor.close()
    checkpoint = torch.load(model_path, map_location=device)
    network = get_aggregator(
        aggregator or "abmil",
        in_dim=checkpoint["in_dim"],
        num_classes=checkpoint["num_classes"],
    ).to(device)
    network.load_state_dict(checkpoint["state_dict"])
    network.eval()
    with torch.inference_mode():
        return network(features)
