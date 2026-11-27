"""One verified feature inventory for slide-local retrieval and analysis planning."""

import asyncio
import hashlib
import json
from pathlib import Path
from sqlalchemy import select, func
from backend.database.models import FeatureArtifact, WSISlide, utc_now


def inspect_artifact(path, coords, model_id, contract=None, provenance=None):
    import torch, h5py, numpy as np
    from .viewer_features import revision

    path = Path(path).resolve()
    coords = Path(coords).resolve() if coords else None
    if path.suffix == ".npy":
        values = np.load(path, mmap_mode="r", allow_pickle=False)
    else:
        try:
            values = torch.load(path, map_location="meta", weights_only=True, mmap=True)
        except RuntimeError:
            values = torch.load(path, map_location="meta", weights_only=True)
        if isinstance(values, dict):
            values = values.get("features")
    if values is None or len(values.shape) != 2 or not values.shape[0]:
        raise ValueError("Invalid feature tensor")
    rows, dimensions = map(int, values.shape)
    if contract and contract["dimensions"] != dimensions:
        raise ValueError("Feature dimensions do not match contract")
    if coords:
        with h5py.File(coords, "r") as file:
            if file["coords"].shape != (rows, 2):
                raise ValueError("Feature coordinates do not match tensor rows")
            attrs = file["coords"].attrs
            if "patch_size" not in attrs and "read_size" not in attrs:
                raise ValueError("Coordinate scale is missing")
    return {
        "artifact_id": hashlib.sha256(str(path).encode()).hexdigest()[:24],
        "wsi_id": path.stem,
        "model_id": model_id,
        "feature_path": str(path),
        "coordinates_path": str(coords) if coords else None,
        "feature_revision": revision(path),
        "coordinates_revision": revision(coords) if coords else None,
        "contract": contract,
        "rows": rows,
        "dimensions": dimensions,
        "provenance": provenance or {},
        "status": "ready",
        "verified_at": utc_now(),
    }


async def upsert_artifacts(db, items):
    if not items:
        return
    for item in items:
        item["artifact_id"] = hashlib.sha256(
            (item["wsi_id"] + "\0" + item["feature_path"]).encode()
        ).hexdigest()[:24]
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    for offset in range(0, len(items), 500):
        statement = insert(FeatureArtifact).values(items[offset : offset + 500])
        await db.execute(
            statement.on_conflict_do_update(
                index_elements=["artifact_id"],
                set_={
                    key: getattr(statement.excluded, key)
                    for key in items[0]
                    if key != "artifact_id"
                },
            )
        )


async def register_manifest(db, slide, path):
    path = Path(path)
    manifest = json.loads(
        await asyncio.to_thread(path.with_suffix(".feature.json").read_text)
    )
    item = await asyncio.to_thread(
        inspect_artifact,
        path,
        manifest["coordinates_path"],
        manifest["contract"]["model_id"],
        manifest["contract"],
        {"source": "producer_contract"},
    )
    item["wsi_id"] = slide.wsi_id
    await upsert_artifacts(db, [item])
    slide.feature_extracted = True


async def registered_features(db, slide):
    from .viewer_features import revision
    from .viewer_text_encoders import available
    from backend.ai.feature_contracts import FeatureContract

    rows = (
        await db.scalars(
            select(FeatureArtifact).where(
                FeatureArtifact.wsi_id == slide.wsi_id,
                FeatureArtifact.status == "ready",
            )
        )
    ).all()

    def inspect():
        items = []
        for row in rows:
            try:
                if row.feature_revision != revision(row.feature_path):
                    continue
                coordinates_valid = bool(
                    row.coordinates_path
                    and row.coordinates_revision == revision(row.coordinates_path)
                )
                contract = (
                    FeatureContract.model_validate(row.contract)
                    if row.contract
                    else None
                )
                aligned = bool(
                    contract
                    and contract.text_encoder
                    and contract.text_encoder.aligned_space == contract.embedding_space
                    and available(contract.text_encoder)
                )
                items.append(
                    {
                        "id": row.artifact_id,
                        "model_id": row.model_id,
                        "preprocessing_id": contract.preprocessing
                        if contract
                        else row.provenance.get(
                            "preprocessing_summary", "verified-coordinate-pairs"
                        ),
                        "image_similarity": coordinates_valid,
                        "text_similarity": aligned,
                        "reason": "feature_coordinates_missing"
                        if not coordinates_valid
                        else None
                        if aligned
                        else "text_alignment_unavailable",
                        "revision": row.feature_revision
                        + ":"
                        + (row.coordinates_revision or ""),
                        "path": row.feature_path,
                        "coords_path": row.coordinates_path,
                        "contract": row.contract or {"dimensions": row.dimensions},
                        "provenance": row.provenance.get("source"),
                    }
                )
            except (OSError, ValueError):
                continue
        return items

    return await asyncio.to_thread(inspect)


async def dataset_feature_summary(db, dataset_ids):
    rows = (
        await db.execute(
            select(
                WSISlide.dataset_id,
                FeatureArtifact.model_id,
                func.count(func.distinct(FeatureArtifact.wsi_id)).label("images"),
                func.count(func.distinct(FeatureArtifact.wsi_id))
                .filter(FeatureArtifact.coordinates_path.is_not(None))
                .label("spatial_images"),
            )
            .join(WSISlide, WSISlide.wsi_id == FeatureArtifact.wsi_id)
            .where(
                WSISlide.dataset_id.in_(dataset_ids), FeatureArtifact.status == "ready"
            )
            .group_by(WSISlide.dataset_id, FeatureArtifact.model_id)
        )
    ).all()
    result = {}
    for dataset, model, images, spatial in rows:
        result.setdefault(dataset, []).append(
            {
                "model_id": model,
                "image_count": images,
                "spatial_image_count": spatial,
                "capability": "visual_features",
                "text_alignment": "requires_explicit_text_encoder_contract",
            }
        )
    return result
