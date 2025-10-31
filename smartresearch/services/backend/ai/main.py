import json
import os
import time
import sys
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, Dict
from sqlalchemy.ext.asyncio import AsyncSession

# AI service: WSI classification with ABMIL inference
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))  # smartresearch/
sys.path.insert(0, ROOT)

from smartresearch.services.backend.database import get_db
from smartresearch.services.backend.database.repositories import WSIRepository

UPLOADS_DIR = os.path.join(ROOT, "uploads")
AI_RESULTS_DIR = os.path.join(UPLOADS_DIR, "ai_results")
TASKS_DIR = os.path.join(UPLOADS_DIR, "tasks")

# Inference implementation directory (now in backend/ai/models)
INFERENCE_DIR = os.path.join(os.path.dirname(__file__), "models")
os.makedirs(INFERENCE_DIR, exist_ok=True)
os.makedirs(AI_RESULTS_DIR, exist_ok=True)
os.makedirs(TASKS_DIR, exist_ok=True)

app = FastAPI(title="SmartResearch AI Service")

# Enable CORS for dev and on-prem SPA
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
except Exception:
    pass

class AnalyzeRequest(BaseModel):
    task: str
    wsi_id: str
    params: Optional[Dict] = None

def _load_custom_inference():
    """
    Load custom inference implementation from models/run_inference.py
    Your colleague should implement: run_inference(wsi_path, params, classes) -> dict
    """
    impl_path = os.path.join(INFERENCE_DIR, "run_inference.py")
    if not os.path.exists(impl_path):
        return None

    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("custom_inference", impl_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "run_inference", None)
    except Exception as e:
        print(f"Failed to load custom inference: {e}")
        return None

def _stub_classification(task_id: str, wsi_id: str, label: str, params: Optional[Dict]) -> Dict:
    """Stub classification using WSI label"""
    if not label:
        raise HTTPException(status_code=400, detail="label missing for WSI")

    return {
        "task_id": task_id,
        "wsi_id": wsi_id,
        "pred": label,
        "probs": {label: 1.0},
        "params": params or {},
        "mode": "stub",
        "finished_at": int(time.time())
    }

@app.get("/health")
def health():
    return {"status": "ok", "service": "ai"}

@app.post("/api/ai/analyze")
async def analyze(req: AnalyzeRequest, db: AsyncSession = Depends(get_db)):
    """
    Analyze a WSI using AI classification.
    For stub mode: uses WSI label from database.
    For custom inference: loads model and classes from params or uses default.
    """
    if req.task != "wsi_classification":
        raise HTTPException(status_code=400, detail="Unsupported task")

    # Get WSI metadata from database
    wsi = await WSIRepository.get_by_id(db, req.wsi_id)
    if not wsi:
        raise HTTPException(status_code=404, detail=f"WSI not found: {req.wsi_id}")

    wsi_path = wsi.wsi_path
    if not wsi_path or not os.path.exists(wsi_path):
        raise HTTPException(status_code=400, detail=f"WSI file not found: {wsi_path}")

    # Get classes from params or use a default set
    # In production, classes should come from the trained model checkpoint
    classes = req.params.get("classes") if req.params else None
    if not classes:
        # Default classes - in production this should come from model metadata
        classes = ["HSIL", "LSIL", "Normal"]  # Example default

    task_id = f"ai-{req.wsi_id}-{int(time.time())}"

    # Try to load custom inference implementation
    inference_func = _load_custom_inference()

    if inference_func:
        # Use custom inference implementation
        try:
            params = req.params or {}
            params.setdefault("tile_size", 256)
            params.setdefault("stride", 256)
            params.setdefault("feature_model", "resnet50_imagenet")
            params.setdefault("aggregator", "mean")
            params.setdefault("batch_size", 64)
            params.setdefault("device", "cuda")

            inference_result = inference_func(wsi_path=wsi_path, params=params, classes=classes)

            result = {
                "task_id": task_id,
                "wsi_id": req.wsi_id,
                "pred": inference_result["pred"],
                "probs": inference_result["probs"],
                "params": params,
                "num_tiles": inference_result.get("num_tiles", 0),
                "finished_at": int(time.time())
            }
        except Exception as e:
            # Fallback to stub if inference fails
            print(f"Custom inference failed: {e}, falling back to stub")
            result = _stub_classification(task_id, req.wsi_id, wsi.label, req.params)
    else:
        # Stub classification: use WSI label from database
        result = _stub_classification(task_id, req.wsi_id, wsi.label, req.params)

    # Write result file for gateway consumption
    with open(os.path.join(AI_RESULTS_DIR, f"{req.wsi_id}.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

    # Write task record
    with open(os.path.join(TASKS_DIR, f"{task_id}.json"), "w", encoding="utf-8") as f:
        json.dump({"task_id": task_id, "status": "completed", "wsi_id": req.wsi_id}, f)

    return {"task_id": task_id, "status": "completed"}

@app.get("/api/ai/tasks/{task_id}")
def task_status(task_id: str):
    path = os.path.join(TASKS_DIR, f"{task_id}.json")
    if not os.path.exists(path):
        return {"task_id": task_id, "status": "not_found"}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data

@app.get("/api/ai/results/{wsi_id}")
def results(wsi_id: str):
    res_path = os.path.join(AI_RESULTS_DIR, f"{wsi_id}.json")
    if not os.path.exists(res_path):
        return {"wsi_id": wsi_id, "pred": None, "probs": None}
    with open(res_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    return result

