"""Markdown rendering helpers for paper outline artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def _string_items(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _append_list(lines: list[str], title: str, items: Sequence[str]) -> None:
    if not items:
        return
    lines.append(f"- {title}:")
    lines.extend(f"  - {item}" for item in items)


def _append_json_block(lines: list[str], title: str, value: Any) -> None:
    if value in (None, [], {}):
        return
    lines.append(f"### {title}")
    lines.append("```json")
    lines.append(json.dumps(value, indent=2, ensure_ascii=False))
    lines.append("```")
    lines.append("")


def outline_to_markdown(outline: Mapping[str, Any]) -> str:
    """Render the canonical outline JSON into a user-readable markdown file."""

    lines: list[str] = ["# 大纲", ""]

    section_plan = outline.get("section_plan")
    lines.extend(["## 章节计划", ""])
    if isinstance(section_plan, list) and section_plan:
        for item in section_plan:
            if not isinstance(item, Mapping):
                continue
            section = str(item.get("section") or "未命名章节")
            goal = str(item.get("goal") or "").strip()
            lines.extend([f"### {section}", ""])
            if goal:
                lines.extend([goal, ""])
            _append_list(lines, "证据输入", _string_items(item.get("evidence_inputs")))
            _append_list(lines, "引用提示", _string_items(item.get("citation_hints")))
            _append_list(lines, "锁定块输入", _string_items(item.get("locked_block_inputs")))
            lines.append("")
    else:
        lines.extend(["暂无章节计划。", ""])

    plotting_plan = outline.get("plotting_plan")
    lines.extend(["## 图表计划", ""])
    if isinstance(plotting_plan, list) and plotting_plan:
        for item in plotting_plan:
            if not isinstance(item, Mapping):
                continue
            figure_id = str(item.get("figure_id") or "未命名图表")
            lines.extend([f"### {figure_id}", ""])
            for key, label in (
                ("kind", "类型"),
                ("source", "来源"),
                ("design_objective", "设计目标"),
                ("backend", "后端"),
            ):
                value = str(item.get(key) or "").strip()
                if value:
                    lines.append(f"- {label}: {value}")
            plot_spec = item.get("plot_spec")
            if plot_spec not in (None, {}, []):
                lines.append("- 绘图参数:")
                lines.append("```json")
                lines.append(json.dumps(plot_spec, indent=2, ensure_ascii=False))
                lines.append("```")
            lines.append("")
    else:
        lines.extend(["暂无图表计划。", ""])

    lines.extend(["## 文献检索", ""])
    macro_lit_search = _string_items(outline.get("macro_lit_search"))
    if macro_lit_search:
        lines.append("### 宏观检索")
        lines.extend(f"- {item}" for item in macro_lit_search)
        lines.append("")

    micro_lit_clusters = outline.get("micro_lit_clusters")
    if isinstance(micro_lit_clusters, list) and micro_lit_clusters:
        lines.append("### 聚焦检索")
        lines.append("")
        for item in micro_lit_clusters:
            if not isinstance(item, Mapping):
                continue
            cluster = str(item.get("cluster") or "未命名主题")
            lines.append(f"#### {cluster}")
            lines.extend(f"- {query}" for query in _string_items(item.get("queries")))
            lines.append("")
    elif not macro_lit_search:
        lines.extend(["暂无文献检索计划。", ""])

    extensions = outline.get("pathlab_extensions")
    if isinstance(extensions, Mapping):
        lines.extend(["## PathLab 扩展", ""])
        _append_list(lines, "模板", _string_items(extensions.get("templates")))
        _append_list(lines, "校验要求", _string_items(extensions.get("guard_requirements")))
        if lines[-1] != "":
            lines.append("")
        _append_json_block(lines, "声明计划", extensions.get("claim_plan"))
        _append_json_block(lines, "表格计划", extensions.get("table_plan"))
        _append_json_block(lines, "模板风格", extensions.get("template_styles"))

    return "\n".join(lines).rstrip() + "\n"
