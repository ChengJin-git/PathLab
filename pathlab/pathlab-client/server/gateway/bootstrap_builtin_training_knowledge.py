"""Manual bootstrap for bundled training recommendation knowledge."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

# This script runs as a standalone bootstrap and should not rely on the shared
# gateway task queue for Marker parsing.
os.environ["PDF_SKIP_MARKER_GPU_QUEUE"] = "1"

from gateway.dependencies import logger
from gateway.routes.chat_training_recommendation import prewarm_training_recommendation_sources


async def _main() -> None:
    results = await prewarm_training_recommendation_sources(force_upgrade=True)
    success = sum(1 for ok in results.values() if ok)
    logger.info(f"Bundled training knowledge bootstrap finished: {success}/{len(results)} sources ready")
    if success != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(_main())
