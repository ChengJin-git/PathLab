"""Command line entrypoint for the standalone paper agent."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Optional

from .bootstrap import configure_uploads_dir
from .pipeline import (
    complete_run,
    create_dev_run,
    run_after_outline,
    run_render_export,
    run_stage,
    run_until_outline,
)
from .regenerate import latest_regenerate_log_summary, regenerate_section


def _add_common_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--uploads-dir", default=None, help="PathLab uploads root. Defaults to Config.get_uploads_dir().")
    parser.add_argument("--config", default=None, help="Optional config.json path for worker compatibility.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pathlab-paper-agent")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the Phase 01 scaffold pipeline for one paper id.")
    run.add_argument("--paper-id", required=True)
    _add_common_runtime_args(run)

    run_until_outline_parser = sub.add_parser("run-until-outline", help="Run through outline generation and stop for approval.")
    run_until_outline_parser.add_argument("--paper-id", required=True)
    _add_common_runtime_args(run_until_outline_parser)

    run_after_outline_parser = sub.add_parser("run-after-outline", help="Resume a paper run after outline approval.")
    run_after_outline_parser.add_argument("--paper-id", required=True)
    _add_common_runtime_args(run_after_outline_parser)

    render_export = sub.add_parser("render-export", help="Re-render final paper outputs and exports.")
    render_export.add_argument("--paper-id", required=True)
    _add_common_runtime_args(render_export)

    run_stage_parser = sub.add_parser("run-stage", help="Run a single stub stage and update manifest.json.")
    run_stage_parser.add_argument("--paper-id", required=True)
    run_stage_parser.add_argument("--stage", required=True)
    _add_common_runtime_args(run_stage_parser)

    scaffold = sub.add_parser("scaffold", help="Create a dev paper run scaffold without Gateway.")
    scaffold.add_argument("--paper-id", default=None)
    _add_common_runtime_args(scaffold)

    serve = sub.add_parser("serve", help="Start the dev-only standalone HTTP service.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=6200)
    _add_common_runtime_args(serve)

    regenerate = sub.add_parser("regenerate", help="Regenerate one paper section without rewriting other sections.")
    regenerate.add_argument("--paper-id", required=True)
    regenerate.add_argument("--section", required=True)
    _add_common_runtime_args(regenerate)

    return parser


async def _cmd_scaffold(paper_id: Optional[str], uploads_dir: Optional[str]) -> int:
    new_id, paths = await create_dev_run(None, paper_id=paper_id, uploads_dir=uploads_dir)
    print(f"created {new_id} at {paths.root}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    uploads_dir = getattr(args, "uploads_dir", None)
    configure_uploads_dir(uploads_dir)

    if args.command == "scaffold":
        return asyncio.run(_cmd_scaffold(args.paper_id, uploads_dir))

    if args.command == "run-stage":
        manifest = run_stage(
            args.paper_id,
            args.stage,
            uploads_dir=uploads_dir,
            config_path=args.config,
        )
        print(f"{manifest.paper_id}: {manifest.current_stage.value} ({manifest.status.value})")
        return 0

    if args.command == "run":
        manifest = complete_run(args.paper_id, uploads_dir=uploads_dir, config_path=args.config)
        print(f"{manifest.paper_id}: {manifest.current_stage.value} ({manifest.status.value})")
        return 0

    if args.command == "run-until-outline":
        manifest = run_until_outline(args.paper_id, uploads_dir=uploads_dir, config_path=args.config)
        print(f"{manifest.paper_id}: {manifest.current_stage.value} ({manifest.status.value})")
        return 0

    if args.command == "run-after-outline":
        manifest = run_after_outline(args.paper_id, uploads_dir=uploads_dir, config_path=args.config)
        print(f"{manifest.paper_id}: {manifest.current_stage.value} ({manifest.status.value})")
        return 0

    if args.command == "render-export":
        manifest = run_render_export(args.paper_id, uploads_dir=uploads_dir, config_path=args.config)
        print(f"{manifest.paper_id}: {manifest.current_stage.value} ({manifest.status.value})")
        return 0

    if args.command == "regenerate":
        manifest = regenerate_section(args.paper_id, args.section, uploads_dir=uploads_dir)
        summary = latest_regenerate_log_summary(args.paper_id, uploads_dir=uploads_dir)
        regenerated = ",".join(summary.get("regenerated_sections", [])) or "none"
        print(
            f"{manifest.paper_id}: regenerate {args.section} -> {regenerated} "
            f"({manifest.current_stage.value}/{manifest.status.value})"
        )
        return 0

    if args.command == "serve":
        import uvicorn

        from .dev_server import create_app

        app = create_app(uploads_dir=Path(uploads_dir).expanduser().resolve() if uploads_dir else None)
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
