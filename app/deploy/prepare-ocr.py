#!/usr/bin/env python3
"""Provision hash-pinned PP-OCRv6 CPU models outside request handling."""

import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from backend.services.ocr_models import (
    MODEL_FILES,
    RELEASE,
    model_directory,
    verify_models,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=model_directory())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if not args.check:
        args.directory.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            for name, (task, digest) in MODEL_FILES.items():
                path = args.directory / name
                if (
                    path.is_file()
                    and hashlib.sha256(path.read_bytes()).hexdigest() == digest
                ):
                    continue
                url = f"https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v{RELEASE}/onnx/PP-OCRv6/{task}/{name}"
                fd, temporary = tempfile.mkstemp(dir=args.directory, prefix=".ocr-")
                try:
                    hasher = hashlib.sha256()
                    with (
                        os.fdopen(fd, "wb") as output,
                        client.stream("GET", url) as response,
                    ):
                        response.raise_for_status()
                        for chunk in response.iter_bytes():
                            output.write(chunk)
                            hasher.update(chunk)
                    if hasher.hexdigest() != digest:
                        raise ValueError("OCR model checksum mismatch: " + name)
                    os.replace(temporary, path)
                finally:
                    Path(temporary).unlink(missing_ok=True)
    files = verify_models(args.directory)
    print("Verified PP-OCRv6 CPU models: " + ", ".join(files))


if __name__ == "__main__":
    main()
