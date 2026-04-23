import asyncio
from importlib import import_module
from unittest.mock import patch

import pytest
from fastapi import HTTPException

training_preflight = import_module("gateway.training_preflight")
Config = import_module("backend.common.config").Config
PreflightPolicy = training_preflight.PreflightPolicy
check_training_inputs = training_preflight.check_training_inputs
build_training_preflight_policy = training_preflight.build_training_preflight_policy


def _default_policy() -> PreflightPolicy:
    return PreflightPolicy(
        local_root_timeout_seconds=10,
        local_sample_timeout_seconds=10,
        local_sample_size=8,
        external_root_timeout_seconds=10,
        external_sample_timeout_seconds=10,
        external_sample_size=5,
    )


@pytest.mark.asyncio
async def test_local_patch_dataset_checks_root_and_sample_only():
    paths = [
        (f"wsi_{i}", f"/uploads/patches/{i}.png", f"{i}.png")
        for i in range(1000)
    ]
    inspected: list[str] = []

    async def fake_exists(path: str) -> bool:
        inspected.append(path)
        return True

    result = await check_training_inputs(
        paths_to_check=paths,
        uploads_dir="/uploads",
        policy=_default_policy(),
        path_exists_fn=fake_exists,
        sample_fn=lambda items, size: list(items)[:size],
    )

    assert result.inaccessible == []
    assert len(inspected) <= 1 + _default_policy().local_sample_size
    assert "/uploads" in inspected


@pytest.mark.asyncio
async def test_missing_sampled_file_blocks_submission():
    paths = [
        ("wsi_1", "/uploads/patches/good.png", "good.png"),
        ("wsi_2", "/uploads/patches/bad.png", "bad.png"),
    ]

    async def fake_exists(path: str) -> bool:
        return path != "/uploads/patches/bad.png"

    result = await check_training_inputs(
        paths_to_check=paths,
        uploads_dir="/uploads",
        policy=_default_policy(),
        path_exists_fn=fake_exists,
        sample_fn=lambda items, size: list(items)[:size],
    )

    assert result.inaccessible == ["bad.png"]


@pytest.mark.asyncio
async def test_root_timeout_blocks_submission():
    paths = [("wsi_1", "/uploads/patches/sample.png", "sample.png")]

    async def fake_exists(path: str) -> bool:
        if path == "/uploads":
            raise asyncio.TimeoutError
        return True

    with pytest.raises(HTTPException) as exc_info:
        _ = await check_training_inputs(
            paths_to_check=paths,
            uploads_dir="/uploads",
            policy=_default_policy(),
            path_exists_fn=fake_exists,
            sample_fn=lambda items, size: list(items)[:size],
        )

    assert exc_info.value.status_code == 503
    assert "Local storage" in exc_info.value.detail


def test_build_training_preflight_policy_uses_config_defaults():
    policy = build_training_preflight_policy()

    assert (
        policy.local_root_timeout_seconds
        == Config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_ROOT_TIMEOUT
    )
    assert (
        policy.local_sample_timeout_seconds
        == Config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_TIMEOUT
    )
    assert policy.local_sample_size == Config.DEFAULT_TRAINING_PREFLIGHT_LOCAL_SAMPLE_SIZE
    assert (
        policy.external_root_timeout_seconds
        == Config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_ROOT_TIMEOUT
    )
    assert (
        policy.external_sample_timeout_seconds
        == Config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_TIMEOUT
    )
    assert (
        policy.external_sample_size
        == Config.DEFAULT_TRAINING_PREFLIGHT_EXTERNAL_SAMPLE_SIZE
    )


@pytest.mark.asyncio
async def test_large_local_patch_dataset_uses_bounded_work():
    policy = PreflightPolicy(
        local_root_timeout_seconds=10,
        local_sample_timeout_seconds=10,
        local_sample_size=3,
        external_root_timeout_seconds=10,
        external_sample_timeout_seconds=10,
        external_sample_size=5,
    )
    paths = [
        (str(i), f"/uploads/patches/{i}.png", f"{i}.png") for i in range(73225)
    ]
    inspected: list[str] = []

    async def fake_exists(path: str) -> bool:
        inspected.append(path)
        return True

    result = await check_training_inputs(
        paths_to_check=paths,
        uploads_dir="/uploads",
        policy=policy,
        path_exists_fn=fake_exists,
        sample_fn=lambda items, size: list(items)[:size],
    )

    assert result.inaccessible == []
    assert len(inspected) <= 1 + policy.local_sample_size


