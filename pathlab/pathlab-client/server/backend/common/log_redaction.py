"""Small helpers for redacting credential-bearing query parameters in logs."""
from __future__ import annotations

import logging
import re
from typing import Any


_TOKEN_QUERY_RE = re.compile(r"(?i)([?&]token=)([^&#\s]+)")


def redact_query_tokens(value: Any) -> str:
    return _TOKEN_QUERY_RE.sub(r"\1[redacted]", str(value))


def _redact_log_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_query_tokens(value)
    return value


class QueryTokenRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_redact_log_value(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                key: _redact_log_value(value)
                for key, value in record.args.items()
            }
        record.msg = redact_query_tokens(record.msg)
        return True


def install_query_token_log_redaction(logger_name: str = "uvicorn.access") -> None:
    logger = logging.getLogger(logger_name)
    if any(isinstance(item, QueryTokenRedactionFilter) for item in logger.filters):
        return
    logger.addFilter(QueryTokenRedactionFilter())
