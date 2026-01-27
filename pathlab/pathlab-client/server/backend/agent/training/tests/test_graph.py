"""
Tests for create_training_graph. Includes a visualization test: Mermaid 文本、PNG 图片，
以及在 Jupyter 里可用的 Image(..draw_mermaid_png())。

Run with -s to see output:
  uv run pytest backend/agent/training/tests/test_graph.py -s -v

Jupyter 中直接显示图片:
  from IPython.display import Image, display
  from backend.agent.training import create_training_graph
  g = create_training_graph()
  display(Image(g.get_graph().draw_mermaid_png()))
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.agent.training import create_training_graph

_TESTS_DIR = Path(__file__).resolve().parent


def test_create_training_graph_compiles():
    """Graph builds and compiles with a mock LLM."""
    g = create_training_graph(llm=MagicMock())
    assert g is not None


def test_training_graph_visualization():
    """
    输出 Mermaid 文本、draw_mermaid_png() 保存 PNG，并打印路径。
    Run: uv run pytest backend/agent/training/tests/test_graph.py::test_training_graph_visualization -s -v
    """
    g = create_training_graph(llm=MagicMock())
    G = g.get_graph()

    # Mermaid 文本
    mermaid = G.draw_mermaid()
    assert "agent" in mermaid and "tools" in mermaid
    print("\n=== Training graph (Mermaid) ===\n")
    print(mermaid)

    # draw_mermaid_png() 保存为 PNG（pytest 下无法 Image() 弹窗，故写文件）
    try:
        png_bytes = G.draw_mermaid_png()
        out_path = _TESTS_DIR / "training_graph.png"
        out_path.write_bytes(png_bytes)
        print(f"\n=== PNG 已保存 ===\n{out_path}\n")
    except Exception as e:
        print(f"\n=== draw_mermaid_png 失败: {e} ===\n")

    # ASCII（需 grandalf）
    try:
        ascii_out = G.draw_ascii()
        print("\n=== Training graph (ASCII) ===\n")
        print(ascii_out)
    except ImportError as e:
        if "grandalf" in str(e):
            print("\n=== ASCII: pip install grandalf ===\n")
        else:
            raise
