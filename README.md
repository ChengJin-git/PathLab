# SmartResearch

> A minimal, on-premise no-code friendly WSI (Whole Slide Image) research platform for digital pathology AI

## Overview

SmartResearch is a microservices-based platform designed for pathology research institutions to:
- **View** ultra-large pathology slides (WSI) in the browser with OpenSeadragon
- **Classify** WSI using custom deep learning models (MIL/ABMIL)
- **Upload** and manage WSI files with support for 16+ formats
- **Train** and evaluate models with an intuitive web interface
- **Deploy** on-premise without cloud dependencies
- **Chat** with AI assistant to set up analysis tasks in natural language

**Key Features:**
- 🔬 **WSI Viewer**: Deep zoom support for gigapixel pathology images with full-screen mode
- 📤 **WSI Upload**: Single/batch file upload with real-time progress tracking
- 📊 **Metadata Management**: Comprehensive patient metadata (age, gender, source/organ)
- ✏️ **Batch Operations**: Edit and delete multiple slides at once
- 📋 **CSV Import**: Batch import via CSV template with detailed results
- 🗂️ **Format Support**: 16+ WSI formats (Aperio, Hamamatsu, Leica, Philips, etc.)
- 🤖 **AI Inference**: Pluggable inference models with hot-reload
- 💬 **AI Assistant**: Natural language task setup with streaming LLM responses
- 🎯 **Integrated Workflow**: Unified task creation with step-by-step guidance
- 🏥 **On-Premise**: Designed for hospital/research lab deployment
- 🚀 **Lightweight**: Minimal dependencies, easy to set up
- 🎨 **User-Friendly**: Medical professional-oriented terminology and interface

## Architecture

**Microservices:**
- **Frontend** (React + Vite, port 5173): SPA with OpenSeadragon viewer
- **Gateway** (FastAPI, port 6100): API orchestration, metadata management
- **Backend Services**:
  - **WSI Service** (FastAPI + ASlide, port 6101): Tile serving, DZI generation
  - **AI Service** (FastAPI, port 6102): Inference execution, model loading

**Production:**
- URL prefix: `/SmartResearch/`
- Nginx reverse proxy for all services
- JWT authentication (frontend) + internal API keys (services)

## Directory layout
```
smartresearch/
├── services/
│   ├── frontend/              # React+Vite app (OSD bundled; SPA under /SmartResearch/)
│   │   ├── src/
│   │   │   ├── pages/         # All page components
│   │   │   │   ├── DashboardPage.tsx
│   │   │   │   ├── AIChatPage.tsx
│   │   │   │   ├── NewTaskPage.tsx
│   │   │   │   ├── TaskListPage.tsx
│   │   │   │   ├── TaskDetailPage.tsx
│   │   │   │   ├── ListPage.tsx (WSI Browser)
│   │   │   │   ├── DetailPage.tsx (WSI Viewer)
│   │   │   │   ├── CheckpointManagerPage.tsx
│   │   │   │   ├── SettingsPage.tsx (Tabbed interface)
│   │   │   │   └── StorageManagementPage.tsx (Legacy, merged into Settings)
│   │   │   ├── components/    # Reusable UI components
│   │   │   │   ├── Layout.tsx
│   │   │   │   └── WSIViewer.tsx
│   │   │   └── api.ts         # API client functions
│   │   ├── public/            # Static assets
│   │   └── package.json
│   ├── gateway/               # FastAPI gateway (auth, task orchestration, AI chat, result aggregation)
│   │   ├── main.py            # Main API endpoints + AI streaming chat
│   │   ├── routes/            # API route modules
│   │   │   ├── training.py    # Training task endpoints
│   │   │   └── storage.py     # Storage management endpoints
│   │   ├── pipeline.py        # Training pipeline orchestration
│   │   └── models.py          # Pydantic models
│   └── backend/               # Backend microservices
│       ├── database/          # PostgreSQL database layer
│       │   ├── models.py      # SQLAlchemy ORM models (WSI, TrainingTask, TrainedModel, etc.)
│       │   ├── repositories.py # Data access layer
│       │   ├── database.py    # Connection management
│       │   └── init_db.py     # Database initialization
│       ├── storage/           # Storage management system
│       │   ├── manager.py     # StorageManager class
│       │   └── README.md      # Storage system documentation
│       ├── wsi/               # FastAPI + ASlide (DZI/tiles/patches/thumbnail)
│       │   ├── main.py        # WSI service endpoints
│       │   └── tiling.py      # Tile extraction logic
│       └── ai/                # FastAPI AI tasks (wsi_classification P0)
│           └── main.py        # AI inference endpoints
├── models/                    # Custom inference implementation
│   ├── lib/                   # Model components (extractors, aggregators)
│   ├── configs/               # Model configuration files
│   ├── checkpoints/           # Trained model weights
│   └── run_inference.py       # Inference script
├── uploads/                   # File storage (managed by StorageManager)
│   ├── wsi_files/             # WSI slide files
│   ├── coordinates/           # Tile coordinates cache (.h5)
│   ├── thumbnails/            # Generated thumbnails (.jpeg)
│   ├── masks/                 # Tissue masks (.npy)
│   ├── ai_results/            # AI analysis results (JSON)
│   ├── training/              # Training task data
│   │   └── {task_id}/
│   │       ├── features/      # Extracted features (.pt)
│   │       └── logs/          # Training logs
│   ├── models/                # Trained model checkpoints
│   │   └── {model_id}/
│   └── logs/                  # System logs
├── docs/                      # API contracts and documentation
├── .env                       # Environment variables (API keys, database URL)
├── start_all.sh               # Start all services
└── stop_all.sh                # Stop all services
```

