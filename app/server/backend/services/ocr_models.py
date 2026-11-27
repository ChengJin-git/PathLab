"""Pinned CPU OCR artifacts; provision explicitly, never download during a read."""

from pathlib import Path
import hashlib
import os

RELEASE = "3.10.0"
MODEL_FILES = {
    "PP-OCRv6_det_small.onnx": (
        "det",
        "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
    ),
    "PP-OCRv6_rec_small.onnx": (
        "rec",
        "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    ),
}


def model_directory() -> Path:
    return Path(
        os.environ.get("PATHLAB_OCR_MODEL_DIR")
        or Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
        / "PathLab/ocr-models"
    )


def verify_models(root: Path | None = None) -> dict[str, Path]:
    root = root or model_directory()
    files = {}
    for name, (_, digest) in MODEL_FILES.items():
        path = root / name
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError(
                "Missing or invalid OCR model "
                + name
                + "; run deploy/prepare-ocr.py with the backend Python"
            )
        files[name] = path
    return files


def create_engine():
    from rapidocr import RapidOCR, OCRVersion, ModelType, EngineType
    import cv2

    files = verify_models()
    cv2.setNumThreads(2)
    engine = RapidOCR(
        params={
            "Global.log_level": "warning",
            "Global.use_cls": False,
            "Global.max_side_len": 2400,
            "EngineConfig.onnxruntime.intra_op_num_threads": 2,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "EngineConfig.onnxruntime.use_cuda": False,
            "EngineConfig.onnxruntime.use_dml": False,
            "EngineConfig.onnxruntime.use_cann": False,
            "EngineConfig.onnxruntime.use_coreml": False,
            "Det.engine_type": EngineType.ONNXRUNTIME,
            "Rec.engine_type": EngineType.ONNXRUNTIME,
            "Det.ocr_version": OCRVersion.PPOCRV6,
            "Rec.ocr_version": OCRVersion.PPOCRV6,
            "Det.model_type": ModelType.SMALL,
            "Rec.model_type": ModelType.SMALL,
            "Det.limit_side_len": 960,
            "Det.limit_type": "max",
            "Det.model_path": str(files["PP-OCRv6_det_small.onnx"]),
            "Rec.model_path": str(files["PP-OCRv6_rec_small.onnx"]),
        }
    )
    detector = engine._load_det_model()
    from rapidocr.ch_ppocr_det.utils import DetPreProcess

    class CpuPreprocess(DetPreProcess):
        def __call__(self, image):
            resized = self.resize(image)
            return detector_tensor(resized) if resized is not None else None

    # The pinned model uses mean/std=.5. Avoid float64 NumPy broadcast temporaries
    # on large scans; OpenCV directly produces the equivalent float32 NCHW tensor.
    detector.get_preprocess = lambda: CpuPreprocess(
        detector.limit_side_len, detector.limit_type
    )
    return engine


def detector_tensor(image):
    import cv2
    import numpy as np

    output = np.empty((1, 3, *image.shape[:2]), dtype=np.float32)
    for index, channel in enumerate(cv2.split(image)):
        cv2.multiply(channel, 1 / 127.5, dst=output[0, index], dtype=cv2.CV_32F)
        cv2.subtract(output[0, index], 1, dst=output[0, index])
    return output
