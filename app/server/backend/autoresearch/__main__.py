"""Run the research supervisor with python -m backend.autoresearch."""
import asyncio
from .engine.worker import main

asyncio.run(main())
