import json
import os
import csv
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, List

# Gateway - minimal P0 implementation: reads/writes local uploads/* files
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # smartresearch/
UPLOADS_DIR = os.path.join(ROOT, "uploads")
METADATA_DIR = os.path.join(UPLOADS_DIR, "metadata")
AI_RESULTS_DIR = os.path.join(UPLOADS_DIR, "ai_results")

os.makedirs(METADATA_DIR, exist_ok=True)
os.makedirs(AI_RESULTS_DIR, exist_ok=True)

# Auto-generate metadata from source.csv if missing
def auto_generate_metadata_from_csv():
    """
    Fallback mechanism: If source.csv exists but metadata JSON files are missing,
    automatically generate them with placeholder values.
    """
    # Look for source.csv in multiple locations
    possible_csv_paths = [
        os.path.join(ROOT, "source.csv"),
        os.path.join(ROOT, "services", "frontend", "public", "source.csv"),
    ]

    source_csv = None
    for csv_path in possible_csv_paths:
        if os.path.exists(csv_path):
            source_csv = csv_path
            break

    if not source_csv:
        print("[Gateway] No source.csv found, skipping auto-generation")
        return

    print(f"[Gateway] Found source.csv at: {source_csv}")

    try:
        with open(source_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print("[Gateway] source.csv is empty")
            return

        generated_count = 0
        for row in rows:
            wsi_id = row.get('wsi_id', '').strip()
            if not wsi_id:
                continue

            metadata_path = os.path.join(METADATA_DIR, f"{wsi_id}.json")

            # Only generate if file doesn't exist
            if os.path.exists(metadata_path):
                continue

            # Generate metadata with available info from CSV
            metadata = {
                "wsi_id": wsi_id,
                "label": row.get('label', 'Unknown').strip(),
                "case_id": row.get('case_id', f'case_{wsi_id}').strip(),
                "wsi_path": row.get('wsi_path', '').strip(),
                # Placeholder values for unknown fields
                "mpp": 0.25,
                "vendor": "Unknown",
                "width": 0,
                "height": 0,
                "magnification": 40,
                "_auto_generated": True
            }

            # Write metadata file
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            print(f"[Gateway] Auto-generated metadata: {metadata_path}")
            generated_count += 1

        if generated_count > 0:
            print(f"[Gateway] ✓ Auto-generated {generated_count} metadata files from source.csv")
        else:
            print("[Gateway] All metadata files already exist")

    except Exception as e:
        print(f"[Gateway] Failed to auto-generate metadata: {e}")

# Run auto-generation on startup
auto_generate_metadata_from_csv()

app = FastAPI(title="SmartResearch Gateway")

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

class WSIClassifyRequest(BaseModel):
    wsi_id: str
    params: Optional[Dict] = None

@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway"}

@app.get("/wsi")
def list_wsi():
    items: List[Dict] = []
    for name in os.listdir(METADATA_DIR):
        if not name.endswith(".json"):
            continue
        wsi_id = name[:-5]
        try:
            with open(os.path.join(METADATA_DIR, name), "r", encoding="utf-8") as f:
                meta = json.load(f)
            items.append({
                "wsi_id": meta.get("wsi_id", wsi_id),
                "label": meta.get("label"),
                "wsi_path": meta.get("wsi_path"),
                "mpp": meta.get("mpp"),
                "vendor": meta.get("vendor"),
            })
        except Exception:
            # skip malformed
            continue
    return {"items": items}

@app.get("/wsi/{wsi_id}")
def get_wsi(wsi_id: str):
    path = os.path.join(METADATA_DIR, f"{wsi_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="wsi_id not found")
    with open(path, "r", encoding="utf-8") as f:
        meta = json.load(f)
    last = None
    res_path = os.path.join(AI_RESULTS_DIR, f"{wsi_id}.json")
    if os.path.exists(res_path):
        with open(res_path, "r", encoding="utf-8") as f:
            last = json.load(f)
    return {"wsi_id": wsi_id, "meta": meta, "last_run": last}

@app.post("/tasks/wsi-classification")
def create_wsi_classification(req: WSIClassifyRequest):
    # P0: Gateway does not orchestrate; client should call AI service directly.
    # We just validate existence and return a suggested task_id.
    path = os.path.join(METADATA_DIR, f"{req.wsi_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="wsi_id not found")
    dummy_task_id = f"task-{req.wsi_id}"
    return {"task_id": dummy_task_id, "status": "queued"}

@app.get("/tasks/{task_id}")
def get_task(task_id: str):
    # P0: No real queue; status unknown
    return {"task_id": task_id, "status": "unknown"}

@app.get("/results/{wsi_id}")
def get_results(wsi_id: str):
    res_path = os.path.join(AI_RESULTS_DIR, f"{wsi_id}.json")
    if not os.path.exists(res_path):
        return {"wsi_id": wsi_id, "result": None}
    with open(res_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    return result

