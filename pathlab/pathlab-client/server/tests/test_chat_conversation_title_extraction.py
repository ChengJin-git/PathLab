from gateway.routes.chat_conversation import (
    _build_title_generation_payload,
    _clean_message_for_title,
)


def test_clean_message_for_title_strips_special_blocks():
    content = '查看数据\n[OPTIONS]{"foo":1}[/OPTIONS]\n继续分析'
    assert _clean_message_for_title(content) == "查看数据\n\n继续分析"


def test_build_title_generation_payload_disables_thinking_for_local_vllm():
    payload = _build_title_generation_payload(
        model="Qwen/Qwen3.5-397B-A17B-FP8",
        title_prompt="Summarize this message",
        use_local_vllm=True,
    )

    assert payload["model"] == "Qwen/Qwen3.5-397B-A17B-FP8"
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_build_title_generation_payload_keeps_openrouter_payload_clean():
    payload = _build_title_generation_payload(
        model="google/gemini-2.0-flash-001",
        title_prompt="Summarize this message",
        use_local_vllm=False,
    )

    assert "chat_template_kwargs" not in payload