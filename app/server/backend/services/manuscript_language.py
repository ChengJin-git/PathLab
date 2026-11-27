"""Translate generated section labels without translating evidence or source text."""

import re

HEADINGS = {
    "zh-CN": dict(
        zip(
            [
                "Abstract",
                "Introduction",
                "Methods",
                "Results",
                "Experiments and results",
                "Discussion",
                "Conclusion",
                "References",
                "Data availability",
                "Code availability",
                "Acknowledgements",
                "Funding",
                "Author contributions",
                "Competing interests",
                "Figures",
            ],
            [
                "摘要",
                "引言",
                "方法",
                "结果",
                "实验与结果",
                "讨论",
                "结论",
                "参考文献",
                "数据可用性",
                "代码可用性",
                "致谢",
                "经费支持",
                "作者贡献",
                "利益冲突",
                "图表",
            ],
            strict=True,
        )
    ),
    "zh-HK": dict(
        zip(
            [
                "Abstract",
                "Introduction",
                "Methods",
                "Results",
                "Experiments and results",
                "Discussion",
                "Conclusion",
                "References",
                "Data availability",
                "Code availability",
                "Acknowledgements",
                "Funding",
                "Author contributions",
                "Competing interests",
                "Figures",
            ],
            [
                "摘要",
                "引言",
                "方法",
                "結果",
                "實驗與結果",
                "討論",
                "結論",
                "參考文獻",
                "資料可用性",
                "程式碼可用性",
                "致謝",
                "經費支持",
                "作者貢獻",
                "利益衝突",
                "圖表",
            ],
            strict=True,
        )
    ),
}


def localize_headings(content: str, language: str) -> str:
    names = HEADINGS.get(language, {})
    fenced = False
    lines = []
    for line in content.splitlines(keepends=True):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = re.match(r"^(#{1,6}) ([^\r\n]+)(\r?\n)?$", line)
        if match and not fenced and match[2].strip() in names:
            line = f"{match[1]} {names[match[2].strip()]}{match[3] or ''}"
        lines.append(line)
    return "".join(lines)


def canonical_heading(name: str) -> str:
    return next(
        (
            key
            for mapping in HEADINGS.values()
            for key, value in mapping.items()
            if value == name
        ),
        name,
    )


def document_language(report: dict) -> str:
    explicit = (report.get("generation") or {}).get("language")
    if explicit in {"en-US", "zh-CN", "zh-HK"}:
        return explicit
    content = report.get("content", "")
    language = max(
        HEADINGS,
        key=lambda language: sum(
            f"## {value}\n" in content for value in HEADINGS[language].values()
        ),
    )
    return (
        language
        if any(f"## {value}\n" in content for value in HEADINGS[language].values())
        else "en-US"
    )
