"""Shared submit-time availability policy for training and inference requests."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.repositories import DatasetRepository
from backend.storage import external_availability


def _unavailable_detail(
    *,
    reason: str | None,
    dataset_id: str | None = None,
    wsi_ids: list[str] | None = None,
    unavailable_count: int | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "code": "EXTERNAL_DATASET_UNAVAILABLE",
        "message": "Selected data is temporarily unavailable because its external storage cannot be reached.",
        "reason": reason or "External storage unavailable",
    }
    if dataset_id:
        detail["dataset_id"] = dataset_id
    if wsi_ids:
        detail["wsi_ids"] = wsi_ids
    if unavailable_count is not None:
        detail["unavailable_count"] = unavailable_count
    return detail


async def require_dataset_available(db: AsyncSession, dataset_id: str) -> None:
    availability = external_availability.get_dataset_availability(dataset_id)
    if availability.get("status") != external_availability.UNAVAILABLE:
        return
    refs_by_dataset = await DatasetRepository.get_wsi_path_refs_batch(db, [dataset_id])
    if not any(
        external_availability.is_external_path(ref.get("wsi_path"))
        for ref in refs_by_dataset.get(dataset_id, [])
    ):
        return
    raise HTTPException(
        status_code=409,
        detail=_unavailable_detail(
            dataset_id=dataset_id,
            reason=availability.get("reason"),
            unavailable_count=int(availability.get("unavailable_count") or 0),
        ),
    )


def require_wsis_available(wsis: list[Any]) -> None:
    unavailable: list[tuple[str, dict[str, Any]]] = []
    for wsi in wsis:
        wsi_path = getattr(wsi, "wsi_path", None)
        if wsi_path is not None and not external_availability.is_external_path(wsi_path):
            continue
        wsi_id = str(getattr(wsi, "wsi_id", wsi))
        availability = external_availability.get_wsi_availability(wsi_id)
        if availability.get("status") == external_availability.UNAVAILABLE:
            unavailable.append((wsi_id, availability))
    if unavailable:
        raise HTTPException(
            status_code=409,
            detail=_unavailable_detail(
                reason=unavailable[0][1].get("reason"),
                wsi_ids=[wsi_id for wsi_id, _ in unavailable],
                unavailable_count=len(unavailable),
            ),
        )
