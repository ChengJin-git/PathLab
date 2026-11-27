import io
import zipfile

import pytest
from docx import Document

from backend.services import manuscript_writer, manuscripts, report_export
from backend.services.manuscript_language import localize_headings


@pytest.mark.parametrize(
    "language,result,references",
    [("zh-CN", "结果", "参考文献"), ("zh-HK", "結果", "參考文獻")],
)
def test_localized_sections_preserve_code_and_survive_template_switch(
    language, result, references
):
    content = localize_headings(
        "## Results\n\nAUROC = 0.81 [1]\n\n```md\n## Results\n```\n\n## References\n\n[1] English source",
        language,
    )
    assert f"## {result}\n" in content and f"## {references}\n" in content
    assert "```md\n## Results\n```" in content
    switched = manuscripts.retarget(
        f"## {references}\n\nEnglish source\n\n## {result}\n\nAUROC 0.81", "conference"
    )
    assert ("實驗與結果" if language == "zh-HK" else "实验与结果") in switched
    assert switched.index("0.81") < switched.index("English source")


def test_partial_chinese_article_and_exports_use_chinese_labels():
    content = manuscript_writer.assembled(
        "conference", {"Abstract": "探索性研究。", "Methods": "记录实验。"}, [], "zh-HK"
    )
    assert (
        "## 摘要" in content and "## 方法" in content and "## Abstract" not in content
    )
    report = {
        "title": "測試文章",
        "template": "conference",
        "content": content,
        "status": "draft",
        "evidence": {},
        "generation": {"language": "zh-HK"},
    }
    paragraphs = "\n".join(
        p.text for p in Document(io.BytesIO(report_export.word(report))).paragraphs
    )
    assert "摘要。" in paragraphs and "關鍵詞" in paragraphs
    with zipfile.ZipFile(io.BytesIO(report_export.latex(report))) as archive:
        tex = archive.read("main.tex").decode()
        assert "\\renewcommand{\\abstractname}{摘要}" in tex
        assert "關鍵詞" in tex
