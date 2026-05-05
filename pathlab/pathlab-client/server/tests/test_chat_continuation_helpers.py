# pyright: reportImplicitRelativeImport=false

from gateway.routes.chat import (
    MAX_DATASETS_IN_CHAT_CONTEXT,
    _build_auto_continue_messages,
    _build_context_retry_messages,
    _filter_datasets_by_query,
    _format_chat_dataset_list,
    _log_chat_timing,
    _prioritize_dataset_lines_for_query,
    _resolve_prompt_language_and_user_text,
)


def test_log_chat_timing_includes_stage_elapsed_and_metadata():
    messages: list[str] = []

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
            "  - ... 2 more dataset(s) omitted from prompt; do NOT assume omitted datasets are unavailable. Ask the user to narrow by dataset name, organ/source, task type, or access type if needed.",
        ]
    )


def test_build_auto_continue_messages_appends_partial_response_and_prompt():
    messages: list[dict[str, object]] = [{"role": "user", "content": "请总结这篇论文"}]

    result = _build_auto_continue_messages(messages, "第一部分回答", "zh_CN")

    assert result[:-2] == messages
    assert result[-2] == {"role": "assistant", "content": "第一部分回答"}
    assert result[-1]["role"] == "user"
    final_content = result[-1]["content"]
    assert isinstance(final_content, str)
    assert "不要重复已经写过的内容" in final_content


def test_build_context_retry_messages_keeps_latest_pdf_and_compacts_long_text():
    long_pdf = "[PDF_CONTEXT]\n" + ("A" * 40000) + "\n[/PDF_CONTEXT]"
    long_prompt = "请完整总结这篇论文\n\n" + ("B" * 30000)
    messages: list[dict[str, object]] = [
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


def test_filter_datasets_by_query_matches_name_substring():
    lines = [
        "  - SegPC (dataset_id=segpc-2021): 100 files",
        "  - Camelyon16 (dataset_id=camelyon16): 400 files",
        "  - TCGA-BRCA (dataset_id=tcga-brca): 1000 files",
    ]

    result = _filter_datasets_by_query(lines, "segpc")

    assert result == ["  - SegPC (dataset_id=segpc-2021): 100 files"]


def test_filter_datasets_by_query_matches_dataset_id_substring():
    lines = [
        "  - SegPC (dataset_id=segpc-2021): 100 files",
        "  - Camelyon16 (dataset_id=camelyon16): 400 files",
    ]

    result = _filter_datasets_by_query(lines, "2021")

    assert result == ["  - SegPC (dataset_id=segpc-2021): 100 files"]


def test_filter_datasets_by_query_is_case_insensitive():
    lines = [
        "  - SegPC (dataset_id=segpc-2021): 100 files",
        "  - Camelyon16 (dataset_id=camelyon16): 400 files",
    ]

    result = _filter_datasets_by_query(lines, "SEGPC")

    assert result == ["  - SegPC (dataset_id=segpc-2021): 100 files"]


def test_filter_datasets_by_query_matches_name_inside_natural_language_question():
    lines = [
        "  - SegPC (dataset_id=segpc-2021): 100 files",
        "  - Camelyon16 (dataset_id=camelyon16): 400 files",
    ]

    result = _filter_datasets_by_query(lines, "我有 SegPC 数据集吗")

    assert result == ["  - SegPC (dataset_id=segpc-2021): 100 files"]


def test_filter_datasets_by_query_returns_empty_when_no_match():
    lines = [
        "  - SegPC (dataset_id=segpc-2021): 100 files",
        "  - Camelyon16 (dataset_id=camelyon16): 400 files",
    ]

    result = _filter_datasets_by_query(lines, "nonexistent")

    assert result == []


def test_filter_datasets_by_query_ignores_lines_without_dataset_id():
    lines = [
        "  - SegPC (dataset_id=segpc-2021): 100 files",
        "  - Some malformed line without id",
    ]

    result = _filter_datasets_by_query(lines, "segpc")

    assert result == ["  - SegPC (dataset_id=segpc-2021): 100 files"]


def test_filter_datasets_by_query_ignores_unparseable_display_names():
    lines = ["dataset_id=camelyon16): malformed cached line"]

    result = _filter_datasets_by_query(lines, "segpc")

    assert result == []


def test_format_chat_dataset_list_prioritizes_query_matches():
    dataset_lines = [f"  - Dataset {i} (dataset_id=d{i}): files" for i in range(1, 35)]
    query = "d30"

    prioritized = _prioritize_dataset_lines_for_query(dataset_lines, query)
    rendered = _format_chat_dataset_list(prioritized, limit=MAX_DATASETS_IN_CHAT_CONTEXT)

    assert "Dataset 30" in rendered
    assert "Dataset 1" in rendered


def test_prioritize_dataset_lines_keeps_original_order_without_match():
    dataset_lines = [
        "  - Dataset 1 (dataset_id=d1): files",
        "  - Dataset 2 (dataset_id=d2): files",
    ]

    prioritized = _prioritize_dataset_lines_for_query(dataset_lines, "missing")

    assert prioritized == dataset_lines


def test_format_chat_dataset_list_marks_truncated_dataset_context():
    datasets_list = _format_chat_dataset_list(
        [f"  - Dataset {i}" for i in range(1, 5)], limit=2
    )

    assert "omitted from prompt" in datasets_list


def test_second_context_retry_is_more_aggressive_than_first():
    long_text = "用户问题\n\n" + ("C" * 30000)
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": long_text},
    ]

    first_retry = _build_context_retry_messages(messages, 0)
    second_retry = _build_context_retry_messages(messages, 1)

    assert first_retry is not None
    assert second_retry is not None
    first_content = first_retry[-1]["content"]
    second_content = second_retry[-1]["content"]
    assert isinstance(first_content, str)
    assert isinstance(second_content, str)
    assert len(second_content) < len(first_content)
