"""Exercise actual Postgres row/advisory locks with simultaneous editors."""

import asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker
from backend.services.viewer_annotations import (
    mutate_regions,
    RegionMutation,
    list_regions,
)
from test_dataset_catalog_and_result_privacy import catalog_db, make_dataset


async def test_simultaneous_region_writes_and_idempotent_replay(catalog_db):
    db, owner, _, _ = catalog_db
    await make_dataset(db, owner)
    factory = async_sessionmaker(db.bind, expire_on_commit=False)

    def body(operation, identity, revision=0, label="A"):
        return RegionMutation(
            operation_id=operation,
            layer="shared",
            changes=[
                {
                    "id": identity,
                    "revision": revision,
                    "value": {
                        "type": "rect",
                        "x": 1,
                        "y": 1,
                        "width": 10,
                        "height": 10,
                        "label": label,
                    },
                }
            ],
        )

    async def save(value):
        async with factory() as session:
            try:
                return await mutate_regions(session, owner, "image-0", value)
            except HTTPException as exc:
                return exc.status_code

    first = body("create", "region")
    a, b = await asyncio.gather(save(first), save(first))
    assert a == b and isinstance(a, dict)
    result = await asyncio.gather(
        save(body("edit-a", "region", 1, "A")), save(body("edit-b", "region", 1, "B"))
    )
    assert sum(isinstance(item, dict) for item in result) == 1 and 409 in result
    result = await asyncio.gather(
        save(body("create-two", "two")), save(body("create-three", "three"))
    )
    assert all(isinstance(item, dict) for item in result)
    async with factory() as session:
        page = await list_regions(session, owner, "image-0", "shared", limit=2)
        following = await list_regions(
            session, owner, "image-0", "shared", limit=2, after=page["next_cursor"]
        )
        assert (
            page["total"] == 3
            and len(page["items"]) == 2
            and len(following["items"]) == 1
        )
