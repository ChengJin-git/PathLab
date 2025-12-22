# PathLab

> A minimal, on-premise no-code friendly WSI (Whole Slide Image) research platform for digital pathology AI

## Overview

PathLab is a microservices-based platform designed for pathology research institutions to:
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
  - **Preprocessing Service** (FastAPI + ASlide, port 6101): Tile serving, DZI generation, patch extraction
  - **AI Service** (FastAPI, port 6102): Inference execution, model loading

**Production:**
- URL prefix: `/PathLab/`
- Nginx reverse proxy for all services
- JWT authentication (frontend) + internal API keys (services)

## Directory layout
```
pathlab/
├── services/
│   ├── frontend/              # React+Vite app (OSD bundled; SPA under /PathLab/)
│   │   ├── src/
│   │   │   ├── pages/         # All page components
│   │   │   │   ├── DashboardPage.tsx
│   │   │   │   ├── AIChatPage.tsx
│   │   │   │   ├── NewTaskPage.tsx
│   │   │   │   ├── TaskListPage.tsx
│   │   │   │   ├── TaskDetailPage.tsx
│   │   │   │   ├── UploadPage.tsx
│   │   │   │   ├── ListPage.tsx (WSI Browser)
│   │   │   │   ├── DetailPage.tsx (WSI Viewer)
│   │   │   │   ├── ResultsViewerPage.tsx
│   │   │   │   ├── ReportGeneratorPage.tsx
│   │   │   │   ├── SettingsPage.tsx (Tabbed interface)
│   │   │   │   └── StorageManagementPage.tsx
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
│       ├── preprocessing/     # FastAPI + ASlide (DZI/tiles/patches/thumbnail)
│       │   ├── main.py        # Preprocessing service endpoints
│       │   └── tiling.py      # Tile extraction logic
│       ├── ai/                # FastAPI AI tasks (wsi_classification, feature extraction)
│       │   ├── main.py        # AI inference endpoints
│       │   ├── extractors/    # Feature extraction models
│       │   ├── aggregators/   # MIL aggregation models
│       │   ├── classifiers/   # Classification models
│       │   └── tasks/         # AI task implementations
│       ├── analysis/          # Analysis service
│       └── paper/             # Paper generation service
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
- /PathLab/api/preprocessing/  → services/backend/preprocessing (6101)
- /PathLab/api/ai/             → services/backend/ai (6102)
- /PathLab/api/                → services/gateway (6100)

## Frontend Pages

The platform includes the following pages:

1. **Dashboard** (`/`) - Overview with statistics and quick actions
   - System statistics (WSI count, task count, results count)
   - Label distribution visualization
   - Quick access to main features

2. **New Task** (`/ai-chat`) - Natural language task setup with streaming chat
   - For non-technical users who prefer conversational interface
   - AI suggests configurations automatically
   - Streaming LLM responses with OpenRouter integration
   - Conversation history management

3. **Custom Setup** (`/task-setup`) - Complete analysis workflow for researchers
   - Step 1: Task Configuration (name, type, description)
   - Step 2: Data Selection (upload/import WSI files)
   - Step 3: Preprocessing (patch extraction + feature extraction)
   - Step 4: Model Configuration (aggregator + training parameters)
   - Step 5: Training & Execution (real-time progress monitoring)
   - Step 6: Results (summary and next steps)
   - Full control over preprocessing and model parameters

4. **Task Browser** (`/task-list`) - Browse and manage training tasks
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

6. **Upload Slides** (`/upload`) - Upload WSI files with metadata
   - Single/multiple file upload with real-time progress tracking
   - Metadata input during upload (label, case_id, age, gender, source)
   - Batch upload support

7. **Slide Browser** (`/wsi-list`) - Browse and manage WSI files with analysis results
   - View all uploaded slides with metadata
   - Import via CSV template
   - Edit/delete individual or multiple slides
   - View all metadata fields in table
   - Analysis results and confidence scores

8. **Slide Viewer** (`/wsi/:wsi_id`) - Full-screen WSI viewer with metadata and AI analysis
   - Deep zoom with OpenSeadragon
   - Metadata panel with patient information
   - AI analysis results display
   - Full-screen mode

9. **Results Viewer** (`/results`) - View and analyze AI inference results
   - Browse all analysis results
   - Filter and search results
   - Export results to various formats

10. **Report Generator** (`/reports`) - Generate analysis reports
    - Create comprehensive analysis reports
    - Customizable report templates
    - Export to PDF/Word formats

11. **Settings** (`/settings`) - Comprehensive system configuration with tabbed interface
    - **General Tab**: AI Configuration (OpenRouter API key, base URL, model selection)
    - **Processing Tab**: Patch & Feature Extraction settings (tile size, stride, tissue segmentation)
    - **Tasks Tab**: Slide Task Configuration (timeout, retry settings)
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
cd pathlab/services/frontend
npm install
cd ../../..
```