## API prefixes (behind Nginx)
- /SmartResearch/api/wsi/  → services/backend/wsi (6101)
- /SmartResearch/api/ai/   → services/backend/ai (6102)
- /SmartResearch/api/      → services/gateway (6100)

## Frontend Pages

The platform includes the following pages:

1. **Dashboard** (`/`) - Overview with statistics and quick actions
   - System statistics (WSI count, task count, results count)
   - Label distribution visualization
   - Quick access to main features

2. **AI Assistant** (`/ai-chat`) - Natural language task setup with streaming chat
   - For non-technical users who prefer conversational interface
   - AI suggests configurations automatically
   - Streaming LLM responses with SiliconFlow integration
   - Conversation history management

3. **New Analysis** (`/task-setup`) - Complete analysis workflow for researchers
   - Step 1: Task Configuration (name, type, description)
   - Step 2: Data Selection (upload/import WSI files)
   - Step 3: Preprocessing (patch extraction + feature extraction)
   - Step 4: Model Configuration (aggregator + training parameters)
   - Step 5: Training & Execution (real-time progress monitoring)
   - Step 6: Results (summary and next steps)
   - Full control over preprocessing and model parameters

4. **Task List** (`/task-list`) - Browse and manage training tasks
   - View all training tasks with status and progress
   - Filter by status (pending, running, completed, failed)
   - Real-time progress updates
   - Delete tasks with storage cleanup

5. **Task Detail** (`/task/:task_id`) - Detailed view of training task
   - Real-time progress monitoring
   - Live log streaming
   - Configuration details (preprocessing, model)
   - WSI list and class distribution
   - Auto-refresh toggle

6. **Slide Browser** (`/wsi-list`) - Browse and manage WSI files with analysis results
   - Upload single/multiple files with metadata
   - Import via CSV template
   - Edit/delete individual or multiple slides
   - View all metadata fields in table
   - Analysis results and confidence scores

7. **Slide Viewer** (`/wsi/:wsi_id`) - Full-screen WSI viewer with metadata and AI analysis
   - Deep zoom with OpenSeadragon
   - Metadata panel with patient information
   - AI analysis results display
   - Full-screen mode

8. **Checkpoint Manager** (`/checkpoint-manager`) - Manage and organize model checkpoints
   - Browse available model checkpoints
   - View checkpoint metadata and performance metrics
   - Load/unload checkpoints for inference
   - Delete unused checkpoints
   - Grid/list view toggle

9. **Settings** (`/settings`) - Comprehensive system configuration with tabbed interface
   - **General Tab**: AI Configuration (SiliconFlow API key, base URL, model selection)
   - **Processing Tab**: Patch & Feature Extraction settings (tile size, stride, tissue segmentation)
   - **Tasks Tab**: Slide Task Configuration (timeout, retry settings)
   - **Models Tab**: Checkpoint Manager settings
   - **Storage Tab**: Storage Management & Cleanup
     - Storage overview with breakdown by category
     - Orphaned files detection and cleanup
     - Storage statistics and monitoring

All pages use medical professional-friendly terminology (e.g., "Slide" instead of "WSI", "Analysis" instead of "Inference").

