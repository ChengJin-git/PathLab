"""Readiness checks for processes that depend on AI and Preprocessing."""

import asyncio
import logging

import httpx

from .config import Config

logger = logging.getLogger(__name__)


async def wait_for_services_ready(
    timeout: float = 60.0, check_interval: float = 2.0
) -> bool:
    services = [
        f"{Config.AI_SERVICE_URL}/health",
        f"{Config.PREPROCESSING_SERVICE_URL}/health",
    ]
    elapsed = 0.0
    while elapsed < timeout:
        all_ready = True
        for url in services:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.get(url)
                    if response.status_code != 200:
                        all_ready = False
                        break
            except Exception:
                all_ready = False
                break

        if all_ready:
            logger.info("✓ All dependent services are ready")
            return True

        await asyncio.sleep(check_interval)
        elapsed += check_interval
        logger.info(
            f"Waiting for services to be ready... ({elapsed:.0f}s/{timeout:.0f}s)"
        )

    logger.warning(f"Timeout waiting for services after {timeout}s")
    return False
