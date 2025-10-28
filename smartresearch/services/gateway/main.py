import json
import os
import csv
import shutil
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional, Dict, List
import httpx
from Aslide import Slide


# Gateway - minimal P0 implementation: reads/writes local uploads/* files
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # smartresearch/
UPLOADS_DIR = os.path.join(ROOT, "uploads")
METADATA_DIR = os.path.join(UPLOADS_DIR, "metadata")
AI_RESULTS_DIR = os.path.join(UPLOADS_DIR, "ai_results")

os.makedirs(METADATA_DIR, exist_ok=True)
os.makedirs(AI_RESULTS_DIR, exist_ok=True)

# AI Service URL (internal communication)
AI_SERVICE_URL = os.environ.get("AI_SERVICE_URL", "http://127.0.0.1:6102")


def extract_wsi_properties(wsi_path: str) -> dict:
    """
    Extract properties from a WSI file using ASlide.
    Returns a dict with mpp, vendor, width, height, magnification.
    Falls back to placeholder values if ASlide is unavailable or reading fails.
    """
    default_props = {
        "mpp": 0.25,
        "vendor": "Unknown",
        "width": 0,
        "height": 0,
        "magnification": 40,
    }

    if not wsi_path or not os.path.exists(wsi_path):
        print(f"[Gateway] WSI file not found: {wsi_path}")
        return default_props

    try:
        with Slide(wsi_path) as slide:
            # Extract properties
            props = {}

            # 1. MPP (microns per pixel)
            try:
                mpp_value = slide.mpp
                if isinstance(mpp_value, (int, float)):
                    props["mpp"] = float(mpp_value)
                elif isinstance(mpp_value, tuple) and len(mpp_value) >= 2:
                    # If mpp is a tuple (mpp_x, mpp_y), take average
                    props["mpp"] = (float(mpp_value[0]) + float(mpp_value[1])) / 2
                else:
                    props["mpp"] = default_props["mpp"]
            except:
                props["mpp"] = default_props["mpp"]

            # 2. Vendor
            try:
                vendor = slide.properties.get('openslide.vendor', 'Unknown')
                props["vendor"] = vendor if vendor else "Unknown"
            except:
                props["vendor"] = default_props["vendor"]

            # 3. Width and Height (from level 0 dimensions)
            try:
                width, height = slide.dimensions
                props["width"] = int(width)
                props["height"] = int(height)
            except:
                props["width"] = default_props["width"]
                props["height"] = default_props["height"]

            # 4. Magnification (objective power)
            try:
                mag = slide.properties.get('openslide.objective-power')
                if mag:
                    props["magnification"] = int(float(mag))
                else:
                    props["magnification"] = default_props["magnification"]
            except:
                props["magnification"] = default_props["magnification"]

            print(f"[Gateway] ✓ Extracted properties from {os.path.basename(wsi_path)}: "
                  f"mpp={props['mpp']:.3f}, vendor={props['vendor']}, "
                  f"size={props['width']}x{props['height']}, mag={props['magnification']}x")

            return props

    except Exception as e:
        print(f"[Gateway] Failed to read WSI properties from {wsi_path}: {e}")
        return default_props


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

            # Get WSI path from CSV
            wsi_path = row.get('wsi_path', '').strip()

            # Extract real properties from WSI file if available
            wsi_props = extract_wsi_properties(wsi_path)

            # Generate metadata with available info from CSV + extracted properties
            metadata = {
                "wsi_id": wsi_id,
                "label": row.get('label', 'Unknown').strip(),
                "case_id": row.get('case_id', f'case_{wsi_id}').strip(),
                "wsi_path": wsi_path,
                # Real properties extracted from WSI file
                "mpp": wsi_props["mpp"],
                "vendor": wsi_props["vendor"],
                "width": wsi_props["width"],
                "height": wsi_props["height"],
                "magnification": wsi_props["magnification"],
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

@app.get("/stats")
def get_stats():
    """
    Get system statistics including WSI count, task count, and results count.
    Returns:
        {
            "wsi_count": int,
            "task_count": int,
            "completed_count": int,
            "results_count": int,
            "labels": {label: count}
        }
    """
    # Count WSI files
    wsi_count = 0
    labels_count = {}
    for name in os.listdir(METADATA_DIR):
        if not name.endswith(".json") or name == "classes.json":
            continue
        wsi_count += 1
        try:
            with open(os.path.join(METADATA_DIR, name), "r", encoding="utf-8") as f:
                meta = json.load(f)
                label = meta.get("label", "Unknown")
                labels_count[label] = labels_count.get(label, 0) + 1
        except Exception:
            continue

    # Count tasks (from AI service tasks directory)
    tasks_dir = os.path.join(UPLOADS_DIR, "tasks")
    task_count = 0
    completed_count = 0
    if os.path.exists(tasks_dir):
        for name in os.listdir(tasks_dir):
            if name.endswith(".json"):
                task_count += 1
                try:
                    with open(os.path.join(tasks_dir, name), "r", encoding="utf-8") as f:
                        task = json.load(f)
                        if task.get("status") == "completed":
                            completed_count += 1
                except Exception:
                    continue

    # Count results
    results_count = 0
    if os.path.exists(AI_RESULTS_DIR):
        for name in os.listdir(AI_RESULTS_DIR):
            if name.endswith(".json"):
                results_count += 1

    return {
        "wsi_count": wsi_count,
        "task_count": task_count,
        "completed_count": completed_count,
        "results_count": results_count,
        "labels": labels_count
    }

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
async def create_wsi_classification(req: WSIClassifyRequest):
    """
    Create a WSI classification task by calling AI Service.
    Gateway orchestrates the request to AI Service.
    """
    # Validate metadata exists
    path = os.path.join(METADATA_DIR, f"{req.wsi_id}.json")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="wsi_id not found")

    # Call AI Service to create analysis task
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{AI_SERVICE_URL}/api/ai/analyze",
                json={
                    "task": "wsi_classification",
                    "wsi_id": req.wsi_id,
                    "params": req.params or {}
                }
            )
            response.raise_for_status()
            result = response.json()
            return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"AI Service error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"AI Service unavailable: {str(e)}")

