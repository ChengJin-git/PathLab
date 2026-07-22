"""Structured paper-agent errors shared by CLI, API, and worker code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PaperAgentError(Exception):
    """Typed backend error with a stable code for API and manifest consumers."""

    code: str
    message: str
    status_code: int = 500
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        payload.update(self.details)
        return payload


def error_payload(error: BaseException) -> dict[str, Any]:
    """Return a JSON-safe error payload for logs, manifests, and APIs."""

    if isinstance(error, PaperAgentError):
        return {
            "code": error.code,
            "message": error.message,
            "type": type(error).__name__,
            "status_code": error.status_code,
            **error.details,
        }
    return {
        "code": "internal_error",
        "message": str(error),
        "type": type(error).__name__,
    }


def error_code(error: BaseException) -> str:
    if isinstance(error, PaperAgentError):
        return error.code
    if isinstance(error, FileNotFoundError):
        return "missing_artifact"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, ValueError):
        return "invalid_request"
    return "internal_error"
