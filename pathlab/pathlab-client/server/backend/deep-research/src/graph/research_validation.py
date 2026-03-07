from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import ToolMessage

from src.tools.result_utils import (
    TOOL_STATUS_SUCCESS,
    parse_tool_result,
)


@dataclass
class ResearchEvidenceSummary:
    valid_hits: int = 0
    valid_hits_by_tool: dict[str, int] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    latest_status_by_tool: dict[str, str] = field(default_factory=dict)

    @property
    def is_sufficient(self) -> bool:
        return self.valid_hits > 0


def summarize_research_evidence(messages: list[Any]) -> ResearchEvidenceSummary:
    summary = ResearchEvidenceSummary()

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        tool_name = getattr(message, "name", "") or ""
        parsed = parse_tool_result(getattr(message, "content", None), tool_name)
        if not isinstance(parsed, dict):
            continue

        meta = parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {}
        tool = meta.get("tool") or tool_name
        status = meta.get("status")
        summary.latest_status_by_tool[tool] = status
        if meta.get("valid_for_research") is True:
            summary.valid_hits += 1
            summary.valid_hits_by_tool[tool] = summary.valid_hits_by_tool.get(tool, 0) + 1
        elif isinstance(meta.get("summary"), str) and meta["summary"].strip():
            summary.issues.append(f"{tool}: {meta['summary']}")

    return summary


def has_sufficient_research_evidence(messages: list[Any], minimum_valid_hits: int) -> bool:
    summary = summarize_research_evidence(messages)
    return summary.valid_hits >= minimum_valid_hits


def build_research_retry_feedback(
    *,
    summary: ResearchEvidenceSummary,
    minimum_valid_hits: int,
    locale: str,
) -> str:
    issue_lines = "\n".join(f"- {issue}" for issue in summary.issues[:5])
    if locale.lower().startswith("zh"):
        base = (
            f"本轮调研的有效证据仍然不足。继续检索，直到至少拿到 {minimum_valid_hits} 次有效命中后再结束当前 research step。\n"
            "以下结果都不能算有效证据：报错、空结果、只有链接没有摘要、页面抓取后几乎没有正文、只返回图片、PathLab API 不可用。\n"
            "优先补充：有摘要的检索结果、成功抓取到足够正文的页面、命中的本地文档，或真实可用的 PathLab 数据。"
        )
        return f"{base}\n最近的问题：\n{issue_lines}" if issue_lines else base

    base = (
        f"The current research step still lacks enough valid evidence. Continue researching until you have at least {minimum_valid_hits} valid evidence hits before concluding this step.\n"
        "Do not count errors, empty results, link-only results, crawl results with almost no body text, image-only search results, or unavailable PathLab API responses as valid evidence.\n"
        "Prioritize search results with meaningful snippets, successfully crawled pages with enough body text, matched local documents, or real PathLab data."
    )
    return f"{base}\nRecent issues:\n{issue_lines}" if issue_lines else base


def build_insufficient_research_summary(
    *,
    summary: ResearchEvidenceSummary,
    minimum_valid_hits: int,
    locale: str,
) -> str:
    issue_lines = "\n".join(f"- {issue}" for issue in summary.issues[:5])
    if locale.lower().startswith("zh"):
        header = f"未能满足进入分析所需的证据门槛：至少 {minimum_valid_hits} 次有效命中。"
        return f"{header}\n{issue_lines}" if issue_lines else header
    header = f"The step did not meet the analysis gate of at least {minimum_valid_hits} valid evidence hits."
    return f"{header}\n{issue_lines}" if issue_lines else header
