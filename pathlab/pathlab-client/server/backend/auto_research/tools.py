"""
Auto Research Agent — PathLab API Tools

8 tools wrapping PathLab Gateway API endpoints for experiment automation.
Uses httpx for async HTTP calls, following the BaseTool pattern from
deep-research/src/tools/pathlab.py.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Type

import httpx
from langchain_core.tools import BaseTool
from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Default gateway URL — overridden by AutoResearchConfig at runtime
_DEFAULT_GATEWAY_URL = "http://127.0.0.1:6100"
_TIMEOUT = 30.0

# Module-level config cache (set by the graph at startup)
_config: dict[str, str] = {
    "gateway_url": _DEFAULT_GATEWAY_URL,
    "auth_token": "",
}


def configure_tools(gateway_url: str, auth_token: str) -> None:
    """Set gateway URL and auth token for all tools."""
    _config["gateway_url"] = gateway_url.rstrip("/")
    _config["auth_token"] = auth_token


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if _config["auth_token"]:
        h["Authorization"] = f"Bearer {_config['auth_token']}"
    return h


def _url(path: str) -> str:
    return f"{_config['gateway_url']}{path}"


def _format_result(tool: str, status: str, data: Any, summary: str = "") -> str:
    """Standard tool result format."""
    return json.dumps({
        "tool": tool,
        "status": status,
        "summary": summary,
        "data": data,
    }, ensure_ascii=False, default=str)


# =============================================================================
# Tool Input Schemas
# =============================================================================

class ListDatasetsInput(BaseModel):
    """Input for listing datasets."""
    query: str = Field(default="", description="Optional search query to filter datasets")


class GetTrainingOptionsInput(BaseModel):
    """Input for getting available training options."""
    pass


class GetGPUInfoInput(BaseModel):
    """Input for getting GPU status."""
    pass


class SubmitTrainingTaskInput(BaseModel):
    """Input for submitting a training task."""
    task_name: str = Field(description="Name for the training task")
    task_type: str = Field(description="Task type: classification, survival, or segmentation")
    dataset_id: str = Field(description="UUID of the dataset to train on")
    feature_extractor: str = Field(description="Feature extractor to use (e.g., UNI2, CONCH)")
    aggregator: str = Field(description="MIL aggregator to use (e.g., abmil, clam_sb)")
    learning_rate: float = Field(default=0.0001, description="Learning rate")
    epochs: int = Field(default=50, description="Number of training epochs")
    optimizer: str = Field(default="adamw", description="Optimizer: adam, sgd, adamw")
    batch_size: int = Field(default=16, description="Batch size")
    split_strategy: str = Field(default="random", description="Split strategy: random, k_fold")
    split_ratios: dict = Field(
        default={"train": 0.7, "val": 0.1, "test": 0.2},
        description="Train/val/test split ratios",
    )
    seed: int = Field(default=42, description="Random seed for reproducibility")


class GetTrainingStatusInput(BaseModel):
    """Input for checking training task status."""
    task_id: str = Field(description="Training task ID to check")


class GenerateSplitsInput(BaseModel):
    """Input for generating dataset splits."""
    dataset_id: str = Field(description="UUID of the dataset")
    strategy: str = Field(default="random", description="Split strategy: random, k_fold, manual")
    ratios: dict = Field(
        default={"train": 0.7, "val": 0.1, "test": 0.2},
        description="Split ratios",
    )
    seed: int = Field(default=42, description="Random seed")


class RunAnalysisInput(BaseModel):
    """Input for running analysis on a completed training task."""
    task_id: str = Field(description="Training task ID to analyze")


class GetAnalysisResultsInput(BaseModel):
    """Input for retrieving analysis results."""
    task_id: str = Field(description="Training task ID")


# =============================================================================
# Tools
# =============================================================================

class ListDatasetsTool(BaseTool):
    """List available datasets in PathLab."""

    name: str = "list_pathlab_datasets"
    description: str = (
        "List all datasets available in PathLab with their file counts, "
        "data types, task types, and source organs. Use this to find datasets "
        "for experiment planning."
    )
    args_schema: Type[BaseModel] = ListDatasetsInput

    def _run(self, query: str = "", run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(self, query: str = "", run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_url("/wsi/datasets"), headers=_headers())
                resp.raise_for_status()
                data = resp.json()

            datasets = data.get("items", [])
            if query:
                q = query.lower()
                datasets = [d for d in datasets if q in json.dumps(d).lower()]

            summary = f"Found {len(datasets)} dataset(s)"
            return _format_result("list_pathlab_datasets", "success", {
                "datasets": datasets,
                "total": len(datasets),
            }, summary)
        except Exception as e:
            return _format_result("list_pathlab_datasets", "error", {"error": str(e)})


class GetTrainingOptionsTool(BaseTool):
    """Get available training options (extractors, aggregators, architectures)."""

    name: str = "get_training_options"
    description: str = (
        "Get all available feature extractors, MIL aggregators, segmentation "
        "architectures, loss functions, and optimizers supported by PathLab. "
        "Use this to know what options are available for experiment design."
    )
    args_schema: Type[BaseModel] = GetTrainingOptionsInput

    def _run(self, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(self, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_url("/training/options"), headers=_headers())
                resp.raise_for_status()
                data = resp.json()

            extractors = [e["name"] for e in data.get("feature_extractors", [])]
            aggregators = [a["name"] for a in data.get("aggregators", [])]
            summary = f"{len(extractors)} extractors, {len(aggregators)} aggregators available"
            return _format_result("get_training_options", "success", data, summary)
        except Exception as e:
            return _format_result("get_training_options", "error", {"error": str(e)})


class GetGPUInfoTool(BaseTool):
    """Get GPU status and availability."""

    name: str = "get_gpu_info"
    description: str = (
        "Check GPU availability, VRAM usage, and task queue status. "
        "Use this to determine if GPUs are available for experiments."
    )
    args_schema: Type[BaseModel] = GetGPUInfoInput

    def _run(self, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(self, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_url("/gpu/info"), headers=_headers())
                resp.raise_for_status()
                data = resp.json()

            gpu_count = data.get("gpu_count", 0)
            summary = f"{gpu_count} GPU(s) detected"
            return _format_result("get_gpu_info", "success", data, summary)
        except Exception as e:
            return _format_result("get_gpu_info", "error", {"error": str(e)})


class SubmitTrainingTaskTool(BaseTool):
    """Submit a training task to PathLab."""

    name: str = "submit_training_task"
    description: str = (
        "Submit a training task to PathLab with specified dataset, feature extractor, "
        "aggregator, and hyperparameters. Returns a task_id for monitoring."
    )
    args_schema: Type[BaseModel] = SubmitTrainingTaskInput

    def _run(self, **kwargs) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(
        self,
        task_name: str,
        task_type: str,
        dataset_id: str,
        feature_extractor: str,
        aggregator: str,
        learning_rate: float = 0.0001,
        epochs: int = 50,
        optimizer: str = "adamw",
        batch_size: int = 16,
        split_strategy: str = "random",
        split_ratios: dict = None,
        seed: int = 42,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        if split_ratios is None:
            split_ratios = {"train": 0.7, "val": 0.1, "test": 0.2}

        request_body = {
            "task_name": task_name,
            "task_type": task_type,
            "data_type": "wsi",
            "dataset_id": dataset_id,
            "preprocessing": {
                "feature_extractor": feature_extractor,
                "use_gpu": True,
            },
            "model": {
                "aggregator": aggregator,
                "learning_rate": learning_rate,
                "epochs": epochs,
                "optimizer": optimizer,
                "batch_size": batch_size,
            },
            "split_config": {
                "strategy": split_strategy,
                "ratios": split_ratios,
                "seed": seed,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _url("/tasks/training"),
                    headers=_headers(),
                    json=request_body,
                )
                resp.raise_for_status()
                data = resp.json()

            task_id = data.get("task_id", "")
            summary = f"Training task submitted: {task_id}"
            return _format_result("submit_training_task", "success", {
                "task_id": task_id,
                "task_name": task_name,
                "config": request_body,
            }, summary)
        except httpx.HTTPStatusError as e:
            error_detail = e.response.text if e.response else str(e)
            return _format_result("submit_training_task", "error", {
                "error": error_detail,
                "config": request_body,
            })
        except Exception as e:
            return _format_result("submit_training_task", "error", {"error": str(e)})


class GetTrainingStatusTool(BaseTool):
    """Check the status of a training task."""

    name: str = "get_training_status"
    description: str = (
        "Get the current status, progress, and metrics of a training task. "
        "Returns status (pending/queued/training/completed/failed), progress percentage, "
        "and metrics if completed."
    )
    args_schema: Type[BaseModel] = GetTrainingStatusInput

    def _run(self, task_id: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(self, task_id: str, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    _url(f"/tasks/training/{task_id}"),
                    headers=_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            status = data.get("status", "unknown")
            progress = data.get("progress", 0)
            summary = f"Task {task_id}: {status} ({progress}%)"
            return _format_result("get_training_status", "success", data, summary)
        except Exception as e:
            return _format_result("get_training_status", "error", {"error": str(e)})


class GenerateSplitsTool(BaseTool):
    """Generate train/val/test splits for a dataset."""

    name: str = "generate_splits"
    description: str = (
        "Generate train/val/test splits for a dataset before training. "
        "Supports random, k-fold, and manual strategies."
    )
    args_schema: Type[BaseModel] = GenerateSplitsInput

    def _run(self, **kwargs) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(
        self,
        dataset_id: str,
        strategy: str = "random",
        ratios: dict = None,
        seed: int = 42,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        if ratios is None:
            ratios = {"train": 0.7, "val": 0.1, "test": 0.2}

        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _url(f"/wsi/datasets/{dataset_id}/splits"),
                    headers=_headers(),
                    json={
                        "strategy": strategy,
                        "ratios": ratios,
                        "seed": seed,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            summary = f"Splits generated for dataset {dataset_id}"
            return _format_result("generate_splits", "success", data, summary)
        except Exception as e:
            return _format_result("generate_splits", "error", {"error": str(e)})


class RunAnalysisTool(BaseTool):
    """Run analysis on a completed training task."""

    name: str = "run_analysis"
    description: str = (
        "Run metrics analysis on a completed training task. "
        "Computes accuracy, AUC, F1, confusion matrix, and other metrics."
    )
    args_schema: Type[BaseModel] = RunAnalysisInput

    def _run(self, task_id: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(self, task_id: str, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    _url(f"/results/tasks/{task_id}/analysis"),
                    headers=_headers(),
                    json={
                        "metrics": ["accuracy", "auc", "f1", "precision", "recall"],
                        "charts": ["confusion_matrix", "roc_curve"],
                    },
                )
                resp.raise_for_status()
                data = resp.json()

            analysis_id = data.get("analysis_id", "")
            summary = f"Analysis started: {analysis_id}"
            return _format_result("run_analysis", "success", data, summary)
        except Exception as e:
            return _format_result("run_analysis", "error", {"error": str(e)})


class GetAnalysisResultsTool(BaseTool):
    """Get analysis results for a training task."""

    name: str = "get_analysis_results"
    description: str = (
        "Retrieve analysis results (metrics, charts) for a completed training task. "
        "Returns accuracy, AUC, F1, and other metrics."
    )
    args_schema: Type[BaseModel] = GetAnalysisResultsInput

    def _run(self, task_id: str, run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        raise NotImplementedError("Use async version")

    async def _arun(self, task_id: str, run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(
                    _url(f"/results/tasks/{task_id}/analysis"),
                    headers=_headers(),
                )
                resp.raise_for_status()
                data = resp.json()

            summary = f"Analysis results for task {task_id}"
            return _format_result("get_analysis_results", "success", data, summary)
        except Exception as e:
            return _format_result("get_analysis_results", "error", {"error": str(e)})


# =============================================================================
# Tool Registry
# =============================================================================

# Tools for the experiment planner node
PLANNER_TOOLS = [
    ListDatasetsTool(),
    GetTrainingOptionsTool(),
    GetGPUInfoTool(),
]

# Tools for the experiment executor node
EXECUTOR_TOOLS = [
    SubmitTrainingTaskTool(),
    GenerateSplitsTool(),
]

# Tools for the experiment monitor node
MONITOR_TOOLS = [
    GetTrainingStatusTool(),
]

# Tools for the results analyzer node
ANALYZER_TOOLS = [
    RunAnalysisTool(),
    GetAnalysisResultsTool(),
]

# All tools
ALL_TOOLS = PLANNER_TOOLS + EXECUTOR_TOOLS + MONITOR_TOOLS + ANALYZER_TOOLS