@pytest.mark.asyncio
async def test_local_root_missing_blocks_submission():
    paths = [("wsi_1", "/uploads/patches/sample.png", "sample.png")]

    async def fake_exists(path: str) -> bool:
        return path != "/uploads"

    with pytest.raises(HTTPException) as exc_info:
        _ = await check_training_inputs(
            paths_to_check=paths,
            uploads_dir="/uploads",
            policy=_default_policy(),
            path_exists_fn=fake_exists,
            sample_fn=lambda items, size: list(items)[:size],
        )

    assert exc_info.value.status_code == 503
    assert "Local storage root is not accessible" in exc_info.value.detail


@pytest.mark.asyncio
async def test_local_sample_timeout_warns_and_allows_submission():
    warnings: list[str] = []

    async def fake_exists(path: str) -> bool:
        if path == "/uploads":
            return True
        await asyncio.sleep(1)
        return True

    result = await check_training_inputs(
        paths_to_check=[("wsi_1", "/uploads/patches/sample.png", "sample.png")],
        uploads_dir="/uploads",
        policy=PreflightPolicy(
            local_root_timeout_seconds=10,
            local_sample_timeout_seconds=0.01,
            local_sample_size=1,
            external_root_timeout_seconds=10,
            external_sample_timeout_seconds=10,
            external_sample_size=5,
        ),
        path_exists_fn=fake_exists,
        sample_fn=lambda items, size: list(items)[:size],
        warn_fn=warnings.append,
    )

    assert result.inaccessible == []
    assert warnings
    assert "allowing submission to proceed" in warnings[0]


@pytest.mark.asyncio
async def test_prefix_collision_path_is_treated_as_external():
    inspected: list[str] = []

    async def fake_exists(path: str) -> bool:
        inspected.append(path)
        return True

    with patch.object(training_preflight, "_mount_root", return_value="/external-root"):
        result = await check_training_inputs(
            paths_to_check=[("wsi_1", "/uploads_extra/sample.png", "sample.png")],
            uploads_dir="/uploads",
            policy=_default_policy(),
            path_exists_fn=fake_exists,
            sample_fn=lambda items, size: list(items)[:size],
        )

    assert result.inaccessible == []
    assert "/uploads" not in inspected
    assert "/external-root" in inspected
    assert "/uploads_extra/sample.png" in inspected


def test_mount_root_handles_exact_mount_match():
    with patch.object(training_preflight, "open", create=True) as mock_open:
        mock_open.return_value.__enter__.return_value = [
            "device /mnt/data ext4 rw 0 0\n",
            "device /mnt/other ext4 rw 0 0\n",
        ]

        root = training_preflight._mount_root("/mnt/data")

    assert root == "/mnt/data"


@pytest.mark.asyncio
async def test_external_sample_timeout_warns_and_allows_submission():
    warnings: list[str] = []

    async def fake_exists(path: str) -> bool:
        if path == "/mnt/data":
            return True
        await asyncio.sleep(1)
        return True

    with patch.object(training_preflight, "_mount_root", return_value="/mnt/data"):
        result = await check_training_inputs(
            paths_to_check=[("wsi_1", "/mnt/data/sample.png", "sample.png")],
            uploads_dir="/uploads",
            policy=PreflightPolicy(
                local_root_timeout_seconds=10,
                local_sample_timeout_seconds=10,
                local_sample_size=8,
                external_root_timeout_seconds=10,
                external_sample_timeout_seconds=0.01,
                external_sample_size=1,
            ),
            path_exists_fn=fake_exists,
            sample_fn=lambda items, size: list(items)[:size],
            warn_fn=warnings.append,
        )

    assert result.inaccessible == []
    assert warnings
    assert "Root: /mnt/data" in warnings[0]


@pytest.mark.asyncio
async def test_missing_external_sampled_file_blocks_submission():
    async def fake_exists(path: str) -> bool:
        return path != "/mnt/data/bad.png"

    with patch.object(training_preflight, "_mount_root", return_value="/mnt/data"):
        result = await check_training_inputs(
            paths_to_check=[
                ("wsi_1", "/mnt/data/good.png", "good.png"),
                ("wsi_2", "/mnt/data/bad.png", "bad.png"),
            ],
            uploads_dir="/uploads",
            policy=_default_policy(),
            path_exists_fn=fake_exists,
            sample_fn=lambda items, size: list(items)[:size],
        )

    assert result.inaccessible == ["bad.png"]
