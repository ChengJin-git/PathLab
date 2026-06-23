# pyright: reportImplicitRelativeImport=false

from gateway.routes.chat import (
    _build_auto_continue_messages,
    _build_context_retry_messages,
    _format_chat_dataset_list,
    _log_chat_timing,
    _resolve_prompt_language_and_user_text,
)


def test_log_chat_timing_includes_stage_elapsed_and_metadata():
    messages = []

    _log_chat_timing(
        "abc123",
        "context_cache",
        1.0,
        now=2.25,
        log_fn=lambda msg: messages.append(msg),
        cache="hit",
        models=3,
    )

    assert messages == [
        "[ChatTiming] req=abc123 stage=context_cache elapsed_ms=1250.0 cache=hit models=3"
    ]


def test_resolve_prompt_language_keeps_user_text_with_explicit_ui_language():
    messages = [{"role": "user", "content": "我想训练一个模型，该用哪个特征提取器？"}]

    detected_lang, user_text = _resolve_prompt_language_and_user_text(messages, "zh_CN")

    assert detected_lang == "zh_CN"
    assert user_text == "我想训练一个模型，该用哪个特征提取器？"


def test_format_chat_dataset_list_caps_rendered_datasets():
    dataset_lines = [f"  - Dataset {i}" for i in range(1, 5)]

    rendered = _format_chat_dataset_list(dataset_lines, limit=2)

    assert rendered == "\n".join(
        [
            "  - Dataset 1",
            "  - Dataset 2",
            "  - ... 2 more dataset(s) omitted from prompt; ask the user to narrow by dataset name, organ/source, task type, or access type if needed.",
        ]
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
