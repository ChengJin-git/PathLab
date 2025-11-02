"""
Gateway routes package

Route modules:
- wsi_crud: WSI CRUD operations (list, get, create, update, delete)
- wsi_batch_upload: Batch WSI upload via CSV
- training_tasks: Training task management
- ai_inference: AI inference task management
- chat: Chat and conversation management
- storage: Storage and file management
- trained_models: Trained model management
"""
from .wsi import router as wsi_router, stats_router
from .wsi_upload import router as wsi_upload_router
from .training import router as training_router
from .ai_tasks import router as ai_tasks_router, results_router
from .models import router as models_router
from .chat import router as chat_router, parse_router
from .storage import router as storage_router

__all__ = [
    "stats_router",
    "wsi_router",
    "wsi_upload_router",
    "training_router",
    "ai_tasks_router",
    "results_router",
    "models_router",
    "chat_router",
    "parse_router",
    "storage_router",
]

