# SmartResearch

> A minimal, on-premise friendly WSI (Whole Slide Image) research platform for digital pathology AI

## Overview

SmartResearch is a microservices-based platform designed for pathology research institutions to:
- **View** ultra-large pathology slides (WSI) in the browser with OpenSeadragon
- **Classify** WSI using custom deep learning models (MIL/ABMIL)
- **Train** and evaluate models with an intuitive web interface
- **Deploy** on-premise without cloud dependencies

**Key Features:**
- 🔬 **WSI Viewer**: Deep zoom support for gigapixel pathology images
- 🤖 **AI Inference**: Pluggable inference models with hot-reload
- 🎯 **Training Pipeline**: End-to-end workflow from data selection to model training
- 🏥 **On-Premise**: Designed for hospital/research lab deployment
- 🚀 **Lightweight**: Minimal dependencies, easy to set up

## Architecture

**Microservices:**
- **Gateway** (FastAPI, port 6100): API orchestration, metadata management
- **WSI Service** (FastAPI + ASlide, port 6101): Tile serving, DZI generation
- **AI Service** (FastAPI, port 6102): Inference execution, model loading
- **Frontend** (React + Vite, port 5173): SPA with OpenSeadragon viewer

**Production:**
- URL prefix: `/SmartResearch/`
- Nginx reverse proxy for all services
- JWT authentication (frontend) + internal API keys (services)

## Directory layout
- services/frontend/       React+Vite app (OSD bundled; SPA under /SmartResearch/)
- services/gateway/        FastAPI gateway (auth, task orchestration, result aggregation)
- services/wsi/            FastAPI + ASlide (DZI/tiles/patches/thumbnail)
- services/ai/             FastAPI AI tasks (wsi_classification P0)
- models/                  Custom inference implementation
- infra/nginx/             Nginx reverse proxy (production)
- docs/                    API contracts and documentation

## API prefixes (behind Nginx)
- /SmartResearch/api/wsi/  → services/wsi (6101)
- /SmartResearch/api/ai/   → services/ai (6102)
- /SmartResearch/api/      → services/gateway (6100)

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

### 2. Prepare Data

Create a `source.csv` file with your WSI data:

```bash
cp docs/source.csv.example source.csv
# Edit source.csv with your actual WSI file paths
```

For detailed data setup instructions, see [DATA_SETUP.md](../DATA_SETUP.md)

### 3. Start All Services

**One-click startup**
```bash
bash smartresearch/start_all.sh
```

**Or start manually**
```bash
# Terminal 1: Gateway
python -m uvicorn smartresearch.services.gateway.main:app --port 6100 --reload

# Terminal 2: WSI Service
python -m uvicorn smartresearch.services.wsi.main:app --port 6101 --reload

# Terminal 3: AI Service
python -m uvicorn smartresearch.services.ai.main:app --port 6102 --reload

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

## Roadmap

### Phase 1: Core Infrastructure 
- [x] Microservices architecture (Gateway, WSI, AI, Frontend)
- [x] WSI viewer with OpenSeadragon
- [x] Basic inference API with fallback mechanism
- [x] Auto-loading custom inference models
- [x] Metadata management from CSV

### Phase 2: Inference Enhancement (Current)
- [x] Model selection UI (placeholder checkboxes)
- [ ] Real model integration (ResNet50, ViT, CTransPath, UNI)
- [ ] Attention map visualization
- [ ] Batch inference support
- [ ] Performance optimization (caching, async)

### Phase 3: Training Pipeline
- [ ] Training data selection UI
- [ ] Model training backend (PyTorch/TensorFlow)
- [ ] Training progress monitoring
- [ ] Hyperparameter tuning interface
- [ ] Model versioning and management

### Phase 4: Advanced Features
- [ ] Multi-task learning support
- [ ] Active learning workflow
- [ ] Annotation tools integration
- [ ] Experiment tracking (MLflow/Weights & Biases)
- [ ] Model comparison and A/B testing

### Phase 5: Production Readiness
- [ ] User authentication and authorization
- [ ] Audit logging
- [ ] Performance monitoring (Prometheus/Grafana)
- [ ] Automated testing (unit, integration, E2E)
- [ ] Docker/Kubernetes deployment
- [ ] Documentation and tutorials

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
- CSV label schema: `dir, case_id, slide_id, label, ext` (see `docs/labels_schema.md`)
- API contracts: see `docs/api_contracts.md`
- Supported WSI formats: `.svs`, `.tif`, `.tiff`, `.ndpi`, `.kfb`, `.mrxs` (via ASlide)

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