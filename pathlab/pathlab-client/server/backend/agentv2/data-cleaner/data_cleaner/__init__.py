"""PathLab Data Cleaner: LLM-driven Excel/CSV auto-cleaning tool.

Usage as Python API:
    from data_cleaner import CleaningPipeline, CleaningConfig

    pipeline = CleaningPipeline(CleaningConfig(preset="wsi"))
    result = pipeline.run("input.xlsx", "output.csv")
"""

__version__ = "0.1.0"

from data_cleaner.pipeline import CleaningPipeline, CleaningConfig, PipelineResult
