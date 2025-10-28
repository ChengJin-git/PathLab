import json
import os
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict

# AI service: WSI classification with ABMIL inference
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))  # smartresearch/
UPLOADS_DIR = os.path.join(ROOT, "uploads")
METADATA_DIR = os.path.join(UPLOADS_DIR, "metadata")
AI_RESULTS_DIR = os.path.join(UPLOADS_DIR, "ai_results")
TASKS_DIR = os.path.join(UPLOADS_DIR, "tasks")

# Inference implementation directory (your colleague will implement here)
INFERENCE_DIR = os.path.join(ROOT, "models")
os.makedirs(INFERENCE_DIR, exist_ok=True)

os.makedirs(METADATA_DIR, exist_ok=True)
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

def _stub_classification(task_id: str, wsi_id: str, meta: Dict, params: Optional[Dict]) -> Dict:
    """Stub classification using metadata label"""
    label = meta.get("label")
    if not label:
        raise HTTPException(status_code=400, detail="label missing in metadata")

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
def analyze(req: AnalyzeRequest):
    if req.task != "wsi_classification":
        raise HTTPException(status_code=400, detail="Unsupported task")
    meta_path = os.path.join(METADATA_DIR, f"{req.wsi_id}.json")
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="wsi_id not found")

    # Load metadata
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)

    wsi_path = meta.get("wsi_path")
    if not wsi_path:
        raise HTTPException(status_code=400, detail="wsi_path missing in metadata")

    # Load classes from classes.json
    classes_path = os.path.join(METADATA_DIR, "classes.json")
    if not os.path.exists(classes_path):
        raise HTTPException(status_code=500, detail="classes.json not found")
    with open(classes_path, "r", encoding="utf-8") as f:
        classes = json.load(f)

    task_id = f"ai-{req.wsi_id}-{int(time.time())}"

    # Try to load custom inference implementation
    inference_func = _load_custom_inference()

    if inference_func and os.path.exists(wsi_path):
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
            result = _stub_classification(task_id, req.wsi_id, meta, req.params)
    else:
        # Stub classification: use metadata label
        result = _stub_classification(task_id, req.wsi_id, meta, req.params)

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

