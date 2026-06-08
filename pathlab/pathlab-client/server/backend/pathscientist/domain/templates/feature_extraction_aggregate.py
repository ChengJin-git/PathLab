from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def atomic_json_dump(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--data-output-dir", required=True)
    parser.add_argument("--extractor", required=True)
    parser.add_argument("--world-size", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    data_output = Path(args.data_output_dir)
    meta_dir = output_dir / "worker_meta"
    features_dir = data_output / "pt_files" / args.extractor
    coords_dir = data_output / "patches"

    workers = []
    for rank in range(args.world_size):
        path = meta_dir / f"worker_{rank}.json"
        if not path.exists():
            raise SystemExit(f"missing worker metadata: {path}")
        workers.append(json.loads(path.read_text(encoding="utf-8")))

    results = {}
    total_wsi = 0
    successful = 0
    patches = 0
    total_time = 0.0
    for worker in workers:
        total_wsi += int(worker.get("total_assigned", 0))
        successful += int(worker.get("successful", 0))
        patches += int(worker.get("patches_extracted", 0))
        total_time = max(total_time, float(worker.get("duration", 0.0)))
        results.update(worker.get("results") or {})

    min_success_rate = float(os.getenv("PATHSCIENTIST_FEATURE_MIN_SUCCESS_RATE", "0.95"))
    success_rate = (successful / total_wsi) if total_wsi > 0 else 0.0
    if successful <= 0:
        status = "failed"
    elif success_rate < min_success_rate:
        status = "partial_failed"
    else:
        status = "completed"

    meta = {
        "status": status,
        "extractor": args.extractor,
        "total_wsi": total_wsi,
        "successful": successful,
        "success_rate": round(success_rate, 4),
        "min_success_rate": min_success_rate,
        "total_time": round(total_time, 1),
        "patches_extracted": patches,
        "features_dir": str(features_dir),
        "coords_dir": str(coords_dir),
        "worker_count": args.world_size,
        "workers": workers,
        "results": results,
    }
    metrics = {
        "patches_extracted": float(patches),
        "successful_wsi": float(successful),
        "total_wsi": float(total_wsi),
        "success_rate": float(round(success_rate, 4)),
        "status": meta["status"],
    }

    atomic_json_dump(meta, output_dir / "extraction_meta.json")
    atomic_json_dump(meta, data_output / "extraction_meta.json")
    atomic_json_dump(metrics, output_dir / "metrics.json")

    if successful <= 0:
        raise SystemExit("no successful WSI feature files")
    if status != "completed":
        raise SystemExit(
            f"feature extraction success rate {success_rate:.4f} below "
            f"required {min_success_rate:.4f} ({successful}/{total_wsi})"
        )


if __name__ == "__main__":
    main()
