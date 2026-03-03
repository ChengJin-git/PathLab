"""CLI entry point — thin wrapper around CleaningPipeline.

Usage:
    python -m data_cleaner input.xlsx -p wsi
    python -m data_cleaner input.csv -t template.csv -o output.csv
    python -m data_cleaner input.xlsx --analyze-only
    python -m data_cleaner --list-presets
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from data_cleaner.pipeline import CleaningPipeline, CleaningConfig
from data_cleaner.prompts import list_presets, PRESETS

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="data_cleaner",
        description="PathLab Data Cleaner: LLM-driven Excel/CSV auto-cleaning tool",
    )
    parser.add_argument("input", nargs="?", default=None, help="Input file (Excel or CSV)")
    parser.add_argument("-o", "--output", default=None, help="Output CSV path")
    parser.add_argument("-t", "--template", default=None, help="Template CSV to match")
    parser.add_argument("-p", "--preset", default=None, choices=list(PRESETS.keys()),
                        help="Built-in preset (wsi, wsi-survival, wsi-seg)")
    parser.add_argument("--sheet", default=None, help="Excel sheet name")
    parser.add_argument("--rules", default="", help="Extra transformation rules")
    parser.add_argument("--analyze-only", action="store_true", help="Only analyze, no cleaning")
    parser.add_argument("--show-code", action="store_true", help="Show generated code, don't execute")
    parser.add_argument("--no-split", action="store_true", help="Skip train/val/test split")
    parser.add_argument("--split-ratio", default="7:1:2", help="Split ratio (default: 7:1:2)")
    parser.add_argument("--split-seed", type=int, default=42, help="Random seed for split")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000/v1", help="LLM API URL")
    parser.add_argument("--api-key", default="sk-pathlab", help="LLM API key")
    parser.add_argument("--model", default="Qwen/Qwen3-235B-A22B-Instruct-2507", help="LLM model")
    parser.add_argument("--max-retries", type=int, default=3, help="Max retries on failure")
    parser.add_argument("--timeout", type=int, default=120, help="Execution timeout (seconds)")
    parser.add_argument("--list-presets", action="store_true", help="List presets and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    return parser


def _parse_ratio(ratio_str: str) -> tuple[float, float, float]:
    """Parse '7:1:2' into normalized tuple."""
    try:
        parts = [float(p) for p in ratio_str.split(":")]
        total = sum(parts)
        return (parts[0] / total, parts[1] / total, parts[2] / total)
    except (ValueError, IndexError):
        return (0.7, 0.1, 0.2)


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_presets:
        print(list_presets())
        return

    if not args.input:
        parser.error("the following arguments are required: input")

    # Logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Build config
    config = CleaningConfig(
        api_url=args.api_url,
        api_key=args.api_key,
        model=args.model,
        preset=args.preset or "",
        template_path=args.template or "",
        extra_rules=args.rules,
        sheet_name=args.sheet,
        max_retries=args.max_retries,
        timeout=args.timeout,
        enable_split=not args.no_split,
        split_ratio=_parse_ratio(args.split_ratio),
        split_seed=args.split_seed,
    )

    pipeline = CleaningPipeline(config)

    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output) if args.output else ""

    # Header
    print(f"{'=' * 60}")
    print(f"PathLab Data Cleaner v0.1")
    print(f"{'=' * 60}")
    print(f"Input:  {input_path}")
    if output_path:
        print(f"Output: {output_path}")
    if config.preset:
        print(f"Preset: {config.preset}")
    print()

    # Run appropriate mode
    if args.analyze_only:
        result = pipeline.analyze_only(input_path)
        if result.success:
            print(result.analysis_report)
        else:
            print(f"Error: {result.error}", file=sys.stderr)
            sys.exit(1)
        return

    if args.show_code:
        result = pipeline.generate_code_only(input_path, output_path)
        if result.success:
            print(result.analysis_report)
            print("\n" + "=" * 60)
            print("GENERATED CODE")
            print("=" * 60)
            print(result.generated_code)
        else:
            print(f"Error: {result.error}", file=sys.stderr)
            sys.exit(1)
        return

    # Full run
    result = pipeline.run(input_path, output_path)

    # Print step results
    for step in result.steps:
        status = "OK" if step.success else "FAIL"
        print(f"  [{status}] {step.name}: {step.message}")

    print()

    if result.success:
        print(f"{'=' * 60}")
        print("SUCCESS!")
        print(f"{'=' * 60}")
        print(f"Output: {result.output_path}")
        print(f"Rows: {result.output_rows}, Columns: {result.output_cols}")
        print(f"Columns: {result.output_columns}")
        if result.split_counts:
            print(f"Split: {result.split_counts}")
    else:
        print(f"{'=' * 60}")
        print("FAILED")
        print(f"{'=' * 60}")
        print(f"Error: {result.error}")
        sys.exit(1)


if __name__ == "__main__":
    main()
