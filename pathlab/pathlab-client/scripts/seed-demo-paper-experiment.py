#!/usr/bin/env python3
"""Seed a completed demo experiment for Paper Agent and result views.

This script is intentionally idempotent: re-running it replaces the same demo
records and files instead of creating duplicates.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
PAPER_AGENT_SRC = SERVER_DIR / "paper_agent" / "src"

for import_path in (str(SERVER_DIR), str(PAPER_AGENT_SRC)):
    if import_path not in sys.path:
        sys.path.insert(0, import_path)

os.environ.setdefault("PATHLAB_UPLOADS_DIR", str(ROOT / ".pathlab-dev" / "uploads"))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://pathlab:pathlab@127.0.0.1:55432/pathlab")
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".pathlab-dev" / "matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy import delete, select

from backend.auth.models import User
from backend.common.config import Config
from backend.database.database import async_session, engine
from backend.database.models import (
    AIResult,
    AnalysisRun,
    DataGroup,
    Dataset,
    DatasetStats,
    PaperGenerationRun,
    TrainedModel,
    TrainingLog,
    TrainingTask,
    TrainingTaskWSI,
    WSISlide,
    utc_now,
)
from pathlab_paper_agent.scaffold import initialize_paper_run
from pathlab_paper_agent.schemas import (
    PaperConfig,
    PaperManifest,
    PaperRunStage,
    PaperRunStatus,
    SourceTaskRef,
    TaskRole,
    TemplateId,
)
from pathlab_paper_agent.storage import PaperRunPaths


TASK_ID = "demo_crc_msi_paper_task"
DATASET_ID = "demo_crc_msi_paper_dataset"
MODEL_ID = "demo_crc_msi_paper_model"
PAPER_ID = "demo_crc_msi_paper_run"
ANALYSIS_ID = "20260704_224500_auto"

TASK_NAME = "Demo CRC MSI Completed Experiment"
PAPER_TITLE = "Patch-Based Prediction of MSI Status in Colorectal Cancer"
CLASSES = ["MSI-H", "MSS"]


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def artifact(
    label: str,
    content_type: str,
    *,
    visibility: str = "public",
    downloadable: bool = True,
    status: str = "ready",
) -> dict[str, Any]:
    return {
        "status": status,
        "visibility": visibility,
        "downloadable": downloadable,
        "label": label,
        "content_type": content_type,
    }


def make_samples() -> list[dict[str, Any]]:
    labels = ["MSI-H"] * 8 + ["MSS"] * 8
    splits = [
        "train",
        "train",
        "train",
        "train",
        "train",
        "val",
        "test",
        "test",
        "train",
        "train",
        "train",
        "train",
        "train",
        "val",
        "test",
        "test",
    ]
    wrong_indices = {5, 12}
    samples: list[dict[str, Any]] = []
    for index, label in enumerate(labels, start=1):
        pred = "MSS" if label == "MSI-H" else "MSI-H"
        if index - 1 not in wrong_indices:
            pred = label
        confidence = 0.88 + ((index % 5) * 0.018)
        if pred != label:
            confidence = 0.59 + ((index % 3) * 0.035)
        probs = {
            "MSI-H": round(confidence if pred == "MSI-H" else 1.0 - confidence, 4),
            "MSS": round(confidence if pred == "MSS" else 1.0 - confidence, 4),
        }
        samples.append(
            {
                "index": index,
                "wsi_id": f"demo_crc_msi_patch_{index:03d}",
                "case_id": f"DEMO-CRC-{(index + 1) // 2:03d}",
                "filename": f"demo_crc_msi_patch_{index:03d}.png",
                "label": label,
                "pred": pred,
                "probs": probs,
                "split": splits[index - 1],
                "age": 48 + (index * 3) % 27,
                "gender": "Female" if index % 2 else "Male",
            }
        )
    return samples


def generate_patch_image(path: Path, sample: dict[str, Any]) -> None:
    rng = random.Random(20260704 + int(sample["index"]))
    base = (239, 194, 206) if sample["label"] == "MSI-H" else (208, 197, 232)
    image = Image.new("RGB", (256, 256), (246, 240, 234))
    draw = ImageDraw.Draw(image, "RGBA")
    for _ in range(110):
        x = rng.randint(-20, 240)
        y = rng.randint(-20, 240)
        w = rng.randint(18, 70)
        h = rng.randint(14, 62)
        color = (
            max(0, min(255, base[0] + rng.randint(-32, 28))),
            max(0, min(255, base[1] + rng.randint(-28, 35))),
            max(0, min(255, base[2] + rng.randint(-26, 30))),
            rng.randint(58, 130),
        )
        draw.ellipse([x, y, x + w, y + h], fill=color)
    for _ in range(24):
        x = rng.randint(0, 240)
        y = rng.randint(0, 240)
        radius = rng.randint(3, 10)
        draw.ellipse(
            [x, y, x + radius, y + radius],
            fill=(92, 50, 110, rng.randint(90, 170)),
        )
    image = image.filter(ImageFilter.GaussianBlur(radius=0.35))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def calculate_metrics(samples: list[dict[str, Any]]) -> dict[str, Any]:
    matrix = [[0, 0], [0, 0]]
    for sample in samples:
        true_idx = CLASSES.index(sample["label"])
        pred_idx = CLASSES.index(sample["pred"])
        matrix[true_idx][pred_idx] += 1

    total = len(samples)
    correct = matrix[0][0] + matrix[1][1]
    per_class: dict[str, Any] = {}
    f1_values = []
    for idx, label in enumerate(CLASSES):
        tp = matrix[idx][idx]
        fp = sum(matrix[row][idx] for row in range(len(CLASSES)) if row != idx)
        fn = sum(matrix[idx][col] for col in range(len(CLASSES)) if col != idx)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if precision + recall else 0.0
        f1_values.append(f1)
        per_class[label] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": sum(matrix[idx]),
        }

    return {
        "accuracy": round(correct / total, 4),
        "macro_f1": round(float(np.mean(f1_values)), 4),
        "auc": 0.9375,
        "sensitivity": round(per_class["MSI-H"]["recall"], 4),
        "specificity": round(per_class["MSS"]["recall"], 4),
        "confusion_matrix": matrix,
        "per_class": per_class,
        "total_samples": total,
    }


def plot_confusion_matrix(path: Path, metrics: dict[str, Any]) -> None:
    matrix = np.array(metrics["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(5.2, 4.4), dpi=180)
    image = ax.imshow(matrix, cmap="Blues")
    ax.set_xticks(range(len(CLASSES)), CLASSES)
    ax.set_yticks(range(len(CLASSES)), CLASSES)
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("Reference label")
    ax.set_title("Confusion Matrix")
    threshold = matrix.max() / 2
    for row in range(matrix.shape[0]):
        for col in range(matrix.shape[1]):
            ax.text(
                col,
                row,
                str(matrix[row, col]),
                ha="center",
                va="center",
                color="white" if matrix[row, col] > threshold else "#14324a",
                fontsize=12,
                fontweight="bold",
            )
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_roc_curve(path: Path) -> None:
    fpr = np.array([0.0, 0.0, 0.05, 0.08, 0.16, 0.28, 0.48, 1.0])
    tpr = np.array([0.0, 0.42, 0.64, 0.78, 0.88, 0.94, 0.98, 1.0])
    fig, ax = plt.subplots(figsize=(5.2, 4.4), dpi=180)
    ax.plot(fpr, tpr, color="#0f766e", linewidth=2.5, label="AUC = 0.94")
    ax.plot([0, 1], [0, 1], color="#8b8b8b", linestyle="--", linewidth=1.2, label="Chance")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("ROC Curve")
    ax.grid(True, color="#d7dee5", linewidth=0.8, alpha=0.8)
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def plot_calibration(path: Path) -> None:
    mean_pred = np.array([0.12, 0.28, 0.43, 0.63, 0.81, 0.93])
    observed = np.array([0.08, 0.24, 0.50, 0.67, 0.78, 0.91])
    fig, ax = plt.subplots(figsize=(5.2, 4.4), dpi=180)
    ax.plot([0, 1], [0, 1], color="#8b8b8b", linestyle="--", linewidth=1.2, label="Perfect")
    ax.plot(mean_pred, observed, marker="o", color="#b45309", linewidth=2.2, label="Model")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Mean predicted probability")
    ax.set_ylabel("Observed MSI-H fraction")
    ax.set_title("Calibration Curve")
    ax.grid(True, color="#e1e6ec", linewidth=0.8, alpha=0.85)
    ax.legend(loc="upper left", frameon=False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def write_analysis_artifacts(uploads_dir: Path, samples: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Path]:
    analysis_dir = uploads_dir / "logs" / "analysis" / TASK_ID / ANALYSIS_ID
    analysis_dir.mkdir(parents=True, exist_ok=True)
    chart_paths = {
        "confusion_matrix": analysis_dir / "confusion_matrix.png",
        "roc_curve": analysis_dir / "roc_curve.png",
        "calibration": analysis_dir / "calibration.png",
    }
    plot_confusion_matrix(chart_paths["confusion_matrix"], metrics)
    plot_roc_curve(chart_paths["roc_curve"])
    plot_calibration(chart_paths["calibration"])

    results = [
        {
            "wsi_id": sample["wsi_id"],
            "case_id": sample["case_id"],
            "label": sample["label"],
            "prediction": sample["pred"],
            "probabilities": sample["probs"],
            "split": sample["split"],
        }
        for sample in samples
    ]
    label_distribution = {label: sum(1 for sample in samples if sample["label"] == label) for label in CLASSES}
    prediction_distribution = {label: sum(1 for sample in samples if sample["pred"] == label) for label in CLASSES}
    summary = {
        "analysis_id": ANALYSIS_ID,
        "task_id": TASK_ID,
        "title": "Post-training performance analysis for demo CRC MSI experiment",
        "dataset_id": DATASET_ID,
        "model_id": MODEL_ID,
        "classes": CLASSES,
        "metrics": metrics,
        "accuracy": metrics["accuracy"],
        "macro_f1": metrics["macro_f1"],
        "auc": metrics["auc"],
        "sensitivity": metrics["sensitivity"],
        "specificity": metrics["specificity"],
        "total_samples": metrics["total_samples"],
        "label_distribution": label_distribution,
        "prediction_distribution": prediction_distribution,
        "confusion_matrix": metrics["confusion_matrix"],
        "chart_paths": {key: str(value) for key, value in chart_paths.items()},
        "results_path": str(analysis_dir / "results.json"),
        "notes": [
            "Synthetic demo dataset for validating the paper-generation workflow.",
            "Generated charts are safe placeholders and should not be treated as clinical evidence.",
        ],
    }
    dump_json(analysis_dir / "summary.json", summary)
    dump_json(analysis_dir / "results.json", {"items": results, "total": len(results)})
    (analysis_dir / "summary_table.csv").write_text(
        "metric,value\n"
        f"accuracy,{metrics['accuracy']}\n"
        f"macro_f1,{metrics['macro_f1']}\n"
        f"auc,{metrics['auc']}\n"
        f"sensitivity,{metrics['sensitivity']}\n"
        f"specificity,{metrics['specificity']}\n",
        encoding="utf-8",
    )
    return chart_paths


def make_training_metrics() -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {
            "accuracy": 0.941,
            "auc": 0.962,
            "loss": 0.183,
            "epochs": 18,
            "loss_history": [0.71, 0.61, 0.52, 0.45, 0.38, 0.31, 0.26, 0.22, 0.19, 0.18],
        },
        {
            "accuracy": 0.875,
            "auc": 0.938,
            "macro_f1": 0.874,
            "loss": 0.286,
            "best_epoch": 14,
            "early_stopping_patience": 6,
        },
    )


async def ensure_admin_user(session) -> User:
    result = await session.execute(select(User).where(User.username == "admin"))
    user = result.scalar_one_or_none()
    if user is None:
        raise RuntimeError("Admin user was not found. Start the project once before seeding demo data.")
    return user


async def clear_existing_demo(session) -> None:
    sample_ids = [sample["wsi_id"] for sample in make_samples()]
    await session.execute(delete(PaperGenerationRun).where(PaperGenerationRun.paper_id == PAPER_ID))
    await session.execute(delete(AnalysisRun).where(AnalysisRun.task_id == TASK_ID))
    await session.execute(delete(AIResult).where((AIResult.task_id == TASK_ID) | (AIResult.wsi_id.in_(sample_ids))))
    await session.execute(delete(TrainedModel).where((TrainedModel.task_id == TASK_ID) | (TrainedModel.model_id == MODEL_ID)))
    await session.execute(delete(TrainingLog).where(TrainingLog.task_id == TASK_ID))
    await session.execute(delete(TrainingTaskWSI).where((TrainingTaskWSI.task_id == TASK_ID) | (TrainingTaskWSI.wsi_id.in_(sample_ids))))
    await session.execute(delete(TrainingTask).where(TrainingTask.task_id == TASK_ID))
    await session.execute(delete(WSISlide).where((WSISlide.dataset_id == DATASET_ID) | (WSISlide.wsi_id.in_(sample_ids))))
    await session.execute(delete(DatasetStats).where(DatasetStats.dataset_id == DATASET_ID))
    await session.execute(delete(Dataset).where(Dataset.dataset_id == DATASET_ID))
    await session.commit()


async def get_or_create_group(session) -> DataGroup:
    result = await session.execute(
        select(DataGroup).where(
            DataGroup.data_type == "patch",
            DataGroup.aggregation_level == "file",
            DataGroup.task_type == "patch_classification",
        )
    )
    group = result.scalar_one_or_none()
    if group is not None:
        return group
    group = DataGroup(
        group_id="demo_patch_file_classification_group",
        name="Patch File-level Classification",
        description="Patch image classification tasks with file-level labels.",
        data_type="patch",
        aggregation_level="file",
        task_type="patch_classification",
    )
    session.add(group)
    await session.flush()
    return group


async def seed_database(
    samples: list[dict[str, Any]],
    metrics: dict[str, Any],
    patch_dir: Path,
    model_dir: Path,
    chart_paths: dict[str, Path],
) -> str:
    async with async_session() as session:
        await clear_existing_demo(session)
        admin = await ensure_admin_user(session)
        user_id = str(admin.id)
        group = await get_or_create_group(session)
        now = utc_now()
        started_at = now - timedelta(hours=3, minutes=18)

        dataset = Dataset(
            dataset_id=DATASET_ID,
            name="Demo CRC MSI Paper Dataset",
            description=(
                "Synthetic colorectal cancer patch dataset seeded for demonstrating "
                "PathLab Paper Agent paper generation."
            ),
            user_id=user_id,
            group_id=group.group_id,
            source_organ="Colorectum",
            is_public=True,
        )
        session.add(dataset)
        await session.flush()
        session.add(
            DatasetStats(
                dataset_id=DATASET_ID,
                file_count=len(samples),
                total_size=sum((patch_dir / sample["filename"]).stat().st_size for sample in samples),
                split_train_count=sum(1 for sample in samples if sample["split"] == "train"),
                split_val_count=sum(1 for sample in samples if sample["split"] == "val"),
                split_test_count=sum(1 for sample in samples if sample["split"] == "test"),
                updated_at=now,
            )
        )

        for sample in samples:
            image_path = patch_dir / sample["filename"]
            session.add(
                WSISlide(
                    wsi_id=sample["wsi_id"],
                    original_filename=sample["filename"],
                    dataset_id=DATASET_ID,
                    case_id=sample["case_id"],
                    label=sample["label"],
                    wsi_path=str(image_path),
                    user_id=user_id,
                    age=sample["age"],
                    gender=sample["gender"],
                    source="Colorectum",
                    split=sample["split"],
                    mpp=0.25,
                    vendor="SyntheticDemo",
                    width=256,
                    height=256,
                    magnification=20,
                    file_size=image_path.stat().st_size,
                    feature_extracted=True,
                    data_type="patch",
                )
            )

        task = TrainingTask(
            task_id=TASK_ID,
            task_name=TASK_NAME,
            task_description=(
                "Completed demo experiment for MSI status classification in colorectal "
                "cancer patches. Includes seeded predictions, model metrics, and "
                "analysis charts for Paper Agent generation."
            ),
            group_id=group.group_id,
            user_id=user_id,
            status="completed",
            progress=100,
            preprocessing_config={
                "tile_size": 256,
                "stride": 256,
                "feature_extractor": "resnet50_demo",
                "feature_batch_size": 32,
                "normalization": "macenko_demo",
                "use_gpu": False,
            },
            model_config={
                "task_type": "patch_classification",
                "aggregator": "attention_mil_demo",
                "optimizer": "adamw",
                "learning_rate": 0.0003,
                "batch_size": 8,
                "epochs": 18,
                "class_weighting": "balanced",
                "primary_metric": "auc",
            },
            classes=CLASSES,
            started_at=started_at,
            finished_at=now,
        )
        session.add(task)
        await session.flush()

        for sample in samples:
            session.add(TrainingTaskWSI(task_id=TASK_ID, wsi_id=sample["wsi_id"], split=sample["split"]))
            session.add(
                AIResult(
                    wsi_id=sample["wsi_id"],
                    task_id=TASK_ID,
                    user_id=user_id,
                    pred=sample["pred"],
                    probs=sample["probs"],
                    extra_metadata={
                        "source": "demo_seed",
                        "model_id": MODEL_ID,
                        "true_label": sample["label"],
                        "split": sample["split"],
                        "analysis_id": ANALYSIS_ID,
                    },
                    created_at=now,
                )
            )

        train_metrics, val_metrics = make_training_metrics()
        session.add(
            TrainedModel(
                model_id=MODEL_ID,
                task_id=TASK_ID,
                model_name="Demo CRC MSI Attention MIL",
                user_id=user_id,
                model_path=str(model_dir / "best_model.pth"),
                config_path=str(model_dir / "model_config.json"),
                classes=CLASSES,
                feature_extractor="resnet50_demo",
                aggregator="attention_mil_demo",
                train_metrics=train_metrics,
                val_metrics=val_metrics,
                is_default=True,
                is_active=True,
                created_at=now,
            )
        )

        logs = [
            ("INFO", "Demo experiment initialized from seeded CRC MSI patch data.", 0, {"progress": 5}),
            ("INFO", "Feature extraction completed for 16 patch images.", 1, {"progress": 35}),
            ("INFO", "Training converged with validation AUC 0.938.", 2, {"progress": 82}),
            ("INFO", "Post-training analysis generated confusion matrix, ROC, and calibration figures.", 3, {"progress": 100}),
        ]
        for level, message, sequence, extra_data in logs:
            session.add(
                TrainingLog(
                    task_id=TASK_ID,
                    level=level,
                    message=message,
                    sequence=sequence,
                    extra_data=extra_data,
                    created_at=started_at + timedelta(minutes=sequence * 41),
                )
            )

        session.add(AnalysisRun(analysis_id=ANALYSIS_ID, task_id=TASK_ID, user_id=user_id, created_at=now))

        config_payload = {
            "title": PAPER_TITLE,
            "paper_type": "research_paper",
            "language": "en",
            "source_tasks": [{"task_id": TASK_ID, "role": "main", "label": TASK_NAME}],
            "selected_templates": ["miccai"],
            "include_external_validation": True,
            "user_idea": (
                "Write a concise research paper describing a patch-based MSI status "
                "classification workflow for colorectal cancer, emphasizing workflow "
                "reproducibility and post-training performance visualization."
            ),
        }
        session.add(
            PaperGenerationRun(
                paper_id=PAPER_ID,
                user_id=user_id,
                title=PAPER_TITLE,
                status="completed",
                current_stage="completed",
                error_message=None,
                config_json=config_payload,
                source_task_ids=[TASK_ID],
                selected_templates=["miccai"],
                started_at=started_at,
                finished_at=now,
            )
        )
        await session.commit()
        return user_id


async def write_paper_run(user_id: str, metrics: dict[str, Any], chart_paths: dict[str, Path]) -> None:
    config = PaperConfig(
        paper_id=PAPER_ID,
        title=PAPER_TITLE,
        paper_type="research_paper",
        language="en",
        source_tasks=[SourceTaskRef(task_id=TASK_ID, role=TaskRole.main, label=TASK_NAME)],
        selected_templates=[TemplateId.miccai],
        include_external_validation=True,
        user_idea=(
            "Write a concise research paper describing a patch-based MSI status "
            "classification workflow for colorectal cancer, emphasizing workflow "
            "reproducibility and post-training performance visualization."
        ),
    )
    paths = await initialize_paper_run(None, config)
    paths.ensure_dirs()

    dump_json(
        paths.source_tasks,
        {
            "items": [
                {
                    "task_id": TASK_ID,
                    "task_name": TASK_NAME,
                    "role": "main",
                    "dataset_id": DATASET_ID,
                    "model_id": MODEL_ID,
                    "status": "completed",
                }
            ]
        },
    )
    (paths.idea).write_text(config.user_idea or "", encoding="utf-8")

    evidence_public = {
        "paper_id": PAPER_ID,
        "owner_user_id": user_id,
        "source_tasks": [
            {
                "task_id": TASK_ID,
                "task_name": TASK_NAME,
                "dataset_id": DATASET_ID,
                "model_id": MODEL_ID,
                "classes": CLASSES,
            }
        ],
        "main_results": {
            "accuracy": metrics["accuracy"],
            "macro_f1": metrics["macro_f1"],
            "auc": metrics["auc"],
            "sensitivity": metrics["sensitivity"],
            "specificity": metrics["specificity"],
            "confusion_matrix": metrics["confusion_matrix"],
            "n": metrics["total_samples"],
        },
        "analysis_summaries": [
            {
                "analysis_id": ANALYSIS_ID,
                "task_id": TASK_ID,
                "chart_paths": {key: str(value) for key, value in chart_paths.items()},
            }
        ],
        "limitations": [
            "This is synthetic seed data intended for workflow demonstration.",
            "Do not interpret metrics as clinical validation.",
        ],
    }
    dump_json(paths.evidence_public, evidence_public)
    dump_json(
        paths.evidence_lock_private,
        {
            "paper_id": PAPER_ID,
            "source": "seed-demo-paper-experiment.py",
            "analysis_dir": str(next(iter(chart_paths.values())).parent),
            "raw_metrics": metrics,
        },
    )
    paths.experimental_log.write_text(
        "# Experimental Log\n\n"
        f"- Training task: `{TASK_ID}`\n"
        f"- Dataset: `{DATASET_ID}` with 16 synthetic patch images\n"
        f"- Metrics: accuracy {metrics['accuracy']}, AUC {metrics['auc']}, macro-F1 {metrics['macro_f1']}\n"
        "- Analysis charts: confusion matrix, ROC curve, and calibration curve\n",
        encoding="utf-8",
    )

    figure_entries = []
    figure_specs = [
        (
            "fig_confusion_matrix",
            "confusion_matrix",
            "demo_confusion_matrix.png",
            "Confusion matrix for the demo CRC MSI classifier.",
        ),
        (
            "fig_roc_curve",
            "roc_curve",
            "demo_roc_curve.png",
            "Receiver operating characteristic curve for MSI-H discrimination.",
        ),
        (
            "fig_calibration",
            "calibration",
            "demo_calibration.png",
            "Reliability curve comparing predicted MSI-H probability with observed frequency.",
        ),
    ]
    for figure_id, chart_key, filename, caption in figure_specs:
        destination = paths.figures_dir / filename
        shutil.copy2(chart_paths[chart_key], destination)
        figure_entries.append(
            {
                "figure_id": figure_id,
                "path": f"figures/{filename}",
                "status": "ready",
                "source": "pathlab_analysis_chart",
                "generator": "chart_passthrough",
                "kind": chart_key,
                "caption": caption,
                "source_path": str(chart_paths[chart_key]),
            }
        )
    dump_json(paths.figures_manifest, {"figures": figure_entries, "generated_by": "demo_seed"})

    table_tex = (
        "\\begin{tabular}{lr}\n"
        "\\toprule\n"
        "Metric & Value \\\\\n"
        "\\midrule\n"
        f"Accuracy & {metrics['accuracy']:.3f} \\\\\n"
        f"Macro-F1 & {metrics['macro_f1']:.3f} \\\\\n"
        f"AUC & {metrics['auc']:.3f} \\\\\n"
        f"Sensitivity & {metrics['sensitivity']:.3f} \\\\\n"
        f"Specificity & {metrics['specificity']:.3f} \\\\\n"
        "\\bottomrule\n"
        "\\end{tabular}\n"
    )
    (paths.tables_dir / "table_2_main_results.tex").write_text(table_tex, encoding="utf-8")
    (paths.locked_blocks_dir / "results_block.tex").write_text(
        f"The seeded demo classifier evaluated {metrics['total_samples']} patch images and "
        f"achieved an accuracy of {metrics['accuracy']:.3f}, macro-F1 of {metrics['macro_f1']:.3f}, "
        f"and AUC of {metrics['auc']:.3f}.",
        encoding="utf-8",
    )

    sections = {
        "abstract": (
            "\\section*{Abstract}\n"
            "We present a seeded PathLab demonstration experiment for patch-based prediction "
            "of microsatellite instability status in colorectal cancer. The run includes "
            "synthetic image patches, completed model outputs, and analysis figures for "
            "end-to-end Paper Agent validation.\n"
        ),
        "methods": (
            "\\section{Methods}\n"
            "Synthetic colorectal cancer patch images were organized into train, validation, "
            "and test splits. A demo attention MIL-style classifier was configured with a "
            "ResNet feature extractor and evaluated using accuracy, macro-F1, AUC, sensitivity, "
            "and specificity.\n"
        ),
        "results": (
            "\\section{Results}\n"
            "\\input{locked_blocks/results_block.tex}\n"
            "The exported figures include a confusion matrix, ROC curve, and calibration curve, "
            "allowing the Paper Agent workspace to demonstrate figure-aware manuscript assembly.\n"
        ),
        "discussion": (
            "\\section{Discussion}\n"
            "This seeded experiment is designed for workflow testing and manuscript-generation "
            "demonstration. The synthetic data and metrics are not intended for clinical claims.\n"
        ),
    }
    for section_name, content in sections.items():
        (paths.sections_dir / f"{section_name}.tex").write_text(content, encoding="utf-8")

    outline = {
        "title": PAPER_TITLE,
        "abstract": "Seeded demonstration of PatchLab/Paper Agent writing from completed experiment artifacts.",
        "sections": [
            {
                "section": "abstract",
                "goal": "Summarize the completed demo experiment and its workflow purpose.",
                "evidence_inputs": ["evidence/evidence_public.json"],
            },
            {
                "section": "methods",
                "goal": "Describe the synthetic patch dataset, model configuration, and metrics.",
                "evidence_inputs": ["inputs/source_tasks.json", "evidence/experimental_log.md"],
            },
            {
                "section": "results",
                "goal": "Report the seeded performance metrics and generated analysis figures.",
                "evidence_inputs": ["evidence/evidence_public.json", "figures/manifest.json"],
                "locked_block_inputs": ["locked_blocks/results_block.tex"],
            },
            {
                "section": "discussion",
                "goal": "Explain workflow use and limitations of synthetic demonstration data.",
                "evidence_inputs": ["evidence/evidence_public.json"],
            },
        ],
        "plotting_plan": [
            {
                "figure_id": entry["figure_id"],
                "kind": entry["kind"],
                "source": entry["source"],
                "design_objective": entry["caption"],
                "backend": "chart_passthrough",
                "plot_spec": {"path": entry["path"]},
            }
            for entry in figure_entries
        ],
        "pathlab": {
            "templates": ["miccai"],
            "table_plan": [{"table_id": "table_2_main_results", "path": "tables/table_2_main_results.tex"}],
            "guard_requirements": ["synthetic_demo_disclaimer"],
        },
    }
    dump_json(paths.outline_json, outline)
    (paths.refs_bib).write_text(
        "@misc{PathLabDemo2026,\n"
        "  title = {PathLab Paper Agent Demonstration Seed},\n"
        "  year = {2026},\n"
        "  note = {Synthetic local workflow fixture}\n"
        "}\n",
        encoding="utf-8",
    )
    (paths.validation_dir / "warnings.md").write_text(
        "# Validation Warnings\n\n"
        "- Synthetic demo data only; do not use for scientific or clinical claims.\n",
        encoding="utf-8",
    )

    now = utc_now()
    stage_log = []
    for stage in [
        PaperRunStage.created,
        PaperRunStage.collecting,
        PaperRunStage.building_evidence,
        PaperRunStage.outlining,
        PaperRunStage.plotting,
        PaperRunStage.section_writing,
        PaperRunStage.validating,
        PaperRunStage.rendering,
        PaperRunStage.exporting,
        PaperRunStage.completed,
    ]:
        stage_log.append(
            {
                "stage": stage.value,
                "status": "completed",
                "ts": now.isoformat(),
                "started_at": now.isoformat(),
                "finished_at": now.isoformat(),
                "duration_ms": 0,
                "message": f"Seeded demo {stage.value} artifact set.",
            }
        )

    artifact_index = {
        "config.json": artifact("Run config", "application/json"),
        "manifest.json": artifact("Run manifest", "application/json"),
        "evidence/evidence_public.json": artifact("Public evidence", "application/json"),
        "evidence/experimental_log.md": artifact("Experimental log", "text/markdown"),
        "drafts/outline.json": artifact("Outline", "application/json"),
        "figures/manifest.json": artifact("Figure manifest", "application/json"),
        "tables/table_2_main_results.tex": artifact("Main results table", "text/x-tex"),
        "locked_blocks/results_block.tex": artifact(
            "Results locked block",
            "text/x-tex",
            visibility="private_backend_only",
            downloadable=False,
        ),
        "citations/refs.bib": artifact("References", "text/x-bibtex"),
        "validation/warnings.md": artifact("Validation warnings", "text/markdown"),
    }
    for section_name in sections:
        artifact_index[f"drafts/sections/{section_name}.tex"] = artifact(
            f"{section_name.title()} section",
            "text/x-tex",
        )
    for _, _, filename, caption in figure_specs:
        artifact_index[f"figures/{filename}"] = artifact(caption, "image/png")

    manifest = PaperManifest(
        paper_id=PAPER_ID,
        status=PaperRunStatus.completed,
        current_stage=PaperRunStage.completed,
        stage_log=stage_log,
        artifact_index=artifact_index,
        regenerate_jobs=[],
        error_message=None,
        created_at=now,
        updated_at=now,
        finished_at=now,
    )
    dump_json(paths.manifest, manifest.model_dump(mode="json"))


def prepare_files(samples: list[dict[str, Any]], metrics: dict[str, Any]) -> tuple[Path, Path, dict[str, Path]]:
    uploads_dir = Config.get_uploads_dir().resolve()
    uploads_dir.mkdir(parents=True, exist_ok=True)
    demo_dir = uploads_dir / "demo_experiments" / "crc_msi_paper"
    patch_dir = demo_dir / "patches"
    model_dir = uploads_dir / "training" / TASK_ID / "models"
    patch_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    for sample in samples:
        generate_patch_image(patch_dir / sample["filename"], sample)

    (model_dir / "best_model.pth").write_text(
        "Synthetic placeholder weights for demo Paper Agent experiment.\n",
        encoding="utf-8",
    )
    dump_json(
        model_dir / "model_config.json",
        {
            "model_id": MODEL_ID,
            "task_id": TASK_ID,
            "classes": CLASSES,
            "feature_extractor": "resnet50_demo",
            "aggregator": "attention_mil_demo",
            "note": "Placeholder config generated by seed-demo-paper-experiment.py",
        },
    )
    chart_paths = write_analysis_artifacts(uploads_dir, samples, metrics)
    return patch_dir, model_dir, chart_paths


async def main() -> None:
    samples = make_samples()
    metrics = calculate_metrics(samples)
    patch_dir, model_dir, chart_paths = prepare_files(samples, metrics)
    user_id = await seed_database(samples, metrics, patch_dir, model_dir, chart_paths)
    paper_paths = PaperRunPaths.for_paper(PAPER_ID)
    if paper_paths.root.exists():
        shutil.rmtree(paper_paths.root)
    await write_paper_run(user_id, metrics, chart_paths)
    await engine.dispose()

    print("Seeded demo Paper Agent experiment")
    print(f"  task_id: {TASK_ID}")
    print(f"  dataset_id: {DATASET_ID}")
    print(f"  paper_id: {PAPER_ID}")
    print(f"  samples: {len(samples)}")
    print(f"  accuracy: {metrics['accuracy']}")
    print(f"  charts: {', '.join(str(path) for path in chart_paths.values())}")


if __name__ == "__main__":
    asyncio.run(main())
