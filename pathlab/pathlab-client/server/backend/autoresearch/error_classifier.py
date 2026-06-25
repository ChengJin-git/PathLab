"""Error classification for experiment failures.

Classifies tracebacks into 12 types with targeted fix hints.
"""
from __future__ import annotations

from enum import Enum


class ErrorType(str, Enum):
    IMPORT = "ImportError"
    CUDA_OOM = "CUDA_OOM"
    SHAPE_MISMATCH = "ShapeMismatch"
    DEVICE_MISMATCH = "DeviceMismatch"
    FILE_NOT_FOUND = "FileNotFound"
    TYPE_ERROR = "TypeError"
    VALUE_ERROR = "ValueError"
    KEY_ERROR = "KeyError"
    SYNTAX_ERROR = "SyntaxError"
    ATTRIBUTE_ERROR = "AttributeError"
    PERMISSION_ERROR = "PermissionError"
    TIMEOUT = "Timeout"
    UNKNOWN = "Unknown"


# Fix hints per error type — injected into LLM observation
ERROR_FIX_HINTS: dict[ErrorType, str] = {
    ErrorType.IMPORT: (
        "Check package name spelling. Use only packages available in the environment. "
        "Try alternative: e.g. sklearn instead of scikit-learn, cv2 instead of opencv."
    ),
    ErrorType.CUDA_OOM: (
        "Reduce batch_size, use gradient checkpointing (torch.utils.checkpoint), "
        "reduce model size, use mixed precision (torch.cuda.amp), or free cache with torch.cuda.empty_cache()."
    ),
    ErrorType.SHAPE_MISMATCH: (
        "Print tensor shapes before the failing line. Check dimension alignment. "
        "Common: feature_dim mismatch between extractor and model, or wrong squeeze/unsqueeze."
    ),
    ErrorType.DEVICE_MISMATCH: (
        "Ensure all tensors and model are on the same device. "
        "Use .to(device) consistently. Check that input data is moved to GPU before model forward."
    ),
    ErrorType.FILE_NOT_FOUND: (
        "Check file paths are correct. Use os.path.exists() to verify before opening. "
        "Check data mount paths match actual locations."
    ),
    ErrorType.TYPE_ERROR: (
        "Check function signatures and argument types. Common: passing wrong type to torch operations, "
        "or None where a tensor is expected."
    ),
    ErrorType.VALUE_ERROR: (
        "Check value ranges and constraints. Common: empty dataset, wrong number of classes, "
        "invalid hyperparameter values."
    ),
    ErrorType.KEY_ERROR: (
        "Check dictionary keys exist before accessing. Common: wrong key in metrics dict, "
        "missing key in config, or wrong split name."
    ),
    ErrorType.SYNTAX_ERROR: (
        "Fix Python syntax. Common: missing colon, unmatched brackets, "
        "wrong indentation, f-string errors."
    ),
    ErrorType.ATTRIBUTE_ERROR: (
        "Check object has the attribute/method. Common: wrong method name on tensor/module, "
        "or accessing attribute on None."
    ),
    ErrorType.PERMISSION_ERROR: (
        "Check file/directory permissions. Output directory may be read-only. "
        "Use OUTPUT_DIR environment variable for writable output."
    ),
    ErrorType.TIMEOUT: (
        "Script exceeded time limit. Reduce epochs, dataset size, or model complexity. "
        "Check for infinite loops."
    ),
    ErrorType.UNKNOWN: (
        "Read the full traceback carefully. Look at the last few lines for the actual error."
    ),
}


def classify_error(error_text: str) -> ErrorType:
    """Classify error type from traceback text."""
    e = error_text.lower()
    if "importerror" in e or "modulenotfounderror" in e:
        return ErrorType.IMPORT
    if "cuda" in e and ("out of memory" in e or "oom" in e):
        return ErrorType.CUDA_OOM
    if "runtimeerror" in e and "size" in e:
        return ErrorType.SHAPE_MISMATCH
    if "runtimeerror" in e and ("device" in e or "cpu" in e or "cuda" in e):
        return ErrorType.DEVICE_MISMATCH
    if "filenotfounderror" in e:
        return ErrorType.FILE_NOT_FOUND
    if "typeerror" in e:
        return ErrorType.TYPE_ERROR
    if "valueerror" in e:
        return ErrorType.VALUE_ERROR
    if "keyerror" in e:
        return ErrorType.KEY_ERROR
    if "syntaxerror" in e:
        return ErrorType.SYNTAX_ERROR
    if "attributeerror" in e:
        return ErrorType.ATTRIBUTE_ERROR
    if "permissionerror" in e:
        return ErrorType.PERMISSION_ERROR
    if "timeout" in e:
        return ErrorType.TIMEOUT
    return ErrorType.UNKNOWN


def extract_error_key_line(error: str) -> str:
    """Extract the most informative line from a traceback (for stuck detection)."""
    lines = error.strip().split("\n")
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith("Traceback") and not line.startswith("File"):
            return line
    return ""


def format_error_analysis(error_text: str) -> str:
    """Classify error and return formatted analysis with fix hints.

    Returns a string like:
        Error Type: ImportError
        Fix Hint: Check package name spelling...
        Key Error Line: ModuleNotFoundError: No module named 'nonexistent'
    """
    error_type = classify_error(error_text)
    hint = ERROR_FIX_HINTS.get(error_type, "")
    key_line = extract_error_key_line(error_text)

    return (
        f"\n--- Error Analysis ---\n"
        f"Error Type: {error_type.value}\n"
        f"Fix Hint: {hint}\n"
        f"Key Error Line: {key_line}\n"
        f"--- End Analysis ---"
    )
