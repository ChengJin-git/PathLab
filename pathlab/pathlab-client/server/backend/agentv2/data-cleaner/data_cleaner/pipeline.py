"""Core pipeline for PathLab Data Cleaner.

Provides a clean Python API that can be imported and called directly,
independent of CLI or web framework.

Usage:
    from data_cleaner.pipeline import CleaningPipeline, CleaningConfig

    config = CleaningConfig(preset="wsi")
    pipeline = CleaningPipeline(config)
    result = pipeline.run("messy_data.xlsx", "output.csv")

    if result.success:
        print(f"Cleaned: {result.output_path}")
        print(f"Rows: {result.output_rows}")
    else:
        print(f"Failed: {result.error}")
"""

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from data_cleaner.file_reader import read_file, ReadResult, FileMetadata
from data_cleaner.analyzer import analyze_table, TableAnalysis, format_analysis_report
from data_cleaner.code_generator import (
    generate_cleaning_code,
    generate_template_code,
    generate_fix,
)
from data_cleaner.executor import execute_code
from data_cleaner.prompts import get_preset, Preset
from data_cleaner.splitter import assign_split

logger = logging.getLogger(__name__)


# ─── Configuration ────────────────────────────────────────────

@dataclass
class CleaningConfig:
    """Configuration for the cleaning pipeline."""

    # LLM settings
    api_url: str = "http://127.0.0.1:8000/v1"
    api_key: str = "sk-pathlab"
    model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"

    # Preset (auto-loads template + rules)
    preset: str = ""  # e.g., "wsi", "wsi-survival"

    # Template (overrides preset template if set)
    template_path: str = ""

    # Extra rules (appended to preset rules)
    extra_rules: str = ""

    # Excel sheet name (None = active sheet)
    sheet_name: Optional[str] = None

    # Execution
    max_retries: int = 3
    timeout: int = 120

    # Split settings
    enable_split: bool = True
    split_ratio: tuple[float, float, float] = (0.7, 0.1, 0.2)
    split_seed: int = 42
    split_label_col: str = "label"
    split_col: str = "split"


# ─── Result Models ────────────────────────────────────────────

@dataclass
class StepResult:
    """Result of a single pipeline step."""
    name: str
    success: bool
    message: str = ""
    duration_ms: int = 0


@dataclass
class PipelineResult:
    """Complete result of a cleaning pipeline run."""

    success: bool
    output_path: str = ""
    error: str = ""

    # Input stats
    input_path: str = ""
    input_rows: int = 0
    input_cols: int = 0
    input_issues: list[str] = field(default_factory=list)

    # Output stats
    output_rows: int = 0
    output_cols: int = 0
    output_columns: list[str] = field(default_factory=list)

    # Split stats (if enabled)
    split_counts: dict[str, int] = field(default_factory=dict)

    # Analysis
    analysis_report: str = ""
    analysis: Optional[TableAnalysis] = None

    # Generated code (for debugging)
    generated_code: str = ""

    # Step-by-step log
    steps: list[StepResult] = field(default_factory=list)

    # The cleaned DataFrame (optional, for direct access)
    df: Optional[pd.DataFrame] = None

    def to_dict(self) -> dict:
        """Serialize to dict (safe for JSON, no DataFrame)."""
        return {
            "success": self.success,
            "output_path": self.output_path,
            "error": self.error,
            "input_path": self.input_path,
            "input_rows": self.input_rows,
            "input_cols": self.input_cols,
            "input_issues": self.input_issues,
            "output_rows": self.output_rows,
            "output_cols": self.output_cols,
            "output_columns": self.output_columns,
            "split_counts": self.split_counts,
            "analysis_report": self.analysis_report,
            "steps": [
                {"name": s.name, "success": s.success, "message": s.message}
                for s in self.steps
            ],
        }


# ─── Pipeline ─────────────────────────────────────────────────