### 2. Start All Services

**One-click startup**
```bash
bash pathlab/start_all.sh
```

**Or start manually**
```bash
# Terminal 1: Gateway
python -m uvicorn pathlab.services.gateway.main:app --port 6100 --reload

# Terminal 2: Preprocessing Service
python -m uvicorn pathlab.services.backend.preprocessing.main:app --port 6101 --reload

# Terminal 3: AI Service
python -m uvicorn pathlab.services.backend.ai.main:app --port 6102 --reload

# Terminal 4: Frontend
cd pathlab/services/frontend
npm run dev
```

### 3. Access

- **Frontend**: http://127.0.0.1:5173
- **Gateway API**: http://127.0.0.1:6100/docs
- **Preprocessing API**: http://127.0.0.1:6101/docs
- **AI API**: http://127.0.0.1:6102/docs

### 4. Stop All Services

```bash
bash pathlab/stop_all.sh
```

## Custom Inference Implementation

The AI service provides modular components for custom inference:

**Model Components:**
- **Extractors** (`pathlab/services/backend/ai/extractors/`): Feature extraction models
- **Aggregators** (`pathlab/services/backend/ai/aggregators/`): MIL aggregation models
- **Classifiers** (`pathlab/services/backend/ai/classifiers/`): Classification models
- **Tasks** (`pathlab/services/backend/ai/tasks/`): Task implementations

See `pathlab/services/backend/ai/README.md` for detailed documentation.

## Current Features (v0.3)

### ✅ Core Platform
- **Microservices Architecture**: Gateway, Preprocessing Service, AI Service, Frontend
- **WSI Viewer**: Full-screen OpenSeadragon viewer with metadata panel
- **WSI Upload**: Single/batch file upload and path-based registration
- **Format Support**: 16+ WSI formats via ASlide
- **Inference API**: Modular AI components with extractors, aggregators, and classifiers
- **Metadata Management**: PostgreSQL database with repository pattern
- **Database Schema**: Support for patient metadata (age, gender, source/organ)
- **Storage Management**: Automated file lifecycle management and cleanup

### ✅ User Interface (Medical Professional-Oriented)
- **Dashboard**: Overview with statistics and quick actions
- **New Task (AI Chat)**: Natural language task setup with streaming LLM chat
- **Custom Setup**: Integrated workflow with step-by-step guidance
  - Task description
  - Model selection (ResNet50, ViT-Base, CTransPath, UNI)
  - Data selection with metadata display
  - Training simulation
- **Task Browser**: View and manage training tasks with real-time progress
- **Upload Slides**: Upload WSI files with metadata
- **Slide Browser**: Table view with analysis results and confidence scores
- **Results Viewer**: Browse and analyze AI inference results
- **Report Generator**: Generate comprehensive analysis reports
- **Settings**: System configuration with tabbed interface
- **Responsive Design**: Modern UI with Tailwind CSS
- **User-Friendly Terminology**: Medical terms instead of technical jargon

### ✅ WSI Upload & Management
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

If you're implementing custom AI models:

1. **Architecture**: The AI service uses modular components (extractors, aggregators, classifiers)
2. **Documentation**: See `pathlab/services/backend/ai/README.md` for detailed specifications
3. **Implementation**: Add your models to the appropriate directories:
   - Feature extractors: `pathlab/services/backend/ai/extractors/`
   - MIL aggregators: `pathlab/services/backend/ai/aggregators/`
   - Classifiers: `pathlab/services/backend/ai/classifiers/`
4. **Testing**: Restart the AI service to load new models

## Notes
- Nginx injects `x-internal-api-key` headers to internal services; frontend only uses JWT
- Database schema: PostgreSQL with Alembic migrations (see `pathlab/services/backend/database/README.md`)
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