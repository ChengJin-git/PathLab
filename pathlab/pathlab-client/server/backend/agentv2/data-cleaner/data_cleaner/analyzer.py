"""LLM-based table structure analyzer.

Sends sample data to the LLM and receives a structured JSON analysis
covering column types, data quality issues, and recommended schema.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from openai import OpenAI

from data_cleaner.file_reader import FileMetadata

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = """\
You are an expert data analyst specializing in biomedical and pathology data.
Your task is to analyze the structure of a messy table and provide a detailed
analysis in JSON format.

## Domain Context

This data likely comes from a pathology / medical research context. Common patterns:
- **WSI filenames**: Whole Slide Image files with extensions like .svs, .tiff, .ndpi, .mrxs
- **Patient IDs**: Hospital IDs, TCGA barcodes (e.g., TCGA-XX-XXXX), study IDs
- **Pathology labels**: tumor/normal, cancer subtypes, Gleason scores, TNM staging (T1-T4, N0-N3, M0-M1)
- **Survival data**: OS (overall survival), PFS (progression-free survival), status (0/1, alive/dead)
- **Clinical features**: age, sex/gender, diagnosis, treatment, grade, stage

## Output Format

Return ONLY a valid JSON object (no markdown fences, no explanation) with this structure:

{
  "columns": [
    {
      "original_name": "the column name as-is",
      "suggested_name": "clean_snake_case_name",
      "semantic_type": "one of: patient_id, wsi_filename, label, category, date, numeric, text, boolean, survival_time, survival_status, unknown",
      "issues": ["list of issues found, e.g., 'mixed formats', 'has nulls', 'inconsistent casing'"]
    }
  ],
  "global_issues": ["list of table-wide issues, e.g., 'duplicate rows', 'header row misaligned'"],
  "suggested_actions": ["list of recommended cleaning actions in priority order"]
}
"""


ANALYSIS_USER_TEMPLATE = """\
Analyze the following table data and provide a structured JSON analysis.

## File Information
- File: {file_path}
- Type: {file_type}
- Rows: {num_rows}, Columns: {num_cols}
- Encoding: {encoding}
{extra_info}

## Detected Issues
{issues}

## Sample Data (first rows)
{sample_markdown}
"""


@dataclass
class ColumnAnalysis:
    """Analysis result for a single column."""

    original_name: str
    suggested_name: str
    semantic_type: str
    issues: list[str] = field(default_factory=list)


@dataclass
class TableAnalysis:
    """Complete analysis result for a table."""

    columns: list[ColumnAnalysis] = field(default_factory=list)
    global_issues: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    raw_json: dict = field(default_factory=dict)


def analyze_table(
    sample_markdown: str,
    metadata: FileMetadata,
    api_url: str = "http://127.0.0.1:8000/v1",
    api_key: str = "sk-pathlab",
    model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507",
) -> TableAnalysis:
    """Analyze table structure using LLM.

    Args:
        sample_markdown: Markdown table of sample data
        metadata: File metadata from reader
        api_url: OpenAI-compatible API URL (local vLLM)
        api_key: API key
        model: Model name

    Returns:
        TableAnalysis with column types, issues, and suggested actions
    """
    client = OpenAI(base_url=api_url, api_key=api_key)

    # Build extra info
    extra_info_parts = []
    if metadata.delimiter != ",":
        extra_info_parts.append(f"- Delimiter: {repr(metadata.delimiter)}")
    if metadata.sheet_names:
        extra_info_parts.append(f"- Sheets: {', '.join(metadata.sheet_names)}")
        extra_info_parts.append(f"- Active sheet: {metadata.active_sheet}")
    if metadata.has_merged_cells:
        extra_info_parts.append("- Has merged cells (already unmerged)")
    extra_info = "\n".join(extra_info_parts) if extra_info_parts else "- (none)"

    # Build issues list
    issues_text = "\n".join(f"- {issue}" for issue in metadata.issues) if metadata.issues else "- No issues detected by pre-scan"

    user_message = ANALYSIS_USER_TEMPLATE.format(
        file_path=metadata.file_path,
        file_type=metadata.file_type,
        num_rows=metadata.num_rows,
        num_cols=metadata.num_cols,
        encoding=metadata.encoding,
        extra_info=extra_info,
        issues=issues_text,
        sample_markdown=sample_markdown,
    )

    logger.info("Sending table data to LLM for analysis...")
    logger.debug(f"User message length: {len(user_message)} chars")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        temperature=0.1,
        max_tokens=4096,
    )

    raw_content = response.choices[0].message.content.strip()
    logger.debug(f"LLM analysis response: {raw_content[:500]}...")

    # Parse JSON from response (handle markdown fences if present)
    analysis = _parse_analysis_json(raw_content)
    return analysis


def _parse_analysis_json(raw: str) -> TableAnalysis:
    """Parse JSON analysis from LLM response, handling common formatting issues."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_newline = text.index("\n")
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[: text.rindex("```")]
    text = text.strip()

    # Try to find JSON object in the text
    # Sometimes LLM wraps with extra text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM analysis JSON: {e}")
        logger.error(f"Raw content: {text[:500]}")
        # Return a minimal analysis
        return TableAnalysis(
            global_issues=["LLM analysis JSON parsing failed"],
            suggested_actions=["Manual review recommended"],
            raw_json={"error": str(e), "raw": text[:1000]},
        )

    # Build structured result
    columns = []
    for col_data in data.get("columns", []):
        columns.append(
            ColumnAnalysis(
                original_name=col_data.get("original_name", ""),
                suggested_name=col_data.get("suggested_name", ""),
                semantic_type=col_data.get("semantic_type", "unknown"),
                issues=col_data.get("issues", []),
            )
        )

    return TableAnalysis(
        columns=columns,
        global_issues=data.get("global_issues", []),
        suggested_actions=data.get("suggested_actions", []),
        raw_json=data,
    )


def format_analysis_report(analysis: TableAnalysis) -> str:
    """Format analysis result as a human-readable report."""
    lines = ["=" * 60, "TABLE STRUCTURE ANALYSIS", "=" * 60, ""]

    if analysis.columns:
        lines.append("COLUMNS:")
        lines.append("-" * 40)
        for col in analysis.columns:
            lines.append(f"  {col.original_name}")
            lines.append(f"    -> Suggested: {col.suggested_name}")
            lines.append(f"    -> Type: {col.semantic_type}")
            if col.issues:
                lines.append(f"    -> Issues: {', '.join(col.issues)}")
            lines.append("")

    if analysis.global_issues:
        lines.append("GLOBAL ISSUES:")
        lines.append("-" * 40)
        for issue in analysis.global_issues:
            lines.append(f"  - {issue}")
        lines.append("")

    if analysis.suggested_actions:
        lines.append("SUGGESTED ACTIONS:")
        lines.append("-" * 40)
        for i, action in enumerate(analysis.suggested_actions, 1):
            lines.append(f"  {i}. {action}")
        lines.append("")

    return "\n".join(lines)