class CleaningPipeline:
    """Core cleaning pipeline. Framework-independent, no print() calls."""

    def __init__(self, config: Optional[CleaningConfig] = None):
        self.config = config or CleaningConfig()
        self._preset: Optional[Preset] = None
        self._template_path: Optional[str] = None
        self._combined_rules: str = ""

        self._resolve_preset()

    def _resolve_preset(self):
        """Load preset and resolve template path + rules."""
        cfg = self.config

        if cfg.preset:
            self._preset = get_preset(cfg.preset)

            # Split settings from preset
            if cfg.enable_split and self._preset.no_split:
                cfg.enable_split = False

        # Template: explicit > preset default
        if cfg.template_path:
            self._template_path = os.path.abspath(cfg.template_path)
        elif self._preset and self._preset.template_path:
            self._template_path = self._preset.template_path

        # Combined rules: preset + extra
        rules_parts = []
        if self._preset:
            rules_parts.append(self._preset.rules)
        if cfg.extra_rules:
            rules_parts.append(f"\n## Additional Rules\n{cfg.extra_rules}")
        self._combined_rules = "\n".join(rules_parts)

    @property
    def llm_kwargs(self) -> dict:
        return {
            "api_url": self.config.api_url,
            "api_key": self.config.api_key,
            "model": self.config.model,
        }

    def run(self, input_path: str, output_path: str = "") -> PipelineResult:
        """Run the full cleaning pipeline.

        Args:
            input_path: Path to the input file (Excel/CSV)
            output_path: Path for output CSV (default: <input>_cleaned.csv)

        Returns:
            PipelineResult with success status, stats, and optional DataFrame
        """
        input_path = os.path.abspath(input_path)
        if not output_path:
            stem = Path(input_path).stem
            output_path = os.path.join(
                os.path.dirname(input_path), f"{stem}_cleaned.csv"
            )
        output_path = os.path.abspath(output_path)

        result = PipelineResult(
            success=False,
            input_path=input_path,
            output_path=output_path,
        )

        # ── Step 1: Read input ─────────────────────────────────
        read_result, template_result = self._step_read(input_path, result)
        if read_result is None:
            return result

        # ── Step 2: Analyze ────────────────────────────────────
        analysis = self._step_analyze(read_result, result)
        if analysis is None:
            return result

        # ── Step 3: Generate code ──────────────────────────────
        intermediate_path, code = self._step_generate(
            read_result, template_result, analysis, output_path, result
        )
        if code is None:
            return result

        # ── Step 4: Execute with retries ───────────────────────
        if not self._step_execute(code, intermediate_path, analysis, read_result, output_path, result):
            return result

        # ── Step 5: Split (optional) ───────────────────────────
        if self.config.enable_split:
            self._step_split(output_path, result)

        # ── Load final DataFrame ───────────────────────────────
        try:
            df = pd.read_csv(output_path)
            result.output_rows = len(df)
            result.output_cols = len(df.columns)
            result.output_columns = df.columns.tolist()
            result.df = df
        except Exception as e:
            logger.warning(f"Could not read output file: {e}")

        result.success = True
        return result

    def analyze_only(self, input_path: str) -> PipelineResult:
        """Run only the analysis step (no cleaning)."""
        input_path = os.path.abspath(input_path)
        result = PipelineResult(success=False, input_path=input_path)

        read_result, _ = self._step_read(input_path, result)
        if read_result is None:
            return result

        analysis = self._step_analyze(read_result, result)
        if analysis is None:
            return result

        result.success = True
        return result

    def generate_code_only(self, input_path: str, output_path: str = "") -> PipelineResult:
        """Run analysis + code generation without executing."""
        input_path = os.path.abspath(input_path)
        if not output_path:
            stem = Path(input_path).stem
            output_path = os.path.join(os.path.dirname(input_path), f"{stem}_cleaned.csv")

        result = PipelineResult(success=False, input_path=input_path, output_path=output_path)

        read_result, template_result = self._step_read(input_path, result)
        if read_result is None:
            return result

        analysis = self._step_analyze(read_result, result)
        if analysis is None:
            return result

        intermediate_path, code = self._step_generate(
            read_result, template_result, analysis, output_path, result
        )
        if code is None:
            return result

        result.success = True
        return result

    # ─── Pipeline Steps ───────────────────────────────────────

    def _step_read(self, input_path: str, result: PipelineResult):
        """Step 1: Read input file (and template if configured)."""
        try:
            read_result = read_file(input_path, sheet_name=self.config.sheet_name)
        except Exception as e:
            result.error = f"Failed to read input file: {e}"
            result.steps.append(StepResult("read_input", False, str(e)))
            return None, None

        meta = read_result.metadata
        result.input_rows = meta.num_rows
        result.input_cols = meta.num_cols
        result.input_issues = meta.issues
        result.steps.append(StepResult(
            "read_input", True,
            f"{meta.num_rows} rows x {meta.num_cols} cols, type={meta.file_type}"
        ))

        # Read template
        template_result = None
        if self._template_path:
            try:
                template_result = read_file(self._template_path)
                result.steps.append(StepResult(
                    "read_template", True,
                    f"{template_result.metadata.num_rows} rows, "
                    f"cols={template_result.df.columns.tolist()}"
                ))
            except Exception as e:
                result.error = f"Failed to read template: {e}"
                result.steps.append(StepResult("read_template", False, str(e)))
                return None, None

        return read_result, template_result

    def _step_analyze(self, read_result: ReadResult, result: PipelineResult):
        """Step 2: Analyze table structure with LLM."""
        try:
            analysis = analyze_table(
                read_result.sample_markdown,
                read_result.metadata,
                **self.llm_kwargs,
            )
        except Exception as e:
            result.error = f"Analysis failed: {e}"
            result.steps.append(StepResult("analyze", False, str(e)))
            return None

        result.analysis = analysis
        result.analysis_report = format_analysis_report(analysis)
        result.steps.append(StepResult(
            "analyze", True,
            f"{len(analysis.columns)} columns analyzed, "
            f"{len(analysis.suggested_actions)} actions suggested"
        ))
        return analysis

    def _step_generate(self, read_result, template_result, analysis,
                       output_path, result: PipelineResult):
        """Step 3: Save intermediate CSV + generate cleaning code."""
        # Save pre-parsed intermediate file
        intermediate_path = os.path.join(
            tempfile.mkdtemp(prefix="data_cleaner_"),
            "parsed_input.csv",
        )
        read_result.df.to_csv(intermediate_path, index=False)

        try:
            if template_result:
                code = generate_template_code(
                    sample_markdown=read_result.sample_markdown,
                    template_markdown=template_result.sample_markdown,
                    analysis=analysis,
                    input_path=intermediate_path,
                    output_path=output_path,
                    extra_rules=self._combined_rules,
                    schema_text=read_result.schema_text,
                    template_schema_text=template_result.schema_text,
                    **self.llm_kwargs,
                )
            else:
                code = generate_cleaning_code(
                    sample_markdown=read_result.sample_markdown,
                    analysis=analysis,
                    input_path=intermediate_path,
                    output_path=output_path,
                    schema_text=read_result.schema_text,
                    **self.llm_kwargs,
                )
        except Exception as e:
            result.error = f"Code generation failed: {e}"
            result.steps.append(StepResult("generate", False, str(e)))
            return None, None

        result.generated_code = code
        result.steps.append(StepResult("generate", True, f"{len(code)} chars"))
        return intermediate_path, code

    def _step_execute(self, code, intermediate_path, analysis,
                      read_result, output_path, result: PipelineResult) -> bool:
        """Step 4: Execute code with retries."""
        current_code = code
        available_columns = read_result.df.columns.tolist()

        for attempt in range(1, self.config.max_retries + 1):
            logger.info(f"Execution attempt {attempt}/{self.config.max_retries}")

            exec_result = execute_code(
                current_code,
                output_path=output_path,
                timeout=self.config.timeout,
            )

            if exec_result.success:
                result.steps.append(StepResult(
                    "execute", True,
                    f"Succeeded on attempt {attempt}"
                ))
                result.generated_code = current_code
                return True

            # Failed — try fix
            logger.warning(f"Attempt {attempt} failed: {exec_result.error_summary[:200]}")

            if attempt < self.config.max_retries:
                error_info = exec_result.stderr[-2000:] if exec_result.stderr else exec_result.error_summary
                try:
                    current_code = generate_fix(
                        previous_code=current_code,
                        error=error_info,
                        analysis=analysis,
                        available_columns=available_columns,
                        **self.llm_kwargs,
                    )
                except Exception as e:
                    logger.error(f"Fix generation failed: {e}")
                    break

        result.error = f"Execution failed after {self.config.max_retries} attempts: {exec_result.error_summary[:500]}"
        result.steps.append(StepResult("execute", False, result.error))
        result.generated_code = current_code
        return False

    def _step_split(self, output_path: str, result: PipelineResult):
        """Step 5: Assign train/val/test split."""
        try:
            df = pd.read_csv(output_path)
            df = assign_split(
                df,
                label_col=self.config.split_label_col,
                split_col=self.config.split_col,
                ratio=self.config.split_ratio,
                seed=self.config.split_seed,
            )
            df.to_csv(output_path, index=False)

            counts = df[self.config.split_col].value_counts().to_dict()
            result.split_counts = counts
            result.steps.append(StepResult(
                "split", True,
                f"train={counts.get('train', 0)}, "
                f"val={counts.get('val', 0)}, "
                f"test={counts.get('test', 0)}"
            ))
        except Exception as e:
            logger.warning(f"Split failed: {e}")
            result.steps.append(StepResult("split", False, str(e)))
