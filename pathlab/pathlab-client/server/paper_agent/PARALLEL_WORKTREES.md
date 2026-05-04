# Paper Agent Parallel Worktrees

This file records the Day-1 parallel branches for implementing the real paper-generation backend after the Phase 01 scaffold.

## Base Contract

All branches start from the Phase 01 scaffold and should preserve these contracts unless the owning branch coordinates a cross-branch change first:

- CLI: `pathlab-paper-agent run`, `run-stage`, `scaffold`, `serve`.
- Dev service: `/health`, `/papers`, `/papers/{paper_id}`, `/papers/{paper_id}/stages/{stage}:run`, file listing.
- Gateway/TaskWorker boundary: TaskWorker invokes the paper agent through `uv run --project server/paper_agent pathlab-paper-agent ...`.
- Artifact protocol: `manifest.json`, artifact visibility/downloadability, public/private evidence split, and export bundle allowlist.
- Orchestrator: keep `src/pathlab_paper_agent/pipeline.py` thin; add real logic inside owned modules.

## Stage Module Ownership

The scaffold stage bodies have been split out of `pipeline.py` to avoid merge conflicts:

```text
src/pathlab_paper_agent/stages/
  collecting.py      # M2 collector entry point
  evidence.py        # M3 PHI scrub + evidence lock entry point
  outlining.py       # M7 outline agent entry point
  plotting.py        # M6 plotting entry point
  literature.py      # M8 literature/citation entry point
  sections.py        # M9 section writer entry point
  validating.py      # M10 guards entry point
  rendering.py       # M4/M11 renderer entry point
  exporting.py       # M11 bundle export entry point
```

## Active Worktrees

| Track | Branch | Worktree | Primary write scope |
|---|---|---|---|
| M2 Collector | `paper/m2-collector` | `/Users/wangyihui/code/PathLab-worktrees/m2-collector` | `collector/`, `stages/collecting.py`, collector schemas/tests |
| M4 Templates | `paper/m4-templates` | `/Users/wangyihui/code/PathLab-worktrees/m4-templates` | `templates/`, `renderers/`, `stages/rendering.py`, `stages/exporting.py`, `docker/paper-latex/` |
| M6a Figures | `paper/m6a-figures` | `/Users/wangyihui/code/PathLab-worktrees/m6a-figures` | `plotting/`, `stages/plotting.py`, figure fixtures/tests |
| M8a Citations | `paper/m8a-citations` | `/Users/wangyihui/code/PathLab-worktrees/m8a-citations` | `citations/`, `stages/literature.py`, citation fixtures/tests |
| M10a Guards | `paper/m10a-guards` | `/Users/wangyihui/code/PathLab-worktrees/m10a-guards` | `validators/`, `stages/validating.py`, guard fixtures/tests |

## Local Setup Per Worktree

Run this once inside each worktree before assigning an agent:

```bash
cd /Users/wangyihui/code/PathLab-worktrees/<name>/pathlab/pathlab-client/server/paper_agent
uv sync
uv run pytest -q
uv run ruff check src tests
```

Smoke a single stage during development:

```bash
uv run pathlab-paper-agent scaffold --paper-id paper_dev_001 --uploads-dir /tmp/pathlab-paper-dev
uv run pathlab-paper-agent run-stage --paper-id paper_dev_001 --stage collecting --uploads-dir /tmp/pathlab-paper-dev
```

Smoke the standalone dev service:

```bash
uv run pathlab-paper-agent serve --host 127.0.0.1 --port 6201 --uploads-dir /tmp/pathlab-paper-dev
```

## Merge Discipline

- Merge branches back into `paper-agent-phase01` one at a time.
- Prefer additive modules and fixture tests over editing shared orchestrator code.
- If a branch must change schema, manifest format, API response, or file visibility, update tests and this contract before merging other branches.
- Never put private evidence, raw prompts, raw responses, PHI-bearing paths, or original case identifiers into public artifacts or export ZIPs.
