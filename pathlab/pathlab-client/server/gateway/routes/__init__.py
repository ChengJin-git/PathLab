"""
Gateway routes package

Route modules:
- auth: User authentication (OAuth with PathHub Server via Casdoor)
- stats: System statistics
- results: AI analysis results
- wsi: WSI CRUD operations (list, get, create, update, delete)
- wsi_upload: Batch WSI upload via CSV
- training: Training task management
- ai_tasks: AI inference task management
- chat: Chat and conversation management
- storage: Storage and file management
- models: Trained model management
- queue: GPU task queue management
"""
from .auth import router as auth_router
from .stats import router as stats_router
from .results import router as results_router
from .wsi import router as wsi_router
from .wsi_upload import router as wsi_upload_router
from .training import router as training_router
from .ai_tasks import router as ai_tasks_router
from .models import router as models_router
from .chat import router as chat_router, parse_router
from .storage import router as storage_router
from .queue import router as queue_router

__all__ = [
    "auth_router",
    "stats_router",
    "results_router",
    "wsi_router",
    "wsi_upload_router",
    "training_router",
    "ai_tasks_router",
    "models_router",
    "chat_router",
    "parse_router",
    "storage_router",
    "queue_router",
]

