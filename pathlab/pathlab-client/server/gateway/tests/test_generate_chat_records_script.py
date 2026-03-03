import re

from gateway.tests.scripts.generate_chat_records import (
    compact_assistant_content,
    generate_debug_conversation_id,
)


def test_generate_debug_conversation_id_has_prefix():
    source_id = "conv_671c13c2e283415b"
    debug_id = generate_debug_conversation_id(source_id)
    assert debug_id.startswith("conv_debug_")
    assert source_id in debug_id


def test_compact_assistant_content_truncates_long_plain_text():
    content = "A" * 300
    compacted = compact_assistant_content(content, max_chars=80)
    assert len(compacted) < len(content)
    assert "[DEBUG_TRUNCATED original_len=300 max_chars=80]" in compacted
    assert compacted.startswith("A" * 80)


def test_compact_assistant_content_keeps_research_meta_block():
    content = (
        "\n\n[PATHLAB_RESEARCH_META]\n"
        '{"version":1,"researchId":"abc","kind":"plan","agent":"planner"}\n'
        "[/PATHLAB_RESEARCH_META]"
    )
    compacted = compact_assistant_content(content, max_chars=20)
    assert compacted == content


def test_compact_assistant_content_normalizes_empty_response():
    compacted = compact_assistant_content("\n\n", max_chars=20)
    assert compacted == "[EMPTY_ASSISTANT_RESPONSE]"


def test_generated_id_sanitizes_unexpected_chars():
    debug_id = generate_debug_conversation_id("conv_xxx/yyy zzz")
    assert re.match(r"^conv_debug_[a-zA-Z0-9_]+$", debug_id)
