import json
import pytest
from gateway.chat.deliverables import (
    TextDelivery,
    parse_deliveries,
    without_delivery_blocks,
)
from gateway.chat.stream_blocks import BlockStreamFilter


def test_stream_filter_hides_payload_across_every_chunk_boundary():
    raw = (
        "准备文件。\n[DELIVER_FILE]"
        + json.dumps({"filename": "report.md", "content": "# 内容\n正文"})
        + "[/DELIVER_FILE]\n请查看文件。"
    )
    for size in range(1, 30):
        stream = BlockStreamFilter(('DELIVER_FILE', 'FILE_DELIVERY', 'RESEARCH_RUN'))
        shown = (
            "".join(stream.feed(raw[i : i + size]) for i in range(0, len(raw), size))
            + stream.finish()
        )
        assert shown == "准备文件。\n\n请查看文件。"
        assert "# 内容" not in shown
    assert parse_deliveries(raw)[0].content == "# 内容\n正文"


def test_incomplete_delivery_does_not_leak_or_become_a_file():
    stream = BlockStreamFilter(('DELIVER_FILE', 'FILE_DELIVERY', 'RESEARCH_RUN'))
    assert stream.feed('Before [DELIVER_FILE]{"content":"private') == "Before "
    assert stream.finish() == ""
    assert parse_deliveries('[DELIVER_FILE]{"content":"partial') == []
    assert without_delivery_blocks("Before [DELIVER_FILE]unfinished") == "Before"


def test_model_cannot_fabricate_server_delivery_receipts():
    from gateway.chat.deliverables import without_model_receipts

    raw = 'Here [FILE_DELIVERY]{"files":[{"id":"invented"}]}[/FILE_DELIVERY] end'
    stream = BlockStreamFilter(('DELIVER_FILE', 'FILE_DELIVERY', 'RESEARCH_RUN'))
    assert "".join(stream.feed(char) for char in raw) + stream.finish() == "Here  end"
    assert without_model_receipts(raw) == "Here  end"


def test_missing_tool_close_is_repaired_only_with_complete_json():
    from gateway.chat.tool_envelopes import (
        close_complete_tool_envelope,
        has_unclosed_tool_envelope,
        strip_tool_envelopes,
    )

    raw = '[WEB_SEARCH]{"query":"Hong Kong weather","num_results":5}'
    assert close_complete_tool_envelope(raw) == raw + "[/WEB_SEARCH]"
    incomplete = '[WEB_SEARCH]{"query":"Hong Kong'
    assert close_complete_tool_envelope(incomplete) == incomplete
    assert has_unclosed_tool_envelope(incomplete)
    assert strip_tool_envelopes(incomplete + "\nfailed") == ""


@pytest.mark.parametrize(
    "name",
    ["../report.md", "/etc/a.md", "C:\\test.md", ".hidden.md", "a.pdf", "a\n.md"],
)
def test_delivery_rejects_arbitrary_paths_and_binary_extensions(name):
    with pytest.raises(ValueError):
        TextDelivery(filename=name, content="Hello")
