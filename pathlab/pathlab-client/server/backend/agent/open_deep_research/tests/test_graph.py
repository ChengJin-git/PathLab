"""
Tests for the deep_researcher graph. Includes a visualization test: Mermaid 文本、PNG 图片。

Run with -s to see output:
  uv run pytest backend/agent/open_deep_research/tests/test_graph.py -s -v

Or from server with open_deep_research on path:
  cd pathlab-client/server && uv run pytest backend/agent/open_deep_research/tests/test_graph.py::test_research_graph_visualization -s -v

Jupyter 中直接显示图片:
  from IPython.display import Image, display
  from open_deep_research.deep_researcher import deep_researcher
  g = deep_researcher.get_graph()
  display(Image(g.draw_mermaid_png()))
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 确保 open_deep_research 可导入（与 backend.agent.graph 一致）
_odr_src = Path(__file__).resolve().parent.parent / "src"
if _odr_src.exists() and str(_odr_src) not in sys.path:
    sys.path.insert(0, str(_odr_src))

_TESTS_DIR = Path(__file__).resolve().parent


def test_research_graph_compiles():
    """deep_researcher 可导入且为已编译的图。"""
    from open_deep_research.deep_researcher import deep_researcher

    assert deep_researcher is not None
    g = deep_researcher.get_graph()
    assert g is not None


def test_research_graph_visualization():
    """
    输出 Mermaid 文本、draw_mermaid_png() 保存 PNG，并打印路径。
    Run: uv run pytest backend/agent/open_deep_research/tests/test_graph.py::test_research_graph_visualization -s -v
    """
    from open_deep_research.deep_researcher import deep_researcher

    g = deep_researcher.get_graph()

    # Mermaid 文本
    mermaid = g.draw_mermaid()
    assert "clarify_with_user" in mermaid or "research" in mermaid or "supervisor" in mermaid
    print("\n=== Research graph (Mermaid) ===\n")
    print(mermaid)

    # draw_mermaid_png() 保存为 PNG
    try:
        png_bytes = g.draw_mermaid_png()
        out_path = _TESTS_DIR / "research_graph.png"
        out_path.write_bytes(png_bytes)
        print(f"\n=== PNG 已保存 ===\n{out_path}\n")
    except Exception as e:
        print(f"\n=== draw_mermaid_png 失败: {e} ===\n")

    # ASCII（需 grandalf）
    try:
        ascii_out = g.draw_ascii()
        print("\n=== Research graph (ASCII) ===\n")
        print(ascii_out)
    except ImportError as e:
        if "grandalf" in str(e):
            print("\n=== ASCII: pip install grandalf ===\n")
        else:
            raise
