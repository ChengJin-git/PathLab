"""
Gateway routes package

Route modules:
- auth_local: Local user authentication (FastAPI-Users with JWT)
- auth: Legacy OAuth authentication (Casdoor - deprecated, kept for reference)
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
- asr: ASR (Automatic Speech Recognition) using DashScope Qwen3-ASR
- heatmap: Heatmap and visualization proxy routes
- gpu: GPU information and status
"""
# Use new local authentication (FastAPI-Users with JWT)
from .auth_local import router as auth_router

# Legacy Casdoor auth (kept for reference, not used)
# from .auth import router as auth_router_legacy

from .stats import router as stats_router
from .results import router as results_router
from .wsi import router as wsi_router
from .wsi_upload import router as wsi_upload_router
from .training import router as training_router
from .ai_tasks import router as ai_tasks_router
from .models import router as models_router
from .chat import router as chat_router
from .storage import router as storage_router
from .queue import router as queue_router
from .asr import router as asr_router
from .heatmap import router as heatmap_router
from .settings import router as settings_router
from .gpu import router as gpu_router

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
    "storage_router",
    "queue_router",
    "asr_router",
    "heatmap_router",
    "settings_router",
    "gpu_router",
]

