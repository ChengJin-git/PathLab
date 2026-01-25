"""
Training tools: built only on the Training API (Gateway /tasks/training and /wsi).

Layout:
  training/
    src/training/   <- tool, graph
    tests/
    run_chat.py     <- REPL 测试 tool 调用

- list_datasets: list datasets to help users understand available data
- list_wsi: list WSI for wsi_ids (use limit=0 for all data)
- create_training_task: create task and run pipeline
  * WSI-level: preprocess -> feature extraction -> MIL training
  * Patch-level: Feature Extractor + Linear Probe training (not MIL)
- list_training_tasks, get_training_task, get_training_task_models
"""

from .src.training import (
    create_training_graph,
    list_datasets_tool,
    list_wsi_tool,
    create_training_task_tool,
    list_training_tasks_tool,
    get_training_task_tool,
    get_training_task_models_tool,
    delete_training_task_tool,
    get_training_logs_tool,
    get_recent_training_logs_tool,
    ListDatasetsInput,
    ListWsiInput,
    CreateTrainingTaskInput,
    ListTrainingTasksInput,
    GetTrainingTaskInput,
    DeleteTrainingTaskInput,
    GetTrainingLogsInput,
    GetRecentTrainingLogsInput,
)

__all__ = [
    "create_training_graph",
    "list_datasets_tool",
    "list_wsi_tool",
    "create_training_task_tool",
    "list_training_tasks_tool",
    "get_training_task_tool",
    "get_training_task_models_tool",
    "delete_training_task_tool",
    "get_training_logs_tool",
    "get_recent_training_logs_tool",
    "ListDatasetsInput",
    "ListWsiInput",
    "CreateTrainingTaskInput",
    "ListTrainingTasksInput",
    "GetTrainingTaskInput",
    "DeleteTrainingTaskInput",
    "GetTrainingLogsInput",
    "GetRecentTrainingLogsInput",
]
