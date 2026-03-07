# Copyright (c) 2025 PathLab
# PathLab tools for querying datasets and models

import logging
from typing import Optional, Type

from langchain_core.callbacks import (
    AsyncCallbackManagerForToolRun,
    CallbackManagerForToolRun,
)
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from src.pathlab import (
    fetch_datasets,
    fetch_trained_models,
    get_supported_feature_extractors,
    get_supported_mil_aggregators,
)

logger = logging.getLogger(__name__)


# ============== Search Datasets Tool ==============

class SearchDatasetsInput(BaseModel):
    """Input for searching PathLab datasets."""
    query: str = Field(
        description="Search query to filter datasets. Can be cancer type (e.g., 'lung', 'breast'), "
                    "task type (e.g., 'classification', 'survival'), or dataset name. "
                    "Use empty string to list all datasets."
    )


class SearchDatasetsTool(BaseTool):
    """Tool for searching user's datasets in PathLab."""
    
    name: str = "search_pathlab_datasets"
    description: str = (
        "Search for datasets in the user's PathLab account. "
        "Use this tool FIRST when user asks about training models or needs data. "
        "Input can be: cancer type (lung, breast, colon), task type (classification, survival), "
        "or leave empty to list all available datasets. "
        "Returns dataset names, file counts, and task types."
    )
    args_schema: Type[BaseModel] = SearchDatasetsInput
    
    def _filter_datasets(self, datasets: list[dict], query: str) -> list[dict]:
        """Filter datasets based on query."""
        if not query or query.strip() == "":
            return datasets
        
        query_lower = query.lower()
        filtered = []
        for ds in datasets:
            name = ds.get("name", "").lower()
            task = ds.get("task_type", "").lower()
            # Match by name or task type
            if query_lower in name or query_lower in task:
                filtered.append(ds)
        return filtered
    
    def _format_results(self, datasets: list[dict], query: str) -> str:
        """Format dataset results for the agent."""
        if not datasets:
            if query:
                return f"No datasets found matching '{query}' in the user's PathLab account."
            return "The user has no datasets in PathLab yet. They need to upload WSI files first, or you can suggest public datasets."
        
        lines = [f"Found {len(datasets)} dataset(s) in PathLab:"]
        for ds in datasets:
            name = ds.get("name", "Unknown")
            count = ds.get("file_count", 0)
            task = ds.get("task_type", "classification")
            data_level = ds.get("data_level", "file")
            lines.append(f"  - {name}: {count} files, task={task}, level={data_level}")
        
        if query:
            lines.append(f"\n(Filtered by: '{query}')")
        
        return "\n".join(lines)

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Synchronous run - uses cached data."""
        from src.pathlab.api import _cache
        
        datasets = _cache.get("datasets", []) or []
        filtered = self._filter_datasets(datasets, query)
        return self._format_results(filtered, query)

    async def _arun(
        self,
        query: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """Asynchronous run - fetches fresh data."""
        try:
            datasets = await fetch_datasets()
            filtered = self._filter_datasets(datasets, query)
            return self._format_results(filtered, query)
        except Exception as e:
            logger.error(f"Error searching PathLab datasets: {e}")
            return f"Error accessing PathLab API: {str(e)}. Please try again later."


# ============== Search Models Tool ==============

class SearchModelsInput(BaseModel):
    """Input for searching PathLab trained models."""
    query: str = Field(
        description="Search query to filter models. Can be model name, extractor name "
                    "(e.g., 'UNI', 'CONCH'), aggregator name (e.g., 'ABMIL', 'TransMIL'), "
                    "or task type. Use empty string to list all models."
    )


class SearchModelsTool(BaseTool):
    """Tool for searching user's trained models in PathLab."""
    
    name: str = "search_pathlab_models"
    description: str = (
        "Search for trained AI models in the user's PathLab account. "
        "Use this to check what models the user has already trained. "
        "Input can be: model name, extractor (UNI, CONCH, Virchow), "
        "aggregator (ABMIL, TransMIL), or leave empty to list all models."
    )
    args_schema: Type[BaseModel] = SearchModelsInput
    
    def _filter_models(self, models: list[dict], query: str) -> list[dict]:
        """Filter models based on query."""
        if not query or query.strip() == "":
            return models
        
        query_lower = query.lower()
        filtered = []
        for m in models:
            name = m.get("name", "").lower()
            extractor = m.get("extractor", "").lower()
            aggregator = m.get("aggregator", "").lower()
            task = m.get("task_type", "").lower()
            # Match by any field
            if (query_lower in name or query_lower in extractor or 
                query_lower in aggregator or query_lower in task):
                filtered.append(m)
        return filtered
    
    def _format_results(self, models: list[dict], query: str) -> str:
        """Format model results for the agent."""
        if not models:
            if query:
                return f"No trained models found matching '{query}' in the user's PathLab account."
            return "The user has no trained models in PathLab yet. They need to train models first using their datasets."
        
        lines = [f"Found {len(models)} trained model(s) in PathLab:"]
        for m in models:
            name = m.get("name", "Unknown")
            extractor = m.get("extractor", "Unknown")
            aggregator = m.get("aggregator", "Unknown")
            task = m.get("task_type", "classification")
            default_mark = " [DEFAULT]" if m.get("is_default") else ""
            lines.append(f"  - {name}: {extractor} + {aggregator}, task={task}{default_mark}")
        
        if query:
            lines.append(f"\n(Filtered by: '{query}')")
        
        return "\n".join(lines)

    def _run(
        self,
        query: str,
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        """Synchronous run - uses cached data."""
        from src.pathlab.api import _cache
        
        models = _cache.get("models", []) or []
        filtered = self._filter_models(models, query)
        return self._format_results(filtered, query)

    async def _arun(
        self,
        query: str,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        """Asynchronous run - fetches fresh data."""
        try:
            models = await fetch_trained_models()
            filtered = self._filter_models(models, query)
            return self._format_results(filtered, query)
        except Exception as e:
            logger.error(f"Error searching PathLab models: {e}")
            return f"Error accessing PathLab API: {str(e)}. Please try again later."


# ============== Get Supported Extractors Tool ==============

class GetExtractorsInput(BaseModel):
    """Input for getting supported feature extractors."""
    query: str = Field(
        default="",
        description="Optional filter query. Leave empty to get all supported extractors."
    )


class GetSupportedExtractorsTool(BaseTool):
    """Tool for listing supported feature extractors in PathLab."""
    
    name: str = "get_pathlab_extractors"
    description: str = (
        "Get the list of supported feature extractors (foundation models) in PathLab. "
        "Use this when user asks about available extractors or needs to choose one. "
        "Returns extractor names, sources, and descriptions."
    )
    args_schema: Type[BaseModel] = GetExtractorsInput

    def _run(
        self,
        query: str = "",
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        extractors = get_supported_feature_extractors()
        
        if query:
            query_lower = query.lower()
            extractors = [e for e in extractors 
                        if query_lower in e["name"].lower() or 
                           query_lower in e["source"].lower() or
                           query_lower in e["description"].lower()]
        
        if not extractors:
            return f"No feature extractors found matching '{query}'."
        
        lines = [f"PathLab supports {len(extractors)} feature extractor(s):"]
        for e in extractors:
            lines.append(f"  - {e['name']} ({e['source']}): {e['description']}")
        
        return "\n".join(lines)

    async def _arun(
        self,
        query: str = "",
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        return self._run(query, run_manager)


# ============== Get Supported Aggregators Tool ==============

class GetAggregatorsInput(BaseModel):
    """Input for getting supported MIL aggregators."""
    query: str = Field(
        default="",
        description="Optional filter query. Leave empty to get all supported aggregators."
    )


class GetSupportedAggregatorsTool(BaseTool):
    """Tool for listing supported MIL aggregators in PathLab."""
    
    name: str = "get_pathlab_aggregators"
    description: str = (
        "Get the list of supported MIL (Multiple Instance Learning) aggregators in PathLab. "
        "Use this when user asks about available aggregation methods or needs to choose one. "
        "Returns aggregator names and descriptions."
    )
    args_schema: Type[BaseModel] = GetAggregatorsInput

    def _run(
        self,
        query: str = "",
        run_manager: Optional[CallbackManagerForToolRun] = None,
    ) -> str:
        aggregators = get_supported_mil_aggregators()
        
        if query:
            query_lower = query.lower()
            aggregators = [a for a in aggregators 
                         if query_lower in a["name"].lower() or 
                            query_lower in a["description"].lower()]
        
        if not aggregators:
            return f"No MIL aggregators found matching '{query}'."
        
        lines = [f"PathLab supports {len(aggregators)} MIL aggregator(s):"]
        for a in aggregators:
            lines.append(f"  - {a['name']}: {a['description']}")
        
        return "\n".join(lines)

    async def _arun(
        self,
        query: str = "",
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
    ) -> str:
        return self._run(query, run_manager)


# ============== Tool Factory Functions ==============

def get_pathlab_dataset_tool() -> SearchDatasetsTool:
    """Get the PathLab dataset search tool."""
    return SearchDatasetsTool()


def get_pathlab_model_tool() -> SearchModelsTool:
    """Get the PathLab model search tool."""
    return SearchModelsTool()


def get_pathlab_extractor_tool() -> GetSupportedExtractorsTool:
    """Get the PathLab extractor info tool."""
    return GetSupportedExtractorsTool()


def get_pathlab_aggregator_tool() -> GetSupportedAggregatorsTool:
    """Get the PathLab aggregator info tool."""
    return GetSupportedAggregatorsTool()


def get_all_pathlab_tools() -> list[BaseTool]:
    """Get all PathLab tools."""
    return [
        get_pathlab_dataset_tool(),
        get_pathlab_model_tool(),
        get_pathlab_extractor_tool(),
        get_pathlab_aggregator_tool(),
    ]
