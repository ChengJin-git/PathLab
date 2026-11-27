"""Stable retrieval failures; transport exception text stays in server logs."""

import errno
import httpx
from backend.common.net_guard import EgressDeniedError


class ArticleDownloadError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def http_failure(status: int) -> str:
    if status in {401, 403, 451}:
        return "access_denied"
    if status in {404, 410}:
        return "not_found"
    if status == 429:
        return "rate_limited"
    return "source_unavailable"


def failure_code(error: Exception) -> str:
    if isinstance(error, ArticleDownloadError):
        return error.code
    if isinstance(error, EgressDeniedError):
        return "blocked_url"
    if isinstance(error, (httpx.TimeoutException, TimeoutError)):
        return "request_timeout"
    if isinstance(error, httpx.HTTPStatusError):
        return http_failure(error.response.status_code)
    if isinstance(error, httpx.RequestError):
        return "network_unreachable"
    if isinstance(error, OSError):
        return "storage_full" if error.errno == errno.ENOSPC else "storage_failed"
    return "unexpected_error"
