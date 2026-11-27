"""Connect persisted models using producer-supplied task-aware prediction specs.

python -m backend.services.connect_research_models --spec-file /path/specs.json
The JSON maps model IDs to PredictionSpec objects. No dataset/model-name inference.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from backend.database.database import engine, safe_session
from backend.database.models import DataGroup, TrainedModel, TrainingTask
from backend.services.research_prediction import (
    CONTRACT,
    prepare_predictor,
    save_manifest,
)


async def connect_models(specifications: dict) -> list[str]:
    connected = []
    for model_id, specification in specifications.items():
        async with safe_session() as db:
            row = (
                await db.execute(
                    select(TrainedModel, TrainingTask, DataGroup.task_type)
                    .join(TrainingTask, TrainingTask.task_id == TrainedModel.task_id)
                    .join(DataGroup, DataGroup.group_id == TrainingTask.group_id)
                    .where(TrainedModel.model_id == model_id)
                )
            ).one_or_none()
            if not row:
                raise ValueError(f"Model not found: {model_id}")
            model, task, task_type = row
            if specification["task_type"] != task_type:
                raise ValueError(f"Prediction task does not match model {model_id}")
            path = Path(model.model_path)
            adapter = (
                path.parent / "adapter"
                if specification["runtime"] == "python"
                else None
            )
            extractor = model.feature_extractor
            already_connected = (task.model_config or {}).get(
                "inference_contract"
            ) == CONTRACT
        manifest = await asyncio.to_thread(
            prepare_predictor, path, extractor, specification, adapter
        )
        await asyncio.to_thread(save_manifest, path.parent, manifest)
        async with safe_session() as db:
            model = await db.scalar(
                select(TrainedModel).where(TrainedModel.model_id == model_id)
            )
            task = await db.scalar(
                select(TrainingTask).where(TrainingTask.task_id == model.task_id)
            )
            task.model_config = {
                **(task.model_config or {}),
                "inference_contract": CONTRACT,
            }
            task.preprocessing_config = {
                **(task.preprocessing_config or {}),
                **manifest["preprocessing"],
            }
            task.classes = manifest["classes"]
            model.classes = manifest["classes"]
            if not already_connected:
                model.is_active = True
            for suffix in [" — research only", " - research only", " (research only)"]:
                model.model_name = model.model_name.removesuffix(suffix)
                task.task_name = task.task_name.removesuffix(suffix)
            await db.commit()
        connected.append(model_id)
    return connected


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(
            "Connected models:",
            ", ".join(await connect_models(json.loads(args.spec_file.read_text()))),
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
