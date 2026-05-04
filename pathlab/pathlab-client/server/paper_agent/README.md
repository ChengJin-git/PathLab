# PathLab Paper Agent

Standalone development runtime for the PathLab paper-generation pipeline.

## Setup

```bash
cd pathlab/pathlab-client/server/paper_agent
uv sync
```

## Commands

```bash
uv run pathlab-paper-agent --help
uv run pathlab-paper-agent run --paper-id paper_dev_001 --uploads-dir /tmp/pathlab_uploads
uv run pathlab-paper-agent run-stage --paper-id paper_dev_001 --stage collecting --uploads-dir /tmp/pathlab_uploads
uv run pathlab-paper-agent serve --host 127.0.0.1 --port 6200 --uploads-dir /tmp/pathlab_uploads
```

`serve` is a dev-only HTTP entrypoint. Production still uses PathLab Gateway + TaskWorker; the worker invokes `pathlab-paper-agent run` as a subprocess.

## Current runtime contract

`run` now executes a deterministic no-LLM scaffold through the full paper-agent
stage sequence:

```text
collecting -> building_evidence -> outlining -> plotting -> literature_review
-> section_writing -> validating -> rendering -> exporting -> completed
```

The scaffold writes the v1 paper-run directory shape (`evidence/`,
`locked_blocks/`, `drafts/sections/`, `final/<template>/`, `exports/*.zip`) so
Gateway, TaskWorker, and the front-end can integrate against stable artifacts
while later milestones replace each stage body with real collectors, LLM
agents, guards, LaTeX compilation, and verified citation/plot generation.
