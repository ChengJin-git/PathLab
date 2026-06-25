import logging

from backend.common.log_redaction import QueryTokenRedactionFilter, redact_query_tokens


def test_redact_query_tokens_hides_token_values_only():
    message = 'GET /autoresearch/sessions/s1/events?token=secret.jwt&include=true HTTP/1.1'

    redacted = redact_query_tokens(message)

    assert "secret.jwt" not in redacted
    assert "token=[redacted]" in redacted
    assert "include=true" in redacted
    assert "/autoresearch/sessions/s1/events" in redacted


def test_query_token_redaction_preserves_numeric_log_args():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "GET", "/autoresearch/sessions?token=secret", "1.1", 200),
        exc_info=None,
    )

    QueryTokenRedactionFilter().filter(record)

    assert isinstance(record.args[-1], int)
    assert "secret" not in record.getMessage()
    assert "token=[redacted]" in record.getMessage()
