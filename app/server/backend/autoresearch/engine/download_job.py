"""Isolated, cancellable dataset acquisition process."""

import asyncio
import json
import os
import sys
from pathlib import Path

from backend.common.config import Config
from backend.common.settings_store import read_config
from backend.database.database import safe_session
from backend.database.models import ResearchJob

from . import store
from .datasets import acquire


async def main(job_id: str):
    settings = Config._build_global_settings(read_config(Config.STORAGE_CONFIG_FILE))
    if settings.get("huggingface_token"):
        os.environ["HF_TOKEN"] = settings["huggingface_token"]
    async with safe_session() as db:
        job = await db.get(ResearchJob, job_id)
    session = await store.get(job.session_id)
    result = await acquire(job.session_id, job.payload["record"], job_id)
    (Path(session.workspace_path) / "downloads" / f"{job_id}.result.json").write_text(
        json.dumps(result)
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
