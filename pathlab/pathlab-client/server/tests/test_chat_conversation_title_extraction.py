from types import SimpleNamespace

from gateway.routes.chat_conversation import (
    _build_title_generation_payload,
    _clean_message_for_title,
    _get_title_source_message,
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


def test_get_title_source_message_uses_first_branch_user_message():
    conversation = SimpleNamespace(
        parent_conversation_id="conv_parent",
        branch_source_message_count=4,
        messages=[
            SimpleNamespace(id=1, role="user", content="原对话首问", variant_group_id=None, is_active_variant=True),
            SimpleNamespace(id=2, role="assistant", content="原对话回复", variant_group_id=None, is_active_variant=True),
            SimpleNamespace(id=3, role="user", content="原对话追问", variant_group_id=None, is_active_variant=True),
            SimpleNamespace(id=4, role="assistant", content="原对话追答", variant_group_id=None, is_active_variant=True),
            SimpleNamespace(id=5, role="user", content="分支里的第一问", variant_group_id=None, is_active_variant=True),
        ],
    )

    assert _get_title_source_message(conversation) == "分支里的第一问"


def test_get_title_source_message_ignores_inactive_variants_when_branching():
    conversation = SimpleNamespace(
        parent_conversation_id="conv_parent",
        branch_source_message_count=2,
        messages=[
            SimpleNamespace(id=1, role="user", content="原问题", variant_group_id=None, is_active_variant=True),
            SimpleNamespace(id=2, role="assistant", content="旧回复", variant_group_id="vg1", is_active_variant=False),
            SimpleNamespace(id=3, role="assistant", content="当前回复", variant_group_id="vg1", is_active_variant=True),
            SimpleNamespace(id=4, role="user", content="分支新问题", variant_group_id=None, is_active_variant=True),
        ],
    )

    assert _get_title_source_message(conversation) == "分支新问题"


def test_build_title_generation_payload_keeps_openrouter_payload_clean():
    payload = _build_title_generation_payload(
        model="google/gemini-2.0-flash-001",
        title_prompt="Summarize this message",
        use_local_vllm=False,
    )

    assert "chat_template_kwargs" not in payload