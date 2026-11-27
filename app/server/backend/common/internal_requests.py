"""Short-lived, path-bound authentication for Gateway-to-service requests."""

import hashlib
import hmac
import os
import time
from fastapi import HTTPException, Request


def signing_key():
    secret = os.environ.get("JWT_SECRET") or os.environ.get("PATHLAB_INTERNAL_SECRET")
    if not secret:
        raise RuntimeError(
            "Start services through server/main.py or configure PATHLAB_INTERNAL_SECRET"
        )
    return secret.encode()


def internal_headers(method, path, params=None):
    from httpx import QueryParams

    if params:
        path += "?" + str(QueryParams(params))
    timestamp = str(int(time.time()))
    signature = hmac.new(
        signing_key(), f"{timestamp}\n{method.upper()}\n{path}".encode(), hashlib.sha256
    ).hexdigest()
    return {"X-PathLab-Time": timestamp, "X-PathLab-Signature": signature}


async def require_internal_request(request: Request):
    timestamp = request.headers.get("X-PathLab-Time", "")
    signature = request.headers.get("X-PathLab-Signature", "")
    try:
        if abs(time.time() - int(timestamp)) > 60:
            raise ValueError()
        target = request.url.path + (
            "?" + request.url.query if request.url.query else ""
        )
        expected = hmac.new(
            signing_key(),
            f"{timestamp}\n{request.method}\n{target}".encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
    except (ValueError, RuntimeError):
        raise HTTPException(403, "Use the authenticated Gateway result API") from None
