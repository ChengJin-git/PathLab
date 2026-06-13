from gateway.routes.chat import (
    _build_auto_continue_messages,
    _build_context_retry_messages,
)


def test_build_auto_continue_messages_appends_partial_response_and_prompt():
    messages = [{"role": "user", "content": "请总结这篇论文"}]

    result = _build_auto_continue_messages(messages, "第一部分回答", "zh_CN")

    assert result[:-2] == messages
    assert result[-2] == {"role": "assistant", "content": "第一部分回答"}
    assert result[-1]["role"] == "user"
    assert "不要重复已经写过的内容" in result[-1]["content"]


def test_build_context_retry_messages_keeps_latest_pdf_and_compacts_long_text():
    long_pdf = "[PDF_CONTEXT]\n" + ("A" * 40000) + "\n[/PDF_CONTEXT]"
    long_prompt = "请完整总结这篇论文\n\n" + ("B" * 30000)
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": long_pdf},
        {"role": "assistant", "content": "recent answer"},
        {"role": "user", "content": long_prompt},
    ]

    compacted = _build_context_retry_messages(messages, 0)

    assert compacted is not None
    assert compacted[0]["content"] == "system prompt"
    assert any(
        isinstance(msg["content"], str) and msg["content"].startswith("[PDF_CONTEXT]")
        for msg in compacted
    )
    compacted_pdf = next(
        msg["content"]
        for msg in compacted
        if isinstance(msg["content"], str) and msg["content"].startswith("[PDF_CONTEXT]")
    )
    assert len(compacted_pdf) < len(long_pdf)
    assert any(
        isinstance(msg["content"], str) and "请完整总结这篇论文" in msg["content"]
        for msg in compacted
    )


def test_second_context_retry_is_more_aggressive_than_first():
    long_text = "用户问题\n\n" + ("C" * 30000)
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": long_text},
    ]

    first_retry = _build_context_retry_messages(messages, 0)
    second_retry = _build_context_retry_messages(messages, 1)

    assert first_retry is not None
    assert second_retry is not None
    assert len(second_retry[-1]["content"]) < len(first_retry[-1]["content"])