## Quick Start

### 1. Install Dependencies

**Backend (minimal)**
```bash
pip install fastapi uvicorn pillow
```

**Frontend**
```bash
cd smartresearch/services/frontend
npm install
cd ../../..
```

### 2. Start All Services

**One-click startup**
```bash
bash smartresearch/start_all.sh
```

**Or start manually**
```bash
# Terminal 1: Gateway
python -m uvicorn smartresearch.services.gateway.main:app --port 6100 --reload

# Terminal 2: WSI Service
python -m uvicorn smartresearch.services.backend.wsi.main:app --port 6101 --reload

# Terminal 3: AI Service
python -m uvicorn smartresearch.services.backend.ai.main:app --port 6102 --reload

# Terminal 4: Frontend
cd smartresearch/services/frontend
npm run dev
```

### 4. Access

- **Frontend**: http://127.0.0.1:5173
- **Gateway API**: http://127.0.0.1:6100/docs
- **AI API**: http://127.0.0.1:6102/docs

### 5. Stop All Services

```bash
bash smartresearch/stop_all.sh
```

## Custom Inference Implementation

The AI service automatically loads custom inference logic from `models/run_inference.py`.

**Your colleague should implement:**
```python
def run_inference(wsi_path: str, params: dict, classes: list) -> dict:
    """
    Args:
        wsi_path: Full path to WSI file
        params: {"tile_size": 256, "stride": 256, ...}
        classes: List of class names
    Returns:
        {"pred": str, "probs": dict, "num_tiles": int}
    """
    # Implement tiling, feature extraction, aggregation here
    pass
```

See `models/README.md` for detailed interface documentation.

**Fallback behavior:**
- If `run_inference.py` doesn't exist → stub mode (uses metadata label)
- If custom inference raises exception → fallback to stub mode

## Current Features (v0.3)

### ✅ Core Platform
- **Microservices Architecture**: Gateway, WSI Service, AI Service, Frontend
- **WSI Viewer**: Full-screen OpenSeadragon viewer with metadata panel
- **WSI Upload**: Single/batch file upload and path-based registration
- **Format Support**: 16+ WSI formats via ASlide
- **Inference API**: Pluggable models with hot-reload and fallback mechanism
- **Metadata Management**: PostgreSQL database with repository pattern
- **Database Schema**: Support for patient metadata (age, gender, source/organ)

### ✅ User Interface (Medical Professional-Oriented)
- **Dashboard**: Overview with statistics and quick actions
- **AI Assistant**: Natural language task setup with streaming LLM chat
- **Slide Browser**: Table view with analysis results and confidence scores
- **New Analysis**: Integrated workflow with step-by-step guidance
  - Task description
  - Model selection (ResNet50, ViT-Base, CTransPath, UNI)
  - Data selection with metadata display
  - Training simulation
- **Checkpoint Manager**: Model checkpoint management interface
  - Browse and organize model checkpoints
  - View checkpoint metadata and performance metrics
  - Load/unload checkpoints for inference
- **Settings**: System configuration (placeholder)
- **Responsive Design**: Modern UI with Tailwind CSS
- **User-Friendly Terminology**: Medical terms instead of technical jargon

### ✅ WSI Upload & Management (Oct 2024)
- [x] **Single File Upload**: Upload WSI files with real-time progress tracking
  - XMLHttpRequest-based upload with accurate progress bars (0-100%)
  - Smooth progress animation with status indicators
  - Support for metadata input during upload (label, case_id, age, gender, source)
- [x] **Batch File Upload**: Upload multiple WSI files simultaneously
  - Individual progress tracking for each file
  - Success/failure status for each upload
  - Automatic list refresh after upload completion
- [x] **CSV Batch Import**: Import multiple WSI files via CSV template
  - Downloadable CSV template with example data
  - Support for all metadata fields (label, case_id, age, gender, source)
  - Detailed upload results with success/failure breakdown
- [x] **Metadata Management**: Comprehensive metadata support
  - **Label**: Disease classification (e.g., Benign, Malignant, Grade 1)
  - **Case ID**: Patient/case identifier
  - **Age**: Patient age in years
  - **Gender**: Patient gender (Male, Female, Other)
  - **Source**: Organ/tissue source (e.g., Cervix, Lung, Breast)
- [x] **Single Edit**: Edit metadata for individual slides
  - Modal dialog with all metadata fields
  - Real-time validation and update
