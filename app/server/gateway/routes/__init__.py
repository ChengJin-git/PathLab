"""
Gateway routes package

Route modules:
- auth: Local user authentication (FastAPI-Users with JWT)
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
- annotation: Annotation draft CRUD and ROI extraction
"""

# Router composition belongs to gateway.app_setup. Importing an individual
# endpoint or Worker helper must not initialize every Gateway feature.