@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    """
    Get task status from AI Service.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AI_SERVICE_URL}/api/ai/tasks/{task_id}")
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return {"task_id": task_id, "status": "not_found"}
        raise HTTPException(status_code=e.response.status_code, detail=f"AI Service error: {e.response.text}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"AI Service unavailable: {str(e)}")

@app.get("/results/{wsi_id}")
async def get_results(wsi_id: str):
    """
    Get AI analysis results for a WSI.
    First tries to get from AI Service, then falls back to local cache.
    """
    # Try to get latest result from AI Service
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{AI_SERVICE_URL}/api/ai/results/{wsi_id}")
            if response.status_code == 200:
                result = response.json()
                # If AI Service has a result, return it
                if result.get("pred") is not None:
                    return result
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        # If AI Service is unavailable, fall back to local cache
        print(f"[Gateway] AI Service unavailable, using local cache: {e}")

    # Fallback: read from local cache
    res_path = os.path.join(AI_RESULTS_DIR, f"{wsi_id}.json")
    if not os.path.exists(res_path):
        return {"wsi_id": wsi_id, "pred": None, "probs": None}

    with open(res_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    return result


class UploadByPathRequest(BaseModel):
    """Request model for uploading WSI by file path"""
    wsi_path: str
    label: Optional[str] = None
    case_id: Optional[str] = None
    wsi_id: Optional[str] = None


@app.post("/wsi/upload/file")
async def upload_wsi_file(
    file: UploadFile = File(...),
    label: Optional[str] = Form(None),
    case_id: Optional[str] = Form(None),
    wsi_id: Optional[str] = Form(None)
):
    """
    Upload a WSI file.
    The file will be saved to uploads directory and metadata will be created.

    Args:
        file: WSI file to upload
        label: Optional label for the WSI
        case_id: Optional case ID
        wsi_id: Optional custom WSI ID (auto-generated if not provided)

    Returns:
        {
            "wsi_id": str,
            "wsi_path": str,
            "label": str,
            "case_id": str,
            "message": str
        }
    """
    try:
        # Generate wsi_id if not provided
        if not wsi_id:
            # Use original filename without extension as base
            base_name = Path(file.filename).stem if file.filename else "wsi"
            wsi_id = f"{base_name}_{uuid.uuid4().hex[:8]}"

        # Get file extension
        file_ext = Path(file.filename).suffix if file.filename else ".tif"
        if not file_ext:
            file_ext = ".tif"

        # Save file to uploads directory
        file_path = os.path.join(UPLOADS_DIR, f"{wsi_id}{file_ext}")

        # Check if file already exists
        if os.path.exists(file_path):
            raise HTTPException(status_code=400, detail=f"WSI file already exists: {wsi_id}")

        # Save uploaded file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        print(f"[Gateway] Saved uploaded file: {file_path}")

        # Extract WSI properties
        wsi_props = extract_wsi_properties(file_path)

        # Generate case_id if not provided
        if not case_id:
            case_id = f"case_{wsi_id}"

        # Create metadata
        metadata = {
            "wsi_id": wsi_id,
            "label": label or "Unknown",
            "case_id": case_id,
            "wsi_path": file_path,
            "mpp": wsi_props["mpp"],
            "vendor": wsi_props["vendor"],
            "width": wsi_props["width"],
            "height": wsi_props["height"],
            "magnification": wsi_props["magnification"],
            "_uploaded": True
        }

        # Save metadata
        metadata_path = os.path.join(METADATA_DIR, f"{wsi_id}.json")
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"[Gateway] Created metadata: {metadata_path}")

        return {
            "wsi_id": wsi_id,
            "wsi_path": file_path,
            "label": metadata["label"],
            "case_id": case_id,
            "message": "WSI uploaded successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Gateway] Failed to upload WSI file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload WSI file: {str(e)}")


@app.post("/wsi/upload/path")
async def upload_wsi_by_path(req: UploadByPathRequest):
    """
    Register a WSI by file path (without copying the file).
    This is useful when WSI files are already on the server.

    Args:
        req: UploadByPathRequest containing wsi_path and optional metadata

    Returns:
        {
            "wsi_id": str,
            "wsi_path": str,
            "label": str,
            "case_id": str,
            "message": str
        }
    """
    try:
        # Validate file exists
        if not os.path.exists(req.wsi_path):
            raise HTTPException(status_code=404, detail=f"WSI file not found: {req.wsi_path}")

        # Generate wsi_id if not provided
        if not req.wsi_id:
            # Use filename without extension as base
            base_name = Path(req.wsi_path).stem
            wsi_id = f"{base_name}_{uuid.uuid4().hex[:8]}"
        else:
            wsi_id = req.wsi_id

        # Check if metadata already exists
        metadata_path = os.path.join(METADATA_DIR, f"{wsi_id}.json")
        if os.path.exists(metadata_path):
            raise HTTPException(status_code=400, detail=f"WSI metadata already exists: {wsi_id}")

        # Extract WSI properties
        wsi_props = extract_wsi_properties(req.wsi_path)

        # Generate case_id if not provided
        case_id = req.case_id or f"case_{wsi_id}"

        # Create metadata
        metadata = {
            "wsi_id": wsi_id,
            "label": req.label or "Unknown",
            "case_id": case_id,
            "wsi_path": req.wsi_path,
            "mpp": wsi_props["mpp"],
            "vendor": wsi_props["vendor"],
            "width": wsi_props["width"],
            "height": wsi_props["height"],
            "magnification": wsi_props["magnification"],
            "_registered_by_path": True
        }

        # Save metadata
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"[Gateway] Registered WSI by path: {metadata_path}")

        return {
            "wsi_id": wsi_id,
            "wsi_path": req.wsi_path,
            "label": metadata["label"],
            "case_id": case_id,
            "message": "WSI registered successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Gateway] Failed to register WSI by path: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to register WSI by path: {str(e)}")

