from gateway.routes.chat import (
    _build_auto_continue_messages,
    _build_context_retry_messages,
    _log_chat_timing,
    _resolve_prompt_language_and_user_text,
)


def test_log_chat_timing_includes_stage_elapsed_and_metadata():
    messages = []
    _log_chat_timing("abc123", "context_cache", 1.0, now=2.25, log_fn=messages.append, cache="hit", models=3)
    assert messages == ["[ChatTiming] req=abc123 stage=context_cache elapsed_ms=1250.0 cache=hit models=3"]


def test_resolve_prompt_language_keeps_user_text_with_explicit_ui_language():
    messages = [{"role": "user", "content": "我想训练一个模型，该用哪个特征提取器？"}]
    lang, text = _resolve_prompt_language_and_user_text(messages, "zh_CN")
    assert lang == "zh_CN"
    assert text == messages[0]["content"]


def test_build_auto_continue_messages_appends_partial_response_and_prompt():
    messages = [{"role": "user", "content": "请总结这篇论文"}]
    result = _build_auto_continue_messages(messages, "第一部分回答", "zh_CN")
    assert result[:-2] == messages
    assert result[-2] == {"role": "assistant", "content": "第一部分回答"}
    assert "不要重复已经写过的内容" in result[-1]["content"]


def test_build_context_retry_messages_keeps_latest_pdf_and_compacts_long_text():
    pdf = "[PDF_CONTEXT]\n" + "A" * 40000 + "\n[/PDF_CONTEXT]"
    messages = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": pdf},
        {"role": "assistant", "content": "recent answer"},
        {"role": "user", "content": "请完整总结这篇论文\n" + "B" * 30000},
    ]
    compacted = _build_context_retry_messages(messages, 0)
    assert compacted[0]["content"] == "system prompt"
    compact_pdf = next(m["content"] for m in compacted if m["content"].startswith("[PDF_CONTEXT]"))
    assert len(compact_pdf) < len(pdf)
    assert any("请完整总结这篇论文" in m["content"] for m in compacted)


def test_second_context_retry_is_more_aggressive_than_first():
    messages = [{"role": "system", "content": "system prompt"}, {"role": "user", "content": "C" * 30000}]
    first = _build_context_retry_messages(messages, 0)
    second = _build_context_retry_messages(messages, 1)
    assert len(second[-1]["content"]) < len(first[-1]["content"])