- [x] **Batch Edit**: Edit metadata for multiple slides at once
  - Select multiple slides with checkboxes
  - Update common fields across selected slides
  - Smart update: empty fields keep existing values
- [x] **Batch Delete**: Delete multiple slides at once
  - Confirmation dialog with slide count
  - Permanent deletion warning
  - Automatic list refresh after deletion
- [x] **Table Display**: Enhanced table view with all metadata fields
  - Sortable columns
  - Checkbox selection for batch operations
  - Color-coded status indicators
  - Responsive design for different screen sizes

### ✅ Recent Updates (Oct 2024)
- [x] Full-screen WSI viewer without layout wrapper
- [x] AI chat interface with streaming responses
- [x] Integrated task creation workflow (NewTaskPage)
- [x] Medical professional-friendly terminology across all pages
- [x] Link to structured setup from AI chat
- [x] Upload progress tracking: Real-time progress bars for file uploads
- [x] Metadata fields expansion**: Added age, gender, source fields
- [x] Batch operations: Edit and delete multiple slides at once
- [x] CSV template: Downloadable template for batch import
- [x] Database migration: Added new columns to support patient metadata
- [x] API optimization: Use `to_dict()` method for consistent data serialization
- [x] SiliconFlow AI Integration

## Roadmap

### Phase 2: Model Integration (Next)
- [ ] Real model integration (ResNet50, ViT, CTransPath, UNI)
- [ ] Feature extraction pipeline
- [ ] MIL/ABMIL aggregation
- [ ] Attention map visualization
- [ ] Batch inference support
- [ ] Performance optimization (caching, async)

### Phase 3: Training Pipeline
- [ ] Real model training backend (PyTorch)
- [ ] Training progress monitoring with WebSocket
- [ ] Hyperparameter tuning interface
- [ ] Model versioning and management
- [ ] Training data augmentation options

### Phase 4: Advanced Features
- [ ] Multi-task learning support
- [ ] Active learning workflow
- [ ] Annotation tools integration
- [ ] Experiment tracking (MLflow/Weights & Biases)
- [ ] Model comparison and A/B testing
- [ ] Export results to various formats

### Phase 5: Production Readiness
- [ ] User authentication and authorization
- [ ] Audit logging
- [ ] Performance monitoring (Prometheus/Grafana)
- [ ] Automated testing (unit, integration, E2E)
- [ ] Docker/Kubernetes deployment
- [ ] Comprehensive documentation and tutorials

## For Model Developers

If you're implementing custom inference models:

1. **Quick Start**: See `models/README.md` for the interface specification
2. **Implementation**: Edit `models/run_inference.py` with your logic
3. **Testing**: No need to restart services - hot reload is enabled
4. **Fallback**: System won't break if your code fails

**Minimal Example:**
```python
# models/run_inference.py
def run_inference(wsi_path: str, params: dict, classes: list) -> dict:
    # 1. Load WSI
    # 2. Extract tiles
    # 3. Extract features
    # 4. Aggregate and classify

    return {
        "pred": "LUAD",
        "probs": {"LUAD": 0.7, "LUSC": 0.2, "Normal": 0.1},
        "num_tiles": 500
    }
```

## Notes
- Nginx injects `x-internal-api-key` headers to internal services; frontend only uses JWT
- Database schema: PostgreSQL with Alembic migrations (see `smartresearch/services/backend/database/README.md`)
- API contracts: see `docs/api_contracts.md`
- Supported WSI formats: `.svs`, `.svslide`, `.ndpi`, `.scn`, `.mrxs`, `.bif`, `.tif`, `.tiff`, `.vsi`, `.vms`, `.vmu`, `.kfb`, `.sdpc`, `.TMAP`, `.mds`, `.mdsx`, `.tron`, `.isyntax` (via ASlide)

## Contributing

Contributions are welcome! Please:
1. Follow the existing code style
2. Add tests for new features
3. Update documentation
4. Submit a pull request

## License

This project is licensed under the GPLv3 license.

## Acknowledgements

- ASlide: https://github.com/MrPeterJin/ASlide
- OpenSeadragon: https://github.com/openseadragon/openseadragon
- FastAPI: https://github.com/tiangolo/fastapi
- React: https://github.com/facebook/react
- Vite: https://github.com/vitejs/vite

## Contact

Cheng Jin <cjinag@connect.ust.hk>